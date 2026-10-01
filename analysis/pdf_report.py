"""
analysis/pdf_report.py

PDF report of a saved simulation run (History), built with reportlab and
matplotlib: every input, then what the Ranking, decision details, Sensitivity
and Statistics tabs show, charts included. The event timeline and the
machines-available chart are left out on purpose: they belong to one
replication of one alternative, and the timeline doesn't fit on a page.

The tables of inputs reuse the parameter frames of the Excel report
(analysis/report.py), so both reports describe the run the same way. Numbers
are formatted like the Simulation page (fmtCell, eur, pct in format.ts), and
the charts are drawn like its Plotly charts: same titles, Times New Roman at
the same sizes, same proportions, two per row.
"""
from __future__ import annotations

import io
import math
import os
import re
from datetime import datetime
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter, ScalarFormatter
import pandas as pd

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle,
    Image, KeepTogether, PageBreak, CondPageBreak,
)
from xml.sax.saxutils import escape

from analysis.report import parameter_frames
from analysis.statistics import CI_BOOTSTRAP_SAMPLES

# Same colours as the app (frontend/src/app.css) and its charts
BRAND = colors.HexColor("#1447E6")
BRAND_LIGHT = colors.HexColor("#DBEAFE")
BORDER = colors.HexColor("#E5E7EB")
HEADER_BACKGROUND = colors.HexColor("#F9FAFB")
TEXT = colors.HexColor("#101828")
TEXT_BODY = colors.HexColor("#4A5565")
TEXT_SUBTLE = colors.HexColor("#6A7282")
DANGER = colors.HexColor("#C70036")
CHART_COLORS = ["#1f77b4", "#d62728", "#2ca02c", "#ff7f0e", "#9467bd",
                "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf", "#0e4c92", "#a01f1f"]

METHOD_LABELS = {"AHP": "AHP", "TOPSIS": "TOPSIS", "ELECTRE2": "ELECTRE II"}

# Same metrics, labels and kinds as the Statistics tab
METRIC_DEFS: dict[str, tuple[str, str]] = {
    "total_cost":                  ("Total cost", "eur"),
    "purchase_cost":               ("Purchase cost", "eur"),
    "corrective_maintenance_cost": ("CM cost", "eur"),
    "preventive_maintenance_cost": ("PM cost", "eur"),
    "normal_availability":         ("Availability — normal", "fraction"),
    "crisis_availability":         ("Availability — crisis", "fraction"),
    "crisis_expected_unmet":       ("Expected unmet demand — crisis", "units"),
}
UNCERTAINTY_KEYS = [metric for metric in METRIC_DEFS if metric != "crisis_expected_unmet"]
UNIT_SUFFIX = {"eur": "€", "fraction": "%", "units": "units"}
REL_HW_FLAG = 0.05

PAGE_SIZE = landscape(A4)
MARGIN = 1.4 * cm
CONTENT_WIDTH = PAGE_SIZE[0] - 2 * MARGIN
CONTENT_HEIGHT = PAGE_SIZE[1] - 2 * MARGIN
COLUMN_GAP = 0.6 * cm
HALF_WIDTH = (CONTENT_WIDTH - COLUMN_GAP) / 2      # one column of the page's two-column grids
ROW_GAP = 12
MAX_CHART_HEIGHT = (CONTENT_HEIGHT - 2 * ROW_GAP) / 2 - 2   # two rows of charts fit on a page
CHART_DPI = 200


# Fonts: DejaVu Sans ships with matplotlib and has η, β, ±, € and the dashes

