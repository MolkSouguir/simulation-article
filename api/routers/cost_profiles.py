from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.dependencies import get_db
from db.models import (
    MaintenanceCostDataModel,
    MaintenanceCostDataCreate,
    MaintenanceCostDataUpdate,
    MaintenanceCostDataRead,
)

router = APIRouter()


def _get_or_404(db: Session, profile_id: UUID) -> MaintenanceCostDataModel:
    profile = db.query(MaintenanceCostDataModel).filter(MaintenanceCostDataModel.id == profile_id).first()  # type: ignore[arg-type]
    if not profile:
        raise HTTPException(status_code=404, detail="Cost profile not found")
    return profile


@router.get("/", response_model=list[MaintenanceCostDataRead])
def list_cost_profiles(db: Session = Depends(get_db)):
    return db.query(MaintenanceCostDataModel).order_by(MaintenanceCostDataModel.id).all() # type: ignore[arg-type]


@router.get("/{profile_id}", response_model=MaintenanceCostDataRead)
def get_cost_profile(profile_id: UUID, db: Session = Depends(get_db)):
    return _get_or_404(db, profile_id)


@router.post("/", response_model=MaintenanceCostDataRead, status_code=201)
def create_cost_profile(body: MaintenanceCostDataCreate, db: Session = Depends(get_db)):
    profile = MaintenanceCostDataModel(**body.model_dump())
    db.add(profile)
    db.flush()
    db.refresh(profile)
    return profile


@router.patch("/{profile_id}", response_model=MaintenanceCostDataRead)
def update_cost_profile(profile_id: UUID, body: MaintenanceCostDataUpdate, db: Session = Depends(get_db)):
    profile = _get_or_404(db, profile_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)
    db.flush()
    db.refresh(profile)
    return profile


@router.delete("/{profile_id}", status_code=204)
def delete_cost_profile(profile_id: UUID, db: Session = Depends(get_db)):
    profile = _get_or_404(db, profile_id)
    db.delete(profile)
