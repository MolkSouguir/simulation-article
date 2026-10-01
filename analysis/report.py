"""
analysis/report.py

Builds the Excel report from a run's results: parameter table, ranking,
ranks with the costs in their confidence intervals (the Sensitivity tab),
resilience, uncertainty, convergence and ranking robustness.

Two callers produce the same sheets: POST /api/simulation/report (the
Simulation page sends back the result it received and downloads the file)
and analysis/ahp.py (the command-line study adds them to its own export).

What the payload may contain (every key is optional):
    confidence_level  float
    alternatives      list[dict]   ranking rows (name, rank, final_score, costs, availabilities, scores)
    criteria_weights  list[dict]   {name, attribute_name, weight}
    consistency_ratio float
    statistics        list[dict]   from analysis.statistics.summarize_alternatives
    bootstrap         dict | None  from analysis.statistics.bootstrap_ranking
    cost_ci_ranking   dict | None  from analysis.statistics.cost_ci_ranking
    parameter_table   dict         from analysis.parameter_table.build_parameter_table
"""
from __future__ import annotations

import io
from typing import Any

import pandas as pd

from analysis.statistics import METRICS, N_REQUIRED_TARGETS

METRIC_LABELS: dict[str, str] = {
    "total_cost": "Total cost",
    "purchase_cost": "Purchase cost",
    "corrective_maintenance_cost": "Corrective maintenance cost",
    "preventive_maintenance_cost": "Preventive maintenance cost",
    "normal_availability": "Availability — normal",
    "crisis_availability": "Availability — crisis",
    "crisis_expected_unmet": "Crisis — expected unmet demand (units)",
}

CONVERGENCE_SHEET_METRICS: tuple[str, ...] = ("total_cost", "normal_availability", "crisis_availability")


# Parameter table