def _register_fonts() -> tuple[str, str]:
    if "DejaVuSans" not in pdfmetrics.getRegisteredFontNames():
        font_directory = os.path.join(matplotlib.get_data_path(), "fonts", "ttf")
        pdfmetrics.registerFont(TTFont("DejaVuSans", os.path.join(font_directory, "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", os.path.join(font_directory, "DejaVuSans-Bold.ttf")))
        pdfmetrics.registerFontFamily("DejaVuSans", normal="DejaVuSans", bold="DejaVuSans-Bold")
    return "DejaVuSans", "DejaVuSans-Bold"


FONT, FONT_BOLD = _register_fonts()

STYLES = {
    "title": ParagraphStyle("title", fontName=FONT_BOLD, fontSize=18, leading=22, textColor=TEXT, spaceAfter=4),
    "subtitle": ParagraphStyle("subtitle", fontName=FONT, fontSize=9.5, leading=13, textColor=TEXT_BODY),
    "h1": ParagraphStyle("h1", fontName=FONT_BOLD, fontSize=14, leading=18, textColor=TEXT, spaceBefore=4, spaceAfter=8),
    "h2": ParagraphStyle("h2", fontName=FONT_BOLD, fontSize=10.5, leading=14, textColor=TEXT, spaceBefore=10, spaceAfter=4),
    "h3": ParagraphStyle("h3", fontName=FONT_BOLD, fontSize=8, leading=11, textColor=TEXT_SUBTLE, spaceBefore=8, spaceAfter=3),
    "body": ParagraphStyle("body", fontName=FONT, fontSize=8.5, leading=12, textColor=TEXT_BODY, spaceAfter=4),
    "note": ParagraphStyle("note", fontName=FONT, fontSize=7.5, leading=10, textColor=TEXT_SUBTLE, spaceBefore=3),
    "cell": ParagraphStyle("cell", fontName=FONT, fontSize=7.5, leading=9.5, textColor=TEXT_BODY),
    "cell_right": ParagraphStyle("cell_right", fontName=FONT, fontSize=7.5, leading=9.5, textColor=TEXT_BODY, alignment=TA_RIGHT),
    "header": ParagraphStyle("header", fontName=FONT_BOLD, fontSize=7.5, leading=9.5, textColor=TEXT_SUBTLE),
    "header_right": ParagraphStyle("header_right", fontName=FONT_BOLD, fontSize=7.5, leading=9.5, textColor=TEXT_SUBTLE, alignment=TA_RIGHT),
}


# Number formatting, as on the Simulation page

def fmt_cell(value: Any) -> str:
    """Small numbers with 4 decimals, large ones rounded with thousands separators (fmtCell)."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        if isinstance(value, int) and abs(value) < 10:
            return str(value)
        return f"{value:.4f}" if abs(value) < 10 else f"{round(value):,}"
    if isinstance(value, (list, tuple)):
        return ", ".join(fmt_cell(item) for item in value)
    if isinstance(value, dict):
        return "; ".join(f"{key}: {fmt_cell(item)}" for key, item in value.items())
    return str(value)


def cell_text(value: Any) -> str:
    """Parameter-table cells as the Statistics tab shows them: whole numbers as they are, others up to 4 decimals."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    if isinstance(value, (list, tuple)):
        return ", ".join(cell_text(item) for item in value)
    if isinstance(value, dict):
        return "; ".join(f"{key}: {cell_text(item)}" for key, item in value.items())
    return str(value)


def eur(amount: float | None) -> str:
    return "—" if amount is None else f"€{round(amount):,}"


def pct(fraction: float | None, decimals: int = 3) -> str:
    return "—" if fraction is None else f"{fraction * 100:.{decimals}f}%"


def fmt_metric(metric: str, value: float | None) -> str:
    if value is None:
        return "—"
    kind = METRIC_DEFS[metric][1]
    if kind == "eur":
        return eur(value)
    if kind == "fraction":
        return f"{value * 100:.3f}%"
    return f"{value:.3f}"


def fmt_half_width(metric: str, value: float | None) -> str:
    if value is None:
        return "—"
    kind = METRIC_DEFS[metric][1]
    if kind == "eur":
        return f"± {eur(value)}"
    if kind == "fraction":
        return f"± {value * 100:.3f} pp"
    return f"± {value:.3f}"


def fmt_relative(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.2f}%"


def with_interval(value_text: str, metric: str, half_width: float | None,
                  relative: float | None = None, show_relative: bool = False) -> str:
    """The value, with its confidence half-width on a second line. With a single
    replication there is no interval, so the second line is left out."""
    if half_width is None:
        return value_text
    interval = fmt_half_width(metric, half_width)
    if show_relative:
        interval += f" ({fmt_relative(relative)})"
    return f"{value_text}\n{interval}"


# Tables

class Flagged(str):
    """Cell text shown in red, like the values the Statistics tab flags."""


class Emphasized(str):
    """Cell text shown in bold, like the ranks that can switch on the Sensitivity tab."""


def _cell(text: Any, right: bool = False, header: bool = False) -> Paragraph:
    if header:
        style = STYLES["header_right" if right else "header"]
    else:
        style = STYLES["cell_right" if right else "cell"]
    if isinstance(text, Flagged):
        style = ParagraphStyle("flagged", parent=style, textColor=DANGER)
    if isinstance(text, Emphasized):
        style = ParagraphStyle("emphasized", parent=style, fontName=FONT_BOLD, textColor=TEXT)
    content = text if isinstance(text, str) else fmt_cell(text)
    return Paragraph(escape(content).replace("\n", "<br/>"), style)


CELL_PADDING = 10          # left + right padding, plus a little slack
MAX_NATURAL_WIDTH = 220    # a long text wraps rather than taking the whole page


def _text_width(text: str, bold: bool) -> float:
    return pdfmetrics.stringWidth(text, FONT_BOLD if bold else FONT, STYLES["cell"].fontSize)


def _column_widths(rows: list[list[str]], available_width: float) -> list[float]:
    """
    Width of each column from its longest line of text (the first row is the
    bold header). When the table is too wide, columns give up space in
    proportion to what they have beyond their longest word, so text wraps
    between words instead of inside them.
    """
    natural, minimum = [], []
    for column in range(len(rows[0])):
        line_widths, word_widths = [0.0], [0.0]
        for row_index, row in enumerate(rows):
            bold = row_index == 0 or isinstance(row[column], Emphasized)
            for line in str(row[column]).split("\n"):
                line_widths.append(_text_width(line, bold))
                word_widths += [_text_width(word, bold) for word in line.split()]
        longest_word = max(word_widths)
        natural.append(min(max(max(line_widths), longest_word), MAX_NATURAL_WIDTH) + CELL_PADDING)
        minimum.append(longest_word + CELL_PADDING)
    if sum(natural) <= available_width:
        return natural
    if sum(minimum) >= available_width:
        return [width * available_width / sum(minimum) for width in minimum]
    share = (available_width - sum(minimum)) / (sum(natural) - sum(minimum))
    return [low + (high - low) * share for low, high in zip(minimum, natural)]


def make_table(
    header: list[str],
    rows: list[list[Any]],
    right_align: set[int] | None = None,
    highlight_rows: set[int] | None = None,
    cell_styles: list[tuple] | None = None,
    available_width: float = CONTENT_WIDTH,
    formatter=fmt_cell,
) -> Table:
    """A table in the app's style: grey header, light borders, text that wraps."""
    right_align = right_align or set()
    # Strings (Flagged included) are kept as they are, anything else is formatted
    text_rows = [[value if isinstance(value, str) else formatter(value) for value in row] for row in rows]
    widths = _column_widths([header] + text_rows, available_width)
    data = [[_cell(title, column in right_align, header=True) for column, title in enumerate(header)]]
    data += [[_cell(value, column in right_align) for column, value in enumerate(row)] for row in text_rows]
    table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BACKGROUND),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, BORDER),
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    for row_index in highlight_rows or set():
        style.append(("BACKGROUND", (0, row_index + 1), (-1, row_index + 1), BRAND_LIGHT))
    style += cell_styles or []
    table.setStyle(TableStyle(style))
    return table


