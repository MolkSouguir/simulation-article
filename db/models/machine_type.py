"""
db/models/machine_type.py

Machine types stored in the database, so new ones can be added from the app
(MachineTypeEnum only lists the two defaults).
"""
import uuid
from sqlmodel import SQLModel, Field


class MachineTypeBase(SQLModel):
    name: str


class MachineTypeModel(MachineTypeBase, table=True):
    __tablename__ = "machine_type"  # type: ignore

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(unique=True)


class MachineTypeCreate(MachineTypeBase):
    pass


class MachineTypeUpdate(SQLModel):
    name: str | None = None


class MachineTypeRead(MachineTypeBase):
    id: uuid.UUID
