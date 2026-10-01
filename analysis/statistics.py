"""
analysis/statistics.py

Monte Carlo statistics for the report: bootstrap confidence intervals on the
means, convergence, how robust the ranking is (bootstrap), and how far each
rank can move with the total costs anywhere in their confidence intervals.

It only reads the per-run numbers already stored on alternative.simulations
(Simulation objects, or SimulationResult stand-ins in parallel runs), so the
simulation and its random numbers are never touched. The bootstraps have their
own random generators, seeded from the run seed.

Metrics, per alternative: total_cost, purchase_cost,
corrective_maintenance_cost, preventive_maintenance_cost, normal_availability,
crisis_availability, and the resilience metrics in RESILIENCE_METRICS
(see functions.helper_functions.calculate_resilience_metrics).

Everything returned is plain Python (numbers, lists, dicts), ready for a JSON
response or a DataFrame.
"""
from __future__ import annotations

import copy
import math
import zlib
from types import SimpleNamespace
from typing import Any, Sequence

import numpy as np

from classes.criteria import Criteria
from classes.decision import DecisionMaking
from classes.decision_method_type import DecisionMethodType
from functions.helper_functions import RESILIENCE_METRICS


METRICS: tuple[str, ...] = (
    "total_cost",
    "purchase_cost",
    "corrective_maintenance_cost",
    "preventive_maintenance_cost",
    "normal_availability",
    "crisis_availability",
    *RESILIENCE_METRICS,
)

# Relative precisions (+/-5 %, 2 %, 1 %) for which we estimate the replications needed
N_REQUIRED_TARGETS: tuple[float, ...] = (0.05, 0.02, 0.01)

# Bootstrap confidence intervals on the means: resamples for the reported
# interval, and for the running interval of the convergence charts, which is
# computed at up to CONVERGENCE_POINTS replication counts and interpolated
# in between (the charts don't need every count, and it keeps big runs fast).
CI_BOOTSTRAP_SAMPLES = 2000
CONVERGENCE_BOOTSTRAP_SAMPLES = 500
CONVERGENCE_POINTS = 40


# Values per replication

def replication_samples(alternative: Any) -> dict[str, np.ndarray]:
    """The value of every metric in every replication, in replication order."""
    runs = alternative.simulations
    purchase = np.array([run.purchase_cost for run in runs], dtype=float)
    corrective = np.array([run.corrective_maintenance_cost for run in runs], dtype=float)
    preventive = np.array([run.preventive_maintenance_cost for run in runs], dtype=float)
    return {
        "total_cost": purchase + corrective + preventive,
        "purchase_cost": purchase,
        "corrective_maintenance_cost": corrective,
        "preventive_maintenance_cost": preventive,
        "normal_availability": np.array([run.normal_availability for run in runs], dtype=float),
        "crisis_availability": np.array([run.crisis_availability for run in runs], dtype=float),
        **{
            metric: np.array([run.resilience.get(metric, np.nan) for run in runs], dtype=float)
            for metric in RESILIENCE_METRICS
        },
    }


# Confidence interval on the mean (bootstrap), and convergence

