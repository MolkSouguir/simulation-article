"""
api/routers/simulation.py

POST /run       Runs the simulations and the decision method, and returns
                everything the Simulation page shows: ranking, matrices,
                sensitivity, statistics, bootstrap, cost variation, parameter
                table and the chart data. The run is also saved for History.
POST /report    Turns a RunResult into the Excel report.
GET  /criteria  The criteria the user can choose from.
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, field_validator

router = APIRouter()


# Criteria the user can choose from. input_type says where the value comes from:
#   threshold_int  a whole number per alternative, which is also used as the
#                  normal or crisis threshold of the simulation
#   computed       nothing to enter, the value comes from the simulation
#   qualitative    a score from 0 to 10 per alternative
#   daily_hours    target operating hours per day per alternative, scored as
#                  worked / scheduled hours (see _attach_hours_criterion in
#                  services/ahp_service.py)

CRITERIA_CATALOG = [
    {
        "attribute_name": "normal_availability",
        "name": "Available Machines — Normal",
        "input_type": "threshold_int",
        "minimize": False,
    },
    {
        "attribute_name": "crisis_availability",
        "name": "Available Machines — Crisis",
        "input_type": "threshold_int",
        "minimize": False,
    },
    {
        "attribute_name": "normal_hours_availability",
        "name": "Availability — Normal",
        "input_type": "daily_hours",
        "minimize": False,
    },
    {
        "attribute_name": "crisis_hours_availability",
        "name": "Availability — Crisis",
        "input_type": "daily_hours",
        "minimize": False,
    },
    {
        "attribute_name": "total_cost",
        "name": "Total Cost",
        "input_type": "computed",
        "minimize": True,
    },
    {
        "attribute_name": "staff_satisfaction",
        "name": "Staff Satisfaction",
        "input_type": "qualitative",
        "minimize": False,
    },
    {
        "attribute_name": "clinical_features",
        "name": "Sensitivity to Obsolescence",
        "input_type": "qualitative",
        "minimize": False,
    },
    {
        "attribute_name": "logistics_procurement",
        "name": "Easiness of Logistics & Procurement",
        "input_type": "qualitative",
        "minimize": False,
    },
]

# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class CriteriaConfig(BaseModel):
    attribute_name: str
    name: str
    minimize: bool = False
    input_type: str  # "threshold_int" | "computed" | "qualitative"


class SimulationConfig(BaseModel):
    name: str = ""
    machine_number: int
    replacement_period: int
    machine_type: str = "ventilator"
    session_days: list[int] = [0, 1, 2, 3, 4, 5, 6]
    shift_durations: list[float] = [24.0]
    # Score per criterion (by attribute_name). For threshold_int criteria it is
    # the normal or crisis threshold. Qualitative scores are passed on as they
    # are, and computed criteria need no entry.
    scores: dict[str, float] = {}

    @field_validator("shift_durations")
    @classmethod
    def _validate_shift_durations(cls, value: list[float]) -> list[float]:
        if not value:
            raise ValueError("shift_durations must contain at least one shift")
        if any(hours <= 0 for hours in value):
            raise ValueError("each shift duration must be positive")
        if sum(value) > 24:
            raise ValueError("total shift hours per day must not exceed 24")
        return value


class RunRequest(BaseModel):
    name: str = ""                               # label on the History page, defaults to the method + fleet type
    method: str = "AHP"                          # "AHP" | "TOPSIS" | "ELECTRE2"
    configurations: list[SimulationConfig]
    criteria_config: list[CriteriaConfig]
    # AHP: upper triangle of the criteria comparison matrix (Saaty 1 to 9),
    # row by row: n * (n - 1) / 2 values.
    pairwise_upper_triangle: list[float] = []
    # TOPSIS and ELECTRE II: one weight per criterion, any positive numbers
    # (they are normalised here).
    direct_weights: list[float] = []
    simulation_number: int = 10
    period: int = 15
    base_year: int = 0
    seed: int = 42
    parallel: bool = False
    max_workers: int | None = None
    # Statistics
    confidence_level: float = 0.95      # for the confidence intervals
    bootstrap_samples: int = 500        # resamples for the ranking robustness, 0 turns it off

    @field_validator("confidence_level")
    @classmethod
    def _validate_confidence(cls, value: float) -> float:
        if not 0.5 <= value < 1.0:
            raise ValueError("confidence_level must be in [0.5, 1)")
        return value

    @field_validator("bootstrap_samples")
    @classmethod
    def _validate_bootstrap(cls, value: int) -> int:
        if value < 0 or value > 20000:
            raise ValueError("bootstrap_samples must be between 0 and 20000")
        return value


class AlternativeResult(BaseModel):
    name: str
    machine_number: int
    replacement_period: int
    total_cost: float
    corrective_maintenance_cost: float
    preventive_maintenance_cost: float
    purchase_cost: float
    normal_availability: float
    crisis_availability: float
    normal_hours_worked: float | None = None
    normal_hours_scheduled: float | None = None
    crisis_hours_worked: float | None = None
    crisis_hours_scheduled: float | None = None
    scores: dict[str, float] = {}
    final_score: float
    rank: int


class CriterionWeight(BaseModel):
    name: str
    attribute_name: str
    weight: float


class MetricStats(BaseModel):
    """Confidence interval and convergence of one metric of one alternative."""
    mean: float | None
    sd: float | None
    se: float | None
    ci_low: float | None
    ci_high: float | None
    half_width: float | None
    rel_half_width: float | None            # half_width / |mean|
    q_low: float | None = None              # lower percentile of the replication values
    q_high: float | None = None             # upper percentile of the replication values
    n_required: dict[str, int | None]       # replications needed for +/-5 %, 2 %, 1 %
    running_mean: list[float]               # mean after 1, 2, ... replications
    running_half_width: list[float | None]  # CI half-width after 1, 2, ... replications


class AlternativeStatistics(BaseModel):
    name: str
    n: int
    metrics: dict[str, MetricStats]  # keyed by analysis.statistics.METRICS


class BootstrapAlternative(BaseModel):
    name: str
    rank_probabilities: list[float]  # first entry: probability of being ranked 1st
    p_best: float
    mean_rank: float
    rank_ci: list[int]               # [low, high] percentile interval of the rank


class BootstrapSummary(BaseModel):
    samples: int
    seed: int
    method: str
    replications_per_alternative: int
    held_constant: list[str]
    alternatives: list[BootstrapAlternative]


class CostCiRankingAlternative(BaseModel):
    name: str
    cost_mean: float                 # mean total cost
    ci_low: float                    # confidence interval on the mean total cost
    ci_high: float
    rank_base: int                   # rank with the mean costs
    rank_best: int                   # its cost at ci_low, the others' at ci_high
    rank_worst: int                  # its cost at ci_high, the others' at ci_low


class CostCiRankingSummary(BaseModel):
    confidence_level: float
    cost_is_criterion: bool          # if total_cost isn't a criterion, ranks can't move
    alternatives: list[CostCiRankingAlternative]


class RunResult(BaseModel):
    run_id: str | None = None        # id of the saved run (None if saving failed)
    alternatives: list[AlternativeResult]
    criteria_weights: list[CriterionWeight]
    consistency_ratio: float
    # Charts of the top-ranked alternative. The others are drawn on request
    # (GET /api/simulation-runs/{id}/charts) for the names in chart_alternatives.
    timeline_json: str | None = None
    availability_json: str | None = None
    chart_alternatives: list[str] = []
    decision_matrix: list[dict] = []
    normalized_scores: list[dict] = []
    weighted_scores: list[dict] = []
    pairwise_matrix: list[dict] = []
    sensitivity_scores: dict = {}
    sensitivity_ranks: dict = {}
    # Statistics
    confidence_level: float = 0.95
    statistics: list[AlternativeStatistics] = []
    bootstrap: BootstrapSummary | None = None
    cost_ci_ranking: CostCiRankingSummary | None = None
    parameter_table: dict = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _round_or_none(value: float | None, decimals: int = 1) -> float | None:
    return round(value, decimals) if value is not None else None


def chart_data_for(alternative, config: dict, period: int) -> dict:
    """
    What the timeline and availability charts of one alternative need, kept
    with the saved run so the charts of any alternative can be drawn later:
    its settings and the compact events of its first replication.
    """
    from visualization.timeline import event_records

    return {
        "machine_number": config["machine_number"],
        "replacement_period": config["replacement_period"],
        "normal_threshold": config["normal_threshold"],
        "crisis_threshold": config["crisis_threshold"],
        "period": period,
        **event_records(alternative.simulations[0].events),
    }


def build_chart_json(alternative_name: str, chart_data: dict) -> tuple[str | None, str | None]:
    """Plotly JSON of the timeline and the availability chart of one alternative."""
    from visualization.timeline import plot_timeline_from_records
    from visualization.availability import availability_from_records, availability_figure

    timeline_json = availability_json = None
    try:
        figure = plot_timeline_from_records(
            chart_data,
            machine_number=chart_data["machine_number"],
            replacement_period=chart_data["replacement_period"],
            period=chart_data["period"],
            alternative_name=alternative_name,
        )
        timeline_json = figure.to_json() if figure else None
    except Exception as chart_error:
        print(f"[charts] Timeline of {alternative_name} failed: {chart_error}")
    try:
        times, availability = availability_from_records(
            chart_data, chart_data["machine_number"], chart_data["period"]
        )
        availability_json = availability_figure(
            times, availability,
            machine_number=chart_data["machine_number"],
            period=chart_data["period"],
            normal_threshold=chart_data["normal_threshold"],
            crisis_threshold=chart_data["crisis_threshold"],
            alternative_name=alternative_name,
        ).to_json()
    except Exception as chart_error:
        print(f"[charts] Availability of {alternative_name} failed: {chart_error}")
    return timeline_json, availability_json


def _save_run(body: "RunRequest", run_result: "RunResult", chart_events: dict) -> str | None:
    """
    Save the request and its full result as a simulation_run row for the
    History page. If saving fails we only log it: the user still gets the
    result, the run just won't show up in the history.

    The chart JSON is not saved: the charts of every alternative are drawn
    again from chart_events when the run is reopened.
    """
    try:
        from db.session import get_session
        from db.models import SimulationRunModel

        machine_type = body.configurations[0].machine_type if body.configurations else ""
        method = body.method.upper()
        run = SimulationRunModel(
            name=body.name.strip() or f"{method} — {machine_type}",
            method=method,
            machine_type=machine_type,
            alternative_count=len(run_result.alternatives),
            simulation_number=body.simulation_number,
            period=body.period,
            seed=body.seed,
            best_alternative=run_result.alternatives[0].name if run_result.alternatives else None,
            request=body.model_dump(mode="json"),
            result=run_result.model_dump(mode="json", exclude={"run_id", "timeline_json", "availability_json"}),
            chart_events=chart_events,
        )
        with get_session() as session:
            session.add(run)
            session.flush()
            return str(run.id)
    except Exception as save_error:
        print(f"[history] Could not save simulation run: {save_error}")
        return None


def _matrix_to_dicts(frame) -> list[dict[str, object]]:
    """DataFrame as a list of rows. Each row keeps its index label under "_row"."""
    rows: list[dict[str, object]] = []
    for index_label, frame_row in frame.iterrows():
        row: dict[str, object] = {"_row": str(index_label)}
        for column, value in frame_row.items():
            row[str(column)] = float(value)
        rows.append(row)
    return rows


def _build_sensitivity_data(alternatives, criteria) -> tuple[dict, dict]:
    """Score and rank of every alternative at each tested weight, per criterion, for the charts."""
    try:
        from analysis.sensitivity import perform_weight_sensitivity_analysis

        sensitivity_results = perform_weight_sensitivity_analysis(
            alternatives, criteria, steps=20
        )
        alternative_names = [alternative.name for alternative in alternatives]
        scores_out: dict = {}
        ranks_out: dict = {}

        for criterion_name, results in sensitivity_results.items():
            weights = [float(weight) for weight in results["test_weights"]]
            scores_array = results["scores"]
            rankings = results["rankings"]

            scores_out[criterion_name] = {"weights": weights}
            ranks_out[criterion_name] = {"weights": weights}

            for alternative_index, alternative_name in enumerate(alternative_names):
                scores_out[criterion_name][alternative_name] = [
                    float(scores_array[step][alternative_index]) for step in range(len(weights))
                ]
                ranks_out[criterion_name][alternative_name] = [
                    int(rankings[step].index(alternative_name)) + 1 for step in range(len(weights))
                ]

        return scores_out, ranks_out
    except Exception:
        return {}, {}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/criteria")
def get_criteria_catalog():
    """The criteria the frontend offers to choose from."""
    return CRITERIA_CATALOG


@router.post("/run", response_model=RunResult)
def run_simulation(body: RunRequest):
    try:
        from services.ahp_service import run_decision
        from classes.decision import build_matrix_from_upper_triangle
        import numpy as np

        method = body.method.upper()
        criteria_count = len(body.criteria_config)

        pairwise_matrix = (
            build_matrix_from_upper_triangle(body.pairwise_upper_triangle, n=criteria_count)
            if method == "AHP"
            else None
        )
        direct_weights = body.direct_weights if method in ("TOPSIS", "ELECTRE2") else None

        criteria_config = [
            {"name": criterion.name, "attribute_name": criterion.attribute_name, "minimize": criterion.minimize,
             "input_type": criterion.input_type}
            for criterion in body.criteria_config
        ]

        configs = []
        for alternative_number, config in enumerate(body.configurations, start=1):
            name = config.name.strip() or f"Alt-{alternative_number}"

            # The availability criteria double as the simulation thresholds.
            # Without them, the whole fleet counts as the target.
            normal_threshold = int(config.scores.get("normal_availability", config.machine_number))
            crisis_threshold = int(config.scores.get("crisis_availability", config.machine_number))

            # Every other score is passed on as an attribute of the alternative
            qualitative = {
                attribute: score for attribute, score in config.scores.items()
                if attribute not in ("normal_availability", "crisis_availability")
            }

            configs.append({
                "name": name,
                "machine_number": config.machine_number,
                "replacement_period": config.replacement_period,
                "normal_threshold": normal_threshold,
                "crisis_threshold": crisis_threshold,
                "machine_type": config.machine_type,
                "session_days": config.session_days,
                "shift_durations": config.shift_durations,
                **qualitative,
            })

        result = run_decision(
            configurations=configs,
            criteria_config=criteria_config,
            method=method,
            pairwise_matrix=pairwise_matrix,
            direct_weights=direct_weights,
            simulation_number=body.simulation_number,
            period=body.period,
            run_sensitivity=False,
            persist=True,
            base_year=body.base_year or None,
            seed=body.seed,
            parallel=body.parallel,
            max_workers=body.max_workers,
            confidence_level=body.confidence_level,
            bootstrap_samples=body.bootstrap_samples,
        )

        alternatives = result["alternatives"]
        decision_result = result["ahp_results"]
        ranking = decision_result["ranking"]
        final_scores = decision_result["final_scores"]
        weights = decision_result["weights"]
        consistency_ratio = decision_result["consistency_ratio"]
        criteria = result["criteria"]

        rank_by_name = {
            ranking_row["Alternative"]: int(ranking.loc[ranking["Alternative"] == ranking_row["Alternative"]].index[0])
            for _, ranking_row in ranking.iterrows()
        }

        qualitative_attributes = [
            criterion.attribute_name for criterion in body.criteria_config
            if criterion.input_type == "qualitative"
        ]

        alternative_results = []
        for alternative in alternatives:
            # The *_hours_availability_worked / _scheduled attributes are only
            # there when the matching daily_hours criterion was in the request
            # (set by _attach_hours_criterion in services/ahp_service.py).
            alternative_results.append(AlternativeResult(
                name=alternative.name,
                machine_number=alternative.machine_number,
                replacement_period=alternative.replacement_period,
                total_cost=round(alternative.total_cost, 2),
                corrective_maintenance_cost=round(alternative.corrective_maintenance_cost, 2),
                preventive_maintenance_cost=round(alternative.preventive_maintenance_cost, 2),
                purchase_cost=round(alternative.purchase_cost, 2),
                normal_availability=round(alternative.normal_availability, 4),
                crisis_availability=round(alternative.crisis_availability, 4),
                normal_hours_worked=_round_or_none(getattr(alternative, "normal_hours_availability_worked", None)),
                normal_hours_scheduled=_round_or_none(getattr(alternative, "normal_hours_availability_scheduled", None)),
                crisis_hours_worked=_round_or_none(getattr(alternative, "crisis_hours_availability_worked", None)),
                crisis_hours_scheduled=_round_or_none(getattr(alternative, "crisis_hours_availability_scheduled", None)),
                scores={attribute: getattr(alternative, attribute, 0) for attribute in qualitative_attributes},
                final_score=round(float(final_scores[alternative.name]), 6),
                rank=rank_by_name.get(alternative.name, 0),
            ))

        alternative_results.sort(key=lambda alternative_result: alternative_result.rank)

        criteria_weights = [
            CriterionWeight(
                name=criterion.name,
                attribute_name=criterion.attribute_name,
                weight=round(float(weights.get(criterion.name, 0)), 4),
            )
            for criterion in body.criteria_config
        ]

        decision_matrix = _matrix_to_dicts(
            __import__("pandas").DataFrame(
                decision_result["decision_matrix"],
                index=[alternative.name for alternative in alternatives],
                columns=[criterion.name for criterion in criteria],
            )
        )
        normalized_scores = _matrix_to_dicts(decision_result["normalized_scores"])
        weighted_scores = _matrix_to_dicts(decision_result["weighted_scores"])
        pairwise_matrix = _matrix_to_dicts(decision_result["pairwise_comparison_matrix"])

        sensitivity_scores, sensitivity_ranks = _build_sensitivity_data(alternatives, criteria)

        # Charts come from the first replication of each alternative
        config_by_name = {config["name"]: config for config in configs}
        chart_events = {
            alternative.name: chart_data_for(alternative, config_by_name[alternative.name], body.period)
            for alternative in alternatives
        }
        top_alternative = alternative_results[0].name if alternative_results else None
        timeline_json, availability_json = (
            build_chart_json(top_alternative, chart_events[top_alternative]) if top_alternative else (None, None)
        )

        run_result = RunResult(
            alternatives=alternative_results,
            criteria_weights=criteria_weights,
            consistency_ratio=round(float(consistency_ratio), 4) if consistency_ratio is not None else -1,
            timeline_json=timeline_json,
            availability_json=availability_json,
            chart_alternatives=[alternative_result.name for alternative_result in alternative_results],
            decision_matrix=decision_matrix,
            normalized_scores=normalized_scores,
            weighted_scores=weighted_scores,
            pairwise_matrix=pairwise_matrix,
            sensitivity_scores=sensitivity_scores,
            sensitivity_ranks=sensitivity_ranks,
            confidence_level=result["confidence_level"],
            statistics=result["statistics"],
            bootstrap=result["bootstrap"],
            cost_ci_ranking=result["cost_ci_ranking"],
            parameter_table=result["parameter_table"],
        )
        run_result.run_id = _save_run(body, run_result, chart_events)
        return run_result

    except Exception as run_error:
        import traceback
        raise HTTPException(status_code=500, detail=str(run_error) + "\n" + traceback.format_exc())


@router.post("/report")
def download_report(body: RunResult):
    """
    Excel report for the article (parameter table, ranking with confidence
    intervals, uncertainty, convergence, rank robustness, resilience), built
    from a result the client already has, so nothing is simulated again. The
    chart fields are not used and can be left out of the request.
    """
    try:
        from analysis.report import build_report_workbook

        payload = body.model_dump(exclude={"timeline_json", "availability_json",
                                           "sensitivity_scores", "sensitivity_ranks"})
        workbook_bytes = build_report_workbook(payload)
        return Response(
            content=workbook_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": 'attachment; filename="simulation_report.xlsx"'},
        )
    except Exception as report_error:
        import traceback
        raise HTTPException(status_code=500, detail=str(report_error) + "\n" + traceback.format_exc())
