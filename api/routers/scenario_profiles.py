from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlmodel import col

from api.dependencies import get_db
from db.models import (
    ScenarioProfileModel,
    ScenarioProfileCreate,
    ScenarioProfileUpdate,
    ScenarioProfileRead,
)

router = APIRouter()


def _get_or_404(db: Session, profile_id: UUID) -> ScenarioProfileModel:
    profile = db.query(ScenarioProfileModel).filter(col(ScenarioProfileModel.id) == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Scenario profile not found")
    return profile


@router.get("/", response_model=list[ScenarioProfileRead])
def list_scenario_profiles(db: Session = Depends(get_db)):
    return db.query(ScenarioProfileModel).order_by(ScenarioProfileModel.name).all()


@router.get("/{profile_id}", response_model=ScenarioProfileRead)
def get_scenario_profile(profile_id: UUID, db: Session = Depends(get_db)):
    return _get_or_404(db, profile_id)


@router.post("/", response_model=ScenarioProfileRead, status_code=201)
def create_scenario_profile(body: ScenarioProfileCreate, db: Session = Depends(get_db)):
    profile = ScenarioProfileModel(name=body.name, config=body.config)
    db.add(profile)
    db.flush()
    db.refresh(profile)
    return profile


@router.patch("/{profile_id}", response_model=ScenarioProfileRead)
def update_scenario_profile(profile_id: UUID, body: ScenarioProfileUpdate, db: Session = Depends(get_db)):
    profile = _get_or_404(db, profile_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)
    db.flush()
    db.refresh(profile)
    return profile


@router.delete("/{profile_id}", status_code=204)
def delete_scenario_profile(profile_id: UUID, db: Session = Depends(get_db)):
    profile = _get_or_404(db, profile_id)
    db.delete(profile)
