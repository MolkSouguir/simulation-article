from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from api.dependencies import get_db
from db.models import MachineModel, MachineCreate, MachineUpdate, MachineRead

router = APIRouter()


def _get_or_404(db: Session, machine_id: UUID) -> MachineModel:
    machine = (
        db.query(MachineModel)
        .options(joinedload(MachineModel.spare_parts))  # type: ignore[arg-type]
        .filter(MachineModel.id == machine_id)  # type: ignore[arg-type]
        .first()
    )
    if not machine:
        raise HTTPException(status_code=404, detail="Machine not found")
    return machine


@router.get("/", response_model=list[MachineRead])
def list_machines(db: Session = Depends(get_db)):
    return (
        db.query(MachineModel)
        .options(joinedload(MachineModel.spare_parts))  # type: ignore[arg-type]
        .order_by(MachineModel.id)  # type: ignore[arg-type]
        .all()
    )


@router.get("/{machine_id}", response_model=MachineRead)
def get_machine(machine_id: UUID, db: Session = Depends(get_db)):
    return _get_or_404(db, machine_id)


@router.post("/", response_model=MachineRead, status_code=201)
def create_machine(body: MachineCreate, db: Session = Depends(get_db)):
    machine = MachineModel(**body.model_dump())
    db.add(machine)
    db.flush()
    db.refresh(machine)
    return machine


@router.patch("/{machine_id}", response_model=MachineRead)
def update_machine(machine_id: UUID, body: MachineUpdate, db: Session = Depends(get_db)):
    machine = _get_or_404(db, machine_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(machine, field, value)
    db.flush()
    db.refresh(machine)
    return machine


@router.delete("/{machine_id}", status_code=204)
def delete_machine(machine_id: UUID, db: Session = Depends(get_db)):
    machine = _get_or_404(db, machine_id)
    db.delete(machine)
