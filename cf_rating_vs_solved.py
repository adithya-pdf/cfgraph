#!/usr/bin/env python3
"""Plot a Codeforces user's contest rating against the number of problems solved.

The script uses only the public Codeforces API:

    user.rating   -> the user's rated contest history
    user.status   -> the user's submissions
    contest.list  -> contest start times / durations (needed for per-contest mode)

Two views are available:

    cumulative (default)
        X = cumulative problems solved
        Y = rating after each rated contest

    contest
        X = problems solved during that contest
        Y = rating after each rated contest

The interactive dashboard is streamlit_app.py. This module contains the shared
Codeforces API/data layer and an optional static matplotlib renderer.

Examples
--------
    python cf_rating_vs_solved.py tourist
    python cf_rating_vs_solved.py tourist --mode contest
    python cf_rating_vs_solved.py            # prompts for a handle

Requirements: requests, matplotlib, numpy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import webbrowser
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import matplotlib

matplotlib.use("Agg")  # Save PNGs without requiring a display/GUI backend.

import matplotlib.pyplot as plt
import numpy as np
import requests
from matplotlib.ticker import MaxNLocator, StrMethodFormatter

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_BASE = "https://codeforces.com/api"
USER_AGENT = "cf-rating-vs-solved/1.0 (+https://codeforces.com/api)"
PAGE_SIZE = 10_000
MAX_SUBMISSIONS = 200_000
CACHE_TTL_SECONDS = 6 * 60 * 60
CONTEST_CACHE_TTL_SECONDS = 24 * 60 * 60
REQUEST_GAP_SECONDS = 2.05  # Codeforces asks for at most one request every 2 seconds.
REQUEST_TIMEOUT = (10, 45)
MAX_RETRIES = 4

PROJECT_DIR = Path(__file__).resolve().parent
CACHE_DIR = PROJECT_DIR / ".cache"
OUTPUT_DIR = PROJECT_DIR / "output"

BG = "#f4f6fb"
PANEL = "#ffffff"
INK = "#0f172a"
MUTED = "#64748b"
GRID = "#e2e8f0"

# Codeforces rank colours. Master and International Master share orange;
# Grandmaster and above share red, exactly as on codeforces.com.
CF_TIERS = (
    ("Newbie", 0, 1199, "#808080"),
    ("Pupil", 1200, 1399, "#008000"),
    ("Specialist", 1400, 1599, "#03A89E"),
    ("Expert", 1600, 1899, "#0000FF"),
    ("Candidate Master", 1900, 2099, "#AA00AA"),
    ("Master", 2100, 2399, "#FF8C00"),
    ("Grandmaster+", 2400, 10000, "#FF0000"),
)

_last_request_at = 0.0


# ---------------------------------------------------------------------------
# Errors / logging
# ---------------------------------------------------------------------------


class CFError(RuntimeError):
    """A user-facing Codeforces API or data error."""


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _throttle() -> None:
    """Keep requests at least REQUEST_GAP_SECONDS apart."""
    global _last_request_at
    now = time.monotonic()
    wait = REQUEST_GAP_SECONDS - (now - _last_request_at)
    if wait > 0:
        time.sleep(wait)


def _cache_file(method: str, params: dict[str, Any]) -> Path:
    payload = json.dumps([method, params], sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    handle = str(params.get("handle", "global")).lower()
    safe_handle = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in handle)
    return CACHE_DIR / f"{safe_handle}_{method.replace('.', '_')}_{digest}.json"


def _read_cache(path: Path, ttl: int) -> Any | None:
    try:
        stat = path.stat()
        if time.time() - stat.st_mtime > ttl:
            return None
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data.get("result")
    except (OSError, ValueError, TypeError):
        return None


def _write_cache(path: Path, result: Any) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump({"saved_at": time.time(), "result": result}, fh)
        tmp.replace(path)
    except OSError:
        # A cache is an optimization; a read-only project directory is fine.
        pass


def cf_api(
    method: str,
    params: dict[str, Any] | None = None,
    *,
    ttl: int = CACHE_TTL_SECONDS,
    refresh: bool = False,
    use_cache: bool = True,
) -> Any:
    """Call a Codeforces API method, with validation, retries, and disk caching."""
    params = dict(params or {})
    cache_path = _cache_file(method, params)

    if use_cache and not refresh:
        cached = _read_cache(cache_path, ttl)
        if cached is not None:
            return cached

    last_error: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        _throttle()
        try:
            response = requests.get(
                f"{API_BASE}/{method}",
                params=params,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as exc:
            last_error = exc
            if attempt < MAX_RETRIES:
                delay = 2 ** attempt
                log(f"  network error ({exc.__class__.__name__}); retrying in {delay}s...")
                time.sleep(delay)
                continue
            raise CFError(
                f"Could not reach codeforces.com after {MAX_RETRIES} attempts. "
                "Check your internet connection and try again."
            ) from exc
        finally:
            global _last_request_at
            _last_request_at = time.monotonic()

        if response.status_code == 429 or 500 <= response.status_code < 600:
            last_error = CFError(f"Codeforces returned HTTP {response.status_code}.")
            if attempt < MAX_RETRIES:
                delay = 2 ** attempt
                log(f"  HTTP {response.status_code}; retrying in {delay}s...")
                time.sleep(delay)
                continue
            raise CFError(
                "Codeforces is rate-limiting or temporarily unavailable "
                f"(HTTP {response.status_code}). Try again in a minute."
            )

        try:
            payload = response.json()
        except ValueError as exc:
            snippet = response.text[:160].replace("\n", " ").strip()
            raise CFError(
                f"Codeforces returned a non-JSON response (HTTP {response.status_code}): {snippet}"
            ) from exc

        if not isinstance(payload, dict) or "status" not in payload:
            raise CFError("Unexpected response shape from the Codeforces API.")

        if payload.get("status") != "OK":
            comment = str(payload.get("comment", "Unknown API error.")).strip()
            lowered = comment.lower()
            if lowered.startswith("handle:"):
                detail = comment.split(":", 1)[1].strip()
                if "not found" in lowered:
                    raise CFError(
                        f"Codeforces handle not found: {params.get('handle', '?')}. "
                        "Check the spelling (handles are case-insensitive)."
                    )
                raise CFError(
                    f"Invalid Codeforces handle {params.get('handle', '?')!r}: {detail}"
                )
            raise CFError(f"Codeforces API error: {comment}")

        result = payload.get("result")
        if use_cache:
            _write_cache(cache_path, result)
        return result

    raise CFError(f"Codeforces API request failed: {last_error}")


# ---------------------------------------------------------------------------
# Data model and fetching
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RatedContest:
    contest_id: int
    name: str
    rank: int
    rating: int
    at: int

    @property
    def date(self) -> datetime:
        return datetime.fromtimestamp(self.at, tz=timezone.utc)


@dataclass(frozen=True)
class AcceptedProblem:
    contest_id: int
    index: str
    at: int
    rating: int | None = None

    @property
    def key(self) -> tuple[int, str]:
        return (self.contest_id, self.index)


@dataclass(frozen=True)
class ContestWindow:
    start: int
    duration: int

    @property
    def end(self) -> int:
        return self.start + self.duration


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def fetch_rating_history(
    handle: str, *, refresh: bool = False, use_cache: bool = True
) -> tuple[str, list[RatedContest]]:
    """Fetch and normalize the user's rated contest history."""
    raw = cf_api(
        "user.rating",
        {"handle": handle},
        ttl=CACHE_TTL_SECONDS,
        refresh=refresh,
        use_cache=use_cache,
    )

    if not isinstance(raw, list) or not raw:
        raise CFError(
            f"{handle} has no rated contest history. "
            "They may be unrated or may not have competed in a rated round yet."
        )

    history: list[RatedContest] = []
    canonical = handle
    for item in raw:
        if not isinstance(item, dict) or "newRating" not in item:
            continue
        canonical = str(item.get("handle") or canonical)
        history.append(
            RatedContest(
                contest_id=_as_int(item.get("contestId"), -1),
                name=str(item.get("contestName") or "Unknown contest"),
                rank=_as_int(item.get("rank"), 0),
                rating=_as_int(item.get("newRating"), 0),
                at=_as_int(item.get("ratingUpdateTimeSeconds"), 0),
            )
        )

    history = [item for item in history if item.contest_id >= 0 and item.at > 0]
    history.sort(key=lambda item: (item.at, item.contest_id))
    if not history:
        raise CFError("Codeforces returned an empty or malformed rating history.")

    return canonical, history


