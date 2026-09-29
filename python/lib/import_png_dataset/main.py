from lib.config import get_data_dir_path_config
from lib.env import Env
from lib.import_png_dataset.args import Args
from lib.import_png_dataset.check import check_against_database, check_environment
from lib.import_png_dataset.insert import insert_image
from lib.import_png_dataset.problems import ProblemLog
from lib.import_png_dataset.submission import read_submission
from lib.logging import log


def import_png_dataset(env: Env, args: Args):
    """
    Validate a submitted directory of PNG images, then insert it.

    Everything is checked before anything is written, and all problems are
    reported together. Any error stops the run with nothing inserted; warnings
    are reported and the run continues.
    """

    data_dir_path = get_data_dir_path_config(env)

    log(env, f"Reading PNG submission at {args.png_dir_path}...")

    problems = ProblemLog()

    check_environment(env, data_dir_path, args, problems)

    images = read_submission(args, problems)

    resolved = check_against_database(env, images, problems)

    # Exits with the full report if anything found was an error.
    problems.report(env, args.png_dir_path, len(images))

    if args.validate_only:
        log(env, "Validation only: nothing was inserted.")
        return

    inserted = 0

    for image in images:
        if insert_image(env, data_dir_path, image, resolved, args.create_pic):
            inserted += 1

    log(
        env,
        f"{inserted} file(s) inserted, {len(images) - inserted} already registered,"
        f" out of {len(images)} validated.",
    )
