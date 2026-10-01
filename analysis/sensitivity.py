import sys
from pathlib import Path

# So "classes" can be imported when this file is run on its own
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from typing import List
from classes import DecisionMaking, Criteria
from classes.decision_method_type import DecisionMethodType

# Dark colours only, so the lines stay readable when printed
DARK_COLORS = ['#1f77b4', '#d62728', '#2ca02c', '#ff7f0e', '#9467bd',
               '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf',
               '#0e4c92', '#a01f1f', '#1f7a1f', '#cc6600', '#6b4c9a']


def perform_weight_sensitivity_analysis(alternatives, criteria : List[Criteria], weight_range=(0.0, 1.0), steps=20):
    """
    One-at-a-time weight sensitivity. For each criterion, its weight goes from
    weight_range[0] to weight_range[1] in `steps` values, and the other weights
    share the rest in proportion to their original values. The scores are the
    AHP weighted sum (value / max, or min / value for costs), whatever method
    was used for the ranking.

    Returns, per criterion name: the tested weights, the ranking (names, best
    first) and the scores at each tested weight.
    """
    results = {}

    original_weights = [criterion.weight for criterion in criteria]

    for target_index, target_criterion in enumerate(criteria):

        test_weights = np.linspace(weight_range[0], weight_range[1], steps)

        criterion_results = {
            'test_weights': test_weights,
            'rankings': [],
            'scores': []
        }

        for test_weight in test_weights:
            # The target gets test_weight and the others share what's left in proportion.
            new_weights = original_weights.copy()
            remaining_weight = 1.0 - test_weight

            other_weights_sum = 0
            for criterion_index, weight in enumerate(original_weights):
                if criterion_index != target_index:
                    other_weights_sum += weight

            if other_weights_sum > 0:
                for criterion_index in range(len(new_weights)):
                    if criterion_index == target_index:
                        new_weights[criterion_index] = test_weight
                    else:
                        new_weights[criterion_index] = (original_weights[criterion_index] / other_weights_sum) * remaining_weight
            else:
                # All other weights are 0: split the rest equally
                new_weights[target_index] = test_weight
                equal_weight = remaining_weight / (len(criteria) - 1)
                for criterion_index in range(len(new_weights)):
                    if criterion_index != target_index:
                        new_weights[criterion_index] = equal_weight

            for criterion_index, criterion in enumerate(criteria):
                criterion.weight = new_weights[criterion_index]

            decision = DecisionMaking(decision_method = DecisionMethodType.AHP)
            for alternative in alternatives:
                decision.add_alternative(alternative)
            for criterion in criteria:
                decision.add_criteria(criterion)

            # Scores are computed here directly, since the weights are set by
            # hand rather than derived from a pairwise matrix.
            alternative_count = len(alternatives)
            criteria_count = len(criteria)
            decision_matrix = np.zeros((alternative_count, criteria_count))

            for alternative_index, alternative in enumerate(alternatives):
                for criterion_index, criterion in enumerate(criteria):
                    value = getattr(alternative, criterion.attribute_name, 0)
                    decision_matrix[alternative_index, criterion_index] = value

            normalized_matrix = np.zeros_like(decision_matrix)
            for criterion_index, criterion in enumerate(criteria):
                column = decision_matrix[:, criterion_index]

                if criterion.minimize:
                    # Lower is better (cost): min / value
                    lowest = np.min(column)
                    if lowest == 0:
                        normalized_matrix[:, criterion_index] = 0
                    else:
                        normalized_matrix[:, criterion_index] = lowest / column
                else:
                    # Higher is better: value / max
                    highest = np.max(column)
                    if highest == 0:
                        normalized_matrix[:, criterion_index] = 0
                    else:
                        normalized_matrix[:, criterion_index] = column / highest

            weighted_matrix = normalized_matrix * new_weights
            final_scores = np.sum(weighted_matrix, axis = 1)

            alternative_names = [alternative.name for alternative in alternatives]
            ranking_df = pd.DataFrame({
                'Alternative': alternative_names,
                'Score': final_scores
            }).sort_values('Score', ascending=False).reset_index(drop=True)

            criterion_results['rankings'].append(ranking_df['Alternative'].tolist())
            criterion_results['scores'].append(final_scores.tolist())

        results[target_criterion.name] = criterion_results

    # Put the original weights back
    for criterion_index, criterion in enumerate(criteria):
        criterion.weight = original_weights[criterion_index]

    return results