def fetch_accepted_problems(
    handle: str,
    first_contest_time: int,
    *,
    refresh: bool = False,
    use_cache: bool = True,
) -> list[AcceptedProblem]:
    """Fetch submissions and keep one earliest acceptance per distinct problem."""
    all_submissions: list[dict[str, Any]] = []
    offset = 1

    while offset <= MAX_SUBMISSIONS:
        page_size = min(PAGE_SIZE, MAX_SUBMISSIONS - offset + 1)
        raw = cf_api(
            "user.status",
            {"handle": handle, "from": offset, "count": page_size},
            ttl=CACHE_TTL_SECONDS,
            refresh=refresh,
            use_cache=use_cache,
        )
        if not isinstance(raw, list):
            raise CFError("Unexpected submission data from the Codeforces API.")
        if not raw:
            break

        all_submissions.extend(item for item in raw if isinstance(item, dict))

        if len(raw) < page_size:
            break
        last_time = _as_int(raw[-1].get("creationTimeSeconds"), 0)
        if last_time and last_time < first_contest_time:
            # Results are newest-first, so nothing older can belong to a rated round.
            break

        offset += len(raw)
        log(f"  fetched {len(all_submissions):,} submissions...")

    if not all_submissions:
        return []

    earliest: OrderedDict[tuple[int, str], AcceptedProblem] = OrderedDict()
    for submission in all_submissions:
        if submission.get("verdict") != "OK":
            continue
        problem = submission.get("problem")
        if not isinstance(problem, dict):
            continue

        contest_id = _as_int(problem.get("contestId", submission.get("contestId")), -1)
        index = str(problem.get("index") or "").strip()
        at = _as_int(submission.get("creationTimeSeconds"), 0)
        if contest_id < 0 or not index or at <= 0:
            continue

        problem_rating = _as_int(problem.get("rating"), 0)
        candidate = AcceptedProblem(
            contest_id=contest_id,
            index=index,
            at=at,
            rating=problem_rating if problem_rating > 0 else None,
        )
        previous = earliest.get(candidate.key)
        if previous is None or at < previous.at:
            earliest[candidate.key] = candidate

    return list(earliest.values())


