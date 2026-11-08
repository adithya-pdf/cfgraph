"""Browser-safe data layer for the stlite build.

Unlike cf_rating_vs_solved.py, this module:
  * uses Pyodide's synchronous XHR helper instead of requests/sockets
  * keeps no disk cache
  * has no matplotlib dependency

The public names match the server-side data layer used by streamlit_app.py.
"""

from __future__ import annotations

import bisect
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlencode

from pyodide.http import open_url

API_BASE = "https://codeforces.com/api"
PAGE_SIZE = 10_000
MAX_SUBMISSIONS = 200_000
REQUEST_GAP_SECONDS = 2.05

_last_request_at = 0.0


class CFError(RuntimeError):
    """A user-facing Codeforces API or data error."""


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


@dataclass
class Series:
    handle: str
    history: list[RatedContest]
    ratings: list[int]
    solved: list[int]
    dates: list[int]


def _as_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _api(method: str, params: dict | None = None):
    """Call a Codeforces API method using Pyodide's synchronous XHR helper."""
    global _last_request_at

    wait = REQUEST_GAP_SECONDS - (time.monotonic() - _last_request_at)
    if wait > 0:
        time.sleep(wait)

    query = urlencode(params or {})
    url = f"{API_BASE}/{method}"
    if query:
        url = f"{url}?{query}"

    try:
        response = open_url(url)
        raw = response.read()
    except Exception as exc:
        raise CFError(
            "The browser could not reach codeforces.com. "
            "Check your connection and try again."
        ) from exc
    finally:
        _last_request_at = time.monotonic()

    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")

    try:
        payload = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise CFError("Codeforces returned an unreadable response.") from exc

    if not isinstance(payload, dict) or payload.get("status") != "OK":
        comment = str(payload.get("comment", "Unknown Codeforces API error.")).strip()
        lowered = comment.lower()
        if "not found" in lowered:
            raise CFError(
                f"Codeforces handle not found: {params.get('handle', '?')}."
            )
        raise CFError(f"Codeforces API error: {comment}")

    return payload.get("result")


def fetch_rating_history(
    handle: str,
    *,
    refresh: bool = False,
    use_cache: bool = True,
) -> tuple[str, list[RatedContest]]:
    raw = _api("user.rating", {"handle": handle})
    if not isinstance(raw, list) or not raw:
        raise CFError(
            f"{handle} has no rated contest history. "
            "They may be unrated or have not competed in a rated round yet."
        )

    canonical = handle
    history: list[RatedContest] = []
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
    all_submissions = []
    offset = 1

    while offset <= MAX_SUBMISSIONS:
        page_size = min(PAGE_SIZE, MAX_SUBMISSIONS - offset + 1)
        raw = _api(
            "user.status",
            {"handle": handle, "from": offset, "count": page_size},
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
            break
        offset += len(raw)

    earliest: dict[tuple[int, str], AcceptedProblem] = {}
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
    *,
    refresh: bool = False,
    use_cache: bool = True,
) -> dict[int, ContestWindow]:
    raw = _api("contest.list", {"gym": "false"})
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


def cumulative_series(
    handle: str,
    history: list[RatedContest],
    accepted: list[AcceptedProblem],
) -> Series:
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
    counts: dict[int, int] = {contest.contest_id: 0 for contest in history}
    rated_ids = set(counts)
    missing_windows: set[int] = set()

    for problem in accepted:
        if problem.contest_id not in rated_ids:
            continue
        window = windows.get(problem.contest_id)
        if window is None:
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


def filter_hard_solves(
    accepted: list[AcceptedProblem],
    history: list[RatedContest],
    margin: int = 0,
) -> list[AcceptedProblem]:
    """Keep solves with problem rating >= rating at solve time + margin."""
    if not accepted or not history:
        return []

    ordered = sorted(history, key=lambda contest: contest.at)
    times = [contest.at for contest in ordered]
    ratings = [contest.rating for contest in ordered]

    hard: list[AcceptedProblem] = []
    for problem in accepted:
        if problem.rating is None:
            continue
        index = bisect.bisect_right(times, problem.at) - 1
        if index >= 0 and problem.rating >= ratings[index] + margin:
            hard.append(problem)
    return hard