def analyze_rank_changes(sensitivity_results, alternatives):
    """Best, worst, average and spread of each alternative's rank over the whole sweep."""
    alternative_names = [alternative.name for alternative in alternatives]
    ranks_by_alternative = {name: [] for name in alternative_names}

    for criterion_name, results in sensitivity_results.items():
        for ranking in results['rankings']:
            for alternative_name in alternative_names:
                rank = ranking.index(alternative_name) + 1
                ranks_by_alternative[alternative_name].append(rank)

    stats = []
    for alternative_name in alternative_names:
        ranks = ranks_by_alternative[alternative_name]
        stats.append({
            'Alternative': alternative_name,
            'Min Rank': min(ranks),
            'Max Rank': max(ranks),
            'Avg Rank': np.mean(ranks),
            'Std Rank': np.std(ranks),
            'Rank Range': max(ranks) - min(ranks)
        })

    return pd.DataFrame(stats).sort_values('Avg Rank')


def _save_legend(alternative_names, output_dir, base_name, extension):
    """Legend of the alternatives as its own image (the article places it under the charts)."""
    from matplotlib.lines import Line2D
    legend_figure = plt.figure(figsize=(19.2, 3))
    legend_axes = legend_figure.add_subplot(111)
    legend_axes.axis('off')

    legend_elements = []
    legend_labels = []
    for alternative_index, alternative_name in enumerate(alternative_names):
        color = DARK_COLORS[alternative_index % len(DARK_COLORS)]
        legend_elements.append(Line2D([0], [0], color=color,
                                      marker='o', linewidth=3.5, markersize=10))
        legend_labels.append(alternative_name)

    legend_columns = int(np.ceil(len(alternative_names) / 2))
    legend_axes.legend(legend_elements, legend_labels,
                       loc='center', ncol=legend_columns, frameon=True, fontsize=24)

    legend_path = output_dir / f"{base_name}_legend{extension}"
    plt.savefig(legend_path, dpi=300, bbox_inches='tight')
    plt.close(legend_figure)
    return str(legend_path)


def plot_sensitivity_analysis(sensitivity_results, alternatives, output_path='assets/sensitivity_analysis.png'):
    """
    Score of every alternative against the weight of each criterion, one image
    per criterion plus a separate legend image (sized for the MDPI template).
    """
    from pathlib import Path
    base_path = Path(output_path)
    output_dir = base_path.parent
    base_name = base_path.stem
    extension = base_path.suffix

    alternative_names = [alternative.name for alternative in alternatives]

    saved_files = []

    for criterion_name, results in sensitivity_results.items():
        figure, axes = plt.subplots(1, 1, figsize=(19.2, 19.2 * 0.62))

        test_weights = results['test_weights']
        scores_array = np.array(results['scores'])  # one row per tested weight, one column per alternative

        for alternative_index, alternative_name in enumerate(alternative_names):
            alternative_scores = scores_array[:, alternative_index]
            color = DARK_COLORS[alternative_index % len(DARK_COLORS)]
            axes.plot(test_weights, alternative_scores, marker='o',
                      color=color, linewidth=3, markersize=6)

        axes.set_xlabel(f'Weight for "{criterion_name}"', fontsize=28)
        axes.set_ylabel('Final AHP Score', fontsize=28)
        axes.set_title(f'Sensitivity Analysis: {criterion_name}', fontsize=32, fontweight='bold', pad=20)
        axes.tick_params(axis='both', which='major', labelsize=22)
        axes.grid(True, alpha=0.3, axis='y')

        plt.tight_layout()

        safe_criterion_name = criterion_name.replace(' ', '_').replace('/', '_')
        individual_path = output_dir / f"{base_name}_{safe_criterion_name}{extension}"
        plt.savefig(individual_path, dpi=300, bbox_inches='tight')
        saved_files.append(str(individual_path))
        plt.close(figure)

    saved_files.append(_save_legend(alternative_names, output_dir, base_name, extension))

    print(f"\n[OK] Sensitivity analysis plots saved ({len(saved_files)} files):")
    for file in saved_files:
        print(f"    - {file}")

    return saved_files


