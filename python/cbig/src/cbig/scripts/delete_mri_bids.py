import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# cbig specific queries
from cbig.database.queries.file import delete_file_entry, get_files_with_candidate_id
from cbig.database.queries.file_parameter import delete_file_parameters
from lib.config import get_data_dir_path_config
from lib.config_file import load_config
from lib.db.queries.candidate import try_get_candidate_with_psc_id
from lib.db.queries.file import try_get_file_with_id
from lib.db.queries.file_parameter import (
    try_get_parameter_value_with_file_id_parameter_name,
)
from lib.exitcode import INVALID_ARG
from lib.logging import log_error_exit
from lib.make_env import make_env
from loris_bids_utils.files.participants import BidsParticipantsTsvFile
from sqlalchemy.orm import Session as Database

# Set from --verbose in main(). When False, only summaries and errors are printed.
verbose = False

# Counts of disk actions, reported in the summary at the end of the run
disk_counts: Counter[str] = Counter()


def vprint(*args: Any, **kwargs: Any):
    """Print only when --verbose is set"""
    if verbose:
        print(*args, **kwargs)


def main():
    global verbose

    parser = argparse.ArgumentParser(
        description="Delete database entries, niftis, sidecars, and pics for a given candidate. "
                    "Run without --confirm and --delete-on-disk first for a trial run."
    )
    parser.add_argument(
        '-p', '--profile',
        help="Name of the python database config file in the config directory."
    )
    parser.add_argument(
        '-i', '--pscid',
        type=str,
        required=True,
        help="The PSCID associated with the candidate's data you wish to delete"
    )
    parser.add_argument(
        '-f', '--project-bids-dir',
        type=str,
        required=True,
        help="Name of the directory containing the CBIGR project's bids"
    )
    parser.add_argument(
        '-c', '--confirm',
        action='store_true',
        help="Commits database entry deletion (must be used with --delete-on-disk)"
    )
    parser.add_argument(
        '-d', '--delete-on-disk',
        action='store_true',
        help="Deletes targeted file(s) on disk (must be used with --confirm)"
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Provide verbose output'
    )

    args = parser.parse_args()

    pscid = args.pscid
    project_folder = args.project_bids_dir
    confirm = args.confirm
    delete_on_disk = args.delete_on_disk
    verbose = args.verbose

    # Environment and database
    config_file = load_config(args.profile)
    env = make_env('delete_mri_bids', {}, config_file, args.verbose)
    db = env.db

    # Using only one of the two flags would leave the disk and the database out of sync
    if confirm != delete_on_disk:
        log_error_exit(
            env,
            "--confirm and --delete-on-disk must be used together (or neither, for a trial run)",
            INVALID_ARG,
        )

    # Paths
    data_path = get_data_dir_path_config(env)
    pics_path = data_path / 'pic'
    bids_path = data_path / 'bids_imports' / project_folder

    if not bids_path.is_dir():
        print(f'{bids_path} does not exist. Check --project-bids-dir')
        sys.exit(INVALID_ARG)

    if not confirm:
        print('TRIAL RUN: nothing will be deleted on disk or in the database\n')

    # ---------------------------------------------------------------------------------------------
    # Run the script
    # ---------------------------------------------------------------------------------------------

    deleted_files = 0
    deleted_params = 0
    try:
        candidate = try_get_candidate_with_psc_id(db, pscid)
        if candidate is None:
            print(f'No candidate found with PSCID {pscid}')
            sys.exit(INVALID_ARG)

        # Must match the column compared in get_files_with_candidate_id's .where(...)
        cand_id = candidate.cand_id

        files = get_files_with_candidate_id(db, cand_id)
        print(f'Found {len(files)} file(s) in the database for PSCID {pscid}')

        # Per file: pic on disk -> parameter rows -> image on disk -> file row.
        # A DB step only runs if the disk step before it succeeded.
        for file in files:
            vprint(f'\n--- File ID {file.id} --- {file.path.name} ---')

            # 1. Pic on disk
            try:
                pic_ok = delete_pic(db, file.id, pics_path, delete_on_disk)
            except Exception as e:
                print(f'Pic cleanup error for file {file.id}: {e}')
                pic_ok = False

            if not pic_ok:
                print(f'Keeping all DB rows for file {file.id}, pic was not deleted')
                continue

            # 2. Parameter rows
            result = delete_file_parameters(db, file.id)
            n = result.rowcount
            vprint(f'{n} parameter row(s) for file {file.id}')
            deleted_params += n

            # 3. Image and sidecars on disk
            try:
                image_ok = delete_bids_file(db, file.id, data_path, delete_on_disk)
            except Exception as e:
                print(f'Image cleanup error for file {file.id}: {e}')
                image_ok = False

            if not image_ok:
                print(f'Keeping file row for file {file.id}, image was not deleted')
                continue

            # 4. File row
            result = delete_file_entry(db, file.id)
            n = result.rowcount
            vprint(f'{n} file row(s) for file {file.id}')
            deleted_files += n

        # Participant-level BIDS cleanup, runs even if no files were found in the database
        vprint(f'\n--- BIDS folders for sub-{pscid} in {bids_path} ---')
        try:
            delete_dirs(bids_path, pscid, delete_on_disk)
        except Exception as e:
            print(f'BIDS folder cleanup failed: {e}. Continuing.')

        try:
            delete_participant_tsv_line(bids_path, pscid, delete_on_disk)
        except Exception as e:
            print(f'participants.tsv cleanup failed: {e}. Continuing.')

        # Disk summary
        verb = 'deleted' if delete_on_disk else 'would be deleted'
        print(f'\nDisk: {disk_counts["images"]} image(s), {disk_counts["sidecars"]} sidecar(s), '
              f'{disk_counts["pics"]} pic(s), {disk_counts["folders"]} empty folder(s) {verb}')
        if disk_counts['missing']:
            print(f'{disk_counts["missing"]} image(s) recorded in the database '
                  f'were already missing on disk')

        # Database summary
        if deleted_files == 0 and deleted_params == 0:
            db.rollback()
            print('Database: nothing to delete.')
        elif confirm:
            db.commit()
            print(f'Database: committed, {deleted_files} file row(s) and '
                  f'{deleted_params} parameter row(s) deleted.')
        else:
            db.rollback()
            print(f'Database (trial run): {deleted_files} file row(s) and {deleted_params} '
                  f'parameter row(s) would be deleted. Use --confirm --delete-on-disk to delete.')
    except Exception:
        db.rollback()
        raise