def parameter_frames(parameter_table: dict[str, Any]) -> dict[str, pd.DataFrame | list[pd.DataFrame]]:
    """One table per sheet. The Decision sheet holds several tables stacked."""
    frames: dict[str, pd.DataFrame | list[pd.DataFrame]] = {}

    run = parameter_table.get("run", {})
    frames["Parameters - Run"] = pd.DataFrame(
        [{"Parameter": key, "Value": _format_value(value)} for key, value in run.items()]
    )

    alternative_rows = []
    for alternative in parameter_table.get("alternatives", []):
        row = {
            "Alternative": alternative["name"],
            "Machine type": alternative["machine_type"],
            "Fleet size N": alternative["machine_number"],
            "Replacement period T (y)": alternative["replacement_period"],
            "Normal threshold": alternative["normal_threshold"],
            "Crisis threshold": alternative["crisis_threshold"],
            "Standby pool": alternative["standby_pool"],
            "Session days (0=Mon)": ", ".join(map(str, alternative["session_days"])),
            "Shift durations (h)": ", ".join(f"{hours:g}" for hours in alternative["shift_durations"]),
            "Cohorts simulated": "; ".join(
                f"{cohort['purchase_year']}×{cohort['count']} @ {cohort['purchase_cost']:g}"
                for cohort in alternative["cohorts_used"]
            ),
        }
        for attribute, score in (alternative.get("scores") or {}).items():
            row[f"score: {attribute}"] = score
        alternative_rows.append(row)
    frames["Parameters - Alternatives"] = pd.DataFrame(alternative_rows)

    frames["Parameters - Fleet"] = pd.DataFrame(parameter_table.get("fleet", [])).rename(columns={
        "machine_type": "Machine type", "purchase_year": "Purchase year", "purchase_cost": "Purchase cost",
        "eta": "η (years)", "beta": "β", "cost_profile": "Cost profile", "pm_programme": "PM programme", "count": "Count",
    })
    frames["Parameters - Spare Parts"] = pd.DataFrame(parameter_table.get("spare_parts", [])).rename(columns={
        "machine_type": "Machine type", "spare_part_type": "Part type", "eta": "η (years)", "beta": "β",
        "purchase_cost": "Unit cost", "cost_profile": "Cost profile", "count": "Count",
    })

    cost_profile_rows = [
        {**{key: value for key, value in profile.items() if key != "used_by"}, "used_by": ", ".join(profile.get("used_by", []))}
        for profile in parameter_table.get("cost_profiles", [])
    ]
    frames["Parameters - Cost Profiles"] = pd.DataFrame(cost_profile_rows).rename(columns={
        "name": "Cost profile", "hourly_labor_cost": "Labour rate (€/h)",
        "corrective_maintenance_hours": "CM labour (h)",
        "corrective_maintenance_additional_downtime_hours": "CM extra downtime (h)",
        "preventive_maintenance_hours": "PM hours", "used_by": "Used by",
    })

    pm_rows = []
    for programme in parameter_table.get("pm_programmes", []):
        for cycle_year in programme["cycle_years"]:
            pm_rows.append({
                "PM programme": programme["name"], "Interval (y)": programme["years_interval"],
                "Cycle length (y)": programme["cycle_length_years"],
                "Cycle year": cycle_year["order"], "PM hours": cycle_year["preventive_maintenance_hours"],
                "Labour rate (€/h)": cycle_year["hourly_labor_cost"], "PM year cost": cycle_year["pm_year_cost"],
                "Parts replaced": ", ".join(cycle_year["parts_replaced"]) or "—",
            })
    frames["Parameters - PM"] = pd.DataFrame(pm_rows)

    decision = parameter_table.get("decision", {})
    decision_frames: list[pd.DataFrame] = []
    settings = [{"Parameter": "Method", "Value": decision.get("method")}]
    if decision.get("consistency_ratio") is not None:
        settings.append({"Parameter": "Consistency ratio", "Value": decision["consistency_ratio"]})
    if decision.get("lambda_max") is not None:
        settings.append({"Parameter": "λmax", "Value": decision["lambda_max"]})
    if decision.get("random_index") is not None:
        settings.append({"Parameter": "Random index (RI)", "Value": decision["random_index"]})
    if decision.get("ahp_weight_derivation"):
        settings.append({"Parameter": "AHP weight derivation", "Value": decision["ahp_weight_derivation"]})
    if decision.get("electre2"):
        for setting_name, setting_value in decision["electre2"].items():
            settings.append({"Parameter": f"ELECTRE II {setting_name}", "Value": setting_value})
    decision_frames.append(pd.DataFrame(settings))
    decision_frames.append(pd.DataFrame(decision.get("criteria", [])).rename(columns={
        "name": "Criterion", "attribute_name": "Attribute", "input_type": "Input type", "minimize": "Minimize", "weight": "Weight",
    }))
    if decision.get("pairwise_matrix"):
        criteria_names = decision["pairwise_matrix"]["criteria"]
        decision_frames.append(
            pd.DataFrame(decision["pairwise_matrix"]["rows"], index=criteria_names, columns=criteria_names)
            .rename_axis("Pairwise (row vs column)")
            .reset_index()
        )
    if decision.get("direct_weights"):
        criteria_names = [criterion["name"] for criterion in decision.get("criteria", [])]
        decision_frames.append(pd.DataFrame({"Criterion": criteria_names, "Direct weight": decision["direct_weights"]}))
    frames["Parameters - Decision"] = decision_frames
    return frames


def _format_value(value: Any) -> Any:
    """Lists and dicts as one line of text, so they fit in a single cell."""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value)
    if isinstance(value, dict):
        return "; ".join(f"{key}: {item}" for key, item in value.items())
    return value


# Statistics

def uncertainty_frame(statistics: list[dict[str, Any]], confidence: float) -> pd.DataFrame:
    """Mean, SD, SE, confidence interval and percentiles of every metric, one row per alternative and metric."""
    confidence_label = f"{confidence * 100:g}%"
    rows = []
    for alternative_stats in statistics:
        for metric in METRICS:
            metric_stats = alternative_stats["metrics"][metric]
            rows.append({
                "Alternative": alternative_stats["name"],
                "Metric": METRIC_LABELS[metric],
                "N": alternative_stats["n"],
                "Mean": metric_stats["mean"],
                "SD": metric_stats["sd"],
                "SE": metric_stats["se"],
                f"Bootstrap CI {confidence_label} low": metric_stats["ci_low"],
                f"Bootstrap CI {confidence_label} high": metric_stats["ci_high"],
                "Half-width": metric_stats["half_width"],
                "Rel. half-width (%)": None if metric_stats["rel_half_width"] is None else metric_stats["rel_half_width"] * 100,
                f"Replications {(1 - confidence) / 2 * 100:g}th pct": metric_stats.get("q_low"),
                f"Replications {(1 + confidence) / 2 * 100:g}th pct": metric_stats.get("q_high"),
            })
    return pd.DataFrame(rows)