def plot_rank_sensitivity_analysis(sensitivity_results, alternatives, output_path='assets/rank_sensitivity_analysis.png'):
    """Same as plot_sensitivity_analysis, with the rank instead of the score (rank 1 at the top)."""
    from pathlib import Path
    base_path = Path(output_path)
    output_dir = base_path.parent
    base_name = base_path.stem
    extension = base_path.suffix

    alternative_names = [alternative.name for alternative in alternatives]

    saved_files = []

    for criterion_name, results in sensitivity_results.items():
        figure, axes = plt.subplots(1, 1, figsize=(19.2, 19.2 * 0.62))

        test_weights = results['test_weights']
        rankings = results['rankings']

        # Rankings are lists of names, turn them into a rank per alternative
        rank_positions = {alternative_name: [] for alternative_name in alternative_names}
        for ranking in rankings:
            for alternative_name in alternative_names:
                rank = ranking.index(alternative_name) + 1
                rank_positions[alternative_name].append(rank)

        for alternative_index, alternative_name in enumerate(alternative_names):
            alternative_ranks = rank_positions[alternative_name]
            color = DARK_COLORS[alternative_index % len(DARK_COLORS)]
            axes.plot(test_weights, alternative_ranks, marker='o',
                      color=color, linewidth=3, markersize=6)

        axes.set_xlabel(f'Weight for "{criterion_name}"', fontsize=28)
        axes.set_ylabel('Rank Position', fontsize=28)
        axes.set_title(f'Rank Sensitivity Analysis: {criterion_name}', fontsize=32, fontweight='bold', pad=20)
        axes.tick_params(axis='both', which='major', labelsize=22)
        axes.grid(True, alpha=0.3, axis='y')

        axes.invert_yaxis()
        axes.set_yticks(range(1, len(alternative_names) + 1))

        plt.tight_layout()

        safe_criterion_name = criterion_name.replace(' ', '_').replace('/', '_')
        individual_path = output_dir / f"{base_name}_{safe_criterion_name}{extension}"
        plt.savefig(individual_path, dpi=300, bbox_inches='tight')
        saved_files.append(str(individual_path))
        plt.close(figure)

    saved_files.append(_save_legend(alternative_names, output_dir, base_name, extension))

    print(f"\n[OK] Rank sensitivity analysis plots saved ({len(saved_files)} files):")
    for file in saved_files:
        print(f"    - {file}")

    return saved_files


def plot_threshold_summary(threshold_df, output_path='assets/threshold_summary.png'):
    """The weights at which two alternatives swap places, one bar chart per criterion."""
    if threshold_df is None or len(threshold_df) == 0:
        print("[WARN] No threshold points found to plot.")
        return None

    from pathlib import Path
    base_path = Path(output_path)
    output_dir = base_path.parent
    base_name = base_path.stem
    extension = base_path.suffix

    saved_files = []

    for criterion_name, group in threshold_df.groupby('Criterion'):
        figure, axes = plt.subplots(1, 1, figsize=(19.2, 19.2 * 0.62))

        y_positions = range(len(group))
        threshold_weights = group['Threshold Weight'].values

        axes.barh(y_positions, threshold_weights, color='#606060', alpha=0.7, edgecolor='black', linewidth=1.5)

        labels = [f"{row['Alternative 1']} ↔ {row['Alternative 2']}"
                  for _, row in group.iterrows()]
        axes.set_yticks(y_positions)
        axes.set_yticklabels(labels, fontsize=22)

        for bar_index, weight in enumerate(threshold_weights):
            axes.text(weight, bar_index, f' w={weight:.3f}', va='center', fontsize=20, fontweight='bold')

        axes.set_xlabel('Critical Weight Threshold', fontsize=28)
        axes.set_title(f'Critical Thresholds: {criterion_name}', fontsize=32, fontweight='bold')
        axes.tick_params(axis='x', which='major', labelsize=22)
        axes.set_xlim(0, 1)
        axes.grid(True, alpha=0.3, axis='x')

        plt.tight_layout()

        safe_criterion_name = criterion_name.replace(' ', '_').replace('/', '_')
        individual_path = output_dir / f"{base_name}_{safe_criterion_name}{extension}"
        plt.savefig(individual_path, dpi=300, bbox_inches='tight')
        saved_files.append(str(individual_path))
        plt.close(figure)

    print(f"[OK] Threshold summary plots saved ({len(saved_files)} files):")
    for file in saved_files:
        print(f"    - {file}")

    return saved_files