def frame_table(frame: pd.DataFrame) -> Table | Paragraph:
    """A DataFrame as a table, with numeric columns right-aligned."""
    if frame is None or frame.empty:
        return Paragraph("— none —", STYLES["note"])
    header = [str(column) for column in frame.columns]
    rows = [[None if (isinstance(value, float) and math.isnan(value)) else value for value in row]
            for row in frame.itertuples(index=False, name=None)]
    right_align = {
        column_index for column_index, column in enumerate(frame.columns)
        if pd.api.types.is_numeric_dtype(frame[column]) and not pd.api.types.is_bool_dtype(frame[column])
    }
    return make_table(header, rows, right_align, formatter=cell_text)


def matrix_table(rows: list[dict[str, Any]]) -> Table | Paragraph:
    """One of the decision matrices (rows keep their label under "_row")."""
    if not rows:
        return Paragraph("— none —", STYLES["note"])
    columns = [key for key in rows[0] if key != "_row"]
    return make_table(
        [""] + columns,
        [[row["_row"]] + [row.get(column) for column in columns] for row in rows],
        right_align=set(range(1, len(columns) + 1)),
    )


# Charts, drawn like the Plotly charts of the Simulation page. A figure is built at
# 72 dpi, so sizes in points are the page's sizes in pixels: a chart in one column
# of the page's two-column grid (about 800 px on a 1920 px screen), fonts as in
# withChartFonts, Plotly's text colour and marker/line sizes.

CHART_PX_WIDTH = 800
PLOTLY_DEFAULT_HEIGHT = 450
CHART_TITLE_SIZE = 22
CHART_AXIS_TITLE_SIZE = 20
CHART_TICK_SIZE = 18
CHART_LEGEND_SIZE = 16
CHART_TEXT = "#444444"     # Plotly's default font colour
CHART_STYLE = {
    "font.family": "serif",
    "font.serif": ["Times New Roman", "Times", "DejaVu Serif"],
    "text.color": CHART_TEXT,
    "axes.labelcolor": CHART_TEXT,
    "xtick.color": CHART_TEXT,
    "ytick.color": CHART_TEXT,
    "xtick.major.size": 0,
    "ytick.major.size": 0,
    "axes.spines.left": False,
    "axes.spines.right": False,
    "axes.spines.top": False,
    "axes.spines.bottom": False,
    "axes.grid": True,
    "axes.axisbelow": True,
    "grid.color": "#E5E7EB",
    "grid.linewidth": 1,
    "legend.frameon": False,
}


def _chart_figure(height_px: float):
    """A figure and its axes, `height_px` screen pixels tall, one grid column wide."""
    return plt.subplots(figsize=(CHART_PX_WIDTH / 72, height_px / 72), dpi=72, layout="constrained")


def _figure_image(figure, width: float, max_height: float | None = None) -> Image:
    """A matplotlib figure as an image `width` points wide, or narrower when it would
    be taller than `max_height`, keeping its proportions."""
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", dpi=CHART_DPI)
    plt.close(figure)
    buffer.seek(0)
    image = Image(buffer)
    scale = width / image.imageWidth
    if max_height is not None:
        scale = min(scale, max_height / image.imageHeight)
    image.drawWidth = image.imageWidth * scale
    image.drawHeight = image.imageHeight * scale
    return image


def _style_axes(figure, axes, title: str, x_label: str, y_label: str) -> None:
    """Plotly centres the title over the whole chart, legend included."""
    figure.suptitle(title, fontsize=CHART_TITLE_SIZE)
    axes.set_xlabel(x_label, fontsize=CHART_AXIS_TITLE_SIZE)
    axes.set_ylabel(y_label, fontsize=CHART_AXIS_TITLE_SIZE)
    axes.tick_params(labelsize=CHART_TICK_SIZE)


def _zero_lines(axes) -> None:
    """Plotly's zero lines: a dark line at 0 on each axis whose range includes it."""
    if min(axes.get_xlim()) <= 0 <= max(axes.get_xlim()):
        axes.axvline(0, color=CHART_TEXT, linewidth=1, zorder=1)
    if min(axes.get_ylim()) <= 0 <= max(axes.get_ylim()):
        axes.axhline(0, color=CHART_TEXT, linewidth=1, zorder=1)


def _right_legend(axes) -> None:
    """Plotly's default legend: one column to the right of the plot, top-aligned."""
    axes.legend(fontsize=CHART_LEGEND_SIZE, loc="upper left", bbox_to_anchor=(1.02, 1.0), borderaxespad=0)