def fetch_contest_windows(
    *, refresh: bool = False, use_cache: bool = True
) -> dict[int, ContestWindow]:
    """Fetch all non-gym contests so per-contest solve windows are exact."""
    raw = cf_api(
        "contest.list",
        {"gym": "false"},
        ttl=CONTEST_CACHE_TTL_SECONDS,
        refresh=refresh,
        use_cache=use_cache,
    )
    if not isinstance(raw, list):
        raise CFError("Unexpected contest list from the Codeforces API.")

    windows: dict[int, ContestWindow] = {}
    for contest in raw:
        if not isinstance(contest, dict):
            continue
        contest_id = _as_int(contest.get("id"), -1)
        start = _as_int(contest.get("startTimeSeconds"), -1)
        duration = _as_int(contest.get("durationSeconds"), 0)
        if contest_id >= 0 and start > 0 and duration > 0:
            windows[contest_id] = ContestWindow(start=start, duration=duration)
    return windows


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


@dataclass
class Series:
    handle: str
    history: list[RatedContest]
    ratings: list[int]
    solved: list[int]
    dates: list[int]


def cumulative_series(
    handle: str, history: list[RatedContest], accepted: list[AcceptedProblem]
) -> Series:
    """For each rating update, count distinct problems accepted by that moment."""
    ordered = sorted(accepted, key=lambda item: (item.at, item.key))
    solved: list[int] = []
    pointer = 0

    for contest in history:
        while pointer < len(ordered) and ordered[pointer].at <= contest.at:
            pointer += 1
        solved.append(pointer)

    return Series(
        handle=handle,
        history=history,
        ratings=[item.rating for item in history],
        solved=solved,
        dates=[item.at for item in history],
    )


def per_contest_series(
    handle: str,
    history: list[RatedContest],
    accepted: list[AcceptedProblem],
    windows: dict[int, ContestWindow],
) -> tuple[Series, int]:
    """Count distinct problems accepted inside each rated contest's time window."""
    counts: dict[int, int] = {contest.contest_id: 0 for contest in history}
    rated_ids = set(counts)
    missing_windows: set[int] = set()

    for problem in accepted:
        if problem.contest_id not in rated_ids:
            continue
        window = windows.get(problem.contest_id)
        if window is None:
            # Keep the point meaningful if Codeforces omits metadata for a round.
            counts[problem.contest_id] += 1
            missing_windows.add(problem.contest_id)
        elif window.start <= problem.at <= window.end:
            counts[problem.contest_id] += 1

    series = Series(
        handle=handle,
        history=history,
        ratings=[item.rating for item in history],
        solved=[counts[item.contest_id] for item in history],
        dates=[item.at for item in history],
    )
    return series, len(missing_windows)


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------


