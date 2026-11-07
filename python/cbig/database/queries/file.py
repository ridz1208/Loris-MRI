from collections.abc import Sequence
from typing import Any, cast

from lib.db.models.candidate import DbCandidate
from lib.db.models.file import DbFile
from lib.db.models.session import DbSession
from sqlalchemy import CursorResult, delete, select
from sqlalchemy.orm import Session as Database


def delete_file_entry(db: Database, file_id: int):
    """
    Delete from the database a file entry based on a file ID.
    """

    return cast(CursorResult[Any], db.execute(delete(DbFile)
        .where(DbFile.id == file_id)))


def get_files_with_candidate_id(db: Database, candidate_id: int) -> Sequence[DbFile]:
    """
    Get the imaging files from the database associated with a given candidate ID.
    """

    return db.execute(select(DbFile)
        .join(DbFile.session)
        .join(DbSession.candidate)
        .where(DbCandidate.cand_id == candidate_id)
    ).scalars().all()
