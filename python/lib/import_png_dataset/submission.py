import datetime
import getpass
import os
import re
from dataclasses import dataclass

from lib.imaging_lib.bids.dataset import BidsDataset
from lib.import_png_dataset.args import Args
from lib.import_png_dataset.problems import ProblemLog
from lib.util.crypto import compute_file_md5_hash
from lib.utilities import read_tsv_file

# First eight bytes of any PNG file. Checked because a renamed JPEG or a
# truncated transfer is a common way for a submission to arrive broken, and both
# would otherwise fail much later with an unhelpful message.
PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'

# mri_scan_type names may not contain commas, hyphens, spaces or periods. A scan
# type read from a file name cannot contain an underscore either, since that is
# the separator the name is split on.
SCAN_TYPE_FROM_FILE_NAME_REGEX = re.compile(r'^[A-Za-z0-9]+$')
SCAN_TYPE_ARG_REGEX       = re.compile(r'^[A-Za-z0-9_]+$')

SESSIONS_TSV_NAME = 'sessions.tsv'

# Matched in full, unlike the prefix match BidsDataset uses. See _read_subjects.
SUBJECT_DIR_REGEX = re.compile(r'sub-([a-zA-Z0-9]+)')
SESSION_DIR_REGEX = re.compile(r'ses-([a-zA-Z0-9]+)')


@dataclass
class SubmissionSubject:
    """
    A participant directory of the submission, with its name read in full.
    """

    label: str
    path: str


@dataclass
class SubmissionSession:
    """
    A visit directory of the submission, with its name read in full.
    """

    label: str
    path: str


@dataclass
class PngImage:
    """
    One PNG image the submission asks to insert, before anything is resolved
    against the database.
    """

    path: str
    psc_id: str
    visit_label: str
    scan_type_name: str
    acq_date: str | None
    md5_hash: str
    location: str


def _is_hidden(name: str) -> bool:
    """
    True for entries no submission ever means to include.

    Covers dotfiles and the AppleDouble companions that macOS writes beside every
    file in a zip archive. The companions matter because they mirror the name they
    shadow: `._sessions.tsv` ends with 'sessions.tsv' and `._t1_001.png` ends with
    '.png', so a suffix test alone picks them up and then fails on their contents,
    which are a binary resource fork rather than the file they appear to be.
    """

    return name.startswith('.')


def read_submission(args: Args, problems: ProblemLog) -> list[PngImage]:
    """
    Walk the submitted directory and return the images it asks to insert.

    Nothing is resolved against the database here. This establishes what the
    submission claims to contain and checks that the directories, the TSV files
    and the images themselves agree with each other.
    """

    # BidsDataset already finds the sub- and ses- directories, reads
    # participants.tsv and validates its participant_id column, so the layout is
    # read exactly one way across this pipeline and the BIDS importer.
    #
    # `validate` is False because a PNG submission is not a BIDS dataset. It
    # borrows the sub-/ses- naming, but has no dataset_description.json and no
    # BIDS-valid file names, so running the PyBIDS validator over it would fail
    # on things that are not wrong here. Nothing this pipeline reads touches the
    # PyBIDS layout in any case.
    dataset = BidsDataset(args.png_dir_path, validate=False)

    tsv_participants = _read_tsv_participants(dataset, args.png_dir_path, problems)

    if tsv_participants is None:
        return []

    subjects = _read_subjects(dataset, args.png_dir_path, problems)

    if not subjects:
        return []

    _report_stray_root_entries(args.png_dir_path, problems)

    for psc_id in sorted(set(tsv_participants) - {subject.label for subject in subjects}):
        problems.warning(
            'participants.tsv',
            f"row 'sub-{psc_id}' has no matching directory; nothing will be inserted"
            f" for that participant.",
        )

    images: list[PngImage] = []

    for subject in subjects:
        if args.subject_label is not None and subject.label != args.subject_label:
            continue

        if subject.label not in tsv_participants:
            problems.error(
                f"sub-{subject.label}",
                "directory has no row in participants.tsv, so it was not part of the"
                " agreed submission.",
            )
            continue

        images += _read_subject(subject, args, problems)

    if args.subject_label is not None \
            and args.subject_label not in {subject.label for subject in subjects}:
        problems.error('--subject', f"no directory sub-{args.subject_label} in the submission.")

    if not images and not problems.has_errors():
        problems.error('root', f"no PNG file found under {args.png_dir_path}.")

    _check_images(images, problems)

    return images


