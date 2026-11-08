"""Interactive Streamlit dashboard: Codeforces problems solved vs. contest rating.

Run with:
    python -m streamlit run streamlit_app.py
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Sequence

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from cf_rating_vs_solved import (
    AcceptedProblem,
    CFError,
    RatedContest,
    Series,
    cumulative_series,
    fetch_accepted_problems,
    fetch_contest_windows,
    fetch_rating_history,
    filter_hard_solves,
    per_contest_series,
)

# ---------------------------------------------------------------------------
# Page setup and visual system
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Codeforces | Rating x Problems",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

BG = "#f4f6fb"
PANEL = "#ffffff"
INK = "#0f172a"
MUTED = "#64748b"
LINE = "#e2e8f0"
FAINT = "#eef2f7"
GREEN = "#15803d"
RED = "#b91c1c"
DEFAULT_HANDLE = "dandere"
MAX_PROFILES = 5

PROFILE_COLORS = ("#0f172a", "#0369a1", "#be123c", "#b45309", "#15803d")
PROFILE_SYMBOLS = ("circle", "diamond", "square", "triangle-up", "cross")
PROFILE_MARKERS = ("\u25cf", "\u25c6", "\u25a0", "\u25b2", "\u271a")


@dataclass(frozen=True)
class Tier:
    label: str
    low: int
    high: int
    color: str


@dataclass
class Profile:
    handle: str
    history: list[RatedContest]
    accepted: list[AcceptedProblem]
    series: Series
    color: str
    symbol: str
    marker: str


# Codeforces rank colours. Adjacent ranks that share a colour are grouped for
# the chart legend, but the hover label uses the exact rank name.
TIERS: tuple[Tier, ...] = (
    Tier("Newbie", 0, 1199, "#808080"),
    Tier("Pupil", 1200, 1399, "#008000"),
    Tier("Specialist", 1400, 1599, "#03A89E"),
    Tier("Expert", 1600, 1899, "#0000FF"),
    Tier("Candidate Master", 1900, 2099, "#AA00AA"),
    Tier("Master", 2100, 2399, "#FF8C00"),
    Tier("Grandmaster+", 2400, 10000, "#FF0000"),
)


def tier_for(rating: int) -> Tier:
    for tier in TIERS:
        if rating <= tier.high:
            return tier
    return TIERS[-1]


def exact_tier(rating: int) -> str:
    if rating < 1200:
        return "Newbie"
    if rating < 1400:
        return "Pupil"
    if rating < 1600:
        return "Specialist"
    if rating < 1900:
        return "Expert"
    if rating < 2100:
        return "Candidate Master"
    if rating < 2300:
        return "Master"
    if rating < 2400:
        return "International Master"
    if rating < 2600:
        return "Grandmaster"
    if rating < 3000:
        return "International Grandmaster"
    return "Legendary Grandmaster"


def year_span(history: Sequence[RatedContest]) -> str:
    first = history[0].date.year
    last = history[-1].date.year
    return str(first) if first == last else f"{first}\u2013{last}"


def inject_css() -> None:
    st.markdown(
        f"""
        <style>
        :root {{
            --bg: {BG};
            --panel: {PANEL};
            --ink: {INK};
            --muted: {MUTED};
            --line: {LINE};
            --faint: {FAINT};
        }}

        html, body, [class*="css"] {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                         Helvetica, Arial, sans-serif;
        }}

        [data-testid="stAppViewContainer"] {{
            background:
                radial-gradient(circle at 82% -12%, rgba(0, 0, 255, 0.055), transparent 34rem),
                radial-gradient(circle at 0% 0%, rgba(3, 168, 158, 0.05), transparent 30rem),
                var(--bg);
        }}

        [data-testid="stHeader"] {{
            background: transparent;
        }}

        [data-testid="stToolbar"] {{
            visibility: visible;
            height: 28px;
            background: transparent;
        }}

        [data-testid="stAppDeployButton"],
        [data-testid="stMainMenu"],
        [data-testid="stToolbarActions"] {{
            display: none;
        }}

        [data-testid="stExpandSidebarButton"] {{
            visibility: visible !important;
            opacity: 1 !important;
            width: 36px !important;
            height: 36px !important;
            margin: 8px 0 0 10px;
            padding: 0 !important;
            background: rgba(255, 255, 255, 0.96) !important;
            border: 1px solid var(--line) !important;
            border-radius: 10px !important;
            box-shadow: 0 3px 12px rgba(15, 23, 42, 0.12);
        }}

        [data-testid="stExpandSidebarButton"] span {{
            color: #0f172a !important;
            font-size: 1.2rem !important;
        }}

        [data-testid="stExpandSidebarButton"]:hover {{
            background: #ffffff !important;
            border-color: #cbd5e1 !important;
        }}

        [data-testid="stDecoration"] {{
            display: none;
        }}

        [data-testid="stSidebar"] {{
            background: rgba(255, 255, 255, 0.92);
            border-right: 1px solid var(--line);
        }}

        [data-testid="stSidebar"] > div:first-child {{
            padding-top: 1.35rem;
        }}

        .block-container {{
            max-width: 1380px;
            padding-top: 1.8rem;
            padding-bottom: 2.8rem;
        }}

        .side-brand {{
            font-weight: 800;
            font-size: 1.05rem;
            letter-spacing: -0.03em;
            color: var(--ink);
            margin: 0 0 0.1rem 0;
        }}
        .side-brand span {{
            color: #0000FF;
        }}
        .side-sub {{
            color: var(--muted);
            font-size: 0.76rem;
            letter-spacing: 0.11em;
            text-transform: uppercase;
            font-weight: 700;
            margin-bottom: 1.2rem;
        }}

        .hero {{
            margin: 0.15rem 0 1.35rem 0;
        }}
        .eyebrow {{
            display: inline-flex;
            align-items: center;
            gap: 0.48rem;
            color: #475569;
            font-size: 0.7rem;
            font-weight: 800;
            letter-spacing: 0.14em;
            text-transform: uppercase;
            margin-bottom: 0.72rem;
        }}
        .live-dot {{
            width: 0.45rem;
            height: 0.45rem;
            border-radius: 50%;
            background: #16a34a;
            box-shadow: 0 0 0 0.22rem rgba(22, 163, 74, 0.12);
        }}
        .hero h1 {{
            color: var(--ink);
            font-size: clamp(2.2rem, 4.2vw, 3.55rem);
            line-height: 0.98;
            letter-spacing: -0.055em;
            font-weight: 800;
            margin: 0;
        }}
        .hero h1 .times {{
            color: #0000FF;
            font-weight: 500;
        }}
        .hero-meta {{
            display: flex;
            align-items: center;
            flex-wrap: wrap;
            gap: 0.5rem;
            color: var(--muted);
            font-size: 0.93rem;
            margin-top: 0.85rem;
        }}
        .handle-pill {{
            display: inline-flex;
            align-items: center;
            gap: 0.38rem;
            background: #eef2ff;
            color: #1e3a8a;
            border: 1px solid #dbe4ff;
            padding: 0.2rem 0.6rem;
            border-radius: 999px;
            font-weight: 700;
            letter-spacing: -0.01em;
        }}
        .meta-sep {{
            color: #cbd5e1;
        }}

        .stat-grid {{
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.8rem;
            margin: 0 0 1.3rem 0;
        }}

        .profile-grid {{
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.8rem;
            margin: 0 0 1.3rem 0;
        }}
        .profile-card {{
            background: rgba(255, 255, 255, 0.9);
            border: 1px solid var(--line);
            border-radius: 14px;
            padding: 0.85rem 1rem 0.75rem 1rem;
            box-shadow: 0 1px 2px rgba(15, 23, 42, 0.025);
        }}
        .profile-head {{
            display: flex;
            align-items: center;
            gap: 0.42rem;
            font-size: 0.78rem;
            font-weight: 800;
            color: var(--ink);
            min-width: 0;
        }}
        .profile-head .handle {{
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }}
        .profile-marker {{
            font-size: 0.8rem;
            line-height: 1;
            flex: 0 0 auto;
        }}
        .profile-rank {{
            margin-left: auto;
            font-size: 0.66rem;
            font-weight: 700;
            color: var(--muted);
            white-space: nowrap;
        }}
        .profile-main {{
            display: flex;
            align-items: baseline;
            gap: 0.45rem;
            margin-top: 0.3rem;
        }}
        .profile-main .value {{
            font-size: 1.5rem;
            font-weight: 800;
            letter-spacing: -0.04em;
            line-height: 1.1;
            font-variant-numeric: tabular-nums;
        }}
        .profile-main .label {{
            color: #94a3b8;
            font-size: 0.67rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            font-weight: 700;
        }}
        .profile-foot {{
            color: var(--muted);
            font-size: 0.72rem;
            margin-top: 0.3rem;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}

        .filter-pill {{
            display: inline-flex;
            align-items: center;
            gap: 0.3rem;
            background: #fff7ed;
            color: #9a3412;
            border: 1px solid #fed7aa;
            padding: 0.2rem 0.6rem;
            border-radius: 999px;
            font-weight: 700;
            font-size: 0.8rem;
        }}

        .hard-pill {{
            display: inline-flex;
            align-items: center;
            gap: 0.3rem;
            background: #eef2ff;
            color: #1e3a8a;
            border: 1px solid #c7d2fe;
            padding: 0.2rem 0.6rem;
            border-radius: 999px;
            font-weight: 700;
            font-size: 0.8rem;
        }}

        .profile-key {{
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: 0.38rem 0.55rem;
            margin: 0.1rem 0 0.5rem 0;
        }}
        .profile-key-label {{
            color: #94a3b8;
            font-size: 0.64rem;
            font-weight: 800;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            margin-right: 0.2rem;
        }}
        .profile-key-chip {{
            display: inline-flex;
            align-items: center;
            gap: 0.34rem;
            background: rgba(255, 255, 255, 0.82);
            border: 1px solid var(--line);
            border-radius: 999px;
            padding: 0.18rem 0.55rem;
            color: #475569;
            font-size: 0.72rem;
            font-weight: 700;
        }}
        .profile-key-marker {{
            font-size: 0.72rem;
            line-height: 1;
        }}
        .stat-card {{
            background: rgba(255, 255, 255, 0.9);
            border: 1px solid var(--line);
            border-radius: 14px;
            padding: 0.95rem 1rem 0.82rem 1rem;
            box-shadow: 0 1px 2px rgba(15, 23, 42, 0.025);
            min-height: 6.5rem;
        }}
        .stat-kicker {{
            color: #94a3b8;
            font-size: 0.64rem;
            font-weight: 800;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            margin-bottom: 0.35rem;
        }}
        .stat-value {{
            color: var(--ink);
            font-size: 1.75rem;
            line-height: 1.15;
            font-weight: 800;
            letter-spacing: -0.045em;
            font-variant-numeric: tabular-nums;
        }}
        .stat-foot {{
            display: flex;
            align-items: center;
            gap: 0.4rem;
            color: var(--muted);
            font-size: 0.76rem;
            margin-top: 0.38rem;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        .tier-dot {{
            width: 0.48rem;
            height: 0.48rem;
            border-radius: 50%;
            flex: 0 0 auto;
        }}
        .delta-up {{ color: {GREEN}; font-weight: 700; }}
        .delta-down {{ color: {RED}; font-weight: 700; }}

        .section-head {{
            display: flex;
            align-items: baseline;
            justify-content: space-between;
            gap: 1rem;
            margin: 0.2rem 0 0.35rem 0;
        }}
        .section-title {{
            color: var(--ink);
            font-size: 1.12rem;
            font-weight: 800;
            letter-spacing: -0.02em;
        }}
        .section-note {{
            color: var(--muted);
            font-size: 0.78rem;
        }}

        div[data-testid="stForm"] {{
            border: 0;
            padding: 0;
        }}

        .stTextInput input {{
            border-radius: 9px;
        }}

        div[data-testid="stButton"] button,
        div[data-testid="stFormSubmitButton"] button {{
            border-radius: 9px;
            font-weight: 700;
        }}

        .sidebar-note {{
            color: #94a3b8;
            font-size: 0.72rem;
            line-height: 1.5;
            margin-top: 0.55rem;
        }}

        .footer {{
            color: #94a3b8;
            font-size: 0.72rem;
            border-top: 1px solid var(--line);
            padding-top: 0.8rem;
            margin-top: 1.4rem;
        }}

        .tier-key {{
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: 0.38rem 0.55rem;
            margin: 0.1rem 0 0.45rem 0;
        }}
        .tier-key-label {{
            color: #94a3b8;
            font-size: 0.64rem;
            font-weight: 800;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            margin-right: 0.2rem;
        }}
        .tier-chip {{
            display: inline-flex;
            align-items: center;
            gap: 0.34rem;
            background: rgba(255, 255, 255, 0.78);
            border: 1px solid var(--line);
            border-radius: 999px;
            padding: 0.18rem 0.52rem;
            color: #475569;
            font-size: 0.7rem;
            white-space: nowrap;
        }}
        .tier-swatch {{
            width: 0.46rem;
            height: 0.46rem;
            border-radius: 50%;
            flex: 0 0 auto;
        }}
        .tier-range {{
            color: #94a3b8;
            font-variant-numeric: tabular-nums;
        }}

        @media (max-width: 1200px) {{
            .stat-grid, .profile-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
        }}
        @media (max-width: 680px) {{
            .stat-grid, .profile-grid {{ grid-template-columns: 1fr; }}
            .block-container {{ padding-top: 1.1rem; }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Data loading (Streamlit cache + the CLI module's disk cache)
# ---------------------------------------------------------------------------


@st.cache_data(ttl=6 * 60 * 60, show_spinner=False)
def load_user(handle: str, nonce: int) -> tuple[str, list[RatedContest], list[AcceptedProblem]]:
    refresh = nonce > 0
    canonical, history = fetch_rating_history(handle, refresh=refresh, use_cache=True)
    accepted = fetch_accepted_problems(
        canonical,
        history[0].at,
        refresh=refresh,
        use_cache=True,
    )
    return canonical, history, accepted


@st.cache_data(ttl=24 * 60 * 60, show_spinner=False)
def load_contest_windows(nonce: int):
    return fetch_contest_windows(refresh=nonce > 0, use_cache=True)


def refresh_data() -> None:
    st.cache_data.clear()
    st.session_state["nonce"] += 1


# ---------------------------------------------------------------------------
# Chart
# ---------------------------------------------------------------------------


def _hover_template(mode: str, hard_solves: bool) -> str:
    if mode == "cumulative":
        solved_label = "Hard solves" if hard_solves else "Problems solved"
    else:
        solved_label = "Hard solves in contest" if hard_solves else "Solved in contest"
    return (
        "<b>@%{customdata[0]}</b> &nbsp;\u00b7&nbsp; %{customdata[1]}<br>"
        "Rating: <b>%{y:,}</b> &nbsp;\u00b7&nbsp; %{customdata[2]}<br>"
        f"{solved_label}: <b>%{{x:,}}</b><br>"
        "Rank: #%{customdata[3]:,} &nbsp;\u00b7&nbsp; %{customdata[4]}"
        "<extra></extra>"
    )


def build_chart(
    profiles: Sequence[Profile],
    mode: str,
    *,
    hard_solves: bool,
    full_scale: bool,
    color_mode: str,
    show_bands: bool,
    show_markers: bool,
) -> go.Figure:
    all_ratings = np.asarray(
        [rating for profile in profiles for rating in profile.series.ratings],
        dtype=int,
    )
    all_solved = np.asarray(
        [solved for profile in profiles for solved in profile.series.solved],
        dtype=int,
    )
    if not len(all_ratings):
        return go.Figure()

    low, high = int(all_ratings.min()), int(all_ratings.max())
    pad = max(55, int((high - low) * 0.07))
    y_min = max(0, low - pad)
    y_max = high + pad
    if full_scale:
        y_max = max(y_max, 3050)
    y_range = [y_min, y_max]
    x_max = max(1, int(all_solved.max()))
    x_range = [0, x_max * 1.05]

    fig = go.Figure()

    if show_bands:
        for tier in TIERS:
            band_low = max(tier.low, y_range[0])
            band_high = min(tier.high, y_range[1])
            if band_high > band_low:
                fig.add_hrect(
                    y0=band_low,
                    y1=band_high,
                    fillcolor=tier.color,
                    opacity=0.15,
                    layer="below",
                    line_width=0,
                )

    dash_styles = ("solid", "dash", "dot", "dashdot", "longdash")
    is_single = len(profiles) == 1

    if mode == "cumulative":
        for index, profile in enumerate(profiles):
            series = profile.series
            fig.add_trace(
                go.Scatter(
                    x=series.solved,
                    y=series.ratings,
                    mode="lines",
                    line=dict(
                        color=profile.color,
                        width=2.6,
                        dash=dash_styles[index % len(dash_styles)],
                    ),
                    opacity=0.78 if not is_single else 0.7,
                    hoverinfo="skip",
                    showlegend=False,
                )
            )

    for index, profile in enumerate(profiles):
        series = profile.series
        handle_values = np.full(len(series.history), profile.handle, dtype=object)
        contest_values = np.asarray(
            [html.escape(contest.name) for contest in series.history], dtype=object
        )
        tier_values = np.asarray(
            [exact_tier(rating) for rating in series.ratings], dtype=object
        )
        rank_values = np.asarray(
            [contest.rank for contest in series.history], dtype=int
        )
        date_values = np.asarray(
            [contest.date.strftime("%d %b %Y") for contest in series.history],
            dtype=object,
        )
        customdata = np.column_stack(
            [handle_values, contest_values, tier_values, rank_values, date_values]
        )
        solved_values = np.asarray(series.solved, dtype=int)
        rating_values = np.asarray(series.ratings, dtype=int)

        if color_mode == "profile":
            fig.add_trace(
                go.Scatter(
                    x=solved_values,
                    y=rating_values,
                    mode="markers",
                    name=profile.handle,
                    showlegend=False,
                    customdata=customdata,
                    hovertemplate=_hover_template(mode, hard_solves),
                    marker=dict(
                        size=7.8 if is_single else 8.2,
                        color=profile.color,
                        symbol=profile.symbol,
                        opacity=1.0,
                        line=dict(color="rgba(255,255,255,0.9)", width=0.5),
                    ),
                )
            )
        else:
            for tier in TIERS:
                mask = np.asarray(
                    [tier_for(rating) == tier for rating in series.ratings], dtype=bool
                )
                if not np.any(mask):
                    continue
                fig.add_trace(
                    go.Scatter(
                        x=solved_values[mask],
                        y=rating_values[mask],
                        mode="markers",
                        name=f"{profile.handle} \u00b7 {tier.label}",
                        showlegend=False,
                        customdata=customdata[mask],
                        hovertemplate=_hover_template(mode, hard_solves),
                        marker=dict(
                            size=7.8 if is_single else 8.2,
                            color=tier.color,
                            symbol=profile.symbol,
                            opacity=1.0,
                            line=dict(color="rgba(255,255,255,0.9)", width=0.5),
                        ),
                    )
                )

    # When several profiles overlap, draw a second, thin line pass above the
    # dots so the chronological path stays legible between dense clusters.
    if mode == "cumulative" and not is_single:
        for profile in profiles:
            fig.add_trace(
                go.Scatter(
                    x=profile.series.solved,
                    y=profile.series.ratings,
                    mode="lines",
                    line=dict(color=profile.color, width=3.0),
                    opacity=0.82,
                    hoverinfo="skip",
                    showlegend=False,
                )
            )

    # Robust median line only makes sense as a single-profile summary.
    if mode == "contest" and is_single:
        series = profiles[0].series
        solved = np.asarray(series.solved, dtype=int)
        ratings = np.asarray(series.ratings, dtype=int)
        xs: list[int] = []
        ys: list[float] = []
        for count in sorted(set(int(value) for value in solved)):
            values = ratings[solved == count]
            if len(values) >= 3:
                xs.append(count)
                ys.append(float(np.median(values)))
        if len(xs) >= 2:
            fig.add_trace(
                go.Scatter(
                    x=xs,
                    y=ys,
                    mode="lines+markers",
                    name="Median rating",
                    showlegend=False,
                    line=dict(color="#0f172a", width=2.2, dash="dash"),
                    marker=dict(color="#0f172a", size=6),
                    hovertemplate=(
                        "Solved <b>%{x:,}</b> problems<br>"
                        "Median rating <b>%{y:,}</b><extra></extra>"
                    ),
                )
            )

    if show_markers:
        for index, profile in enumerate(profiles):
            series = profile.series
            ratings = np.asarray(series.ratings, dtype=int)
            solved = np.asarray(series.solved, dtype=int)
            latest = len(ratings) - 1
            peak = max(
                range(len(ratings)),
                key=lambda i: (int(ratings[i]), int(series.dates[i])),
            )

            fig.add_trace(
                go.Scatter(
                    x=[solved[latest]],
                    y=[ratings[latest]],
                    mode="markers",
                    showlegend=False,
                    hoverinfo="skip",
                    marker=dict(
                        size=13,
                        symbol=profile.symbol,
                        color="rgba(255,255,255,0.98)",
                        line=dict(color=profile.color, width=2.8),
                    ),
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=[solved[peak]],
                    y=[ratings[peak]],
                    mode="markers",
                    showlegend=False,
                    hoverinfo="skip",
                    marker=dict(
                        size=14 if not is_single else 15,
                        symbol="star",
                        color="#f59e0b" if is_single else profile.color,
                        line=dict(color="white", width=1.3),
                    ),
                )
            )

    if show_markers and is_single:
        series = profiles[0].series
        ratings = np.asarray(series.ratings, dtype=int)
        solved = np.asarray(series.solved, dtype=int)
        latest = len(ratings) - 1
        peak = max(
            range(len(ratings)),
            key=lambda i: (int(ratings[i]), int(series.dates[i])),
        )
        x_mid = float(np.median(solved))

        if peak != latest:
            peak_dx = -22 if solved[peak] >= x_mid else 22
            fig.add_annotation(
                x=int(solved[peak]),
                y=int(ratings[peak]),
                text=f"Peak {int(ratings[peak]):,}",
                showarrow=True,
                arrowhead=0,
                arrowcolor="#94a3b8",
                ax=peak_dx,
                ay=27,
                bgcolor="rgba(255,255,255,0.96)",
                bordercolor=LINE,
                borderwidth=1,
                borderpad=4,
                font=dict(size=10, color="#92400e"),
            )

        latest_dx = -20 if solved[latest] >= x_mid else 20
        latest_text = "Latest \u00b7 peak" if peak == latest else "Latest"
        fig.add_annotation(
            x=int(solved[latest]),
            y=int(ratings[latest]),
            text=latest_text,
            showarrow=True,
            arrowhead=0,
            arrowcolor="#94a3b8",
            ax=latest_dx,
            ay=-28,
            bgcolor="rgba(255,255,255,0.96)",
            bordercolor=LINE,
            borderwidth=1,
            borderpad=4,
            font=dict(size=10, color=INK),
        )

    x_label = (
        ("Hard solves (cumulative)" if hard_solves else "Problems solved (cumulative)")
        if mode == "cumulative"
        else ("Hard solves in contest" if hard_solves else "Problems solved in contest")
    )
    fig.update_layout(
        height=650,
        margin=dict(l=78, r=28, t=24, b=74),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(255,255,255,0.92)",
        font=dict(
            family='-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
            color=INK,
            size=12,
        ),
        hovermode="closest",
        hoverlabel=dict(
            bgcolor="white",
            bordercolor=LINE,
            font=dict(color=INK, size=12),
        ),
        showlegend=False,
        xaxis=dict(
            title=dict(text=x_label, font=dict(size=12, color=MUTED), standoff=16),
            range=x_range,
            showgrid=True,
            gridcolor=FAINT,
            zeroline=False,
            linecolor=LINE,
            tickcolor=LINE,
            ticks="outside",
            tickformat=",d",
            fixedrange=False,
            dtick=1 if mode == "contest" and x_max <= 12 else None,
            automargin=True,
        ),
        yaxis=dict(
            title=dict(text="Contest rating", font=dict(size=12, color=MUTED), standoff=14),
            range=y_range,
            showgrid=True,
            gridcolor=FAINT,
            zeroline=False,
            linecolor=LINE,
            tickcolor=LINE,
            ticks="outside",
            tickformat=",d",
            fixedrange=False,
            automargin=True,
        ),
        dragmode="pan",
    )
    return fig


# ---------------------------------------------------------------------------
# Small UI helpers
# ---------------------------------------------------------------------------


def rating_tier_key() -> None:
    chips = []
    for tier in TIERS:
        high = "2400+" if tier.label == "Grandmaster+" else f"{tier.low:,}\u2013{tier.high:,}"
        chips.append(
            f'<span class="tier-chip">'
            f'<span class="tier-swatch" style="background:{tier.color}"></span>'
            f'{html.escape(tier.label)} <span class="tier-range">{high}</span>'
            f"</span>"
        )
    st.markdown(
        '<div class="tier-key"><span class="tier-key-label">Rank colours</span>'
        + "".join(chips)
        + "</div>",
        unsafe_allow_html=True,
    )


@dataclass
class Controls:
    handles: list[str]
    mode: str
    rating_range: tuple[int, int] | None
    hard_solves: bool
    hard_margin: int
    full_scale: bool
    color_mode: str
    show_bands: bool
    show_markers: bool
    error: str


def filter_text(rating_range: tuple[int, int] | None) -> str | None:
    if rating_range is None:
        return None
    low, high = rating_range
    if low == high:
        return f"Problems rated {low:,}"
    return f"Problems rated {low:,}\u2013{high:,}"


def stat_cards(profile: Profile, mode: str, hard_solves: bool) -> None:
    series = profile.series
    history = series.history
    latest = history[-1]
    latest_tier = tier_for(latest.rating)
    peak_index = max(
        range(len(history)),
        key=lambda index: (history[index].rating, history[index].at),
    )
    peak = history[peak_index]
    peak_tier = tier_for(peak.rating)

    delta = latest.rating - history[-2].rating if len(history) > 1 else 0
    delta_class = "delta-up" if delta >= 0 else "delta-down"
    delta_text = f"{delta:+,}"

    if mode == "cumulative":
        solved_value = series.solved[-1]
        solved_foot = (
            f"{solved_value - series.solved[-2]:+,} since previous round"
            if len(series.solved) > 1
            else ("distinct hard solves" if hard_solves else "distinct accepted")
        )
        solved_label = "HARD SOLVES" if hard_solves else "PROBLEMS SOLVED"
    else:
        solved_value = int(sum(series.solved))
        median = int(np.median(series.solved))
        solved_foot = (
            f"median {median} hard per rated round"
            if hard_solves
            else f"median {median} per rated round"
        )
        solved_label = (
            "HARD SOLVES IN RATED ROUNDS" if hard_solves else "SOLVED IN RATED ROUNDS"
        )

    st.markdown(
        f"""
        <div class="stat-grid">
            <div class="stat-card">
                <div class="stat-kicker">LATEST RATING</div>
                <div class="stat-value" style="color:{latest_tier.color}">{latest.rating:,}</div>
                <div class="stat-foot">
                    <span class="tier-dot" style="background:{latest_tier.color}"></span>
                    {html.escape(exact_tier(latest.rating))}
                    <span class="{delta_class}">{delta_text}</span>
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-kicker">PEAK RATING</div>
                <div class="stat-value" style="color:{peak_tier.color}">{peak.rating:,}</div>
                <div class="stat-foot">
                    <span class="tier-dot" style="background:{peak_tier.color}"></span>
                    {peak.date.strftime("%d %b %Y")}
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-kicker">RATED ROUNDS</div>
                <div class="stat-value">{len(history):,}</div>
                <div class="stat-foot">{year_span(history)} &nbsp;\u00b7&nbsp; latest {latest.date.strftime("%d %b")}</div>
            </div>
            <div class="stat-card">
                <div class="stat-kicker">{solved_label}</div>
                <div class="stat-value">{solved_value:,}</div>
                <div class="stat-foot">{solved_foot}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def profile_cards(profiles: Sequence[Profile], mode: str, hard_solves: bool) -> None:
    cards = []
    for profile in profiles:
        series = profile.series
        history = series.history
        latest = history[-1]
        peak = max(history, key=lambda contest: (contest.rating, contest.at))
        latest_tier = tier_for(latest.rating)
        if mode == "cumulative":
            solved_value = series.solved[-1]
            solved_foot = (
                f"{solved_value:,} hard" if hard_solves else f"{solved_value:,} solved"
            )
        else:
            solved_value = int(sum(series.solved))
            solved_foot = (
                f"{solved_value:,} hard \u00b7 {int(np.median(series.solved))} median"
                if hard_solves
                else f"{solved_value:,} solved \u00b7 {int(np.median(series.solved))} median"
            )

        cards.append(
            f'<div class="profile-card">'
            f'<div class="profile-head">'
            f'<span class="profile-marker" style="color:{profile.color}">{profile.marker}</span>'
            f'<span class="handle">@{html.escape(profile.handle)}</span>'
            f'<span class="profile-rank">{html.escape(exact_tier(latest.rating))}</span>'
            f"</div>"
            f'<div class="profile-main">'
            f'<span class="value" style="color:{latest_tier.color}">{latest.rating:,}</span>'
            f'<span class="label">rating</span>'
            f"</div>"
            f'<div class="profile-foot">'
            f"Peak {peak.rating:,} &nbsp;\u00b7&nbsp; {len(history):,} rounds "
            f"&nbsp;\u00b7&nbsp; {solved_foot}"
            f"</div>"
            f"</div>"
        )

    st.markdown(
        '<div class="profile-grid">' + "".join(cards) + "</div>",
        unsafe_allow_html=True,
    )


def sidebar_controls() -> Controls:
    if "profiles" not in st.session_state:
        st.session_state.profiles = [DEFAULT_HANDLE]
    if "mode" not in st.session_state:
        st.session_state.mode = "cumulative"
    if "nonce" not in st.session_state:
        st.session_state.nonce = 0
    if "form_error" not in st.session_state:
        st.session_state.form_error = ""

    with st.sidebar:
        st.markdown('<div class="side-brand">CF<span>GRAPH</span></div>', unsafe_allow_html=True)
        st.markdown('<div class="side-sub">Rating analytics</div>', unsafe_allow_html=True)

        known = list(dict.fromkeys(["dandere", "tourist"] + st.session_state.profiles))
        selected = st.multiselect(
            "Profiles",
            options=known,
            default=st.session_state.profiles,
            accept_new_options=True,
            max_selections=MAX_PROFILES,
            placeholder="Choose or type a handle",
            key="profile_selector",
            help=(
                "Add up to five Codeforces handles. Type a new handle and press Enter "
                "to add it as a chip."
            ),
        )
        st.caption("Type a handle and press Enter to add it. Changes apply immediately.")

        mode_label = st.radio(
            "Chart view",
            options=("Cumulative solved", "Per contest"),
            index=0 if st.session_state.mode == "cumulative" else 1,
            captions=(
                "Total distinct problems solved over time",
                "Problems solved inside each rated round",
            ),
            key="mode_selector",
        )

        candidates: list[str] = []
        invalid: list[str] = []
        seen: set[str] = set()
        for raw in selected:
            candidate = str(raw).strip()
            if not 3 <= len(candidate) <= 24:
                invalid.append(candidate or "(empty)")
                continue
            key = candidate.lower()
            if key in seen:
                continue
            seen.add(key)
            candidates.append(candidate)

        if invalid:
            st.session_state.form_error = (
                "These handles are invalid: " + ", ".join(invalid) +
                ". Handles must be 3\u201324 characters."
            )
        elif not candidates:
            st.session_state.form_error = "Add at least one Codeforces handle."
        else:
            st.session_state.form_error = ""
            st.session_state.profiles = candidates
            st.session_state.mode = (
                "cumulative" if mode_label == "Cumulative solved" else "contest"
            )

        st.divider()
        filter_error = ""
        filter_mode = st.radio(
            "Problem rating filter",
            options=("All ratings", "Custom range"),
            horizontal=True,
            key="rating_filter_mode",
            help=(
                "Count only accepted problems whose Codeforces problem rating falls "
                "between P and Q."
            ),
        )
        rating_range: tuple[int, int] | None = None
        if filter_mode == "Custom range":
            p_col, q_col = st.columns(2)
            p_value = p_col.number_input(
                "P (min)",
                min_value=0,
                max_value=4000,
                value=1600,
                step=100,
                key="problem_rating_p",
                help="Minimum Codeforces problem rating to count.",
            )
            q_value = q_col.number_input(
                "Q (max)",
                min_value=0,
                max_value=4000,
                value=1900,
                step=100,
                key="problem_rating_q",
                help="Maximum Codeforces problem rating to count.",
            )
            if p_value > q_value:
                filter_error = "P must be less than or equal to Q."
            else:
                rating_range = (int(p_value), int(q_value))
                st.caption(
                    f"Counting only problems rated {int(p_value):,}\u2013{int(q_value):,}. "
                    "Unrated problems are excluded."
                )
        else:
            st.caption("Counting every accepted problem, including unrated problems.")

        hard_solves = st.toggle(
            "Hard solves only",
            value=False,
            help=(
                "Count a problem only when its Codeforces rating is greater than or "
                "equal to your rating at the time you solved it, plus the margin."
            ),
        )
        hard_margin = 0
        if hard_solves:
            hard_margin = int(st.number_input(
                "Hardness margin (x)",
                min_value=-3000,
                max_value=3000,
                value=0,
                step=50,
                key="hard_margin",
                help=(
                    "A problem counts only when its rating is at least your rating "
                    "at solve time plus x. Negative x makes the rule easier; "
                    "positive x makes it harder."
                ),
            ))
            if hard_margin == 0:
                threshold_text = "your rating when you solved it"
            elif hard_margin > 0:
                threshold_text = f"your rating + {hard_margin}"
            else:
                threshold_text = f"your rating - {abs(hard_margin)}"
            st.caption(
                f"Hard solve = problem rating \u2265 {threshold_text}. "
                "Solves before your first rating update are excluded."
            )

        color_mode = "rank"
        if len(st.session_state.profiles) > 1:
            st.divider()
            color_label = st.radio(
                "Colour dots by",
                options=("Rank tier", "Profile"),
                index=1,
                horizontal=True,
                key="color_mode_multi",
                help="Rank tier keeps the Codeforces palette; Profile gives each handle its own colour.",
            )
            color_mode = "profile" if color_label == "Profile" else "rank"

        st.divider()
        show_bands = st.toggle(
            "Rating-tier bands",
            value=True,
            help="Shade the chart by Codeforces rank colour.",
        )
        full_scale = st.toggle(
            "Full rating scale",
            value=True,
            help=(
                "Extend the Y axis to 3000+ so every Codeforces rank colour "
                "is visible, even above your peak rating."
            ),
        )
        show_markers = st.toggle(
            "Peak / latest markers",
            value=True,
            help="Call out the highest rating and the most recent round.",
        )

        st.button(
            "Refresh from Codeforces",
            on_click=refresh_data,
            width="stretch",
            help="Ignore both the in-memory and on-disk caches for this run.",
        )
        st.markdown(
            '<div class="sidebar-note">'
            "Public API only \u00b7 no login \u00b7 responses cached for 6 hours."
            "</div>",
            unsafe_allow_html=True,
        )

    return Controls(
        handles=list(st.session_state.profiles),
        mode=st.session_state.mode,
        rating_range=rating_range,
        hard_solves=hard_solves,
        hard_margin=hard_margin,
        full_scale=full_scale,
        color_mode=color_mode,
        show_bands=show_bands,
        show_markers=show_markers,
        error=st.session_state.form_error or filter_error,
    )


def render_hero(
    profiles: Sequence[Profile],
    mode: str,
    rated_text: str | None,
    hard_solves: bool,
    hard_margin: int,
) -> None:
    total_rounds = sum(len(profile.history) for profile in profiles)
    first_year = min(profile.history[0].date.year for profile in profiles)
    last_year = max(profile.history[-1].date.year for profile in profiles)
    years = str(first_year) if first_year == last_year else f"{first_year}\u2013{last_year}"
    metric_name = "hard solves" if hard_solves else "problems solved"
    mode_note = (
        f"X = cumulative {metric_name} \u00b7 Y = contest rating"
        if mode == "cumulative"
        else f"X = {metric_name} in a round \u00b7 Y = contest rating"
    )
    pills = "".join(
        f'<span class="handle-pill">@{html.escape(profile.handle)}</span>'
        for profile in profiles
    )
    if len(profiles) > 1:
        meta = (
            f"{pills}"
            f"<span>{len(profiles)} profiles</span>"
            f'<span class="meta-sep">/</span>'
            f"<span>{total_rounds:,} rounds total</span>"
            f'<span class="meta-sep">/</span>'
            f"<span>{years}</span>"
            f'<span class="meta-sep">/</span>'
            f"<span>{mode_note}</span>"
        )
    else:
        meta = (
            f"{pills}"
            f"<span>{total_rounds:,} rated rounds</span>"
            f'<span class="meta-sep">/</span>'
            f"<span>{years}</span>"
            f'<span class="meta-sep">/</span>'
            f"<span>{mode_note}</span>"
        )
    filter_pill = (
        f'<span class="filter-pill">{html.escape(rated_text)}</span>'
        if rated_text
        else ""
    )
    hard_pill = (
        f'<span class="hard-pill">Hard solves \u00b7 {hard_margin:+d}</span>'
        if hard_solves and hard_margin
        else '<span class="hard-pill">Hard solves only</span>'
        if hard_solves
        else ""
    )
    title = "Hard solves" if hard_solves else "Problems solved"
    st.markdown(
        '<div class="hero">'
        '<div class="eyebrow"><span class="live-dot"></span> Codeforces analytics</div>'
        f'<h1>{title} <span class="times">\u00d7</span> rating</h1>'
        f'<div class="hero-meta">{meta}{filter_pill}{hard_pill}</div>'
        "</div>",
        unsafe_allow_html=True,
    )


def profile_key(profiles: Sequence[Profile]) -> None:
    if len(profiles) < 2:
        return
    chips = "".join(
        f'<span class="profile-key-chip">'
        f'<span class="profile-key-marker" style="color:{profile.color}">{profile.marker}</span>'
        f'@{html.escape(profile.handle)}'
        f"</span>"
        for profile in profiles
    )
    st.markdown(
        '<div class="profile-key"><span class="profile-key-label">Profiles</span>'
        + chips
        + "</div>",
        unsafe_allow_html=True,
    )


def data_table(profiles: Sequence[Profile], mode: str, hard_solves: bool) -> None:
    solved_column = "Hard solves" if hard_solves else "Solved"
    rows = []
    for profile in profiles:
        for contest, solved in zip(profile.series.history, profile.series.solved):
            rows.append(
                {
                    "Profile": profile.handle,
                    "Date": contest.date.strftime("%Y-%m-%d"),
                    "Contest": contest.name,
                    "Rank": contest.rank,
                    solved_column: int(solved),
                    "Rating": contest.rating,
                    "Tier": exact_tier(contest.rating),
                }
            )
    frame = pd.DataFrame(rows)
    suffix = "_hard" if hard_solves else ""
    if len(profiles) == 1:
        frame = frame.drop(columns=["Profile"])
        file_name = f"{profiles[0].handle}_{mode}{suffix}.csv"
    else:
        file_name = f"cf_profiles_{mode}{suffix}.csv"
    frame = frame.sort_values("Date", ascending=False)

    with st.expander("View the underlying rounds", expanded=False):
        st.dataframe(
            frame,
            width="stretch",
            height=350,
            hide_index=True,
            column_config={
                "Profile": st.column_config.TextColumn("Profile", width="small"),
                "Date": st.column_config.TextColumn("Date", width="small"),
                "Contest": st.column_config.TextColumn("Contest", width="large"),
                "Rank": st.column_config.NumberColumn("Rank", format="%d", width="small"),
                solved_column: st.column_config.NumberColumn(
                    solved_column,
                    format="%d",
                    width="small",
                    help=(
                        "Cumulative hard solves"
                        if mode == "cumulative" and hard_solves
                        else "Cumulative total"
                        if mode == "cumulative"
                        else "Hard solves in contest"
                        if hard_solves
                        else "Solved in contest"
                    ),
                ),
                "Rating": st.column_config.NumberColumn("Rating", format="%d", width="small"),
                "Tier": st.column_config.TextColumn("Tier", width="medium"),
            },
        )
        st.download_button(
            "Download CSV",
            data=frame.to_csv(index=False).encode("utf-8"),
            file_name=file_name,
            mime="text/csv",
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

inject_css()
controls = sidebar_controls()

if controls.error:
    st.markdown(
        """
        <div class="hero">
            <div class="eyebrow"><span class="live-dot"></span> Codeforces analytics</div>
            <h1>Problems solved <span class="times">\u00d7</span> rating</h1>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.error(controls.error)
    st.info("Fix the highlighted controls in the sidebar.")
    st.stop()

loaded: list[tuple[str, list[RatedContest], list[AcceptedProblem]]] = []
failures: list[tuple[str, str]] = []
seen_handles: set[str] = set()

with st.spinner(f"Loading {len(controls.handles)} profile(s) from Codeforces..."):
    for handle in controls.handles:
        try:
            canonical, history, accepted = load_user(handle, st.session_state.nonce)
        except CFError as exc:
            failures.append((handle, str(exc)))
            continue

        key = canonical.lower()
        if key in seen_handles:
            continue
        seen_handles.add(key)

        if controls.rating_range is not None:
            low, high = controls.rating_range
            accepted = [
                problem
                for problem in accepted
                if problem.rating is not None and low <= problem.rating <= high
            ]

        if controls.hard_solves:
            accepted = filter_hard_solves(
                accepted,
                history,
                margin=controls.hard_margin,
            )

        loaded.append((canonical, history, accepted))

if not loaded:
    st.markdown(
        """
        <div class="hero">
            <div class="eyebrow"><span class="live-dot"></span> Codeforces analytics</div>
            <h1>Problems solved <span class="times">\u00d7</span> rating</h1>
        </div>
        """,
        unsafe_allow_html=True,
    )
    for handle, message in failures:
        st.error(f"@{handle}: {message}")
    st.info("Check the handle spelling and try again. Handles are case-insensitive.")
    st.stop()

windows = None
if controls.mode == "contest":
    with st.spinner("Loading contest time windows..."):
        try:
            windows = load_contest_windows(st.session_state.nonce)
        except CFError as exc:
            st.error(str(exc))
            st.stop()

profiles: list[Profile] = []
missing_windows = 0
for index, (canonical, history, accepted) in enumerate(loaded):
    if controls.mode == "cumulative":
        series = cumulative_series(canonical, history, accepted)
    else:
        series, missing = per_contest_series(canonical, history, accepted, windows or {})
        missing_windows += missing

    profiles.append(
        Profile(
            handle=canonical,
            history=history,
            accepted=accepted,
            series=series,
            color=PROFILE_COLORS[index % len(PROFILE_COLORS)],
            symbol=PROFILE_SYMBOLS[index % len(PROFILE_SYMBOLS)],
            marker=PROFILE_MARKERS[index % len(PROFILE_MARKERS)],
        )
    )

rated_text = filter_text(controls.rating_range)
render_hero(
    profiles,
    controls.mode,
    rated_text,
    controls.hard_solves,
    controls.hard_margin,
)

if failures:
    for handle, message in failures:
        st.warning(f"Could not load @{handle}: {message}")

if len(profiles) == 1:
    stat_cards(profiles[0], controls.mode, controls.hard_solves)
else:
    profile_cards(profiles, controls.mode, controls.hard_solves)

if missing_windows:
    st.warning(
        f"{missing_windows} rated round(s) had no contest-window metadata; "
        "all accepted submissions for those rounds were counted."
    )

if (rated_text or controls.hard_solves) and not any(
    sum(profile.series.solved) for profile in profiles
):
    st.warning(
        "No solved problems match the current problem-rating and hard-solve filters. "
        "Try widening P\u2013Q or disabling Hard solves only."
    )

if controls.hard_solves:
    hard_suffix = f" ({controls.hard_margin:+d})" if controls.hard_margin else ""
    chart_title = (
        f"Cumulative hard solves{hard_suffix} vs. rating"
        if controls.mode == "cumulative"
        else f"Hard solves per contest{hard_suffix} vs. rating"
    )
else:
    chart_title = (
        "Cumulative problems solved vs. rating"
        if controls.mode == "cumulative"
        else "Problems solved per contest vs. rating"
    )
if len(profiles) > 1:
    if controls.color_mode == "profile":
        chart_note = "Each dot is a rated round. Colour and marker shape identify the profile."
    else:
        chart_note = "Each dot is a rated round. Fill colour = rank tier, marker shape = profile."
else:
    chart_note = (
        "Each dot is a rated round, coloured by rank. The line follows your contest history."
        if controls.mode == "cumulative"
        else "Each dot is a rated round, coloured by rank. Dashed line = median rating per solve count."
    )
if controls.hard_solves:
    if controls.hard_margin > 0:
        margin_note = f" + {controls.hard_margin}"
    elif controls.hard_margin < 0:
        margin_note = f" - {abs(controls.hard_margin)}"
    else:
        margin_note = ""
    chart_note += (
        f" Hard solve = problem rating \u2265 rating at solve time{margin_note}."
    )

st.markdown(
    f"""
    <div class="section-head">
        <div class="section-title">{chart_title}</div>
        <div class="section-note">{chart_note}</div>
    </div>
    """,
    unsafe_allow_html=True,
)

fig = build_chart(
    profiles,
    controls.mode,
    hard_solves=controls.hard_solves,
    full_scale=controls.full_scale,
    color_mode=controls.color_mode,
    show_bands=controls.show_bands,
    show_markers=controls.show_markers,
)
st.plotly_chart(
    fig,
    width="stretch",
    theme=None,
    config={
        "displaylogo": False,
        "scrollZoom": True,
        "modeBarButtonsToRemove": ["lasso2d", "select2d"],
        "toImageButtonOptions": {
            "format": "png",
            "filename": "cf_" + "_".join(profile.handle for profile in profiles),
            "scale": 2,
        },
    },
)

profile_key(profiles)
rating_tier_key()
st.caption("Hover any dot for the profile, contest, rating, rank, and solve count.")

data_table(profiles, controls.mode, controls.hard_solves)

st.markdown(
    '<div class="footer">'
    "Unofficial Codeforces analytics \u00b7 Data from the public Codeforces API "
    "\u00b7 Built with Python, Streamlit, and Plotly."
    "</div>",
    unsafe_allow_html=True,
)
