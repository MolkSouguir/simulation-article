from collections.abc import Sequence
from typing import List
import numpy as np
import pandas as pd
from pyDecision.algorithm.ahp import ahp_method as _pyDecision_ahp
from pyDecision.algorithm.topsis import topsis_method as _pyDecision_topsis

from .alternative import Alternative
from .criteria import Criteria
from .decision_method_type import DecisionMethodType

# pyDecision's random index by matrix size. Its ahp_method only returns the
# weights and the CR, so λmax and RI are worked out again here, the same way.
AHP_RANDOM_INDEX = (0, 0, 0, 0.58, 0.9, 1.12, 1.24, 1.32, 1.41, 1.45, 1.49, 1.51, 1.48, 1.56, 1.57, 1.59)


def ahp_consistency_parts(pairwise_matrix: np.ndarray, weights: np.ndarray, wd: str) -> tuple[float, float | None]:
    """
    (λmax, RI) behind pyDecision's consistency ratio, CR = ((λmax - n) / (n - 1)) / RI.
    λmax is the largest eigenvalue with wd 'me', otherwise the mean of (A w)_i / w_i.
    RI is None past the table (more than 15 criteria).
    """
    size = pairwise_matrix.shape[1]
    if wd in ("me", "max_eigen"):
        lambda_max = float(np.max(np.real(np.linalg.eigvals(pairwise_matrix))))
    else:
        lambda_max = float(np.mean(np.sum(pairwise_matrix * weights, axis=1) / weights))
    random_index = float(AHP_RANDOM_INDEX[size]) if size < len(AHP_RANDOM_INDEX) else None
    return lambda_max, random_index


def build_matrix_from_upper_triangle(values: Sequence[float], n: int) -> np.ndarray:
    """
    Rebuild the full n x n pairwise comparison matrix from its upper triangle,
    given row by row. The lower triangle holds the reciprocals.

    For n = 3: values = [a01, a02, a12]
    """
    matrix = np.ones((n, n))
    value_index = 0
    for row in range(n):
        for column in range(row + 1, n):
            matrix[row, column] = values[value_index]
            matrix[column, row] = 1.0 / values[value_index]
            value_index += 1
    return matrix


def _ranking_frame(alternative_names: list[str], final_scores) -> pd.DataFrame:
    """Alternatives sorted by final score, indexed by rank (1 = best)."""
    ranking_df = (
        pd.DataFrame({"Alternative": alternative_names, "Final Score": final_scores})
        .sort_values("Final Score", ascending=False)
        .reset_index(drop=True)
    )
    ranking_df.index = ranking_df.index + 1
    ranking_df.index.name = "Rank"
    return ranking_df