def resilience_frame(payload: dict[str, Any], confidence: float) -> pd.DataFrame:
    """Per alternative: expected unmet demand in a crisis."""
    stats_by_name = {alternative_stats["name"]: alternative_stats for alternative_stats in payload.get("statistics", []) or []}
    rows = []
    for alternative in sorted(payload.get("alternatives", []), key=lambda alternative: alternative.get("rank", 0)):
        unmet = (stats_by_name.get(alternative["name"], {}).get("metrics", {}) or {}).get("crisis_expected_unmet") or {}
        row = {
            "Alternative": alternative["name"],
            "N machines": alternative.get("machine_number"),
            "Expected unmet demand (units)": unmet.get("mean"),
        }
        if _has_spread(payload):
            row[f"Expected unmet demand ± ({confidence * 100:g}% CI)"] = unmet.get("half_width")
        rows.append(row)
    return pd.DataFrame(rows)


def cost_ci_frame(payload: dict[str, Any]) -> pd.DataFrame:
    """Per alternative: its rank with the total costs anywhere in their confidence intervals."""
    cost_ci_ranking = payload.get("cost_ci_ranking") or {}
    if not cost_ci_ranking:
        return pd.DataFrame()
    label = f"{cost_ci_ranking.get('confidence_level', 0.95) * 100:g}%"
    result_by_name = {result["name"]: result for result in cost_ci_ranking.get("alternatives", [])}
    rows = []
    for alternative in sorted(payload.get("alternatives", []), key=lambda alternative: alternative.get("rank", 0)):
        result = result_by_name.get(alternative["name"], {})
        rows.append({
            "Alternative": alternative["name"],
            "Total cost (mean)": result.get("cost_mean"),
            f"CI {label} low": result.get("ci_low"),
            f"CI {label} high": result.get("ci_high"),
            "Rank": result.get("rank_base", alternative.get("rank")),
            "Best rank (own cost at CI low, others at CI high)": result.get("rank_best"),
            "Worst rank (own cost at CI high, others at CI low)": result.get("rank_worst"),
        })
    return pd.DataFrame(rows)


def convergence_summary_frame(statistics: list[dict[str, Any]]) -> pd.DataFrame:
    """Relative half-width reached, and replications needed for +/-5 %, 2 % and 1 %."""
    rows = []
    for alternative_stats in statistics:
        for metric in METRICS:
            metric_stats = alternative_stats["metrics"][metric]
            row = {
                "Alternative": alternative_stats["name"],
                "Metric": METRIC_LABELS[metric],
                "N run": alternative_stats["n"],
                "Rel. half-width at N (%)": None if metric_stats["rel_half_width"] is None else metric_stats["rel_half_width"] * 100,
            }
            for target in N_REQUIRED_TARGETS:
                row[f"N for ±{target * 100:g}%"] = metric_stats["n_required"].get(f"{target:g}")
            rows.append(row)
    return pd.DataFrame(rows)


def convergence_series_frame(statistics: list[dict[str, Any]], metric: str) -> pd.DataFrame:
    """Running mean and half-width of one metric after each replication, two columns per alternative."""
    max_replications = max((alternative_stats["n"] for alternative_stats in statistics), default=0)
    columns: dict[str, list] = {"Replication": list(range(1, max_replications + 1))}
    for alternative_stats in statistics:
        metric_stats = alternative_stats["metrics"][metric]
        running_mean = metric_stats["running_mean"] + [None] * (max_replications - len(metric_stats["running_mean"]))
        running_half_width = metric_stats["running_half_width"] + [None] * (max_replications - len(metric_stats["running_half_width"]))
        columns[f"{alternative_stats['name']} mean"] = running_mean
        columns[f"{alternative_stats['name']} half-width"] = running_half_width
    return pd.DataFrame(columns)


def bootstrap_frame(bootstrap: dict[str, Any] | None) -> pd.DataFrame:
    """Probability of each rank per alternative, from the bootstrap."""
    if not bootstrap:
        return pd.DataFrame()
    alternative_count = len(bootstrap["alternatives"])
    rows = []
    for alternative in bootstrap["alternatives"]:
        row = {
            "Alternative": alternative["name"],
            "P(best)": alternative["p_best"],
            "Mean rank": alternative["mean_rank"],
            "Rank interval low": alternative["rank_ci"][0],
            "Rank interval high": alternative["rank_ci"][1],
        }
        for rank_index in range(alternative_count):
            row[f"P(rank {rank_index + 1})"] = alternative["rank_probabilities"][rank_index]
        rows.append(row)
    return pd.DataFrame(rows).sort_values("Mean rank").reset_index(drop=True)


