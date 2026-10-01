"""
analysis/ahp.py

The whole study from the command line: simulate the 12 configurations of
analysis/runner.py, rank them with AHP, export everything to Excel and,
optionally, run the full sensitivity analysis.

    python -m analysis.ahp
"""
import os
import numpy as np
import pandas as pd

from db.session import ensure_postgres_ready
from db.loader import load_config
from services.ahp_service import run_ahp
from analysis.sensitivity import run_full_sensitivity_analysis
from analysis.runner import CONFIGURATIONS
from classes.decision import build_matrix_from_upper_triangle
import database


CRITERIA_CONFIG = [
    {"name": "Availability in normal situation min 36", "attribute_name": "normal_availability", "minimize": False},
    {"name": "Availability in crisis situation min 44",  "attribute_name": "crisis_availability",  "minimize": False},
    {"name": "Total cost",                               "attribute_name": "total_cost",            "minimize": True},
    {"name": "Staff satisfaction",                       "attribute_name": "staff_satisfaction",    "minimize": False},
    {"name": "Sensitivity to obsolescence",              "attribute_name": "clinical_features",     "minimize": False},
    {"name": "Easiness of Logistics & Procurement",      "attribute_name": "logistics_procurement", "minimize": False},
]

# The expert's pairwise comparisons of the criteria (Saaty scale 1 to 9), in
# the order of CRITERIA_CONFIG. Only the upper triangle, row by row:
# n * (n - 1) / 2 values. A value above 1 means the row criterion matters more
# than the column one. Use 1/3, 1/5, ... when the column criterion matters more.
CRITERIA_PAIRWISE_UPPER = [
    # C1 vs C2..C6
    1,   3,   5,   7,   9,
    # C2 vs C3..C6
         3,   5,   7,   9,
    # C3 vs C4..C6
              3,   5,   7,
    # C4 vs C5..C6
                   3,   5,
    # C5 vs C6
                        3,
]

CRITERIA_PAIRWISE_MATRIX = build_matrix_from_upper_triangle(
    CRITERIA_PAIRWISE_UPPER, n=len(CRITERIA_CONFIG)
)


def export_to_excel(result: dict, output_path: str = "assets/ahp_results.xlsx"):
    """Write the result of run_ahp() to an Excel file, one table per sheet."""
    alternatives = result["alternatives"]
    criteria = result["criteria"]
    ahp_results = result["ahp_results"]

    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        alternative_rows = []
        for alternative in alternatives:
            row = {
                "Alternative": alternative.name,
                "Machine Number": alternative.machine_number,
                "Replacement Period": alternative.replacement_period,
                "Total Cost": alternative.total_cost,
                "Normal Availability %": alternative.normal_availability,
                "Crisis Availability %": alternative.crisis_availability,
                "CM Cost": alternative.corrective_maintenance_cost,
                "PM Cost": alternative.preventive_maintenance_cost,
                "Purchase Cost": alternative.purchase_cost,
            }
            for attribute in ("clinical_features", "staff_satisfaction", "logistics_procurement"):
                if hasattr(alternative, attribute):
                    row[attribute.replace("_", " ").title()] = getattr(alternative, attribute)
            alternative_rows.append(row)
        pd.DataFrame(alternative_rows).to_excel(writer, sheet_name="Alternative Details", index=False)

        pd.DataFrame([{
            "Criteria": criterion.name, "Attribute": criterion.attribute_name,
            "Weight": criterion.weight,
            "Minimize": criterion.minimize,
        } for criterion in criteria]).to_excel(writer, sheet_name="Criteria", index=False)

        ahp_results["pairwise_comparison_matrix"].to_excel(writer, sheet_name="Pairwise Comparison")
        pd.DataFrame({
            "Metric": ["Consistency Ratio (CR)", "Is Consistent?"],
            "Value": [
                ahp_results["consistency_ratio"],
                "Yes" if ahp_results["consistency_ratio"] < 0.10 else "No",
            ],
        }).to_excel(writer, sheet_name="Consistency Check", index=False)
        pd.DataFrame(
            ahp_results["decision_matrix"],
            index=[alternative.name for alternative in alternatives],
            columns=[criterion.name for criterion in criteria],
        ).to_excel(writer, sheet_name="Decision Matrix")
        ahp_results["normalized_scores"].to_excel(writer, sheet_name="Normalized Scores")
        ahp_results["weighted_scores"].to_excel(writer, sheet_name="Weighted Scores")
        ahp_results["ranking"].to_excel(writer, sheet_name="Final Ranking")

        def _to_fraction(value):
            """Closest fraction with numerator and denominator from 1 to 9, as text ("1/3")."""
            if abs(value - 1.0) < 0.01:
                return "1"
            best_fraction, best_error = (1, 1), float('inf')
            for denominator in range(1, 10):
                for numerator in range(1, 10):
                    error = abs(numerator / denominator - value)
                    if error < best_error:
                        best_error, best_fraction = error, (numerator, denominator)
            numerator, denominator = best_fraction
            return str(numerator) if denominator == 1 else f"{numerator}/{denominator}"

        # One sheet per criterion if the method compared alternatives pairwise
        # (our AHP doesn't, so this is usually empty).
        for criterion_name, pairwise_frame in ahp_results.get("alternative_pairwise_matrices", {}).items():
            pairwise_frame.map(_to_fraction).to_excel(writer, sheet_name=f"PW {criterion_name}"[:31])

        # Same report sheets as the Excel download in the app
        if result.get("statistics"):
            from analysis.report import write_report
            write_report(writer, _report_payload(result))

    print(f"[OK] Results exported to: {output_path}")


