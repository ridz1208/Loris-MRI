import datetime
import os
import re

import lib.exitcode
from lib.db.models.file import DbFile
from lib.db.queries.config import try_get_config_with_setting_name
from lib.db.queries.file import try_get_file_with_hash, try_get_file_with_rel_path
from lib.env import Env
from lib.imaging_lib.file import register_imaging_file
from lib.imaging_lib.file_parameter import register_file_parameter, register_file_parameters
from lib.import_png_dataset.check import PNG_FILE_TYPE, Resolved
from lib.import_png_dataset.submission import PngImage
from lib.logging import log, log_error_exit, log_verbose, log_warning
from lib.util.crypto import compute_file_blake2b_hash
from lib.utilities import copy_file

# Subdirectory under the visit directory, the PNG equivalent of the 'mri' and
# 'pet' directories move_minc writes into.
ASSEMBLY_SUBDIR = 'png'

# Width in pixels of the pic shown in the imaging browser.
PIC_WIDTH = 200


def insert_image(
    env: Env, data_dir_path: str, image: PngImage, resolved: Resolved, create_pic: bool,
) -> bool:
    """
    Copy and register one validated PNG image. Returns whether it was inserted.
    """

    candidate     = resolved.candidates[image.psc_id]
    session       = resolved.sessions[(image.psc_id, image.visit_label)]
    mri_scan_type = resolved.mri_scan_types[image.scan_type_name]

    assert candidate is not None and session is not None

    blake2b_hash = compute_file_blake2b_hash(image.path)

    # try_get_file_with_hash matches either file_blake2b_hash or md5hash in a
    # single query, so one call covers both. Checked here rather than during
    # validation because an image inserted earlier in this same run counts too.
    existing = try_get_file_with_hash(env.db, blake2b_hash)

    if existing is not None:
        log_warning(
            env,
            f"{image.location} is already registered in the files table as"
            f" {existing.rel_path} (FileID {existing.id}). Skipping.",
        )
        return False

    file_rel_path = _determine_file_rel_path(env, session, image.scan_type_name)
    file_path     = os.path.join(data_dir_path, file_rel_path)

    # 0o775, not 0o770: Apache serves the image for download and reads the pic
    # for the imaging browser thumbnail, and it is not in the owning group on
    # every install. The core pipeline leaves the mode to the umask for the same
    # reason. A directory created 0o770 renders as a broken image with nothing
    # logged anywhere.
    os.makedirs(os.path.dirname(file_path), mode=0o775, exist_ok=True)

    # A copy rather than a move, so the submitted directory survives the run and
    # can be re-ingested after a failure. The Perl pipeline moves instead,
    # because it owns the incoming upload; here the caller does.
    #
    # lib.utilities.copy_file rather than lib.util.fs.copy_file: the latter is
    # named for files but calls shutil.copytree, so it only works on directories.
    # This is the helper the BIDS importer uses for single files, and it also
    # refuses to overwrite a different file that is already at the destination.
    copy_file(image.path, file_path, env.verbose)

    # Everything from here writes to the database. If any of it fails, the copy
    # above is an orphan: a file in the assembly tree that no files row points
    # at, which nothing will ever clean up and which will collide with the next
    # run's version counter. So the copy is removed before the error is raised.
    try:
        # register_imaging_file sets the user, the insert time, the coordinate
        # and output spaces, and SourceFileID. The last one matters: it is a
        # foreign key onto files.FileID with a default of 0, so a row that omits
        # it inserts 0 and the constraint rejects it.
        file = register_imaging_file(
            env,
            PNG_FILE_TYPE,
            file_rel_path,
            session,
            mri_scan_type,
            echo_time                = None,
            echo_number              = None,
            phase_encoding_direction = None,
        )

        # A PNG carries no header and no JSON sidecar, so sessions.tsv is the
        # only place an acquisition date can come from. register_imaging_file
        # does not take one, since a DICOM or NIfTI brings its own.
        if image.acq_date is not None:
            file.acquisition_date = datetime.date.fromisoformat(image.acq_date)

        # source_filename preserves the name the submitter gave the image, which
        # the rename to the assembly convention would otherwise lose.
        register_file_parameters(env, file, {
            'md5hash':           image.md5_hash,
            'file_blake2b_hash': blake2b_hash,
            'source_filename':   os.path.basename(image.path),
        })

        env.db.commit()
    except Exception as exception:
        env.db.rollback()

        if os.path.exists(file_path):
            os.remove(file_path)

        log_error_exit(
            env,
            f"Could not register {image.location}: {exception}",
            lib.exitcode.INSERT_FAILURE,
        )

    log(env, f"{image.location} inserted as FileID {file.id} ({file_rel_path})")

    if create_pic:
        _create_pic(env, data_dir_path, file)

    return True


