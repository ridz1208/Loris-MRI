import getpass
import os
from dataclasses import dataclass, field

from lib.db.models.candidate import DbCandidate
from lib.db.models.mri_scan_type import DbMriScanType
from lib.db.models.session import DbSession
from lib.db.queries.candidate import try_get_candidate_with_psc_id
from lib.db.queries.imaging_file_type import get_all_imaging_file_types
from lib.db.queries.mri_scan_type import try_get_mri_scan_type_with_name
from lib.db.queries.session import try_get_session_with_cand_id_visit_label
from lib.db.queries.visit import try_get_visit_with_visit_label
from lib.env import Env
from lib.import_png_dataset.args import Args
from lib.import_png_dataset.problems import ProblemLog
from lib.import_png_dataset.submission import PngImage

PNG_FILE_TYPE = 'png'


@dataclass
class Resolved:
    """
    The database objects a submission refers to, each looked up once.
    """

    candidates:     dict[str, DbCandidate | None]           = field(default_factory=dict)
    sessions:       dict[tuple[str, str], DbSession | None] = field(default_factory=dict)
    mri_scan_types: dict[str, DbMriScanType | None]         = field(default_factory=dict)
    known_visits:   dict[str, bool]                         = field(default_factory=dict)


def check_environment(env: Env, data_dir_path: str, args: Args, problems: ProblemLog):
    """
    Check the destinations and lookup tables the insertion will need.

    Done first, because these fail for every image equally and a submitter should
    not be told their delivery is fine only to hit a missing lookup row on the
    first insert.
    """

    if not os.path.isdir(data_dir_path):
        problems.error('dataDirBasepath', f"'{data_dir_path}' is not a directory.")
        return

    subdirectories = ['assembly'] + (['pic'] if args.create_pic else [])

    for subdirectory in subdirectories:
        path = os.path.join(data_dir_path, subdirectory)

        if not os.path.isdir(path):
            problems.error(
                f"{subdirectory}/",
                f"'{path}' does not exist. It is created by imaging_install.sh.",
            )
        elif not os.access(path, os.W_OK):
            problems.error(
                f"{subdirectory}/", f"'{path}' is not writable by {getpass.getuser()}.",
            )

    # files.FileType is a foreign key onto ImagingFileTypes.type, so without this
    # row every insert is rejected by the constraint.
    file_types = {file_type.type for file_type in get_all_imaging_file_types(env.db)}

    if PNG_FILE_TYPE not in file_types:
        problems.error(
            'ImagingFileTypes',
            "no 'png' row. Add it with: INSERT INTO ImagingFileTypes (type, description)"
            " VALUES ('png','PNG image');",
        )


def check_against_database(env: Env, images: list[PngImage], problems: ProblemLog) -> Resolved:
    """
    Resolve every candidate, visit, session and scan type the submission names.

    Nothing is written here. A submission naming three unknown scan types reports
    all three, rather than failing on the first and being re-run.
    """

    resolved = Resolved()

    if problems.has_errors():
        # Resolving against the database is pointless if the submission itself is
        # malformed, and the extra messages would bury the real problems.
        return resolved

    for image in images:
        _resolve_candidate(env, image, resolved, problems)
        _resolve_visit(env, image, resolved, problems)
        _resolve_session(env, image, resolved, problems)
        _resolve_scan_type(env, image, resolved, problems)

    return resolved


def _resolve_candidate(env: Env, image: PngImage, resolved: Resolved, problems: ProblemLog):
    if image.psc_id in resolved.candidates:
        return

    candidate = try_get_candidate_with_psc_id(env.db, image.psc_id)

    if candidate is None:
        problems.error(
            f"sub-{image.psc_id}",
            "no candidate in the candidate table with this PSCID. Re-identification is"
            " expected to have run before this script.",
        )

    resolved.candidates[image.psc_id] = candidate


def _resolve_visit(env: Env, image: PngImage, resolved: Resolved, problems: ProblemLog):
    """
    Check the visit label is one LORIS knows about.

    Separate from the session lookup, and checked first, because the two failures
    have different fixes. An unknown visit label means the label itself is not
    configured in LORIS and no candidate could ever have it; a missing session
    means the label is fine but this candidate has no visit with it.
    """

    if image.visit_label in resolved.known_visits:
        return

    visit = try_get_visit_with_visit_label(env.db, image.visit_label)

    if visit is None:
        problems.error(
            f"ses-{image.visit_label}",
            f"'{image.visit_label}' is not a visit label configured in LORIS. Visit"
            f" labels are never created by this script; they are set up during project"
            f" onboarding.",
        )

    resolved.known_visits[image.visit_label] = visit is not None


def _resolve_session(env: Env, image: PngImage, resolved: Resolved, problems: ProblemLog):
    candidate   = resolved.candidates[image.psc_id]
    session_key = (image.psc_id, image.visit_label)

    if candidate is None or session_key in resolved.sessions:
        return

    # Only worth looking up when the visit label itself is known; otherwise the
    # submitter gets two messages for one problem.
    if not resolved.known_visits.get(image.visit_label, False):
        resolved.sessions[session_key] = None
        return

    session = try_get_session_with_cand_id_visit_label(
        env.db, candidate.cand_id, image.visit_label
    )

    if session is None:
        problems.error(
            f"sub-{image.psc_id}/ses-{image.visit_label}",
            f"no active session for CandID {candidate.cand_id} with visit label"
            f" '{image.visit_label}'. Sessions are not created by this script and must"
            f" already exist in LORIS.",
        )

    resolved.sessions[session_key] = session


def _resolve_scan_type(env: Env, image: PngImage, resolved: Resolved, problems: ProblemLog):
    if image.scan_type_name in resolved.mri_scan_types:
        return

    mri_scan_type = try_get_mri_scan_type_with_name(env.db, image.scan_type_name)

    if mri_scan_type is None:
        problems.error(
            image.location,
            f"scan type '{image.scan_type_name}' has no entry in the mri_scan_type table."
            f" Scan types are never created by this script; add it first, or pass"
            f" --loris_scan_type.",
        )

    resolved.mri_scan_types[image.scan_type_name] = mri_scan_type