# =============================================================================
#  participants.tsv
# =============================================================================

def _read_tsv_participants(
    dataset: BidsDataset, png_dir_path: str, problems: ProblemLog,
) -> dict[str, object] | None:
    """
    Read and check participants.tsv. Returns None when the file is unusable.
    """

    path = os.path.join(png_dir_path, 'participants.tsv')

    if not os.path.isfile(path):
        problems.error(
            'root',
            "no participants.tsv. It lists the participants the submission is expected"
            " to contain.",
        )
        return None

    if os.path.getsize(path) == 0:
        problems.error('participants.tsv', "the file is empty.")
        return None

    # A submission saved as CSV rather than tab-separated is the single most
    # common TSV mistake, and produces a baffling "missing participant_id"
    # otherwise.
    with open(path, encoding='utf-8-sig', errors='replace') as tsv_file:
        header = tsv_file.readline()

    if '\t' not in header and ',' in header:
        problems.error(
            'participants.tsv',
            "the header has no tab but does contain commas; the file looks"
            " comma-separated. Save it as Tab Delimited Text.",
        )
        return None

    try:
        tsv_participants = dataset.tsv_participants
    except Exception as exception:
        problems.error('participants.tsv', f"could not be read: {exception}")
        return None

    if not tsv_participants:
        problems.error('participants.tsv', "the file has a header but no data rows.")
        return None

    # The reader indexes rows by identifier, so a repeated row is silently
    # collapsed. Counted from the raw file so it stays visible.
    _check_duplicate_keys(path, 'participant_id', 'participants.tsv', problems)

    return tsv_participants  # type: ignore[return-value]


# =============================================================================
#  Directories
# =============================================================================

def _read_subjects(
    dataset: BidsDataset, png_dir_path: str, problems: ProblemLog,
) -> list[SubmissionSubject]:
    """
    Return the participant directories, rejecting any whose name is not readable.

    The directories are enumerated here rather than taken from
    `BidsDataset.subjects`, because that property matches a name with
    `re.match(r'sub-([a-zA-Z0-9]+)')`, which is a prefix match. A directory named
    `sub-ARCHI_0001` yields the label `ARCHI`, and `sub-P014-B` yields `P014`,
    with nothing to show that the rest of the name was dropped. Worse, the
    `BidsSubject.path` it builds is derived from the truncated label, so it points
    at a directory that does not exist.

    A prefix match is the right behaviour for a BIDS dataset, where an entity is
    followed by other entities. It is the wrong behaviour here, where the whole
    directory name is one identifier, so the name is matched in full instead and a
    mismatch is reported rather than silently trimmed.
    """

    subjects: list[SubmissionSubject] = []
    found_any = False

    for entry in sorted(os.scandir(png_dir_path), key=lambda entry: entry.name):
        if not entry.is_dir() or not entry.name.startswith('sub-'):
            continue

        found_any = True

        match = SUBJECT_DIR_REGEX.fullmatch(entry.name)

        if match is None:
            problems.error(
                entry.name,
                "participant identifiers may only contain letters and numbers after the"
                " sub- prefix. This directory cannot be read as an identifier, so"
                " nothing in it was looked at.",
            )
            continue

        subjects.append(SubmissionSubject(label=match.group(1), path=entry.path))

    if not found_any:
        problems.error('root', "no sub- directory found.")

    return subjects