def _has_spread(payload: dict[str, Any]) -> bool:
    """At least 2 replications per alternative, so there are confidence intervals, convergence and rank robustness."""
    statistics = payload.get("statistics", []) or []
    return bool(statistics) and statistics[0].get("n", 0) >= 2


def ranking_frame(payload: dict[str, Any]) -> pd.DataFrame:
    """The ranking with costs, availabilities and their confidence half-widths (with at least 2 replications)."""
    stats_by_name = {alternative_stats["name"]: alternative_stats for alternative_stats in payload.get("statistics", [])}
    has_spread = _has_spread(payload)
    rows = []
    for alternative in sorted(payload.get("alternatives", []), key=lambda alternative: alternative.get("rank", 0)):
        metric_stats = stats_by_name.get(alternative["name"], {}).get("metrics", {})

        def half_width(metric: str):
            return (metric_stats.get(metric) or {}).get("half_width")

        row = {
            "Rank": alternative.get("rank"),
            "Alternative": alternative["name"],
            "N machines": alternative.get("machine_number"),
            "T (y)": alternative.get("replacement_period"),
            "Final score": alternative.get("final_score"),
            "Total cost": alternative.get("total_cost"), "Total cost ± (CI)": half_width("total_cost"),
            "CM cost": alternative.get("corrective_maintenance_cost"),
            "PM cost": alternative.get("preventive_maintenance_cost"),
            "Purchase cost": alternative.get("purchase_cost"),
            "Avail. normal": alternative.get("normal_availability"), "Avail. normal ± (CI)": half_width("normal_availability"),
            "Avail. crisis": alternative.get("crisis_availability"), "Avail. crisis ± (CI)": half_width("crisis_availability"),
            "Expected unmet demand (crisis)": (metric_stats.get("crisis_expected_unmet") or {}).get("mean"),
            "Expected unmet demand ± (CI)": half_width("crisis_expected_unmet"),
        }
        if not has_spread:
            row = {column: value for column, value in row.items() if "± (CI)" not in column}
        for attribute, score in (alternative.get("scores") or {}).items():
            row[attribute] = score
        rows.append(row)
    return pd.DataFrame(rows)


# Workbook

def write_report(writer: pd.ExcelWriter, payload: dict[str, Any]) -> None:
    """Write all the report sheets into an open ExcelWriter."""
    confidence = float(payload.get("confidence_level", 0.95))
    statistics = payload.get("statistics", []) or []

    for sheet_name, frame in parameter_frames(payload.get("parameter_table", {}) or {}).items():
        if isinstance(frame, list):
            # Several tables on one sheet, with two empty rows between them
            start_row = 0
            for table in frame:
                table.to_excel(writer, sheet_name=sheet_name[:31], index=False, startrow=start_row)
                start_row += len(table) + 3
        else:
            frame.to_excel(writer, sheet_name=sheet_name[:31], index=False)

    ranking_frame(payload).to_excel(writer, sheet_name="Ranking", index=False)
    cost_ci_table = cost_ci_frame(payload)
    if not cost_ci_table.empty:
        cost_ci_table.to_excel(writer, sheet_name="Cost CI Ranking", index=False)
    resilience_frame(payload, confidence).to_excel(writer, sheet_name="Resilience", index=False)

    if _has_spread(payload):
        uncertainty_frame(statistics, confidence).to_excel(
            writer, sheet_name=f"Uncertainty ({confidence * 100:g}% CI)"[:31], index=False
        )
        convergence_summary_frame(statistics).to_excel(writer, sheet_name="Convergence Summary", index=False)
        for metric in CONVERGENCE_SHEET_METRICS:
            convergence_series_frame(statistics, metric).to_excel(
                writer, sheet_name=f"Conv - {METRIC_LABELS[metric]}"[:31].replace("—", "-"), index=False
            )

    robustness_table = bootstrap_frame(payload.get("bootstrap"))
    if not robustness_table.empty:
        robustness_table.to_excel(writer, sheet_name="Rank Robustness", index=False)


def build_report_workbook(payload: dict[str, Any]) -> bytes:
    """The report as the bytes of an .xlsx file."""
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        write_report(writer, payload)
    return buffer.getvalue()