def _below_legend(axes, y: float, handles: list | None = None) -> None:
    """A horizontal legend of two items under the plot, left-aligned (orientation "h" at x = 0)."""
    axes.legend(handles=handles, fontsize=CHART_LEGEND_SIZE, loc="upper left", bbox_to_anchor=(0, y),
                ncol=2, borderaxespad=0)


def _two_columns(flowables: list) -> Table:
    """Flowables two per row, like the two-column grids of the Simulation page."""
    rows = [flowables[index:index + 2] for index in range(0, len(flowables), 2)]
    if len(rows[-1]) == 1:
        rows[-1].append("")
    table = Table(rows, colWidths=[HALF_WIDTH + COLUMN_GAP, HALF_WIDTH], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (0, -1), COLUMN_GAP),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), ROW_GAP),
    ]))
    return table


def rank_sensitivity_chart(label: str, ranks: dict) -> Image:
    """Rank of every alternative against the weight of one criterion."""
    weights = ranks["weights"]
    alternative_names = [name for name in ranks if name != "weights"]
    with plt.rc_context(CHART_STYLE):
        figure, axes = _chart_figure(34 * len(alternative_names) + 170)   # height as on the page
        for index, name in enumerate(alternative_names):
            axes.plot(weights, ranks[name], marker="o", markersize=4, linewidth=2,
                      color=CHART_COLORS[index % len(CHART_COLORS)], label=name)
        _style_axes(figure, axes, f"Rank Sensitivity: {label}", f'Weight of "{label}"', "Rank")
        axes.set_yticks(range(1, len(alternative_names) + 1))
        axes.invert_yaxis()
        _zero_lines(axes)
        _right_legend(axes)
        return _figure_image(figure, HALF_WIDTH, MAX_CHART_HEIGHT)


RANK_SWITCH_COLOR = "#1447E6"   # alternatives that can switch rank (brand)
RANK_STABLE_COLOR = "#6A7282"   # ranks that hold (subtle text grey)


def rank_range_chart(cost_ci_ranking: dict, confidence_label: str) -> Image:
    """
    Every alternative at its rank with the mean costs and, for the ones that can
    switch, an arrow to each rank they reach with the total costs in their CI.
    """
    entries = sorted(cost_ci_ranking["alternatives"], key=lambda entry: entry["rank_base"])
    count = len(entries)
    marker = dict(marker="o", markersize=11, markeredgecolor="white", markeredgewidth=2, linestyle="")
    with plt.rc_context(CHART_STYLE):
        figure, axes = _chart_figure(34 * count + 170)   # height as on the page
        for row, entry in enumerate(entries):
            can_switch = entry["rank_best"] != entry["rank_worst"]
            for rank in sorted({entry["rank_best"], entry["rank_worst"]} - {entry["rank_base"]}):
                axes.annotate("", xy=(rank, row), xytext=(entry["rank_base"], row),
                              arrowprops=dict(arrowstyle="-|>", color=RANK_SWITCH_COLOR, lw=2, mutation_scale=16,
                                              shrinkA=7, shrinkB=0))
            axes.plot(entry["rank_base"], row, color=RANK_SWITCH_COLOR if can_switch else RANK_STABLE_COLOR,
                      zorder=3, **marker)
        axes.set_yticks(range(count), [entry["name"] for entry in entries])
        axes.set_ylim(count - 0.5, -0.5)
        axes.set_xticks(range(1, count + 1))
        axes.set_xlim(0.5, count + 0.5)
        _style_axes(figure, axes, f"Rank range with total costs in their {confidence_label}", "Ranks", "")
        _below_legend(axes, -0.22, handles=[
            Line2D([], [], color=RANK_STABLE_COLOR, label="Rank holds", **marker),
            Line2D([], [], color=RANK_SWITCH_COLOR, label="Rank switches", **marker),
        ])
        return _figure_image(figure, HALF_WIDTH, MAX_CHART_HEIGHT)


def running_mean_chart(metric: str, chosen: dict, confidence_label: str) -> Image:
    """Running mean of one alternative with its confidence band."""
    label, kind = METRIC_DEFS[metric]
    scale = 100 if kind == "fraction" else 1
    metric_stats = chosen["metrics"][metric]
    replications = list(range(1, len(metric_stats["running_mean"]) + 1))
    mean = [value * scale for value in metric_stats["running_mean"]]
    half_widths = [(width or 0) * scale for width in metric_stats["running_half_width"]]
    with plt.rc_context(CHART_STYLE):
        figure, axes = _chart_figure(PLOTLY_DEFAULT_HEIGHT)
        axes.fill_between(replications, [m - h for m, h in zip(mean, half_widths)],
                          [m + h for m, h in zip(mean, half_widths)],
                          color="#1f77b4", alpha=0.18, linewidth=0, label=confidence_label)
        axes.plot(replications, mean, color="#1f77b4", marker="o", markersize=4, linewidth=2, label="Running mean")
        _style_axes(figure, axes, f"Running mean — {chosen['name']} — {label}", "Replications",
                    f"{label} ({UNIT_SUFFIX[kind]})")
        axes.xaxis.get_major_locator().set_params(integer=True)
        # Whole values on the axis, as Plotly shows them, rather than an offset or a power of ten
        if kind == "eur":
            axes.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:,.0f}"))
        else:
            plain = ScalarFormatter(useOffset=False)
            plain.set_scientific(False)
            axes.yaxis.set_major_formatter(plain)
        _below_legend(axes, -0.32)
        return _figure_image(figure, HALF_WIDTH, MAX_CHART_HEIGHT)


