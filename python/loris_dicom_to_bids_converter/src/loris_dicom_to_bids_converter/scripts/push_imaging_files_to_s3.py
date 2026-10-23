#!/usr/bin/env python

"""Script that takes file paths in the database and push them to an S3 bucket"""

import os

from lib.lorisgetopt import LorisGetOpt

from loris_dicom_to_bids_converter.push_imaging_files_to_s3_pipeline import PushImagingFilesToS3Pipeline


def main():
    usage = (
        "\n"

        "********************************************************************\n"
        " PUSH IMAGING FILES TO AMAZON S3 BUCKET SCRIPT\n"
        "********************************************************************\n"
        "The program gets all the files associated to an upload ID and push them to an Amazon S3 bucket.\n\n"

        "usage  : push-imaging-files-to-s3 -p <profile> -u <upload_id> ...\n\n"

        "options: \n"
        "\t-p, --profile            : Name of the python database config file in config\n"
        "\t-u, --upload_id          : ID of the upload (from mri_upload) related to the DICOM archive to process\n"
        "\t-v, --verbose            : If set, be verbose\n\n"

        "required options are: \n"
        "\t--upload_id\n"
    )

    options_dict = {
        "profile": {
            "value": None, "required": False, "expect_arg": True, "short_opt": "p", "is_path": False
        },
        "upload_id": {
            "value": None, "required": True, "expect_arg": True, "short_opt": "u", "is_path": False
        },
        "verbose": {
            "value": False, "required": False, "expect_arg": False, "short_opt": "v", "is_path": False
        },
        "help": {
            "value": False, "required": False, "expect_arg": False, "short_opt": "h", "is_path": False
        },
    }

    # get the options provided by the user
    loris_getopt_obj = LorisGetOpt(usage, options_dict, os.path.basename(__file__[:-3]))

    # push to S3 pipeline
    PushImagingFilesToS3Pipeline(loris_getopt_obj, os.path.basename(__file__[:-3]))


if __name__ == "__main__":
    main()