def _bootstrap_means(values: np.ndarray, resamples: int, generator: np.random.Generator) -> np.ndarray:
    """Means of `resamples` samples of len(values) drawn from values with replacement."""
    size = values.size
    batch = max(1, 2_000_000 // size)  # resamples per batch, so a batch holds about 2 million values
    means = np.empty(resamples)
    for start in range(0, resamples, batch):
        stop = min(start + batch, resamples)
        means[start:stop] = values[generator.integers(0, size, size=(stop - start, size))].mean(axis=1)
    return means


def _percentile_interval(means: np.ndarray, confidence: float) -> tuple[float, float]:
    """
    Percentile interval of bootstrap means: the ceil(B (1 - c) / 2)-th and
    ceil(B (1 + c) / 2)-th sorted values, counting from 1 (at least the 1st).
    The rounding keeps float noise from tipping the ceil.
    """
    ordered = np.sort(means)
    count = ordered.size
    lower_position = max(1, math.ceil(round(count * (1 - confidence) / 2, 9)))
    upper_position = min(count, math.ceil(round(count * (1 + confidence) / 2, 9)))
    return float(ordered[lower_position - 1]), float(ordered[upper_position - 1])


def _bootstrap_half_width(values: np.ndarray, resamples: int, confidence: float,
                          generator: np.random.Generator) -> tuple[float, float, float]:
    """(lower, upper, half-width) of the bootstrap percentile interval on the mean of values."""
    if values.std() == 0:
        mean = float(values.mean())
        return mean, mean, 0.0
    lower, upper = _percentile_interval(_bootstrap_means(values, resamples, generator), confidence)
    return lower, upper, (upper - lower) / 2


def _convergence_counts(sample_size: int) -> np.ndarray:
    """Replication counts at which the running interval is computed: all of them, or CONVERGENCE_POINTS spread geometrically."""
    if sample_size - 1 <= CONVERGENCE_POINTS:
        return np.arange(2, sample_size + 1)
    return np.unique(np.round(np.geomspace(2, sample_size, CONVERGENCE_POINTS)).astype(int))


def _finite_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    return float(value) if math.isfinite(value) else None


def summarize_samples(samples: np.ndarray, confidence: float = 0.95,
                      generator: np.random.Generator | None = None) -> dict[str, Any]:
    """
    Mean, standard deviation, standard error and bootstrap percentile
    confidence interval on the mean, plus the mean and interval half-width
    after each replication (for the convergence charts).

    The interval comes from CI_BOOTSTRAP_SAMPLES resamples of the
    replications. It can be asymmetric: ci_low and ci_high are its bounds,
    half_width is half its width (what the page shows as +/-).

    q_low and q_high are percentiles of the replication values themselves
    (at 95 %: the 2.5th and 97.5th), so they show how much a single run can
    vary, not how precise the mean is.

    With a single replication, only the mean is filled in.
    """
    if generator is None:
        generator = np.random.default_rng(0)
    values = np.asarray(samples, dtype=float)
    sample_size = int(values.size)
    mean = float(values.mean()) if sample_size else float("nan")

    if sample_size < 2:
        return {
            "mean": _finite_or_none(mean),
            "sd": None, "se": None,
            "ci_low": None, "ci_high": None,
            "half_width": None, "rel_half_width": None,
            "q_low": None, "q_high": None,
            "n_required": {f"{target:g}": None for target in N_REQUIRED_TARGETS},
            "running_mean": [mean] if sample_size else [],
            "running_half_width": [None] if sample_size else [],
        }

    sd = float(values.std(ddof=1))
    se = sd / math.sqrt(sample_size)
    ci_low, ci_high, half_width = _bootstrap_half_width(values, CI_BOOTSTRAP_SAMPLES, confidence, generator)
    relative_half_width = half_width / abs(mean) if mean != 0 else None
    q_low, q_high = (float(quantile) for quantile in np.quantile(
        values, [(1 - confidence) / 2, (1 + confidence) / 2], method="inverted_cdf"))

    # Replications needed to reach each target precision: the half-width
    # shrinks like 1 / sqrt(n), so scale the current one.
    n_required: dict[str, int | None] = {}
    for target in N_REQUIRED_TARGETS:
        if mean == 0:
            n_required[f"{target:g}"] = None
        elif half_width == 0:
            n_required[f"{target:g}"] = 1
        else:
            n_required[f"{target:g}"] = int(math.ceil(sample_size * (half_width / (target * abs(mean))) ** 2))

    # Mean after 1, 2, ... replications (the incremental form stays accurate
    # for costs in the millions)
    running_mean: list[float] = []
    current_mean = 0.0
    for count, value in enumerate(values, start=1):
        current_mean += (value - current_mean) / count
        running_mean.append(float(current_mean))

    # Half-width after 2, 3, ... replications: bootstrapped at a few counts
    # (the last one is the reported interval) and interpolated in between
    counts = _convergence_counts(sample_size)
    count_half_widths = [
        _bootstrap_half_width(values[:count], CONVERGENCE_BOOTSTRAP_SAMPLES, confidence, generator)[2]
        for count in counts[:-1]
    ] + [half_width]
    all_counts = np.arange(2, sample_size + 1)
    running_half_width: list[float | None] = [None] + [
        float(value) for value in np.interp(all_counts, counts, count_half_widths)
    ]

    return {
        "mean": mean,
        "sd": sd,
        "se": se,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "half_width": half_width,
        "rel_half_width": _finite_or_none(relative_half_width),
        "q_low": q_low,
        "q_high": q_high,
        "n_required": n_required,
        "running_mean": running_mean,
        "running_half_width": running_half_width,
    }


def _metric_generator(seed: int, alternative_name: str, metric: str) -> np.random.Generator:
    """
    Random generator for the bootstrap of one metric of one alternative. It
    depends only on the seed and the two names, so an alternative's intervals
    don't change when other alternatives are added or reordered.
    """
    return np.random.default_rng([abs(int(seed)), zlib.crc32(alternative_name.encode()), zlib.crc32(metric.encode())])


def summarize_alternative(alternative: Any, confidence: float = 0.95, seed: int = 0) -> dict[str, Any]:
    """Statistics of every metric of one alternative."""
    samples = replication_samples(alternative)
    replication_count = int(next(iter(samples.values())).size)
    return {
        "name": alternative.name,
        "n": replication_count,
        "metrics": {
            metric: summarize_samples(samples[metric], confidence, _metric_generator(seed, alternative.name, metric))
            for metric in METRICS
        },
    }


def summarize_alternatives(alternatives: Sequence[Any], confidence: float = 0.95, seed: int = 0) -> list[dict[str, Any]]:
    return [summarize_alternative(alternative, confidence, seed) for alternative in alternatives]


# Ranking robustness (bootstrap)

def _rank_alternatives(
    proxies: list[SimpleNamespace],
    criteria: list[Criteria],
    method: DecisionMethodType,
    pairwise_matrix: np.ndarray | None,
    direct_weights: Sequence[float] | None,
    wd: str,
) -> dict[str, int]:
    """Rank stand-in alternatives with the chosen method. Returns {name: rank}."""
    decision = DecisionMaking(decision_method=method)
    for proxy in proxies:
        decision.add_alternative(proxy)  # type: ignore[arg-type]
    for criterion in criteria:
        decision.add_criteria(criterion)

    if method == DecisionMethodType.TOPSIS:
        decision_result = decision.TOPSIS(weights=np.asarray(direct_weights, dtype=float))
    elif method == DecisionMethodType.ELECTRE2:
        decision_result = decision.ELECTRE2(weights=np.asarray(direct_weights, dtype=float))
    else:
        decision_result = decision.AHP(pairwise_matrix=pairwise_matrix, wd=wd)  # type: ignore[arg-type]

    ranking = decision_result["ranking"]  # indexed by rank (from 1), with an "Alternative" column
    return {str(ranking_row["Alternative"]): int(rank) for rank, ranking_row in ranking.iterrows()}


def bootstrap_ranking(
    alternatives: Sequence[Any],
    criteria: Sequence[Criteria],
    method: DecisionMethodType,
    pairwise_matrix: np.ndarray | None = None,
    direct_weights: Sequence[float] | None = None,
    wd: str = "m",
    samples: int = 500,
    seed: int = 0,
    confidence: float = 0.95,
) -> dict[str, Any] | None:
    """
    How stable the ranking is, by bootstrap.

    `samples` times: draw each alternative's replications again with
    replacement, take the new means of the simulated metrics, rank again with
    the same method, and note every alternative's rank. Qualitative scores and
    anything else that isn't in METRICS (such as the daily-hours
    availabilities, which come from a single run) stay as they are.

    Returns None when there is nothing to resample (fewer than 2 replications,
    or samples <= 0).
    """
    if samples <= 0 or not alternatives:
        return None
    samples_per_alternative = [replication_samples(alternative) for alternative in alternatives]
    replication_count = int(next(iter(samples_per_alternative[0].values())).size)
    if replication_count < 2:
        return None

    alternative_count = len(alternatives)
    attribute_names = [criterion.attribute_name for criterion in criteria]
    constant_attributes = [attribute for attribute in attribute_names if attribute not in METRICS]
    resampled_attributes = [attribute for attribute in attribute_names if attribute in METRICS]

    # Copies, because the decision methods write weight and score on the criteria
    criteria_copies = [copy.copy(criterion) for criterion in criteria]

    random_generator = np.random.default_rng(seed)
    rank_counts = np.zeros((alternative_count, alternative_count), dtype=int)  # [alternative, rank - 1]
    rank_draws = np.zeros((samples, alternative_count), dtype=int)

    for draw in range(samples):
        proxies: list[SimpleNamespace] = []
        for alternative_index, alternative in enumerate(alternatives):
            resampled_indexes = random_generator.integers(0, replication_count, size=replication_count)
            attributes: dict[str, float] = {}
            for attribute in resampled_attributes:
                attributes[attribute] = float(samples_per_alternative[alternative_index][attribute][resampled_indexes].mean())
            for attribute in constant_attributes:
                attributes[attribute] = float(getattr(alternative, attribute, 0) or 0)
            proxies.append(SimpleNamespace(name=alternative.name, **attributes))

        ranks = _rank_alternatives(proxies, criteria_copies, method, pairwise_matrix, direct_weights, wd)
        for alternative_index, alternative in enumerate(alternatives):
            rank = ranks[alternative.name]
            rank_counts[alternative_index, rank - 1] += 1
            rank_draws[draw, alternative_index] = rank

    # Percentile interval from the sorted draws: the floor(B * alpha / 2)-th and
    # ceil(B * (1 - alpha / 2))-th values, counting from 1. The rounding keeps
    # float noise from tipping floor/ceil, and the bounds keep small B valid.
    alpha = 1 - confidence
    lower_position = max(1, math.floor(round(samples * alpha / 2, 9)))
    upper_position = min(samples, math.ceil(round(samples * (1 - alpha / 2), 9)))
    alternative_results = []
    for alternative_index, alternative in enumerate(alternatives):
        rank_probabilities = rank_counts[alternative_index] / samples
        sorted_ranks = np.sort(rank_draws[:, alternative_index])
        alternative_results.append({
            "name": alternative.name,
            "rank_probabilities": [float(probability) for probability in rank_probabilities],
            "p_best": float(rank_probabilities[0]),
            "mean_rank": float(rank_draws[:, alternative_index].mean()),
            "rank_ci": [int(sorted_ranks[lower_position - 1]), int(sorted_ranks[upper_position - 1])],
        })

    return {
        "samples": int(samples),
        "seed": int(seed),
        "method": method.value,
        "replications_per_alternative": replication_count,
        "held_constant": constant_attributes,
        "alternatives": alternative_results,
    }


# Ranking with every total cost inside its confidence interval

def cost_ci_ranking(
    alternatives: Sequence[Any],
    criteria: Sequence[Criteria],
    method: DecisionMethodType,
    statistics: Sequence[dict[str, Any]],
    pairwise_matrix: np.ndarray | None = None,
    direct_weights: Sequence[float] | None = None,
    wd: str = "m",
    confidence: float = 0.95,
) -> dict[str, Any] | None:
    """
    How far each alternative's rank can move when the total costs may be
    anywhere in their confidence intervals.

    For every alternative, two more rankings: its best case (its total cost at
    the lower bound of its interval, every other alternative's at the upper
    bound) and its worst case (the reverse). Every other criterion keeps the
    value the decision used, and nothing is simulated again. The intervals are
    the ones in `statistics` (summarize_alternatives), so this is about how
    precisely the simulation estimated the costs, not about the prices.

    The reported range also covers the rank with the mean costs.

    Returns None without intervals (fewer than 2 replications) or without
    alternatives.
    """
    interval_by_name = {entry["name"]: entry["metrics"]["total_cost"] for entry in statistics}
    if not alternatives or any(
        interval_by_name.get(alternative.name, {}).get("ci_low") is None for alternative in alternatives
    ):
        return None

    attribute_names = [criterion.attribute_name for criterion in criteria]
    criteria_copies = [copy.copy(criterion) for criterion in criteria]
    base_attributes = {
        alternative.name: {attribute: float(getattr(alternative, attribute, 0) or 0) for attribute in attribute_names}
        for alternative in alternatives
    }

    def ranks_with_costs(cost_by_name: dict[str, float] | None) -> dict[str, int]:
        proxies = []
        for name, attributes in base_attributes.items():
            if cost_by_name is not None and "total_cost" in attributes:
                attributes = {**attributes, "total_cost": cost_by_name[name]}
            proxies.append(SimpleNamespace(name=name, **attributes))
        return _rank_alternatives(proxies, criteria_copies, method, pairwise_matrix, direct_weights, wd)

    lower = {name: float(interval["ci_low"]) for name, interval in interval_by_name.items()}
    upper = {name: float(interval["ci_high"]) for name, interval in interval_by_name.items()}
    base_ranks = ranks_with_costs(None)
    alternative_results = []
    for alternative in alternatives:
        name = alternative.name
        best_case = ranks_with_costs({**upper, name: lower[name]})[name]
        worst_case = ranks_with_costs({**lower, name: upper[name]})[name]
        alternative_results.append({
            "name": name,
            "cost_mean": float(interval_by_name[name]["mean"]),
            "ci_low": lower[name],
            "ci_high": upper[name],
            "rank_base": int(base_ranks[name]),
            "rank_best": int(min(best_case, base_ranks[name])),
            "rank_worst": int(max(worst_case, base_ranks[name])),
        })

    return {
        "confidence_level": float(confidence),
        "cost_is_criterion": "total_cost" in attribute_names,
        "alternatives": alternative_results,
    }