def relative_half_width_chart(metric: str, statistics: list[dict], confidence_label: str) -> Image:
    """Relative confidence half-width of every alternative against the number of replications."""
    label = METRIC_DEFS[metric][0]
    with plt.rc_context(CHART_STYLE):
        figure, axes = _chart_figure(PLOTLY_DEFAULT_HEIGHT)
        max_replications = 1
        for index, alternative_stats in enumerate(statistics):
            stats_for_metric = alternative_stats["metrics"][metric]
            values = [float("nan") if half_width is None or value == 0 else half_width / abs(value) * 100
                      for value, half_width in zip(stats_for_metric["running_mean"], stats_for_metric["running_half_width"])]
            axes.plot(range(1, len(values) + 1), values, linewidth=2,
                      color=CHART_COLORS[index % len(CHART_COLORS)], label=alternative_stats["name"])
            max_replications = max(max_replications, alternative_stats["n"])
        axes.plot([1, max_replications], [REL_HW_FLAG * 100] * 2, color="#d62728", linestyle="--", linewidth=1)
        axes.annotate(f"{REL_HW_FLAG * 100:g}% target", xy=(max_replications, REL_HW_FLAG * 100),
                      ha="right", va="bottom", fontsize=CHART_LEGEND_SIZE, color="#d62728")
        axes.set_ylim(bottom=0)
        axes.set_xlim(1, max(max_replications, 2))
        _style_axes(figure, axes, f"Relative {confidence_label} half-width — {label}", "Replications",
                    "Half-width / mean (%)")
        axes.xaxis.get_major_locator().set_params(integer=True)
        _zero_lines(axes)
        _right_legend(axes)
        return _figure_image(figure, HALF_WIDTH, MAX_CHART_HEIGHT)


# Sections

def _heading(text: str, style: str = "h2") -> Paragraph:
    return Paragraph(escape(text), STYLES[style])


def _section_heading(text: str) -> list:
    """A heading that starts a new page when there's no room for a few lines under it."""
    return [CondPageBreak(3 * cm), _heading(text)]


def _paragraph(text: str, style: str = "body") -> Paragraph:
    return Paragraph(escape(text), STYLES[style])


def inputs_section(request: dict, result: dict) -> list:
    story: list = [_heading("1. Inputs", "h1")]

    criteria = request.get("criteria_config", [])
    story += _section_heading("Criteria")
    story.append(make_table(
        ["Criterion", "Type", "Minimize"],
        [[criterion["name"], criterion["input_type"], "yes" if criterion.get("minimize") else "no"] for criterion in criteria],
    ))

    input_criteria = [criterion for criterion in criteria if criterion["input_type"] != "computed"]
    configurations = request.get("configurations", [])
    story += _section_heading("Alternatives")
    story.append(make_table(
        ["Name", "Machines", "Replacement (yrs)"] + [criterion["name"] for criterion in input_criteria],
        [
            [config.get("name"), config.get("machine_number"), config.get("replacement_period")]
            + [config.get("scores", {}).get(criterion["attribute_name"]) for criterion in input_criteria]
            for config in configurations
        ],
        right_align=set(range(1, 3 + len(input_criteria))),
        formatter=cell_text,
    ))

    frames = parameter_frames(result.get("parameter_table") or {})
    titles = {
        "Parameters - Run": "Run settings",
        "Parameters - Alternatives": "Alternatives as simulated",
        "Parameters - Fleet": "Fleet (machine cohorts loaded)",
        "Parameters - Spare Parts": "Spare parts",
        "Parameters - Cost Profiles": "Cost profiles",
        "Parameters - PM": "Preventive maintenance programmes",
        "Parameters - Decision": "Decision method, criteria and weights",
    }
    for key, title in titles.items():
        frame = frames.get(key)
        if frame is None:
            continue
        story += _section_heading(title)
        tables = frame if isinstance(frame, list) else [frame]
        for table in tables:
            story.append(frame_table(table))
            story.append(Spacer(1, 6))
    return story