def _style_axes(ax: plt.Axes) -> None:
    ax.set_facecolor(PANEL)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#cbd5e1")
        ax.spines[side].set_linewidth(1.0)
    ax.grid(axis="y", color=GRID, linewidth=0.9, alpha=0.9)
    ax.set_axisbelow(True)
    ax.tick_params(axis="both", colors=MUTED, labelsize=10, length=0, pad=7)


def _new_figure(title: str, subtitle: str) -> tuple[plt.Figure, plt.Axes]:
    fig, ax = plt.subplots(figsize=(12, 7.1), dpi=160, facecolor=BG)
    fig.subplots_adjust(left=0.075, right=0.97, top=0.80, bottom=0.12)
    _style_axes(ax)

    fig.text(0.075, 0.955, title, fontsize=22, fontweight="bold", color=INK,
             ha="left", va="top")
    fig.text(0.075, 0.895, subtitle, fontsize=10.5, color=MUTED,
             ha="left", va="top")
    return fig, ax


def _callout(ax: plt.Axes, xy: tuple[float, float], text: str, *,
             offset: tuple[float, float], color: str, ha: str = "left") -> None:
    ax.annotate(
        text,
        xy=xy,
        xytext=offset,
        textcoords="offset points",
        ha=ha,
        va="center",
        fontsize=8.8,
        color=color,
        linespacing=1.3,
        bbox=dict(boxstyle="round,pad=0.42", facecolor="white",
                  edgecolor="#e2e8f0", alpha=0.96),
        arrowprops=dict(arrowstyle="-", color="#94a3b8", linewidth=0.8,
                        shrinkA=3, shrinkB=5),
        zorder=10,
    )


def _tier_scatter(ax: plt.Axes, solved: np.ndarray, ratings: np.ndarray,
                  *, size: float) -> list[Any]:
    handles: list[Any] = []
    for label, low, high, color in CF_TIERS:
        mask = (ratings >= low) & (ratings <= high)
        if not np.any(mask):
            continue
        handle = ax.scatter(
            solved[mask],
            ratings[mask],
            s=size,
            color=color,
            edgecolors="white",
            linewidths=0.55,
            alpha=0.9,
            label=label,
            zorder=3,
        )
        handles.append(handle)
    return handles


def _rating_limits(ax: plt.Axes, solved: np.ndarray, ratings: np.ndarray) -> tuple[int, int]:
    ax.set_xlim(0, max(1.0, float(np.max(solved))) * 1.05)
    low, high = int(np.min(ratings)), int(np.max(ratings))
    pad = max(55, int((high - low) * 0.08))
    y_min, y_max = max(0, low - pad), high + pad
    ax.set_ylim(y_min, y_max)
    ax.xaxis.set_major_locator(MaxNLocator(nbins=8, integer=True))
    ax.yaxis.set_major_locator(MaxNLocator(nbins=7, integer=True))
    ax.xaxis.set_major_formatter(StrMethodFormatter("{x:,.0f}"))
    ax.yaxis.set_major_formatter(StrMethodFormatter("{x:,.0f}"))
    return y_min, y_max


def _add_tier_bands(ax: plt.Axes, y_min: int, y_max: int) -> None:
    for _, low, high, color in CF_TIERS:
        bottom = max(low, y_min)
        top = min(high, y_max)
        if top > bottom:
            ax.axhspan(bottom, top, color=color, alpha=0.045, zorder=0)


def _tier_legend(ax: plt.Axes, *, title: str = "Rating tier") -> None:
    handles, labels = ax.get_legend_handles_labels()
    if not handles:
        return
    legend = ax.legend(
        handles,
        labels,
        loc="best",
        title=title,
        frameon=True,
        facecolor="white",
        edgecolor="#e2e8f0",
        framealpha=0.96,
        fontsize=8.6,
        title_fontsize=9,
    )
    legend.get_title().set_color(MUTED)