class DecisionMaking:
    def __init__(self, decision_method: DecisionMethodType):
        self.alternatives: List[Alternative] = []
        self.criteria: List[Criteria] = []
        self.decision_method = decision_method

    def add_alternative(self, alternative: Alternative):
        self.alternatives.append(alternative)

    def add_criteria(self, criteria: Criteria):
        self.criteria.append(criteria)

    def _decision_matrix(self) -> np.ndarray:
        """One row per alternative, one column per criterion, raw values."""
        matrix = np.zeros((len(self.alternatives), len(self.criteria)))
        for alternative_index, alternative in enumerate(self.alternatives):
            for criterion_index, criterion in enumerate(self.criteria):
                matrix[alternative_index, criterion_index] = getattr(alternative, criterion.attribute_name, 0)
        return matrix

    def normalize_column(self, values: np.ndarray, minimize: bool) -> np.ndarray:
        """
        Score each alternative as a fraction of the best one on this criterion:

          maximize: value / max(values)
          minimize: min(values) / value

        This keeps the same absolute difference worth the same score, whatever
        the scale of the criterion. We tried dividing by the column total
        instead, but then criteria with large values (availability, 86 to 100 %)
        get squeezed and the 0 to 10 qualitative scores end up dominating even
        with lower weights.

        The ratios are not rescaled to sum to 1. Their weighted sum is the
        final AHP score.
        """
        value_count = len(values)
        if minimize:
            safe_values = np.where(values == 0, np.finfo(float).eps, values)
            best = safe_values.min()
            priorities = best / safe_values
        else:
            best = values.max()
            if best == 0:
                return np.ones(value_count) / value_count
            priorities = values / best

        return priorities

    def AHP(self, pairwise_matrix: np.ndarray, wd: str = "m"):
        """
        AHP: criteria weights from the pairwise comparison matrix, then a
        weighted sum of the normalised scores of each alternative.

        pairwise_matrix is the expert's n x n criteria matrix on the Saaty 1-9
        scale (see build_matrix_from_upper_triangle). wd is how pyDecision
        turns it into weights: 'm' (normalise columns, average rows, the
        default), 'g' (geometric mean of rows) or 'me' (principal eigenvector).
        """
        if not self.alternatives:
            raise ValueError("No alternatives added for analysis")
        if not self.criteria:
            raise ValueError("No criteria added for analysis")

        criteria_count = len(self.criteria)
        if pairwise_matrix.shape != (criteria_count, criteria_count):
            raise ValueError(
                f"pairwise_matrix must be {criteria_count}×{criteria_count}, "
                f"got {pairwise_matrix.shape}"
            )

        # Criteria weights and consistency ratio
        weights, consistency_ratio = _pyDecision_ahp(pairwise_matrix, wd=wd)
        if np.isnan(consistency_ratio):  # with 2 or fewer criteria RI = 0, so 0/0
            consistency_ratio = 0.0
        lambda_max, random_index = ahp_consistency_parts(pairwise_matrix, weights, wd)
        for criterion_index, criterion in enumerate(self.criteria):
            criterion.weight = weights[criterion_index]

        alternative_names = [alternative.name for alternative in self.alternatives]
        criteria_names = [criterion.name for criterion in self.criteria]
        decision_matrix = self._decision_matrix()

        # Score the alternatives on each criterion
        normalized_matrix = np.zeros_like(decision_matrix)
        for criterion_index, criterion in enumerate(self.criteria):
            normalized_matrix[:, criterion_index] = self.normalize_column(
                decision_matrix[:, criterion_index], minimize=criterion.minimize
            )

        weighted_matrix = normalized_matrix * weights
        final_scores = np.sum(weighted_matrix, axis=1)

        for alternative_index, alternative in enumerate(self.alternatives):
            for criterion_index, criterion in enumerate(self.criteria):
                criterion.score = normalized_matrix[alternative_index, criterion_index]

        return {
            "decision_matrix": decision_matrix,
            "normalized_scores": pd.DataFrame(normalized_matrix, index=alternative_names, columns=criteria_names),
            "weighted_scores": pd.DataFrame(weighted_matrix, index=alternative_names, columns=criteria_names),
            "final_scores": pd.Series(final_scores, index=alternative_names, name="Final Score"),
            "ranking": _ranking_frame(alternative_names, final_scores),
            "weights": dict(zip(criteria_names, weights)),
            "consistency_ratio": consistency_ratio,
            "lambda_max": lambda_max,
            "random_index": random_index,
            "pairwise_comparison_matrix": pd.DataFrame(
                pairwise_matrix, index=criteria_names, columns=criteria_names
            ),
            "alternative_pairwise_matrices": {},
        }

    def ELECTRE2(
        self,
        weights: np.ndarray,
        c_plus: float = 0.65,
        c_minus: float = 0.35,
        d_threshold: float = 0.40,
    ):
        """
        ELECTRE II.

        Builds a strong and a weak outranking relation from the concordance and
        discordance of every pair of alternatives, then ranks them by averaging
        a forward distillation (best first) and a backward one (worst first).

        weights can be any positive numbers, they are normalised here.
        c_plus and c_minus are the concordance levels for strong and weak
        outranking. d_threshold is the largest normalised disadvantage allowed
        on any single criterion.
        """
        if not self.alternatives:
            raise ValueError("No alternatives added for analysis")
        if not self.criteria:
            raise ValueError("No criteria added for analysis")

        alternative_count = len(self.alternatives)
        criteria_count = len(self.criteria)
        alternative_names = [alternative.name for alternative in self.alternatives]
        criteria_names = [criterion.name for criterion in self.criteria]

        normalized_weights = np.array(weights, dtype=float)
        normalized_weights = normalized_weights / normalized_weights.sum()
        for criterion_index, criterion in enumerate(self.criteria):
            criterion.weight = normalized_weights[criterion_index]

        decision_matrix = self._decision_matrix()

        # Rescale every criterion to 0..1 (1 = best) so discordance doesn't
        # depend on the units of the criterion.
        normalized_matrix = np.zeros_like(decision_matrix)
        for criterion_index, criterion in enumerate(self.criteria):
            column = decision_matrix[:, criterion_index]
            lowest, highest = column.min(), column.max()
            value_range = highest - lowest if highest != lowest else 1.0
            if criterion.minimize:
                normalized_matrix[:, criterion_index] = (highest - column) / value_range
            else:
                normalized_matrix[:, criterion_index] = (column - lowest) / value_range

        concordance = np.zeros((alternative_count, alternative_count))
        discordance = np.zeros((alternative_count, alternative_count))

        for first in range(alternative_count):
            for second in range(alternative_count):
                if first == second:
                    continue
                # Concordance: total weight of the criteria where `first` is at least as good
                at_least_as_good = normalized_matrix[first] >= normalized_matrix[second]
                concordance[first, second] = normalized_weights[at_least_as_good].sum()

                # Discordance: largest margin by which `second` beats `first` on a criterion
                difference = normalized_matrix[second] - normalized_matrix[first]
                disadvantages = difference[difference > 0]
                discordance[first, second] = disadvantages.max() if len(disadvantages) > 0 else 0.0

        # Strong: concordance >= c_plus and discordance <= d
        # Weak:   c_minus <= concordance < c_plus and discordance <= d
        not_self = ~np.eye(alternative_count, dtype=bool)
        strong_outranking = (concordance >= c_plus) & (discordance <= d_threshold) & not_self
        weak_outranking = (
            (concordance >= c_minus) & (concordance < c_plus) & (discordance <= d_threshold) & not_self
        )
        outranking = strong_outranking | weak_outranking

        def _distill(outranking: np.ndarray, reverse: bool) -> list[list[int]]:
            """Repeatedly take out the best (or, with reverse, the worst) group."""
            remaining = set(range(alternative_count))
            order: list[list[int]] = []
            while remaining:
                remaining_list = list(remaining)
                # Net score inside the remaining set: how many it beats minus how many beat it
                net_scores = {}
                for candidate in remaining_list:
                    beats = sum(1 for other in remaining_list if other != candidate and outranking[candidate, other])
                    beaten_by = sum(1 for other in remaining_list if other != candidate and outranking[other, candidate])
                    net_scores[candidate] = beats - beaten_by
                target_score = max(net_scores.values()) if not reverse else min(net_scores.values())
                group = [candidate for candidate in remaining_list if net_scores[candidate] == target_score]
                order.append(group)
                remaining -= set(group)
            return order

        forward = _distill(outranking, reverse=False)    # best first
        backward = _distill(outranking, reverse=True)    # worst first, flipped below
        backward_best_first = list(reversed(backward))

        forward_rank = {}
        for position, group in enumerate(forward):
            for alternative_index in group:
                forward_rank[alternative_index] = position

        backward_rank = {}
        for position, group in enumerate(backward_best_first):
            for alternative_index in group:
                backward_rank[alternative_index] = position

        average_rank = {
            alternative_index: (forward_rank[alternative_index] + backward_rank[alternative_index]) / 2.0
            for alternative_index in range(alternative_count)
        }

        # A lower average rank is better, so flip it to make a higher score better.
        worst_rank_plus_one = max(average_rank.values()) + 1
        final_scores = np.array(
            [worst_rank_plus_one - average_rank[alternative_index] for alternative_index in range(alternative_count)],
            dtype=float,
        )

        return {
            "decision_matrix": decision_matrix,
            "normalized_scores": pd.DataFrame(normalized_matrix, index=alternative_names, columns=criteria_names),
            "weighted_scores": pd.DataFrame(
                normalized_matrix * normalized_weights, index=alternative_names, columns=criteria_names
            ),
            "final_scores": pd.Series(final_scores, index=alternative_names, name="Final Score"),
            "ranking": _ranking_frame(alternative_names, final_scores),
            "weights": dict(zip(criteria_names, normalized_weights)),
            "consistency_ratio": None,
            "pairwise_comparison_matrix": pd.DataFrame(
                np.zeros((criteria_count, criteria_count)), index=criteria_names, columns=criteria_names
            ),
            "alternative_pairwise_matrices": {},
        }

    def TOPSIS(self, weights: np.ndarray):
        """
        TOPSIS, computed by pyDecision.

        weights can be any positive numbers, in the same order as self.criteria,
        and are normalised to sum to 1. Returns the same keys as AHP(). There
        is no consistency ratio for TOPSIS, so it is None.
        """
        if not self.alternatives:
            raise ValueError("No alternatives added for analysis")
        if not self.criteria:
            raise ValueError("No criteria added for analysis")

        alternative_count = len(self.alternatives)
        criteria_count = len(self.criteria)
        alternative_names = [alternative.name for alternative in self.alternatives]
        criteria_names = [criterion.name for criterion in self.criteria]

        normalized_weights = np.array(weights, dtype=float)
        normalized_weights = normalized_weights / normalized_weights.sum()
        for criterion_index, criterion in enumerate(self.criteria):
            criterion.weight = normalized_weights[criterion_index]

        decision_matrix = self._decision_matrix()
        criterion_type = ["min" if criterion.minimize else "max" for criterion in self.criteria]

        # pyDecision expects one row per alternative, one column per criterion
        scores = _pyDecision_topsis(
            decision_matrix, normalized_weights, criterion_type, graph=False, verbose=False
        )

        # pyDecision doesn't expose its intermediate matrices, so these stay empty.
        return {
            "decision_matrix": decision_matrix,
            "normalized_scores": pd.DataFrame(
                np.zeros((alternative_count, criteria_count)), index=alternative_names, columns=criteria_names
            ),
            "weighted_scores": pd.DataFrame(
                np.zeros((alternative_count, criteria_count)), index=alternative_names, columns=criteria_names
            ),
            "final_scores": pd.Series(scores, index=alternative_names, name="Final Score"),
            "ranking": _ranking_frame(alternative_names, scores),
            "weights": dict(zip(criteria_names, normalized_weights)),
            "consistency_ratio": None,
            "pairwise_comparison_matrix": pd.DataFrame(
                np.zeros((criteria_count, criteria_count)), index=criteria_names, columns=criteria_names,
            ),
            "alternative_pairwise_matrices": {},
        }