def find_threshold_points(sensitivity_results, alternatives, tolerance=1e-6):
    """
    Weights at which two alternatives get the same score, i.e. where they swap
    places. Found where the difference of their scores changes sign between
    two tested weights, then placed by linear interpolation.
    """
    alternative_names = [alternative.name for alternative in alternatives]
    all_thresholds = []

    for criterion_name, results in sensitivity_results.items():
        test_weights = results['test_weights']
        scores_array = np.array(results['scores'])  # one row per tested weight, one column per alternative

        for first_index in range(len(alternative_names)):
            for second_index in range(first_index + 1, len(alternative_names)):
                first_name = alternative_names[first_index]
                second_name = alternative_names[second_index]

                first_scores = scores_array[:, first_index]
                second_scores = scores_array[:, second_index]

                score_diff = first_scores - second_scores

                for step in range(len(score_diff) - 1):
                    if score_diff[step] * score_diff[step + 1] < 0:
                        weight_before, weight_after = test_weights[step], test_weights[step + 1]
                        diff_before, diff_after = score_diff[step], score_diff[step + 1]

                        # Weight at which the difference reaches zero
                        threshold_weight = weight_before - diff_before * (weight_after - weight_before) / (diff_after - diff_before)

                        # Score of the first alternative at that weight
                        fraction = (threshold_weight - weight_before) / (weight_after - weight_before)
                        threshold_score = first_scores[step] + fraction * (first_scores[step + 1] - first_scores[step])

                        all_thresholds.append({
                            'Criterion': criterion_name,
                            'Alternative 1': first_name,
                            'Alternative 2': second_name,
                            'Threshold Weight': threshold_weight,
                            'Score at Threshold': threshold_score,
                            'Direction': 'A1→A2' if score_diff[step] > 0 else 'A2→A1'
                        })

    if all_thresholds:
        return pd.DataFrame(all_thresholds).sort_values(['Criterion', 'Threshold Weight'])
    else:
        return pd.DataFrame(columns=['Criterion', 'Alternative 1', 'Alternative 2',
                                     'Threshold Weight', 'Score at Threshold', 'Direction'])


def analyze_stability_regions(sensitivity_results, alternatives):
    """Weight ranges over which the ranking doesn't change, per criterion."""
    stability_analysis = []

    for criterion_name, results in sensitivity_results.items():
        test_weights = results['test_weights']
        rankings = results['rankings']

        stable_regions = []
        current_region_start = test_weights[0]
        current_ranking = rankings[0]

        for step in range(1, len(rankings)):
            if rankings[step] != current_ranking:
                # The ranking changed: close the current region
                stable_regions.append({
                    'Start Weight': current_region_start,
                    'End Weight': test_weights[step - 1],
                    'Range': test_weights[step - 1] - current_region_start,
                    'Ranking': ' > '.join(current_ranking[:3])  # top 3
                })
                current_region_start = test_weights[step]
                current_ranking = rankings[step]

        stable_regions.append({
            'Start Weight': current_region_start,
            'End Weight': test_weights[-1],
            'Range': test_weights[-1] - current_region_start,
            'Ranking': ' > '.join(current_ranking[:3])
        })

        region_count = len(stable_regions)
        total_range = test_weights[-1] - test_weights[0]
        largest_region = max(stable_regions, key=lambda region: region['Range'])

        stability_analysis.append({
            'Criterion': criterion_name,
            'Number of Stable Regions': region_count,
            'Largest Stable Region': largest_region['Range'],
            'Largest Region %': (largest_region['Range'] / total_range) * 100,
            'Most Stable Ranking': largest_region['Ranking'],
            'Stability Score': largest_region['Range'] / region_count  # higher = more stable
        })

    return pd.DataFrame(stability_analysis).sort_values('Stability Score', ascending=False)


