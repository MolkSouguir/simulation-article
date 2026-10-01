"""
analysis/runner.py

The 12 fleet configurations of the study, and run_alternatives() to simulate them.
Edit CONFIGURATIONS to add, remove or change a configuration.
"""
from __future__ import annotations

import random
from services.simulation_service import run_simulation
from classes.alternative import Alternative


# Each dict goes straight to run_simulation(). machine_number,
# replacement_period, normal_threshold and crisis_threshold are required,
# and any other key becomes a qualitative criterion on the Alternative.
CONFIGURATIONS: list[dict] = [
    {"machine_number": 38, "replacement_period": 7,  "normal_threshold": 36, "crisis_threshold": 44, "clinical_features": 10,  "staff_satisfaction": 7.5, "logistics_procurement": 7.5},
    {"machine_number": 41, "replacement_period": 7,  "normal_threshold": 36, "crisis_threshold": 44, "clinical_features": 10,  "staff_satisfaction": 7.5, "logistics_procurement": 7.5},
    {"machine_number": 45, "replacement_period": 7,  "normal_threshold": 36, "crisis_threshold": 44, "clinical_features": 10,  "staff_satisfaction": 7.5, "logistics_procurement": 7.5},
    {"machine_number": 38, "replacement_period": 9,  "normal_threshold": 36, "crisis_threshold": 44, "clinical_features": 10,  "staff_satisfaction": 10,  "logistics_procurement": 10},
    {"machine_number": 41, "replacement_period": 9,  "normal_threshold": 36, "crisis_threshold": 44, "clinical_features": 10,  "staff_satisfaction": 10,  "logistics_procurement": 10},
    {"machine_number": 45, "replacement_period": 9,  "normal_threshold": 36, "crisis_threshold": 44, "clinical_features": 10,  "staff_satisfaction": 10,  "logistics_procurement": 10},
    {"machine_number": 38, "replacement_period": 12, "normal_threshold": 36, "crisis_threshold": 44, "clinical_features": 7.5, "staff_satisfaction": 7.5, "logistics_procurement": 10},
    {"machine_number": 41, "replacement_period": 12, "normal_threshold": 36, "crisis_threshold": 44, "clinical_features": 7.5, "staff_satisfaction": 7.5, "logistics_procurement": 10},
    {"machine_number": 45, "replacement_period": 12, "normal_threshold": 36, "crisis_threshold": 44, "clinical_features": 7.5, "staff_satisfaction": 7.5, "logistics_procurement": 10},
    {"machine_number": 38, "replacement_period": 15, "normal_threshold": 36, "crisis_threshold": 44, "clinical_features": 5,   "staff_satisfaction": 5,   "logistics_procurement": 7.5},
    {"machine_number": 41, "replacement_period": 15, "normal_threshold": 36, "crisis_threshold": 44, "clinical_features": 5,   "staff_satisfaction": 5,   "logistics_procurement": 7.5},
    {"machine_number": 45, "replacement_period": 15, "normal_threshold": 36, "crisis_threshold": 44, "clinical_features": 5,   "staff_satisfaction": 5,   "logistics_procurement": 7.5},
]


def run_alternatives(
    simulation_number: int = 100,
    period: int = 15,
    configurations: list[dict] | None = None,
    persist: bool = True,
    seed: int = 42,
) -> list[Alternative]:
    """
    Simulate every configuration (CONFIGURATIONS unless others are given) and
    return the Alternatives in the same order.
    """
    random.seed(seed)
    chosen_configurations = configurations or CONFIGURATIONS
    alternatives = []

    for alternative_number, config in enumerate(chosen_configurations, start=1):
        name = config.get("name", f"alternative-{alternative_number}")
        extra = {
            key: value for key, value in config.items()
            if key not in ("name", "machine_number", "replacement_period",
                           "normal_threshold", "crisis_threshold")
        }
        alternative, db_id = run_simulation(
            name=name,
            machine_number=config["machine_number"],
            replacement_period=config["replacement_period"],
            period=period,
            simulation_number=simulation_number,
            normal_threshold=config.get("normal_threshold", 36),
            crisis_threshold=config.get("crisis_threshold", 44),
            persist=persist,
            **extra,
        )
        alternatives.append(alternative)
        print(f"[runner] {name} done — cost={alternative.total_cost:,.0f} "
              f"normal={alternative.normal_availability:.1f}% "
              f"{'(saved to DB)' if db_id else ''}")

    return alternatives