def _read_sessions(subject: SubmissionSubject, problems: ProblemLog) -> list[SubmissionSession]:
    """
    Return the visit directories of a participant, rejecting unreadable names.

    Same prefix-match trap as the participant directories, and more likely to
    bite: `4_month_echocardiography` is a perfectly good LORIS visit label, but
    `ses-4_month_echocardiography` would yield the label `4` and then fail a
    lookup naming a visit the submitter never mentioned.
    """

    sessions: list[SubmissionSession] = []

    for entry in sorted(os.scandir(subject.path), key=lambda entry: entry.name):
        if not entry.is_dir() or not entry.name.startswith('ses-'):
            continue

        match = SESSION_DIR_REGEX.fullmatch(entry.name)

        if match is None:
            problems.error(
                f"sub-{subject.label}/{entry.name}",
                "visit directory names may only contain letters and numbers after the"
                " ses- prefix. A LORIS visit label that contains other characters cannot"
                " be given as a directory name; ask the ARCHIMEDES team how to submit it.",
            )
            continue

        sessions.append(SubmissionSession(label=match.group(1), path=entry.path))

    return sessions


def _report_stray_root_entries(png_dir_path: str, problems: ProblemLog):
    """
    Warn about anything at the top level the layout does not account for.

    Usually harmless, occasionally the reason a participant is missing: a
    directory named `Sub-ARCHI0001` or `ARCHI0001` does not match the sub-
    pattern at all, so it is invisible to the walk and would otherwise vanish
    without comment.
    """

    strays = [
        name for name in sorted(os.listdir(png_dir_path))
        if not _is_hidden(name)
        and name != 'participants.tsv'
        and not (
            name.startswith('sub-')
            and os.path.isdir(os.path.join(png_dir_path, name))
        )
    ]

    if strays:
        problems.warning(
            'root',
            f"{len(strays)} entr(y/ies) not matching the expected layout were ignored:"
            f" {', '.join(strays[:5])}{' ...' if len(strays) > 5 else ''}",
        )


# =============================================================================
#  Per participant
# =============================================================================

def _read_subject(subject: SubmissionSubject, args: Args, problems: ProblemLog) -> list[PngImage]:
    """
    Read one participant's optional sessions.tsv and the images under each visit.
    """

    location = f"sub-{subject.label}"

    acq_dates, tsv_present = _read_sessions_tsv(subject, location, problems)

    if acq_dates is None:
        return []

    sessions = _read_sessions(subject, problems)

    if not sessions:
        problems.warning(location, "no ses- directory; nothing to insert for this participant.")
        return []

    if tsv_present:
        for visit_label in sorted(set(acq_dates) - {session.label for session in sessions}):
            problems.warning(
                f"{location}/{SESSIONS_TSV_NAME}",
                f"row 'ses-{visit_label}' has no matching directory.",
            )

    images: list[PngImage] = []

    for session in sessions:
        visit_label = session.label or ''

        if args.session_label is not None and visit_label != args.session_label:
            continue

        # sessions.tsv is optional, so the ses- directories are what define the
        # visits. When the file is there it supplies acquisition dates and a
        # cross-check; a directory it does not list is worth flagging, but not
        # worth refusing, since the directory is the authority.
        if tsv_present and visit_label not in acq_dates:
            problems.warning(
                f"{location}/ses-{visit_label}",
                "directory has no row in sessions.tsv; no acquisition date will be"
                " recorded for it.",
            )

        images += _read_session(
            session, subject.label, acq_dates.get(visit_label), args, problems
        )

    return images


