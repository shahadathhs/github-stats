from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Set

import aiohttp

from .queries import Queries


def streaks_from_days(days: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Given a list of {date, contributionCount, weekday} (assumed chronological),
    compute the current streak, the longest streak, and the best day.

    "Current streak" tolerates today having no contributions yet by starting
    from yesterday if the last day is empty.
    """
    counts = [d.get("contributionCount", 0) for d in days]
    dates = [d.get("date") for d in days]
    n = len(counts)

    # Current streak (tolerate today being empty): walk back from the last
    # contributing day and record the run's start/end dates.
    end = n - 1
    if end >= 0 and counts[end] == 0:
        end -= 1
    start = end
    while start >= 0 and counts[start] > 0:
        start -= 1
    start += 1
    current = max(0, end - start + 1) if end >= 0 else 0
    current_range = (
        [dates[start], dates[end]]
        if current > 0 and 0 <= start <= end < n
        else [None, None]
    )

    # Longest streak: track the longest run of positive days and its span.
    longest = 0
    best_lo = best_hi = 0
    run_start = None
    for i in range(n):
        if counts[i] > 0:
            if run_start is None:
                run_start = i
            run_len = i - run_start + 1
            if run_len > longest:
                longest = run_len
                best_lo, best_hi = run_start, i
        else:
            run_start = None
    longest_range = (
        [dates[best_lo], dates[best_hi]] if longest > 0 else [None, None]
    )

    best = {"date": None, "count": 0}
    for d in days:
        if d.get("contributionCount", 0) > best["count"]:
            best = {"date": d.get("date"), "count": d.get("contributionCount", 0)}

    return {
        "current": current,
        "current_range": current_range,
        "longest": longest,
        "longest_range": longest_range,
        "best": best,
    }


class Stats(object):
    """
    Retrieve the slices of GitHub statistics the redesigned cards use:
    language usage across the user's repositories, and their contribution
    rhythm over a rolling window.
    """

    def __init__(
        self,
        username: str,
        access_token: str,
        session: aiohttp.ClientSession,
        exclude_repos: Optional[Set] = None,
        exclude_langs: Optional[Set] = None,
    ):
        self.username = username
        self._exclude_repos = set() if exclude_repos is None else exclude_repos
        self._exclude_langs_lower = {
            x.lower() for x in (exclude_langs or set())
        }
        self.queries = Queries(username, access_token, session)

        self._name: Optional[str] = None
        self._languages: Optional[Dict[str, Dict[str, Any]]] = None
        self._contributions: Optional[Dict[str, Any]] = None

    async def _load_languages(self) -> None:
        """Page through owned repos and aggregate their language sizes."""
        languages: Dict[str, Dict[str, Any]] = {}
        cursor = None
        while True:
            res = await self.queries.query(
                Queries.repos_with_languages(cursor)
            )
            viewer = res.get("data", {}).get("viewer", {})
            if self._name is None:
                self._name = viewer.get("name") or viewer.get("login") or self.username

            repos = viewer.get("repositories", {})
            for repo in repos.get("nodes", []) or []:
                if repo is None:
                    continue
                name = repo.get("nameWithOwner")
                if name in self._exclude_repos:
                    continue
                for edge in repo.get("languages", {}).get("edges", []) or []:
                    node = edge.get("node", {}) or {}
                    lang = node.get("name", "Other")
                    if lang.lower() in self._exclude_langs_lower:
                        continue
                    size = edge.get("size", 0)
                    if lang in languages:
                        languages[lang]["size"] += size
                    else:
                        languages[lang] = {
                            "size": size,
                            "color": node.get("color"),
                        }

            page_info = repos.get("pageInfo", {})
            if page_info.get("hasNextPage"):
                cursor = page_info.get("endCursor")
            else:
                break

        total = sum(v["size"] for v in languages.values()) or 1
        for v in languages.values():
            v["prop"] = 100 * v["size"] / total

        self._languages = languages

    async def _load_contributions(self, days: int = 365) -> None:
        """Fetch the contribution calendar for the rolling window + streaks."""
        date_to = date.today()
        date_from = date_to - timedelta(days=days)
        iso_to = f"{date_to.isoformat()}T00:00:00Z"
        iso_from = f"{date_from.isoformat()}T00:00:00Z"

        res = await self.queries.query(
            Queries.contribution_calendar(iso_from, iso_to)
        )
        viewer = res.get("data", {}).get("viewer", {})
        if self._name is None:
            self._name = viewer.get("name") or self.username

        cal = (
            viewer.get("contributionsCollection", {}).get("contributionCalendar", {})
        )
        weeks = cal.get("weeks", []) or []
        days_flat = [d for w in weeks for d in (w.get("contributionDays") or [])]
        months = [
            {"firstDay": m.get("firstDay"), "name": m.get("name")}
            for m in (cal.get("months", []) or [])
        ]

        self._contributions = {
            "total": cal.get("totalContributions", 0),
            "weeks": weeks,
            "months": months,
            "days": days_flat,
            **streaks_from_days(days_flat),
        }

    @property
    async def name(self) -> str:
        if self._name is None:
            await self._load_languages()
        return self._name or self.username

    @property
    async def languages(self) -> Dict[str, Dict[str, Any]]:
        if self._languages is None:
            await self._load_languages()
        assert self._languages is not None
        return self._languages

    @property
    async def languages_sorted(self) -> List[Dict[str, Any]]:
        langs = await self.languages
        return [
            {"name": k, **v}
            for k, v in sorted(
                langs.items(), key=lambda kv: kv[1].get("size", 0), reverse=True
            )
        ]

    @property
    async def contributions(self) -> Dict[str, Any]:
        if self._contributions is None:
            await self._load_contributions()
        assert self._contributions is not None
        return self._contributions