def _determine_file_rel_path(env: Env, session, scan_type_name: str) -> str:
    """
    Build a file path that does not collide with anything in the visit already.

    Both the directory and the name follow the convention move_minc produces for
    MINC files, so a PNG sits alongside them and reads the same way:

        assembly/<CandID>/<VisitLabel>/png/native/
        <prefix>_<CandID>_<VisitLabel>_<scan_type>_<NNN>.png

    where <prefix> is the 'prefix' setting from the Config module, the same
    value move_minc uses. No hyphens anywhere: the MINC files have none, and
    mri_scan_type names may not contain them either.

    The version is incremented until the path is free, exactly as move_minc
    does. Deriving it from the database rather than from the submitted file
    names is what makes a second delivery to the same visit safe; numbering from
    the input would restart at 1 and overwrite the first delivery.
    """

    cand_id     = session.candidate.cand_id
    visit_label = session.visit_label
    prefix      = _get_prefix_config(env)

    directory = os.path.join(
        'assembly', str(cand_id), visit_label, ASSEMBLY_SUBDIR, 'native'
    )

    version = 1

    while True:
        file_name = f"{prefix}_{cand_id}_{visit_label}_{scan_type_name}_{version:03d}.png"
        rel_path  = os.path.join(directory, file_name)

        if try_get_file_with_rel_path(env.db, rel_path) is None:
            return rel_path

        version += 1


def _get_prefix_config(env: Env) -> str:
    """
    Read the 'prefix' setting that move_minc uses to name assembled files.
    """

    config = try_get_config_with_setting_name(env.db, 'prefix')

    if config is None or config.value is None:
        log_error_exit(
            env,
            "No 'prefix' configuration value found in the database. It is the same"
            " setting the MINC insertion uses to name assembled files.",
            lib.exitcode.MISSING_CONFIG_SETTING,
        )

    return config.value


def _create_pic(env: Env, data_dir_path: str, file: DbFile):
    """
    Write the check pic and register it in parameter_file.

    imaging_lib.nifti_pic.create_imaging_pic cannot be reused: it renders a
    volume with nilearn's plot_anat and builds its name by stripping a .nii or
    .nii.gz suffix. The naming convention it produces is followed here, file ID
    included, which is why this runs after the registration rather than before.
    """

    cand_id      = file.session.candidate.cand_id
    file_path    = os.path.join(data_dir_path, file.rel_path)
    pic_name     = re.sub(r'\.png$', f"_{file.id}_check.png", os.path.basename(file.rel_path))
    pic_rel_path = os.path.join(str(cand_id), pic_name)
    pic_path     = os.path.join(data_dir_path, 'pic', pic_rel_path)

    try:
        os.makedirs(os.path.dirname(pic_path), mode=0o775, exist_ok=True)

        # Pillow arrives with matplotlib, which nilearn already requires.
        from PIL import Image

        with Image.open(file_path) as image:
            # Flattened onto black: these exports often carry an alpha channel,
            # and a transparent surround renders as a broken image in the imaging
            # browser rather than as the image itself.
            flat = Image.new('RGB', image.size, (0, 0, 0))
            flat.paste(image, mask=image.split()[3] if image.mode == 'RGBA' else None)

            width  = min(PIC_WIDTH, flat.width)
            height = max(1, round(flat.height * (width / flat.width)))

            flat.resize((width, height)).save(pic_path, 'PNG')
    except Exception as exception:
        # A missing pic costs a preview, not the insertion, so this warns rather
        # than failing. The files row is already valid without it.
        log_warning(env, f"Could not create the pic for FileID {file.id}: {exception}")
        return

    register_file_parameter(env, file, 'check_pic_filename', pic_rel_path)

    log_verbose(env, f"Created pic {pic_rel_path}")
