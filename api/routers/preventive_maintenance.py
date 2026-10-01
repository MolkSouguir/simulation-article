from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from api.dependencies import get_db
from db.models import (
    PreventiveMaintenanceModel,
    PMCycleYearModel,
    PMCycleYearPartModel,
    PreventiveMaintenanceCreate,
    PreventiveMaintenanceUpdate,
    PreventiveMaintenanceRead,
)

router = APIRouter()


def _load(db: Session, pm_id: UUID) -> PreventiveMaintenanceModel:
    """PM programme with its cycle years and their parts, or a 404."""
    schedule = (
        db.query(PreventiveMaintenanceModel)
        .options(
            joinedload(PreventiveMaintenanceModel.cycle_years)  # type: ignore[arg-type]
            .joinedload(PMCycleYearModel.parts)  # type: ignore[arg-type]
        )
        .filter(PreventiveMaintenanceModel.id == pm_id)  # type: ignore[arg-type]
        .first()
    )
    if not schedule:
        raise HTTPException(status_code=404, detail="PM program not found")
    return schedule


@router.get("/", response_model=list[PreventiveMaintenanceRead])
def list_pm_programs(db: Session = Depends(get_db)):
    return (
        db.query(PreventiveMaintenanceModel)
        .options(
            joinedload(PreventiveMaintenanceModel.cycle_years)  # type: ignore[arg-type]
            .joinedload(PMCycleYearModel.parts)  # type: ignore[arg-type]
        )
        .order_by(PreventiveMaintenanceModel.id)  # type: ignore[arg-type]
        .all()
    )


@router.get("/{pm_id}", response_model=PreventiveMaintenanceRead)
def get_pm_program(pm_id: UUID, db: Session = Depends(get_db)):
    return _load(db, pm_id)


@router.post("/", response_model=PreventiveMaintenanceRead, status_code=201)
def create_pm_program(body: PreventiveMaintenanceCreate, db: Session = Depends(get_db)):
    schedule = PreventiveMaintenanceModel(name=body.name, years_interval=body.years_interval)
    db.add(schedule)
    db.flush()

    for cycle_year_data in body.cycle_years:
        cycle_year = PMCycleYearModel(
            order=cycle_year_data.order,
            preventive_maintenance_hours=cycle_year_data.preventive_maintenance_hours,
            hourly_labor_cost=cycle_year_data.hourly_labor_cost,
            pm_year_cost=cycle_year_data.pm_year_cost,
            preventive_maintenance_id=schedule.id,
        )
        db.add(cycle_year)
        db.flush()
        for part_type in cycle_year_data.parts:
            db.add(PMCycleYearPartModel(spare_part_type=part_type, pm_cycle_year_id=cycle_year.id))

    db.flush()
    return _load(db, schedule.id)


@router.patch("/{pm_id}", response_model=PreventiveMaintenanceRead)
def update_pm_program(pm_id: UUID, body: PreventiveMaintenanceUpdate, db: Session = Depends(get_db)):
    schedule = _load(db, pm_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(schedule, field, value)
    db.flush()
    return _load(db, pm_id)


@router.delete("/{pm_id}", status_code=204)
def delete_pm_program(pm_id: UUID, db: Session = Depends(get_db)):
    schedule = _load(db, pm_id)
    db.delete(schedule)