# -------------------------------------------------------------------------------------------------
# Helpers
# Disk helpers return True on success (including "already missing" and trial runs)
# and False only when an actual deletion failed.
# -------------------------------------------------------------------------------------------------

def delete_pic(db: Database, file_id: int, pics_path: Path, delete_on_disk: bool) -> bool:
    """Delete the check pic of a file, found in the parameter_file table"""

    parameter = try_get_parameter_value_with_file_id_parameter_name(
        db, file_id, 'check_pic_filename')
    if parameter is None or not parameter.value:
        vprint(f'No pic recorded for file {file_id}')
        return True

    full_path = pics_path / parameter.value

    if not full_path.is_file():
        vprint(f'{full_path} not found on disk, continuing')
    elif delete_on_disk:
        try:
            full_path.unlink()
            vprint(f'Deleted {full_path}')
        except OSError as e:
            print(f"Couldn't delete {full_path}: {e}")
            return False
        disk_counts['pics'] += 1
    else:
        vprint(f'Would delete {full_path}')
        disk_counts['pics'] += 1

    delete_dir_if_empty(full_path.parent, delete_on_disk)
    return True


def delete_bids_file(db: Database, file_id: int, data_path: Path, delete_on_disk: bool) -> bool:
    """Delete the image of a file on disk, plus its sidecars"""

    file = try_get_file_with_id(db, file_id)
    if file is None or not file.path:
        vprint(f'No path recorded for file {file_id}, nothing to delete on disk')
        return True

    full_path = data_path / file.path
    ok = True

    if not full_path.is_file():
        vprint(f'{full_path} not found on disk, continuing')
        disk_counts['missing'] += 1
    elif delete_on_disk:
        try:
            full_path.unlink()
            vprint(f'Deleted {full_path}')
            disk_counts['images'] += 1
        except OSError as e:
            print(f"Couldn't delete {full_path}: {e}")
            ok = False
    else:
        vprint(f'Would delete {full_path}')
        disk_counts['images'] += 1

    # Sidecars may still exist even when the image itself is gone
    if not delete_sidecars(full_path, delete_on_disk):
        ok = False

    return ok