def identify_critical_criteria(sensitivity_results, alternatives):
    """How much each criterion's weight moves the scores and the ranks."""
    alternative_names = [alternative.name for alternative in alternatives]
    impacts = []

    for criterion_name, results in sensitivity_results.items():
        scores_array = np.array(results['scores'])
        total_variance = np.sum(np.var(scores_array, axis=0))

        # Count every time an alternative changes rank from one tested weight to the next
        rankings = results['rankings']
        rank_changes = 0
        for step in range(len(rankings) - 1):
            for alternative_name in alternative_names:
                if rankings[step].index(alternative_name) != rankings[step + 1].index(alternative_name):
                    rank_changes += 1

        impacts.append({
            'Criterion': criterion_name,
            'Score Variance': total_variance,
            'Rank Changes': rank_changes,
            'Impact Score': total_variance + rank_changes * 0.1  # both combined into one number
        })

    return pd.DataFrame(impacts).sort_values('Impact Score', ascending=False)


def run_full_sensitivity_analysis(alternatives, criteria, output_dir='assets'):
    """Run every sensitivity analysis above (30 weight steps) and save the charts and an Excel file."""
    print("\n[*] Performing OAT weight sensitivity analysis...")
    sensitivity_results = perform_weight_sensitivity_analysis(alternatives, criteria, steps = 30)

    print("[*] Analyzing rank changes...")
    rank_stats = analyze_rank_changes(sensitivity_results, alternatives)

    print("[*] Finding critical weight thresholds...")
    threshold_points = find_threshold_points(sensitivity_results, alternatives)

    print("[*] Analyzing stability regions...")
    stability_regions = analyze_stability_regions(sensitivity_results, alternatives)

    print("[*] Identifying critical criteria...")
    critical_criteria = identify_critical_criteria(sensitivity_results, alternatives)

    print("[*] Generating visualizations...")
    plot_sensitivity_analysis(sensitivity_results, alternatives,
                              output_path=f'{output_dir}/sensitivity_analysis.png')
    plot_rank_sensitivity_analysis(sensitivity_results, alternatives,
                                   output_path=f'{output_dir}/rank_sensitivity_analysis.png')
    plot_threshold_summary(threshold_points, output_path=f'{output_dir}/threshold_summary.png')

    print("[*] Exporting results to Excel...")
    excel_path = f'{output_dir}/sensitivity_analysis.xlsx'
    with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
        rank_stats.to_excel(writer, sheet_name='Rank Stability', index=False)
        critical_criteria.to_excel(writer, sheet_name='Criteria Impact', index=False)
        threshold_points.to_excel(writer, sheet_name='Threshold Points', index=False)
        stability_regions.to_excel(writer, sheet_name='Stability Regions', index=False)

        # The scores at every tested weight, one sheet per criterion
        for criterion_name, results in sensitivity_results.items():
            sheet_name = criterion_name[:31]  # Excel limit on sheet names
            score_table = pd.DataFrame({
                'Weight': results['test_weights'],
                **{f'{alternative.name}_score': np.array(results['scores'])[:, alternative_index]
                   for alternative_index, alternative in enumerate(alternatives)}
            })
            score_table.to_excel(writer, sheet_name=sheet_name, index=False)

    print(f"[OK] Sensitivity analysis Excel report saved to: {excel_path}")
    print(f"\n[OK] Sensitivity analysis complete!")

    return {
        'sensitivity_results': sensitivity_results,
        'rank_stability': rank_stats,
        'criteria_impact': critical_criteria,
        'threshold_points': threshold_points,
        'stability_regions': stability_regions
    }


if __name__ == "__main__":
    # Run the AHP study, then the sensitivity analysis on its result
    from analysis.ahp import main

    result = main()
    sensitivity_output = run_full_sensitivity_analysis(result["alternatives"], result["criteria"])
