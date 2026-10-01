from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session, load_only, defer
from sqlmodel import col

from api.dependencies import get_db
from db.models import (
    SimulationRunModel,
    SimulationRunSummary,
    SimulationRunUpdate,
    SimulationRunRead,
)

router = APIRouter()

_SUMMARY_COLUMNS = [getattr(SimulationRunModel, f) for f in SimulationRunSummary.model_fields]


def _get_or_404(db: Session, run_id: UUID, *options) -> SimulationRunModel:
    run = db.query(SimulationRunModel).options(*options).filter(col(SimulationRunModel.id) == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Simulation run not found")
    return run


@router.get("/", response_model=list[SimulationRunSummary])
def list_simulation_runs(db: Session = Depends(get_db)):
    # Only the summary columns: the saved request and result can be several MB per run.
    return (
        db.query(SimulationRunModel)
        .options(load_only(*_SUMMARY_COLUMNS))
        .order_by(col(SimulationRunModel.created_at).desc())
        .all()
    )


@router.get("/{run_id}", response_model=SimulationRunRead)
def get_simulation_run(run_id: UUID, db: Session = Depends(get_db)):
    # The chart events are only read by /charts, one alternative at a time
    return _get_or_404(db, run_id, defer(SimulationRunModel.chart_events))


@router.get("/{run_id}/charts")
def get_simulation_run_charts(run_id: UUID, alternative: str, db: Session = Depends(get_db)):
    """Timeline and availability charts (Plotly JSON) of one alternative of a saved run."""
    from api.routers.simulation import build_chart_json

    run = _get_or_404(db, run_id, load_only(SimulationRunModel.chart_events))   # the id is always loaded
    chart_data = (run.chart_events or {}).get(alternative)
    if chart_data is None:
        raise HTTPException(status_code=404, detail=f"No chart data for alternative '{alternative}' in this run")
    timeline_json, availability_json = build_chart_json(alternative, chart_data)
    return {"alternative": alternative, "timeline_json": timeline_json, "availability_json": availability_json}


@router.get("/{run_id}/pdf")
def download_simulation_run_pdf(run_id: UUID, db: Session = Depends(get_db)):
    """
    PDF report of a saved run: every input, then the Ranking, decision details,
    Sensitivity and Statistics tabs with their charts. The event timeline and
    availability charts are left out.
    """
    from analysis.pdf_report import build_run_pdf, pdf_filename

    run = _get_or_404(db, run_id, defer(SimulationRunModel.chart_events))
    try:
        pdf_bytes = build_run_pdf(
            name=run.name, created_at=run.created_at, request=run.request, result=run.result,
        )
    except Exception as report_error:
        import traceback
        raise HTTPException(status_code=500, detail=str(report_error) + "\n" + traceback.format_exc())
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{pdf_filename(run.name, run.created_at)}"'},
    )


@router.patch("/{run_id}", response_model=SimulationRunSummary)
def update_simulation_run(run_id: UUID, body: SimulationRunUpdate, db: Session = Depends(get_db)):
    run = _get_or_404(db, run_id, defer(SimulationRunModel.chart_events))
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(run, field, value)
    db.flush()
    db.refresh(run)
    return run


@router.delete("/{run_id}", status_code=204)
def delete_simulation_run(run_id: UUID, db: Session = Depends(get_db)):
    run = _get_or_404(db, run_id)
    db.delete(run)