def plot_cumulative(series: Series, output: Path, *, dpi: int = 160) -> None:
    ratings = np.asarray(series.ratings, dtype=float)
    solved = np.asarray(series.solved, dtype=float)
    n = len(series.history)

    first_date = series.history[0].date
    last_date = series.history[-1].date
    year_text = (
        str(first_date.year)
        if first_date.year == last_date.year
        else f"{first_date.year}\u2013{last_date.year}"
    )
    peak_index = max(range(n), key=lambda i: (series.ratings[i], series.dates[i]))

    title = "Problems solved vs. contest rating"
    subtitle = (
        f"{series.handle}  \u00b7  {n:,} rated rounds  \u00b7  {year_text}  "
        f"\u00b7  {series.solved[-1]:,} distinct problems solved"
    )
    fig, ax = _new_figure(title, subtitle)
    y_min, y_max = _rating_limits(ax, solved, ratings)
    _add_tier_bands(ax, y_min, y_max)

    if n > 1:
        ax.plot(
            solved,
            ratings,
            color="#94a3b8",
            linewidth=1.7,
            alpha=0.5,
            zorder=2,
        )

    _tier_scatter(ax, solved, ratings, size=28)

    # Start / latest / peak markers.
    ax.scatter(solved[0], ratings[0], s=68, facecolor="white", edgecolor="#334155",
               linewidth=1.5, zorder=5)
    ax.scatter(solved[-1], ratings[-1], s=92, facecolors="none", edgecolors="#111827",
               linewidth=2.0, zorder=6)
    ax.scatter(solved[peak_index], ratings[peak_index], marker="*", s=240,
               facecolor="#f59e0b", edgecolor="white", linewidth=0.8, zorder=7)

    mid = float(np.median(solved))
    latest_ha = "right" if solved[-1] >= mid else "left"
    latest_dx = -16 if latest_ha == "right" else 16
    latest_text = (
        f"Latest / peak\n{series.ratings[-1]:,} rating"
        if peak_index == n - 1
        else f"Latest\n{series.ratings[-1]:,} rating"
    )
    _callout(
        ax,
        (float(solved[-1]), float(ratings[-1])),
        latest_text,
        offset=(latest_dx, -28),
        ha=latest_ha,
        color="#111827",
    )

    if peak_index != n - 1:
        peak_ha = "right" if solved[peak_index] >= mid else "left"
        peak_dx = -16 if peak_ha == "right" else 16
        _callout(
            ax,
            (float(solved[peak_index]), float(ratings[peak_index])),
            f"Peak\n{series.ratings[peak_index]:,}",
            offset=(peak_dx, 26),
            ha=peak_ha,
            color="#92400e",
        )

    _tier_legend(ax)
    ax.set_xlabel("Problems solved (cumulative)", color=MUTED, fontsize=10.5, labelpad=10)
    ax.set_ylabel("Contest rating", color=MUTED, fontsize=10.5, labelpad=10)

    fig.text(
        0.075,
        0.027,
        "X: distinct accepted problems up to each rating update.  Y: rating after the round.  "
        "Source: Codeforces API.",
        fontsize=8.5,
        color="#94a3b8",
        ha="left",
        va="bottom",
    )
    fig.text(
        0.97,
        0.027,
        datetime.now().strftime("Generated %d %b %Y"),
        fontsize=8.5,
        color="#94a3b8",
        ha="right",
        va="bottom",
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=dpi, facecolor=BG, bbox_inches="tight", pad_inches=0.22)
    plt.close(fig)