def _read_sessions_tsv(
    subject: SubmissionSubject, location: str, problems: ProblemLog,
) -> tuple[dict[str, str | None] | None, bool]:
    """
    Read one participant's sessions.tsv.

    Returns the acquisition dates it holds, and whether the file was present.
    """

    # The file is sessions.tsv. A sub-<PSCID>_ prefix is accepted too, since some
    # submissions carry one, but it must name this participant:
    # sub-X_sessions.tsv sitting in sub-Y's directory is a copy-paste error, and
    # reading it would apply the wrong visit list to every image with nothing
    # flagged anywhere.
    found = sorted(
        name for name in os.listdir(subject.path)
        if not _is_hidden(name)
        and name.lower().endswith(SESSIONS_TSV_NAME)
        and os.path.isfile(os.path.join(subject.path, name))
    )

    if not found:
        # Optional, as in a BIDS dataset, so this warns rather than failing. It
        # is worth a warning all the same: a PNG has no header and no JSON
        # sidecar, so sessions.tsv is the only place an acquisition date can come
        # from, and it cannot be recovered later without going back to the
        # submitter.
        problems.warning(
            location,
            "no sessions.tsv. Continuing with the visits named by the ses- directories;"
            " no acquisition date will be recorded for any of them.",
        )
        return {}, False

    if len(found) > 1:
        problems.error(
            location,
            f"{len(found)} sessions files in the participant's directory"
            f" ({', '.join(found)}); there must be at most one.",
        )
        return None, True

    name = found[0]
    path = os.path.join(subject.path, name)

    claimed = re.fullmatch(r'sub-(.+)_sessions\.tsv', name, flags=re.IGNORECASE)

    if claimed is not None and claimed.group(1) != subject.label:
        problems.error(
            location,
            f"the sessions file is named {name}, which belongs to sub-{claimed.group(1)},"
            f" not to this directory. Rename it to {SESSIONS_TSV_NAME} or move it to the"
            f" right participant.",
        )
        return None, True

    if name != SESSIONS_TSV_NAME:
        problems.warning(
            location,
            f"the sessions file is named {name}; rename it to {SESSIONS_TSV_NAME}."
            f" Reading it anyway.",
        )

    if os.path.getsize(path) == 0:
        problems.error(f"{location}/{name}", "the file is empty.")
        return None, True

    try:
        rows = read_tsv_file(path)
    except Exception as exception:
        problems.error(f"{location}/{name}", f"could not be read: {exception}")
        return None, True

    if not rows:
        problems.error(f"{location}/{name}", "the file has a header but no data rows.")
        return None, True

    if 'session_id' not in rows[0]:
        problems.error(
            f"{location}/{name}",
            f"no session_id column. Columns found: {', '.join(rows[0].keys())}.",
        )
        return None, True

    acq_dates: dict[str, str | None] = {}

    for row in rows:
        session_id = (row.get('session_id') or '').strip()

        if not session_id:
            problems.error(f"{location}/{name}", "a row has an empty session_id.")
            continue

        visit_label = re.sub(r'^ses-', '', session_id)

        if visit_label in acq_dates:
            problems.error(
                f"{location}/{name}", f"session_id '{session_id}' appears more than once.",
            )
            continue

        acq_dates[visit_label] = _read_acq_date(row, f"{location}/{name}", session_id, problems)

    return acq_dates, True


def _read_acq_date(
    row: dict[str, str], location: str, session_id: str, problems: ProblemLog,
) -> str | None:
    """
    Return acq_date as YYYY-MM-DD, or None when it is absent or unusable.
    """

    acq_date = (row.get('acq_date') or '').strip()

    if not acq_date:
        return None

    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', acq_date):
        problems.error(
            location, f"acq_date '{acq_date}' for {session_id} is not in YYYY-MM-DD format.",
        )
        return None

    try:
        parsed = datetime.date.fromisoformat(acq_date)
    except ValueError:
        problems.error(location, f"acq_date '{acq_date}' for {session_id} is not a real date.")
        return None

    # Not an error: a date slightly ahead of the clock can be a timezone or a
    # scheduling artifact. Worth surfacing, not worth refusing.
    if parsed > datetime.date.today():
        problems.warning(location, f"acq_date '{acq_date}' for {session_id} is in the future.")

    return acq_date


# =============================================================================
#  Per visit
# =============================================================================

def _read_session(
    session: SubmissionSession,
    psc_id: str,
    acq_date: str | None,
    args: Args,
    problems: ProblemLog,
) -> list[PngImage]:
    """
    Collect the images of one visit, checking the directory's contents.
    """

    location = f"sub-{psc_id}/ses-{session.label}"

    png_paths: list[str] = []
    strays: list[str] = []

    for name in sorted(os.listdir(session.path)):
        path = os.path.join(session.path, name)

        if _is_hidden(name):
            continue

        if os.path.isdir(path):
            problems.warning(
                location,
                f"contains a subdirectory '{name}'. Images are expected directly inside"
                f" the visit directory, and it was not searched.",
            )
            continue

        if name.lower().endswith('.png'):
            png_paths.append(path)
        else:
            strays.append(name)

    if strays:
        problems.warning(
            location,
            f"{len(strays)} non-PNG file(s) will be ignored:"
            f" {', '.join(strays[:5])}{' ...' if len(strays) > 5 else ''}",
        )

    if not png_paths:
        problems.warning(location, "no PNG file; nothing to insert for this visit.")
        return []

    images: list[PngImage] = []

    for path in png_paths:
        file_name      = os.path.basename(path)
        image_location = f"{location}/{file_name}"

        images.append(PngImage(
            path           = path,
            psc_id         = psc_id,
            visit_label    = session.label or '',
            scan_type_name = _determine_scan_type(file_name, image_location, args, problems),
            acq_date       = acq_date,
            md5_hash       = '',
            location       = image_location,
        ))

    return images


