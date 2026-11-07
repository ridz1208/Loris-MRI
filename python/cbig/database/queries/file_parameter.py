from typing import Any, cast

from lib.db.models.file_parameter import DbFileParameter
from sqlalchemy import CursorResult, delete
from sqlalchemy.orm import Session as Database


def delete_file_parameters(db: Database, file_id: int) -> CursorResult[Any]:
    """
    Delete a file parameter row from the database using its FileID
    """

    return cast(CursorResult[Any], db.execute(delete(DbFileParameter)
        .where(DbFileParameter.file_id == file_id)))