def plot_per_contest(series: Series, output: Path, *, dpi: int = 160) -> None:
    ratings = np.asarray(series.ratings, dtype=float)
    solved = np.asarray(series.solved, dtype=float)
    n = len(series.history)

    first_date = series.history[0].date
    last_date = series.history[-1].date
    year_text = (
        str(first_date.year)
        if first_date.year == last_date.year
        else f"{first_date.year}\u2013{last_date.year}"
    )
    median_solved = int(np.median(solved))
    best = int(max(solved))

    title = "Problems solved per contest vs. rating"
    subtitle = (
        f"{series.handle}  \u00b7  {n:,} rated rounds  \u00b7  {year_text}  "
        f"\u00b7  median {median_solved} solved per round  \u00b7  best {best}"
    )
    fig, ax = _new_figure(title, subtitle)
    y_min, y_max = _rating_limits(ax, solved, ratings)
    _add_tier_bands(ax, y_min, y_max)

    _tier_scatter(ax, solved, ratings, size=44)

    # Robust summary: median rating for each number of problems solved.
    line_x: list[int] = []
    line_y: list[float] = []
    for count in sorted(set(int(value) for value in solved)):
        values = ratings[solved == count]
        if len(values) >= 3:
            line_x.append(count)
            line_y.append(float(np.median(values)))

    if len(line_x) >= 2:
        ax.plot(
            line_x,
            line_y,
            color="#111827",
            linewidth=2.0,
            linestyle=(0, (5, 3)),
            label="Median rating",
            zorder=4,
        )

    _tier_legend(ax)
    ax.set_xlabel("Problems solved in contest", color=MUTED, fontsize=10.5, labelpad=10)
    ax.set_ylabel("Contest rating", color=MUTED, fontsize=10.5, labelpad=10)

    fig.text(
        0.075,
        0.027,
        "X: distinct accepted problems inside each contest window.  "
        "Y: rating after the round.  Source: Codeforces API.",
        fontsize=8.5,
        color="#94a3b8",
        ha="left",
        va="bottom",
    )
    fig.text(
        0.97,
        0.027,
        datetime.now().strftime("Generated %d %b %Y"),
        fontsize=8.5,
        color="#94a3b8",
        ha="right",
        va="bottom",
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=dpi, facecolor=BG, bbox_inches="tight", pad_inches=0.22)
    plt.close(fig)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _safe_filename(handle: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in handle)
    return cleaned.strip("._") or "user"


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot a Codeforces user's contest rating against problems solved.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python cf_rating_vs_solved.py tourist\n"
            "  python cf_rating_vs_solved.py tourist --mode contest\n"
            "  python cf_rating_vs_solved.py --refresh\n"
        ),
    )
    parser.add_argument("handle", nargs="?", help="Codeforces handle (prompted if omitted)")
    parser.add_argument(
        "--mode",
        choices=("cumulative", "contest"),
        default="cumulative",
        help="cumulative total solved (default) or problems solved per contest",
    )
    parser.add_argument("-o", "--output", type=Path, help="output PNG path")
    parser.add_argument("--dpi", type=int, default=160, help="PNG resolution (default: 160)")
    parser.add_argument("--refresh", action="store_true", help="ignore cached API responses")
    parser.add_argument("--no-cache", action="store_true", help="do not read or write the API cache")
    parser.add_argument("--open", action="store_true", dest="open_image",
                        help="open the PNG when finished")
    return parser.parse_args(argv)


def _summary(series: Series, mode: str) -> None:
    history = series.history
    peak = max(series.ratings)
    total = series.solved[-1]
    print()
    print(f"Handle          {series.handle}")
    print(f"Rated rounds    {len(history):,}")
    print(f"Rating range    {min(series.ratings):,} -> {max(series.ratings):,}  "
          f"(peak {peak:,})")
    if mode == "cumulative":
        print(f"Problems solved {total:,} distinct (by latest rated round)")
    else:
        print(f"Problems solved {int(sum(series.solved)):,} across rated rounds  "
              f"(median {int(np.median(series.solved))}/round)")
    print(f"Latest round    {history[-1].name}  |  "
          f"{history[-1].date.strftime('%d %b %Y')}")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)

    handle = (args.handle or "").strip()
    if not handle:
        try:
            handle = input("Codeforces handle: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nNo handle provided.", file=sys.stderr)
            return 1
    if not handle:
        print("Error: a Codeforces handle is required.", file=sys.stderr)
        return 1
    if not 3 <= len(handle) <= 24:
        print("Error: Codeforces handles must be 3-24 characters long.", file=sys.stderr)
        return 1

    if args.dpi < 72 or args.dpi > 600:
        print("Error: --dpi must be between 72 and 600.", file=sys.stderr)
        return 1

    use_cache = not args.no_cache
    output = args.output or OUTPUT_DIR / f"{_safe_filename(handle)}_{args.mode}.png"

    try:
        log(f"Fetching rating history for {handle}...")
        canonical, history = fetch_rating_history(
            handle, refresh=args.refresh, use_cache=use_cache
        )

        log("Fetching submissions...")
        accepted = fetch_accepted_problems(
            canonical,
            history[0].at,
            refresh=args.refresh,
            use_cache=use_cache,
        )
        log(f"  {len(accepted):,} distinct accepted problems found.")

        if args.mode == "cumulative":
            series = cumulative_series(canonical, history, accepted)
            _summary(series, "cumulative")
            plot_cumulative(series, output, dpi=args.dpi)
        else:
            log("Fetching contest time windows...")
            windows = fetch_contest_windows(
                refresh=args.refresh, use_cache=use_cache
            )
            series, missing = per_contest_series(canonical, history, accepted, windows)
            _summary(series, "contest")
            if missing:
                log(
                    f"Warning: no contest-window metadata for {missing} round(s); "
                    "all accepted submissions for those rounds were counted."
                )
            plot_per_contest(series, output, dpi=args.dpi)

    except CFError as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130

    print(f"Chart           {output.resolve()}")
    if args.open_image:
        webbrowser.open(output.resolve().as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
