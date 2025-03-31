from typing import Optional

from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import Base


class DbCohort(Base):
    __tablename__ = 'subproject'

    id                             : Mapped[int]            = mapped_column('SubprojectID', primary_key=True)
    name                           : Mapped[str]            = mapped_column('title')
    use_edc                        : Mapped[Optional[bool]] = mapped_column('useEDC')
    window_difference              : Mapped[Optional[str]]  = mapped_column('WindowDifference')
    recruitment_target             : Mapped[Optional[int]]  = mapped_column('RecruitmentTarget')