def ranking_section(request: dict, result: dict) -> list:
    method = METHOD_LABELS.get(request.get("method", "AHP").upper(), request.get("method", "AHP"))
    story: list = [PageBreak(), _heading("2. Ranking", "h1")]

    summary = []
    consistency_ratio = result.get("consistency_ratio", -1)
    if consistency_ratio is not None and consistency_ratio >= 0:
        verdict = "✓" if consistency_ratio < 0.1 else "⚠ inconsistent"
        summary.append(f"Consistency Ratio {consistency_ratio * 100:.2f}% {verdict}")
    summary += [f"{weight['name']} {weight['weight'] * 100:.1f}%" for weight in result.get("criteria_weights", [])]
    summary.append(f"Seed {request.get('seed')}")
    story.append(_paragraph(" · ".join(summary)))

    # Means only, as on the Ranking tab: the intervals are in section 5 (Statistics)
    attributes = {criterion["attribute_name"] for criterion in request.get("criteria_config", [])}
    qualitative = [criterion for criterion in request.get("criteria_config", []) if criterion["input_type"] == "qualitative"]
    header = ["Rank", "Alternative", "Machines", "Repl. (yrs)", f"{method} Score",
              "Total Cost", "CM Cost", "PM Cost", "Purchase"]
    if "normal_availability" in attributes:
        header.append("Avail. Normal")
    if "crisis_availability" in attributes:
        header.append("Avail. Crisis")
    if "normal_hours_availability" in attributes:
        header.append("Availability - Normal")
    if "crisis_hours_availability" in attributes:
        header.append("Availability - Crisis")
    header += [criterion["name"] for criterion in qualitative]

    def hours_ratio(worked, scheduled):
        return "—" if worked is None or not scheduled else f"{worked / scheduled:.4f}"

    rows, highlight = [], set()
    for row_index, alternative in enumerate(result.get("alternatives", [])):
        row = [
            f"#{alternative['rank']}", alternative["name"], alternative["machine_number"], alternative["replacement_period"],
            f"{alternative['final_score']:.4f}",
            eur(alternative["total_cost"]),
            eur(alternative["corrective_maintenance_cost"]),
            eur(alternative["preventive_maintenance_cost"]),
            eur(alternative["purchase_cost"]),
        ]
        if "normal_availability" in attributes:
            row.append(pct(alternative["normal_availability"]))
        if "crisis_availability" in attributes:
            row.append(pct(alternative["crisis_availability"]))
        if "normal_hours_availability" in attributes:
            row.append(hours_ratio(alternative.get("normal_hours_worked"), alternative.get("normal_hours_scheduled")))
        if "crisis_hours_availability" in attributes:
            row.append(hours_ratio(alternative.get("crisis_hours_worked"), alternative.get("crisis_hours_scheduled")))
        row += [cell_text(alternative.get("scores", {}).get(criterion["attribute_name"])) for criterion in qualitative]
        if alternative["rank"] == 1:
            highlight.add(row_index)
        rows.append(row)
    story.append(make_table(header, rows, right_align=set(range(4, len(header))), highlight_rows=highlight))
    return story


def decision_details_section(request: dict, result: dict) -> list:
    method = METHOD_LABELS.get(request.get("method", "AHP").upper(), request.get("method", "AHP"))
    story: list = [PageBreak(), _heading(f"3. {method} details", "h1")]
    for title, key in (
        ("Decision Matrix (raw values)", "decision_matrix"),
        ("Normalized Scores", "normalized_scores"),
        ("Weighted Scores", "weighted_scores"),
        ("Criteria Pairwise Comparison Matrix", "pairwise_matrix"),
    ):
        story.append(KeepTogether([_heading(title), matrix_table(result.get(key) or [])]))
    return story


# The availability criteria are called service rates in the sensitivity charts
SERVICE_RATE_LABELS = {
    "normal_availability": "Service Rate — Normal",
    "crisis_availability": "Service Rate — Crisis",
}


def chart_criterion_label(criterion_name: str, result: dict) -> str:
    attribute = next((weight.get("attribute_name") for weight in result.get("criteria_weights", [])
                      if weight["name"] == criterion_name), None)
    return SERVICE_RATE_LABELS.get(attribute, criterion_name)


def sensitivity_section(request: dict, result: dict) -> list:
    story: list = [PageBreak(), _heading("4. Sensitivity", "h1")]
    ranks = result.get("sensitivity_ranks") or {}
    story += _section_heading("Criteria weights")
    story.append(_paragraph(
        "One weight at a time is moved from 0 to 1 while the others are rescaled in proportion, and the "
        "alternatives are ranked again with the weighted sum."
    ))
    if ranks:
        story.append(_two_columns([
            rank_sensitivity_chart(chart_criterion_label(criterion, result), ranks[criterion]) for criterion in ranks
        ]))
    else:
        story.append(_paragraph("Weight sensitivity data not available."))
    story += cost_ci_section(result)
    return story


def cost_ci_section(result: dict) -> list:
    """Every alternative's rank with the total costs anywhere in their confidence intervals:
    the table, and the rank range chart next to it."""
    label = f"{round(result.get('confidence_level', 0.95) * 100)}% CI"
    cost_ci_ranking = result.get("cost_ci_ranking")
    heading = _heading(f"Total cost within its {label}")
    if not cost_ci_ranking:
        replications = (result.get("statistics") or [{}])[0].get("n", 0)
        return [CondPageBreak(3 * cm), heading, _paragraph(
            "Needs at least 2 replications (no confidence interval)." if replications < 2
            else "Not available for this run (saved before this check existed). Run it again to see it."
        )]
    result_by_name = {entry["name"]: entry for entry in cost_ci_ranking.get("alternatives", [])}
    rows = []
    for alternative in result.get("alternatives", []):
        entry = result_by_name.get(alternative["name"])
        if not entry:
            rows.append([alternative["name"]] + ["—"] * 4)
            continue
        if entry["rank_best"] == entry["rank_worst"]:
            rank_range = f"{entry['rank_best']} (stable)"
        else:
            rank_range = Emphasized(f"{entry['rank_best']}–{entry['rank_worst']}")
        rows.append([alternative["name"], eur(entry["cost_mean"]), f"{eur(entry['ci_low'])} – {eur(entry['ci_high'])}",
                     entry["rank_base"], rank_range])
    table = make_table(["Alternative", "Total cost", label, "Rank", "Rank range"], rows,
                       right_align={1, 2, 3, 4}, available_width=HALF_WIDTH)
    # The page explains the rank range in the column's tooltip
    table_part = [table, _paragraph("Rank range — best: its total cost at the lower end of its interval, every other "
                                    "alternative's at the upper end. Worst: the reverse.", "note")]

    story: list = [heading]
    if not cost_ci_ranking.get("cost_is_criterion", True):
        story.append(_paragraph("Total cost is not a criterion in this run, so ranks cannot change."))
    chart = rank_range_chart(cost_ci_ranking, label) if cost_ci_ranking.get("alternatives") else Spacer(0, 0)
    _, table_height = table.wrap(HALF_WIDTH, CONTENT_HEIGHT)
    if table_height < CONTENT_HEIGHT - 4 * cm:
        story.append(_two_columns([table_part, chart]))
        return [KeepTogether(story)]
    # Too many alternatives to fit next to the chart: the chart goes under the table
    return [CondPageBreak(3 * cm)] + story + table_part + [Spacer(1, 8), chart]