def delete_sidecars(image_path: Path, delete_on_disk: bool) -> bool:
    """Delete the sidecar files (json, bval, bvec) next to a NIfTI image"""

    name = image_path.name
    if name.endswith('.nii.gz'):
        stem = name[:-len('.nii.gz')]
    elif name.endswith('.nii'):
        stem = name[:-len('.nii')]
    else:
        return True

    ok = True
    for ext in ['.json', '.bval', '.bvec']:
        sidecar = image_path.with_name(stem + ext)
        if not sidecar.is_file():
            continue

        if delete_on_disk:
            try:
                sidecar.unlink()
                vprint(f'Deleted {sidecar}')
            except OSError as e:
                print(f"Couldn't delete {sidecar}: {e}")
                ok = False
                continue
        else:
            vprint(f'Would delete {sidecar}')
        disk_counts['sidecars'] += 1

    return ok


def delete_dirs(bids_path: Path, pscid: str, delete_on_disk: bool):
    """Delete MRI modality, session and subject dirs for a participant if they are empty"""

    subject_dir = bids_path / f"sub-{pscid.removeprefix('sub-')}"

    if not subject_dir.is_dir():
        print(f'{subject_dir} does not exist. Skipping folder cleanup')
        return

    modalities = ['anat', 'dwi', 'fmap', 'func']

    for session_dir in subject_dir.glob('ses-*'):
        for modality in modalities:
            delete_dir_if_empty(session_dir / modality, delete_on_disk)

        delete_dir_if_empty(session_dir, delete_on_disk)

    delete_dir_if_empty(subject_dir, delete_on_disk)


def delete_dir_if_empty(folder_path: Path, delete_on_disk: bool):
    """Delete the folder if it exists and is empty"""

    if not folder_path.is_dir():
        return

    if any(folder_path.iterdir()):
        vprint(f'Not deleting {folder_path}, folder is not empty')
        return

    if delete_on_disk:
        try:
            folder_path.rmdir()
            vprint(f'Deleted empty folder {folder_path}')
        except OSError as e:
            print(f"Couldn't delete folder {folder_path}: {e}")
            return
    else:
        vprint(f'Would delete empty folder {folder_path}')
    disk_counts['folders'] += 1


def delete_participant_tsv_line(bids_path: Path, pscid: str, delete_on_disk: bool):
    """Remove a participant's row from participants.tsv"""

    tsv_path = bids_path / 'participants.tsv'
    participant_id = pscid.removeprefix('sub-')

    if not tsv_path.is_file():
        print(f'{tsv_path} does not exist. Skipping')
        return

    participants_file = BidsParticipantsTsvFile(tsv_path)

    row = participants_file.get_row(participant_id)
    if row is None:
        print(f'sub-{participant_id} not found in participants.tsv')
        return

    if not delete_on_disk:
        print(f'Would remove sub-{participant_id} from participants.tsv')
        return

    participants_file.rows.remove(row)

    tmp_path = tsv_path.with_name(tsv_path.name + '.tmp')
    participants_file.write(tmp_path)
    tmp_path.replace(tsv_path)
    print(f'Removed sub-{participant_id} from participants.tsv')


if __name__ == "__main__":
    main()
