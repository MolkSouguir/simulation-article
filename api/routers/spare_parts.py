from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.dependencies import get_db
from db.models import SparePartModel, SparePartCreate, SparePartUpdate, SparePartRead

router = APIRouter()


def _get_or_404(db: Session, part_id: UUID) -> SparePartModel:
    part = db.query(SparePartModel).filter(SparePartModel.id == part_id).first()  # type: ignore[arg-type]
    if not part:
        raise HTTPException(status_code=404, detail="Spare part not found")
    return part


@router.get("/", response_model=list[SparePartRead])
def list_spare_parts(machine_id: UUID | None = None, db: Session = Depends(get_db)):
    query = db.query(SparePartModel).order_by(SparePartModel.id)  # type: ignore[arg-type]
    if machine_id is not None:
        query = query.filter(SparePartModel.machine_id == machine_id)  # type: ignore[arg-type]
    return query.all()


@router.get("/{part_id}", response_model=SparePartRead)
def get_spare_part(part_id: UUID, db: Session = Depends(get_db)):
    return _get_or_404(db, part_id)


@router.post("/", response_model=SparePartRead, status_code=201)
def create_spare_part(body: SparePartCreate, db: Session = Depends(get_db)):
    part = SparePartModel(**body.model_dump())
    db.add(part)
    db.flush()
    db.refresh(part)
    return part


@router.patch("/{part_id}", response_model=SparePartRead)
def update_spare_part(part_id: UUID, body: SparePartUpdate, db: Session = Depends(get_db)):
    part = _get_or_404(db, part_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(part, field, value)
    db.flush()
    db.refresh(part)
    return part


@router.delete("/{part_id}", status_code=204)
def delete_spare_part(part_id: UUID, db: Session = Depends(get_db)):
    part = _get_or_404(db, part_id)
    db.delete(part)
