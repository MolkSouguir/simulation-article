from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlmodel import col

from api.dependencies import get_db
from db.models.machine import MachineModel
from db.models.machine_type import MachineTypeModel, MachineTypeCreate, MachineTypeUpdate, MachineTypeRead

router = APIRouter()


def _get_or_404(db: Session, machine_type_id: UUID) -> MachineTypeModel:
    machine_type = db.query(MachineTypeModel).filter(col(MachineTypeModel.id) == machine_type_id).first()
    if not machine_type:
        raise HTTPException(status_code=404, detail="Machine type not found")
    return machine_type


@router.get("/", response_model=list[MachineTypeRead])
def list_machine_types(db: Session = Depends(get_db)):
    return db.query(MachineTypeModel).order_by(MachineTypeModel.name).all()


@router.post("/", response_model=MachineTypeRead, status_code=201)
def create_machine_type(body: MachineTypeCreate, db: Session = Depends(get_db)):
    existing = db.query(MachineTypeModel).filter(col(MachineTypeModel.name) == body.name).first()
    if existing:
        raise HTTPException(status_code=409, detail="Machine type name already exists")
    machine_type = MachineTypeModel(**body.model_dump())
    db.add(machine_type)
    db.flush()
    db.refresh(machine_type)
    return machine_type


@router.patch("/{machine_type_id}", response_model=MachineTypeRead)
def update_machine_type(machine_type_id: UUID, body: MachineTypeUpdate, db: Session = Depends(get_db)):
    machine_type = _get_or_404(db, machine_type_id)
    if body.name is not None:
        existing = db.query(MachineTypeModel).filter(
            col(MachineTypeModel.name) == body.name,
            col(MachineTypeModel.id) != machine_type_id,
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail="Machine type name already exists")
        machine_type.name = body.name
    db.flush()
    db.refresh(machine_type)
    return machine_type


@router.delete("/{machine_type_id}", status_code=204)
def delete_machine_type(machine_type_id: UUID, db: Session = Depends(get_db)):
    machine_type = _get_or_404(db, machine_type_id)
    # Machines reference the type by name, so it can't go while machines still use it.
    in_use = db.query(MachineModel).filter(col(MachineModel.machine_type) == machine_type.name).count()
    if in_use:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete '{machine_type.name}': {in_use} machine{'s' if in_use != 1 else ''} "
                    f"still {'use' if in_use != 1 else 'uses'} this type. Reassign or remove them first.",
        )
    db.delete(machine_type)
