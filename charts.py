"""
charts.py — generates PNG chart images for the Money Manager bot.

All functions are synchronous and return raw bytes (PNG) or None if there
is nothing to draw.  Call them from async handlers and wrap the result in
io.BytesIO before passing to send_photo.

Requires:  pip install matplotlib
"""

import io
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional

import matplotlib
matplotlib.use("Agg")          # non-interactive, safe for servers / Windows
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

plt.rcParams["font.family"] = "DejaVu Sans"   # bundled with matplotlib, supports Cyrillic

# ─────────────── palette ───────────────
BG            = "#1A1A2E"
CARD          = "#16213E"
ACCENT_BLUE   = "#4A90D9"
ACCENT_GREEN  = "#27AE60"
ACCENT_RED    = "#E74C3C"
ACCENT_GOLD   = "#F39C12"
TEXT_MAIN     = "#ECEFF4"
TEXT_DIM      = "#8892A4"
GRID_LINE     = "#2C3E50"
PROGRESS_BG   = "#2C3E50"

PIE_COLORS = [
    "#4A90D9", "#E74C3C", "#27AE60", "#F39C12", "#9B59B6",
    "#1ABC9C", "#E67E22", "#3498DB", "#E91E63", "#00BCD4",
    "#8BC34A", "#FF5722", "#607D8B", "#795548",
]


# ─────────────── helpers ───────────────

def _short(n: float) -> str:
    """Format large numbers compactly."""
    if abs(n) >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if abs(n) >= 1_000:
        return f"{n/1_000:.0f}K"
    return f"{n:.0f}"


def _fig_to_bytes(fig: plt.Figure) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    buf.seek(0)
    data = buf.read()
    plt.close(fig)
    return data


def _style_ax(ax: plt.Axes):
    ax.set_facecolor(CARD)
    ax.tick_params(colors=TEXT_MAIN, labelsize=8)
    ax.xaxis.label.set_color(TEXT_MAIN)
    ax.yaxis.label.set_color(TEXT_MAIN)
    for spine in ax.spines.values():
        spine.set_edgecolor(GRID_LINE)


# ─────────────── Goals progress bars ───────────────

def generate_goals_chart(goals: list, title: str = "Goals Progress") -> Optional[bytes]:
    """Horizontal progress bar for each goal."""
    if not goals:
        return None

    # Sort: active first, then completed
    active    = [g for g in goals if not g.get("completed")]
    completed = [g for g in goals if g.get("completed")]
    display   = active + completed
    n = len(display)

    fig_h = max(3.5, n * 1.35 + 1.8)
    fig, ax = plt.subplots(figsize=(12, fig_h))
    fig.patch.set_facecolor(BG)
    _style_ax(ax)

    for idx, goal in enumerate(display):
        y = n - 1 - idx
        target  = goal["target_amount"] or 1
        current = goal["current_amount"]
        pct     = min(100.0, current / target * 100)
        done    = bool(goal.get("completed"))

        bar_color = ACCENT_GREEN if done else ACCENT_BLUE

        # Background track
        ax.barh(y, 100, height=0.52, color=PROGRESS_BG, left=0, zorder=2)
        # Progress fill
        ax.barh(y, pct, height=0.52, color=bar_color, left=0, zorder=3,
                alpha=0.9)

        # Title label (left)
        lbl = ("✓ " if done else "") + goal["title"]
        ax.text(-1.5, y, lbl, ha="right", va="center",
                color=TEXT_MAIN, fontsize=8.5, fontweight="bold")

        # Amount label (right)
        cur_s = f"{current:,.0f}"
        tgt_s = f"{target:,.0f}"
        currency = goal.get("currency", "")
        ax.text(102, y, f"{cur_s} / {tgt_s} {currency}",
                ha="left", va="center", color=TEXT_DIM, fontsize=7.5)

        # Percentage inside bar
        if pct >= 12:
            ax.text(pct / 2, y, f"{pct:.0f}%",
                    ha="center", va="center",
                    color="white", fontsize=7.5, fontweight="bold", zorder=4)
        else:
            ax.text(pct + 1.5, y, f"{pct:.0f}%",
                    ha="left", va="center",
                    color=TEXT_DIM, fontsize=7, zorder=4)

    # 100 % reference line
    ax.axvline(100, color=TEXT_DIM, linestyle="--", linewidth=0.8, alpha=0.5)
    ax.set_xlim(-2, 175)
    ax.set_ylim(-0.7, n - 0.3)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_xticklabels(["0%", "25%", "50%", "75%", "100%"],
                       color=TEXT_DIM, fontsize=8)
    ax.set_yticks([])
    ax.grid(axis="x", color=GRID_LINE, linewidth=0.5, alpha=0.6, zorder=0)
    ax.set_title(title, color=TEXT_MAIN, fontsize=13, fontweight="bold", pad=14)

    fig.tight_layout(pad=1.6)
    return _fig_to_bytes(fig)


# ─────────────── Expense pie chart ───────────────

