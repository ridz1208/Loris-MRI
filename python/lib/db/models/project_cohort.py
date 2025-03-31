from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

import lib.db.models.project as db_project
from lib.db.base import Base


class DbProjectCohort(Base):
    __tablename__ = 'project_subproject_rel'

    id         : Mapped[int] = mapped_column('ProjectSubprojectRelID', primary_key=True)
    project_id : Mapped[int] = mapped_column('ProjectID', ForeignKey('Project.ProjectID'))
    cohort_id  : Mapped[int] = mapped_column('SubprojectID')

    project : Mapped['db_project.DbProject'] = relationship('DbProject')
