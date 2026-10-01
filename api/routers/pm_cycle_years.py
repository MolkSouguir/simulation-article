from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.dependencies import get_db
from db.models import (
    PMCycleYearModel,
    PMCycleYearPartModel,
    PMCycleYearCreate,
    PMCycleYearUpdate,
    PMCycleYearRead,
    PreventiveMaintenanceModel,
)

router = APIRouter()

# pm_id comes from the route prefix in api/main.py:
# /api/preventive-maintenance/{pm_id}/cycle-years


def _get_pm_or_404(db: Session, pm_id: UUID) -> PreventiveMaintenanceModel:
    schedule = db.query(PreventiveMaintenanceModel).filter(PreventiveMaintenanceModel.id == pm_id).first()  # type: ignore[arg-type]
    if not schedule:
        raise HTTPException(status_code=404, detail="PM program not found")
    return schedule


def _get_cycle_year_or_404(db: Session, pm_id: UUID, cycle_year_id: UUID) -> PMCycleYearModel:
    cycle_year = (
        db.query(PMCycleYearModel)
        .filter(PMCycleYearModel.id == cycle_year_id, PMCycleYearModel.preventive_maintenance_id == pm_id)  # type: ignore[arg-type]
        .first()
    )
    if not cycle_year:
        raise HTTPException(status_code=404, detail="Cycle year not found")
    return cycle_year


@router.post("/", response_model=PMCycleYearRead, status_code=201)
def create_cycle_year(pm_id: UUID, body: PMCycleYearCreate, db: Session = Depends(get_db)):
    _get_pm_or_404(db, pm_id)
    cycle_year = PMCycleYearModel(
        order=body.order,
        preventive_maintenance_hours=body.preventive_maintenance_hours,
        hourly_labor_cost=body.hourly_labor_cost,
        pm_year_cost=body.pm_year_cost,
        preventive_maintenance_id=pm_id,
    )
    db.add(cycle_year)
    db.flush()
    for part_type in body.parts:
        db.add(PMCycleYearPartModel(spare_part_type=part_type, pm_cycle_year_id=cycle_year.id))
    db.flush()
    db.refresh(cycle_year)
    return cycle_year


@router.patch("/{cycle_year_id}", response_model=PMCycleYearRead)
def update_cycle_year(pm_id: UUID, cycle_year_id: UUID, body: PMCycleYearUpdate, db: Session = Depends(get_db)):
    cycle_year = _get_cycle_year_or_404(db, pm_id, cycle_year_id)
    for field, value in body.model_dump(exclude_unset=True, exclude={"parts"}).items():
        setattr(cycle_year, field, value)
    # A new parts list replaces the old one completely.
    if body.parts is not None:
        db.query(PMCycleYearPartModel).filter(PMCycleYearPartModel.pm_cycle_year_id == cycle_year_id).delete()  # type: ignore[arg-type]
        for part_type in body.parts:
            db.add(PMCycleYearPartModel(spare_part_type=part_type, pm_cycle_year_id=cycle_year_id))
    db.flush()
    db.refresh(cycle_year)
    return cycle_year


@router.delete("/{cycle_year_id}", status_code=204)
def delete_cycle_year(pm_id: UUID, cycle_year_id: UUID, db: Session = Depends(get_db)):
    cycle_year = _get_cycle_year_or_404(db, pm_id, cycle_year_id)
    db.delete(cycle_year)
