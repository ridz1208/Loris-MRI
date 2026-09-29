#!/usr/bin/env python

"""Script to insert a submitted directory of PNG images into LORIS."""

import os
from typing import Any

from lib.import_png_dataset.args import Args
from lib.import_png_dataset.main import import_png_dataset
from lib.lorisgetopt import LorisGetOpt
from lib.make_env import make_env

__license__ = "GPLv3"


def pack_args(options_dict: dict[str, Any]) -> Args:
    return Args(
        png_dir_path   = os.path.normpath(options_dict['directory']['value']),
        subject_label  = strip_prefix(options_dict['subject']['value'], 'sub-'),
        session_label  = strip_prefix(options_dict['visit']['value'], 'ses-'),
        scan_type_name = options_dict['loris_scan_type']['value'],
        validate_only  = options_dict['validate_only']['value'],
        create_pic     = options_dict['create_pic']['value'],
        verbose        = options_dict['verbose']['value'],
    )


def strip_prefix(value: str | None, prefix: str) -> str | None:
    """
    Accept a filter given either with or without its sub-/ses- prefix.
    """

    if value is None:
        return None

    return value[len(prefix):] if value.startswith(prefix) else value


def main():
    usage = (
        "\n"
        "The program inserts a submitted directory of PNG images, such as\n"
        "echocardiogram stills or ECG traces, into the files table. A PNG carries\n"
        "no header the pipeline can read, so everything comes from the directory\n"
        "names and the file names.\n"
        "\n"
        "Expected layout:\n"
        "\t<directory>/participants.tsv\n"
        "\t<directory>/sub-<PSCID>/sessions.tsv            (optional)\n"
        "\t<directory>/sub-<PSCID>/ses-<VisitLabel>/<scan_type>_<NNN>.png\n"
        "\n"
        "participants.tsv lists the participants the submission should contain.\n"
        "sessions.tsv is optional, as in a BIDS dataset: the ses- directories\n"
        "define the visits, and the file only supplies acquisition dates. The\n"
        "scan type is read from the start of each file name and must already\n"
        "exist in the mri_scan_type table.\n"
        "\n"
        "The whole submission is validated first and every problem is reported\n"
        "together. Any error stops the run with nothing inserted.\n"
        "\n"
        "usage  : run_png_insertion.py -d <png_directory> -p <profile>\n"
        "\n"
        "options: \n"
        "\t-p, --profile          : name of the python database config file in"
        " dicom-archive/.loris_mri\n"
        "\t-d, --directory        : directory of PNG images to parse & insert into LORIS\n"
        "\t-s, --subject          : restrict the run to one participant, as sub-<PSCID>\n"
        "\t-V, --visit            : restrict the run to one visit, as ses-<VisitLabel>\n"
        "\t-t, --loris_scan_type  : LORIS scan type from the mri_scan_type table. Overrides\n"
        "\t                         the scan type read from the file names\n"
        "\t-n, --validate_only    : run every check and report, then exit without inserting\n"
        "\t-c, --create_pic       : create the pics to be displayed in the imaging browser\n"
        "\t-v, --verbose          : be verbose\n"
    )

    options_dict = {
        "profile": {
            "value": None, "required": True, "expect_arg": True, "short_opt": "p", "is_path": False
        },
        "directory": {
            "value": None, "required": True, "expect_arg": True, "short_opt": "d", "is_path": True
        },
        "subject": {
            "value": None, "required": False, "expect_arg": True, "short_opt": "s", "is_path": False
        },
        "visit": {
            "value": None, "required": False, "expect_arg": True, "short_opt": "V", "is_path": False
        },
        "loris_scan_type": {
            "value": None, "required": False, "expect_arg": True, "short_opt": "t", "is_path": False
        },
        "validate_only": {
            "value": False, "required": False, "expect_arg": False, "short_opt": "n",
            "is_path": False
        },
        "create_pic": {
            "value": False, "required": False, "expect_arg": False, "short_opt": "c",
            "is_path": False
        },
        "verbose": {
            "value": False, "required": False, "expect_arg": False, "short_opt": "v",
            "is_path": False
        },
        "help": {
            "value": False, "required": False, "expect_arg": False, "short_opt": "h",
            "is_path": False
        },
    }

    # Get the CLI arguments and initiate the environment.
    loris_getopt_obj = LorisGetOpt(usage, options_dict, os.path.basename(__file__[:-3]))
    env = make_env(loris_getopt_obj)

    args = pack_args(loris_getopt_obj.options_dict)

    import_png_dataset(env, args)


if __name__ == '__main__':
    main()