def generate_pie_chart(
    by_category: Dict[str, float],
    title: str = "Expenses by Category",
) -> Optional[bytes]:
    """Pie chart of expenses broken down by category."""
    if not by_category:
        return None

    items  = sorted(by_category.items(), key=lambda x: x[1], reverse=True)
    labels = [k for k, _ in items]
    values = [v for _, v in items]
    total  = sum(values)
    colors = (PIE_COLORS * 4)[:len(labels)]

    fig, ax = plt.subplots(figsize=(10, 7))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)

    wedges, _, autotexts = ax.pie(
        values,
        colors=colors,
        autopct=lambda p: f"{p:.1f}%" if p >= 3 else "",
        startangle=140,
        pctdistance=0.76,
        wedgeprops={"linewidth": 1.5, "edgecolor": BG},
    )
    for at in autotexts:
        at.set_color("white")
        at.set_fontsize(8)
        at.set_fontweight("bold")

    # Legend
    legend_lines = [
        f"{lbl}  —  {_short(val)}  ({val/total*100:.1f}%)"
        for lbl, val in zip(labels, values)
    ]
    patches = [mpatches.Patch(color=c, label=l)
               for c, l in zip(colors, legend_lines)]
    ax.legend(
        handles=patches,
        loc="lower center",
        bbox_to_anchor=(0.5, -0.28),
        ncol=2,
        fontsize=7.5,
        framealpha=0.15,
        facecolor=CARD,
        edgecolor=GRID_LINE,
        labelcolor=TEXT_MAIN,
    )

    ax.set_title(title, color=TEXT_MAIN, fontsize=13, fontweight="bold", pad=14)
    fig.tight_layout(pad=1.6)
    return _fig_to_bytes(fig)


# ─────────────── Income vs Expenses bar chart ───────────────

def _group_key_and_label(dt: datetime, period: str):
    """Return (sort_key, display_label) for a datetime given the period."""
    if period == "week":
        return dt.strftime("%Y-%m-%d"), dt.strftime("%a\n%d %b")
    if period == "month":
        return dt.strftime("%Y-%m-%d"), dt.strftime("%d %b")
    if period == "6months":
        # ISO week — label shows Monday of that week
        year, week, _ = dt.isocalendar()
        return f"{year}-W{week:02d}", dt.strftime("%d %b")
    # year or custom-long
    return dt.strftime("%Y-%m"), dt.strftime("%b\n%Y")


def generate_bar_chart(
    transactions: list,
    period: str,
    income_label: str = "Income",
    expense_label: str = "Expenses",
    title: str = "Income vs Expenses",
) -> Optional[bytes]:
    """Grouped bar chart of income and expenses over time."""
    if not transactions:
        return None

    income_map:  Dict[str, float] = defaultdict(float)
    expense_map: Dict[str, float] = defaultdict(float)
    label_map:   Dict[str, str]   = {}

    for tx in transactions:
        try:
            dt = datetime.strptime(tx["created_at"][:10], "%Y-%m-%d")
        except Exception:
            continue
        key, lbl = _group_key_and_label(dt, period)
        label_map[key] = lbl
        if tx["type"] == "income":
            income_map[key]  += tx["amount"]
        else:
            expense_map[key] += tx["amount"]

    all_keys = sorted(set(list(income_map) + list(expense_map)))
    if not all_keys:
        return None

    incomes  = [income_map.get(k, 0)  for k in all_keys]
    expenses = [expense_map.get(k, 0) for k in all_keys]
    x_labels = [label_map[k] for k in all_keys]
    n = len(all_keys)

    fig_w = max(9, n * 1.1 + 2)
    fig, ax = plt.subplots(figsize=(fig_w, 6))
    fig.patch.set_facecolor(BG)
    _style_ax(ax)

    x     = np.arange(n)
    width = 0.38

    bars_i = ax.bar(x - width / 2, incomes,  width, label=income_label,
                    color=ACCENT_GREEN, alpha=0.88, zorder=3)
    bars_e = ax.bar(x + width / 2, expenses, width, label=expense_label,
                    color=ACCENT_RED,   alpha=0.88, zorder=3)

    max_val = max(max(incomes, default=0), max(expenses, default=0))
    offset  = max_val * 0.015 if max_val else 1

    for bar in bars_i:
        h = bar.get_height()
        if h > 0:
            ax.text(bar.get_x() + bar.get_width() / 2, h + offset,
                    _short(h), ha="center", va="bottom",
                    color=TEXT_MAIN, fontsize=7, zorder=4)

    for bar in bars_e:
        h = bar.get_height()
        if h > 0:
            ax.text(bar.get_x() + bar.get_width() / 2, h + offset,
                    _short(h), ha="center", va="bottom",
                    color=TEXT_MAIN, fontsize=7, zorder=4)

    ax.set_xticks(x)
    rotation = 30 if n > 8 else 0
    ax.set_xticklabels(x_labels, color=TEXT_MAIN, fontsize=8,
                       rotation=rotation, ha="right" if rotation else "center")
    ax.grid(axis="y", color=GRID_LINE, linewidth=0.5, alpha=0.6, zorder=0)
    ax.set_axisbelow(True)
    ax.set_title(title, color=TEXT_MAIN, fontsize=13, fontweight="bold", pad=14)

    legend = ax.legend(
        facecolor=CARD, edgecolor=GRID_LINE,
        labelcolor=TEXT_MAIN, fontsize=9,
    )

    fig.tight_layout(pad=1.6)
    return _fig_to_bytes(fig)


# ─────────────── auto-period helper ───────────────

def period_for_days(days: int) -> str:
    """Pick the best bar-chart grouping for a custom date range."""
    if days <= 31:
        return "month"       # group by day
    if days <= 180:
        return "6months"     # group by week
    return "year"            # group by month