def statistics_section(request: dict, result: dict) -> list:
    confidence_label = f"{round(result.get('confidence_level', 0.95) * 100)}% CI"
    statistics = result.get("statistics") or []
    stats_by_name = {stats["name"]: stats for stats in statistics}
    replications = statistics[0]["n"] if statistics else 0
    story: list = [PageBreak(), _heading("5. Statistics", "h1")]

    has_spread = replications >= 2
    if has_spread:
        story.append(_paragraph(
            f"{replications} replications per alternative · intervals are bootstrap percentile "
            f"{confidence_label} on the mean ({CI_BOOTSTRAP_SAMPLES:,} resamples of the replications) · convergence flagged when the relative half-width exceeds {REL_HW_FLAG * 100:g}%."
        ))
    else:
        story.append(_paragraph(
            f"{replications} replication{'' if replications == 1 else 's'} per alternative. Confidence intervals, "
            f"convergence and ranking robustness need at least 2 replications, so they are left out."
        ))
    if not statistics:
        return story

    if has_spread:
        story += uncertainty_part(statistics, confidence_label)
    story += resilience_part(result, stats_by_name, confidence_label, has_spread)
    if has_spread:
        story += convergence_part(result, statistics, confidence_label)
        story += ranking_robustness_part(result.get("bootstrap"), confidence_label)

    story.append(_paragraph("The parameter table of this run is in section 1 (Inputs).", "note"))
    return story


def uncertainty_part(statistics: list, confidence_label: str) -> list:
    story: list = []
    rows = []
    for stats in statistics:
        row = [stats["name"], stats["n"]]
        for metric in UNCERTAINTY_KEYS:
            metric_stats = stats["metrics"][metric]
            text = with_interval(fmt_metric(metric, metric_stats["mean"]), metric, metric_stats["half_width"],
                                 metric_stats["rel_half_width"], show_relative=True)
            flagged = metric_stats["rel_half_width"] is not None and metric_stats["rel_half_width"] > REL_HW_FLAG
            row.append(Flagged(text) if flagged else text)
        rows.append(row)
    story += _section_heading(f"Uncertainty — mean ± {confidence_label} half-width (relative half-width)")
    table = make_table(["Alternative", "N"] + [METRIC_DEFS[metric][0] for metric in UNCERTAINTY_KEYS], rows,
                       right_align=set(range(1, 2 + len(UNCERTAINTY_KEYS))))
    story.append(table)
    story.append(_paragraph('SD, SE and CI bounds for every metric are in the Excel report ("Uncertainty" sheet).', "note"))
    return story


def resilience_part(result: dict, stats_by_name: dict, confidence_label: str, has_spread: bool) -> list:
    story: list = []
    text = ("Expected unmet demand: average number of devices missing to reach the crisis target, following the fleet "
            "continuously and assuming crisis demand for the whole horizon"
            + (f" (mean ± {confidence_label} half-width)." if has_spread else "."))
    header = ["Alternative", "Expected unmet demand"]
    rows = []
    for alternative in result.get("alternatives", []):
        unmet = stats_by_name.get(alternative["name"], {}).get("metrics", {}).get("crisis_expected_unmet") or {}
        rows.append([alternative["name"],
                     with_interval(fmt_metric("crisis_expected_unmet", unmet.get("mean")), "crisis_expected_unmet",
                                   unmet.get("half_width"))])
    story += _section_heading("Resilience")
    story.append(_paragraph(text))
    story.append(make_table(header, rows, right_align={1}))
    return story