def _report_payload(result: dict) -> dict:
    """Reshape the run_decision() result like the API's RunResult, which analysis.report expects."""
    ahp_results = result["ahp_results"]
    ranking = ahp_results["ranking"]
    rank_by_name = {ranking_row["Alternative"]: int(rank) for rank, ranking_row in ranking.iterrows()}
    final_scores = ahp_results["final_scores"]
    qualitative_attributes = [
        criterion.attribute_name for criterion in result["criteria"]
        if criterion.attribute_name not in ("normal_availability", "crisis_availability", "total_cost")
    ]
    return {
        "confidence_level": result.get("confidence_level", 0.95),
        "consistency_ratio": ahp_results.get("consistency_ratio"),
        "criteria_weights": [
            {"name": criterion.name, "attribute_name": criterion.attribute_name, "weight": float(criterion.weight)}
            for criterion in result["criteria"]
        ],
        "alternatives": [{
            "name": alternative.name,
            "rank": rank_by_name.get(alternative.name, 0),
            "final_score": float(final_scores[alternative.name]),
            "machine_number": alternative.machine_number,
            "replacement_period": alternative.replacement_period,
            "total_cost": alternative.total_cost,
            "corrective_maintenance_cost": alternative.corrective_maintenance_cost,
            "preventive_maintenance_cost": alternative.preventive_maintenance_cost,
            "purchase_cost": alternative.purchase_cost,
            "normal_availability": alternative.normal_availability,
            "crisis_availability": alternative.crisis_availability,
            "scores": {attribute: getattr(alternative, attribute, None) for attribute in qualitative_attributes},
        } for alternative in result["alternatives"]],
        "statistics": result["statistics"],
        "bootstrap": result["bootstrap"],
        "cost_ci_ranking": result.get("cost_ci_ranking"),
        "parameter_table": result["parameter_table"],
    }


def main(simulation_number: int = 10, period: int = 15, run_sensitivity: bool = False):
    """Run the study and write assets/ahp_results.xlsx (plus the sensitivity output if asked)."""
    os.makedirs("assets", exist_ok=True)

    result = run_ahp(
        configurations=CONFIGURATIONS,
        criteria_config=CRITERIA_CONFIG,
        pairwise_matrix=CRITERIA_PAIRWISE_MATRIX,
        simulation_number=simulation_number,
        period=period,
        run_sensitivity=False,   # run below instead, so its files go to assets/
        persist=True,
    )

    export_to_excel(result, output_path="assets/ahp_results.xlsx")

    if run_sensitivity:
        run_full_sensitivity_analysis(
            result["alternatives"],
            result["criteria"],
            output_dir="assets",
        )

    return result


if __name__ == "__main__":
    ensure_postgres_ready()
    if not database.db_machines:
        load_config()
    main(simulation_number=10, period=15, run_sensitivity=True)
