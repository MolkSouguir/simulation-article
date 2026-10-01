"""
api/routers/tools.py

POST /api/tools/weibull-analysis

Takes an Excel file (.xlsx or .xlsm) with one sheet per machine model, in the
format of the GMAO intervention export, and returns for each model the Weibull
parameters (beta, eta), the mean repair time and the mean cost.

Columns read from the GMAO export (index from 0, from its header row):

    Index  Excel col  Header (French)                            Used for
    -----  ---------  -----------------------------------------  ------------------------
    9      J          Matériel                                   machine ID (group TBFs)
    11     L          Coût réalisé opérations                    parts cost (€)
    12     M          Coût réalisé main d'oeuvre                 labour cost (€)
    15     P          Durée des occupations main d'oeuvre        MTTR (timedelta)
    23     X          Date/heure de début de l'intervention      failure timestamp

These positions are fixed in the code: if the export's columns move, update
them in _detect_columns.
"""

import io
import datetime
from typing import Any

import numpy as np
import openpyxl
from fastapi import APIRouter, HTTPException, UploadFile, File
from scipy.stats import weibull_min

router = APIRouter()

# Summary or raw-data sheets that aren't a machine model
SKIP_SHEETS = {"feuil1", "feuil2", "feuil3", "summary", "résumé", "resume"}


def _to_float(value: object) -> float:
    """Cell value as a float. Anything that isn't a number counts as 0."""
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _fit_weibull_mle(tbf_days: list[float]) -> tuple[float, float]:
    """
    Fit a two-parameter Weibull distribution by maximum likelihood.

    Returns (beta, eta), with eta in the same unit as tbf_days. scipy's
    weibull_min uses f(x) = (c/scale) (x/scale)^(c-1) exp(-(x/scale)^c),
    so its c is our beta and its scale our eta.
    """
    data = np.array(tbf_days, dtype=float)
    # loc is fixed at 0 to get the two-parameter form
    shape, _, scale = weibull_min.fit(data, floc=0)
    return float(shape), float(scale)


def _detect_columns(header_row: tuple) -> dict[str, int]:
    """
    Column positions, read from the header row.

    Two layouts are supported: the file produced by our merge script (English
    headers such as 'Machine ID', 'Nature', 'Cost Ops'), and the raw GMAO
    export, whose columns are at fixed positions.
    """
    normalized_map = {
        "machine id":  "machine_id",
        "nature":      "nature",
        "cost ops":    "cost_ops",
        "cost labor":  "cost_labor",
        "mttr (h)":    "mttr_h",
        "start datetime": "start_dt",
    }
    detected: dict[str, int] = {}
    for column_index, cell in enumerate(header_row):
        if cell is None:
            continue
        key = str(cell).strip().lower()
        if key in normalized_map:
            detected[normalized_map[key]] = column_index

    if detected:
        return detected

    # Raw GMAO export: fixed positions
    return {
        "machine_id": 9,
        "nature":     13,
        "cost_ops":   11,
        "cost_labor": 12,
        "mttr_td":    15,     # no "mttr_h": the repair time is a timedelta here instead
        "start_dt":   23,
    }


def _parse_sheet(sheet) -> dict[str, Any]:
    """Statistics for one sheet (one machine model)."""
    tbf_days_all: list[float] = []
    mttr_hours_all: list[float] = []
    cost_all: list[float] = []

    # Failure dates of each machine
    machine_dates: dict[str, list[datetime.datetime]] = {}

    header = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True))
    columns = _detect_columns(header)
    normalized = "mttr_h" in columns and columns.get("mttr_h") is not None

    for row in sheet.iter_rows(min_row=2, values_only=True):
        if not row or row[columns["machine_id"]] is None:
            continue

        # Only corrective interventions (CORR_INT, CORR_EXT) are failures.
        # Preventive (PREV_*) and control (CTRL_*) visits are left out: mixed
        # into the times between failures they push beta below 1.
        nature = str(row[columns["nature"]]).strip().upper() if row[columns["nature"]] is not None else ""
        if not nature.startswith("CORR"):
            continue

        machine_id = str(row[columns["machine_id"]]).strip()
        start_dt = row[columns["start_dt"]]
        cost_ops   = _to_float(row[columns["cost_ops"]])
        cost_labor = _to_float(row[columns["cost_labor"]])

        cost_all.append(cost_ops + cost_labor)

        if normalized:
            # Merged file: repair time already in hours
            mttr_value = row[columns["mttr_h"]]
            if isinstance(mttr_value, (int, float)) and mttr_value > 0:
                mttr_hours_all.append(float(mttr_value))
        else:
            # Raw GMAO export: repair time as a timedelta
            duration = row[columns["mttr_td"]]
            if isinstance(duration, datetime.timedelta):
                mttr_hours_all.append(duration.total_seconds() / 3600.0)

        if isinstance(start_dt, datetime.datetime) and machine_id:
            machine_dates.setdefault(machine_id, []).append(start_dt)

    # Times between consecutive failures of the same machine
    n_machines = len(machine_dates)
    n_failures = sum(len(dates) for dates in machine_dates.values())

    for dates in machine_dates.values():
        sorted_dates = sorted(dates)
        for failure_index in range(1, len(sorted_dates)):
            delta_days = (sorted_dates[failure_index] - sorted_dates[failure_index - 1]).total_seconds() / 86400.0
            if delta_days > 0:
                tbf_days_all.append(delta_days)

    result: dict[str, Any] = {
        "n_machines": n_machines,
        "n_failures": n_failures,
        "n_tbf": len(tbf_days_all),
        "mean_mttr_hours": round(np.mean(mttr_hours_all).item(), 3) if mttr_hours_all else None,
        "mean_cost_eur": round(np.mean(cost_all).item(), 2) if cost_all else None,
        "beta": None,
        "eta_days": None,
        "eta_years": None,
        "warning": None,
    }

    if len(tbf_days_all) >= 3:
        try:
            beta, eta_days = _fit_weibull_mle(tbf_days_all)
            result["beta"] = round(beta, 4)
            result["eta_days"] = round(eta_days, 2)
            result["eta_years"] = round(eta_days / 365.25, 4)
        except Exception as exc:
            result["warning"] = f"Weibull fit failed: {exc}"
    else:
        result["warning"] = f"Not enough TBF points ({len(tbf_days_all)}) to fit Weibull (need ≥ 3)"

    return result


@router.post("/weibull-analysis")
async def weibull_analysis(file: UploadFile = File(...)):
    """Read the uploaded Excel file and return the Weibull parameters of each model sheet."""
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="Only .xlsx / .xlsm files are supported.")

    contents = await file.read()
    try:
        workbook = openpyxl.load_workbook(io.BytesIO(contents), read_only=True, keep_vba=True, data_only=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not open workbook: {exc}")

    results = []
    for sheet_name in workbook.sheetnames:
        if sheet_name.strip().lower() in SKIP_SHEETS:
            continue
        sheet = workbook[sheet_name]
        stats = _parse_sheet(sheet)
        results.append({"model": sheet_name, **stats})

    workbook.close()
    return {"models": results}