def convergence_part(result: dict, statistics: list, confidence_label: str) -> list:
    """Convergence, one metric at a time."""
    story: list = []
    top_alternative = (result.get("alternatives") or [{}])[0].get("name", statistics[0]["name"])
    chosen = next((stats for stats in statistics if stats["name"] == top_alternative), statistics[0])
    # The heading and its text stay on the page of the first metric's charts
    intro = [_heading("Convergence"), _paragraph(
        f"Left: running mean of {top_alternative} (ranked 1st) with its {confidence_label} band. Right: relative "
        f"half-width of every alternative. \"N for ±x%\" is the replication count at which the half-width would fall "
        f"to x% of the mean, scaling the current half-width by 1/√N."
    )]
    for metric in METRIC_DEFS:
        rows = []
        for stats in statistics:
            metric_stats = stats["metrics"][metric]
            flagged = metric_stats["rel_half_width"] is not None and metric_stats["rel_half_width"] > REL_HW_FLAG
            rows.append([
                stats["name"], METRIC_DEFS[metric][0], stats["n"],
                Flagged(fmt_relative(metric_stats["rel_half_width"]) + " ⚠") if flagged
                else fmt_relative(metric_stats["rel_half_width"]),
                metric_stats["n_required"].get("0.05"), metric_stats["n_required"].get("0.02"),
                metric_stats["n_required"].get("0.01"),
            ])
        story.append(KeepTogether(intro + [
            _heading(METRIC_DEFS[metric][0], "h3"),
            _two_columns([
                running_mean_chart(metric, chosen, confidence_label),
                relative_half_width_chart(metric, statistics, confidence_label),
            ]),
        ]))
        intro = []
        story.append(make_table(
            ["Alternative", "Metric", "N run", "Rel. half-width at N", "N for ±5%", "N for ±2%", "N for ±1%"], rows,
            right_align={2, 3, 4, 5, 6},
        ))
    return story


def ranking_robustness_part(bootstrap: dict | None, confidence_label: str) -> list:
    story = _section_heading("Ranking robustness (bootstrap)")
    if bootstrap:
        held_constant = bootstrap.get("held_constant") or []
        story.append(_paragraph(
            f"{bootstrap['samples']} resamples of the {bootstrap['replications_per_alternative']} replications per "
            f"alternative, re-ranked with {bootstrap['method']}"
            + (f" · held constant: {', '.join(held_constant)}." if held_constant else ".")
        ))
        alternatives = sorted(bootstrap["alternatives"], key=lambda entry: entry["mean_rank"])
        rank_count = len(alternatives)
        rows, cell_styles = [], []
        for row_index, entry in enumerate(alternatives):
            row = [entry["name"], f"{entry['p_best'] * 100:.1f}%", f"{entry['mean_rank']:.2f}",
                   f"{entry['rank_ci'][0]}–{entry['rank_ci'][1]}"]
            for rank_index, probability in enumerate(entry["rank_probabilities"]):
                row.append(f"{probability * 100:.0f}%" if probability > 0 else "·")
                shade = (None if probability <= 0 else 0.10 if probability < 0.25 else 0.25 if probability < 0.5
                         else 0.45 if probability < 0.75 else 0.70)
                if shade:
                    cell = (4 + rank_index, row_index + 1)
                    cell_styles.append(("BACKGROUND", cell, cell, colors.Color(0.078, 0.278, 0.902, alpha=shade)))
            rows.append(row)
        story.append(make_table(
            ["Alternative", "P(rank 1)", "Mean rank", f"{confidence_label.replace(' CI', '')} rank interval"]
            + [f"#{rank + 1}" for rank in range(rank_count)],
            rows, right_align=set(range(1, 4 + rank_count)), cell_styles=cell_styles,
        ))
    else:
        story.append(_paragraph("Bootstrap not run (bootstrap draws set to 0)."))
    return story


# Document

def pdf_filename(name: str, created_at: datetime) -> str:
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_") or "simulation_run"
    local_time = created_at.astimezone() if created_at.tzinfo else created_at
    return f"{safe_name}_{local_time:%Y-%m-%d}.pdf"


def build_run_pdf(name: str, created_at: datetime, request: dict, result: dict) -> bytes:
    """The PDF report of one saved run, as bytes."""
    buffer = io.BytesIO()
    local_time = created_at.astimezone() if created_at.tzinfo else created_at

    def draw_footer(canvas, document):
        canvas.saveState()
        canvas.setFont(FONT, 7.5)
        canvas.setFillColor(TEXT_SUBTLE)
        canvas.drawString(MARGIN, 0.8 * cm, f"{name} · {local_time:%d %b %Y, %H:%M}")
        canvas.drawRightString(PAGE_SIZE[0] - MARGIN, 0.8 * cm, f"Page {document.page}")
        canvas.restoreState()

    document = BaseDocTemplate(
        buffer, pagesize=PAGE_SIZE, leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN, bottomMargin=MARGIN, title=name, author="SimulationApp",
    )
    # No padding inside the frame, so CONTENT_WIDTH and CONTENT_HEIGHT are what the story gets
    frame = Frame(MARGIN, MARGIN, CONTENT_WIDTH, CONTENT_HEIGHT, id="content",
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    document.addPageTemplates([PageTemplate(id="page", frames=[frame], onPage=draw_footer)])

    method = METHOD_LABELS.get(request.get("method", "AHP").upper(), request.get("method", "AHP"))
    machine_type = (request.get("configurations") or [{}])[0].get("machine_type", "")
    best = (result.get("alternatives") or [{}])[0].get("name", "—")
    story: list = [
        Paragraph(escape(name), STYLES["title"]),
        _paragraph(
            f"Saved {local_time:%d %b %Y, %H:%M} · {method} · {machine_type} · "
            f"{len(request.get('configurations', []))} alternatives · {request.get('simulation_number')} Monte Carlo runs · "
            f"{request.get('period')}-year horizon · seed {request.get('seed')} · ranked 1st: {best}",
            "subtitle",
        ),
        Spacer(1, 10),
    ]
    story += inputs_section(request, result)
    story += ranking_section(request, result)
    story += decision_details_section(request, result)
    story += sensitivity_section(request, result)
    story += statistics_section(request, result)

    document.build(story)
    return buffer.getvalue()