def _determine_scan_type(
    file_name: str, location: str, args: Args, problems: ProblemLog,
) -> str:
    """
    Read the scan type off the start of a file name and check its shape.

    `echo_001.png` yields 'echo'; `ecg.png` yields 'ecg'. The character set is
    checked here rather than left to the database lookup, because "scan type
    'echo-2d' not found" is a much less useful message than saying hyphens are
    not allowed in the first place.
    """

    if args.scan_type_name is not None:
        if not SCAN_TYPE_ARG_REGEX.fullmatch(args.scan_type_name):
            problems.error(
                '--loris_scan_type',
                f"'{args.scan_type_name}' contains characters that mri_scan_type names"
                f" may not hold. Letters, numbers and underscores only.",
            )

        return args.scan_type_name

    stem = re.sub(r'\.png$', '', file_name, flags=re.IGNORECASE)

    # Everything before the first underscore, or the whole stem when the file
    # name carries no sequence number.
    scan_type_name = stem.split('_')[0]

    if not scan_type_name:
        problems.error(
            location,
            "the file name begins with an underscore, so no scan type can be read from"
            " it. Expected <scan_type>_<NNN>.png.",
        )
    elif not SCAN_TYPE_FROM_FILE_NAME_REGEX.fullmatch(scan_type_name):
        problems.error(
            location,
            f"scan type '{scan_type_name}' read from the file name contains characters"
            f" that mri_scan_type names may not hold. Letters and numbers only.",
        )

    return scan_type_name


# =============================================================================
#  The images themselves
# =============================================================================

def _check_images(images: list[PngImage], problems: ProblemLog):
    """
    Check every image is readable, non-empty and really a PNG.

    Also catches the same image submitted twice within one delivery, which the
    database duplicate check cannot see, because neither copy is inserted yet
    when the first one is checked.
    """

    hashes_seen: dict[str, str] = {}

    for image in images:
        if not os.access(image.path, os.R_OK):
            problems.error(image.location, f"not readable by {getpass.getuser()}.")
            continue

        if os.path.getsize(image.path) == 0:
            problems.error(image.location, "the file is empty.")
            continue

        try:
            with open(image.path, 'rb') as image_file:
                signature = image_file.read(len(PNG_SIGNATURE))
        except OSError as exception:
            problems.error(image.location, f"could not be read: {exception}")
            continue

        if signature != PNG_SIGNATURE:
            problems.error(
                image.location,
                "does not start with the PNG signature. It is named .png but is another"
                " format, or the transfer was truncated.",
            )
            continue

        image.md5_hash = compute_file_md5_hash(image.path)

        if image.md5_hash in hashes_seen:
            problems.warning(
                image.location,
                f"is byte-identical to {hashes_seen[image.md5_hash]} in the same"
                f" submission. Only the first will be inserted.",
            )
        else:
            hashes_seen[image.md5_hash] = image.location


def _check_duplicate_keys(path: str, column: str, location: str, problems: ProblemLog):
    """
    Report a repeated key in a TSV file.

    The readers index rows by their identifier, so a repeated row is silently
    collapsed and the submitter is never told which of the two was used.
    """

    try:
        rows = read_tsv_file(path)
    except Exception:
        # Already reported by the caller, which read the same file.
        return

    seen: set[str] = set()

    for row in rows:
        value = (row.get(column) or '').strip()

        if not value:
            continue

        if value in seen:
            problems.error(location, f"{column} '{value}' appears more than once.")

        seen.add(value)
