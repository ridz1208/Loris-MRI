from dataclasses import dataclass


@dataclass
class Args:
    """
    Command line arguments of the PNG insertion pipeline.
    """

    png_dir_path: str
    subject_label: str | None
    session_label: str | None
    scan_type_name: str | None
    validate_only: bool
    create_pic: bool
    verbose: bool
