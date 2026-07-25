import asyncio
import math
import os
import re
from datetime import date
from pathlib import Path

import aiohttp

from .stats import Stats

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = ROOT / "templates"
GENERATED_DIR = ROOT / "generated"

# Heatmap geometry
CELL = 10
GAP = 3
STEP = CELL + GAP
LEFT_PAD = 28
TOP_PAD = 24
STATS_Y = TOP_PAD + 7 * STEP + 16


def _level_for(count: int) -> int:
    if count <= 0:
        return 0
    if count < 4:
        return 1
    if count < 7:
        return 2
    if count < 10:
        return 3
    return 4


def _short_month(iso_date: str) -> str:
    try:
        y, m, _ = iso_date.split("-")
        return date(int(y), int(m), 1).strftime("%b")
    except Exception:
        return ""


def _format_day(iso_date: str) -> str:
    try:
        y, m, d = iso_date.split("-")
        return f"{date(int(y), int(m), 1).strftime('%b')} {int(d)}"
    except Exception:
        return iso_date


def render_heatmap_cells(contrib: dict) -> str:
    cells = []
    for wi, week in enumerate(contrib["weeks"]):
        for day in week.get("contributionDays", []) or []:
            row = day.get("weekday", 0)
            x = LEFT_PAD + wi * STEP
            y = TOP_PAD + row * STEP
            lvl = _level_for(day.get("contributionCount", 0))
            cells.append(
                f'<rect class="lvl{lvl}" x="{x}" y="{y}" '
                f'width="{CELL}" height="{CELL}" rx="2">'
                f'<title>{day.get("date")}: {day.get("contributionCount", 0)}</title>'
                f"</rect>"
            )
    return "\n".join(cells)


def render_month_labels(contrib: dict) -> str:
    labels = []
    current = None
    for wi, week in enumerate(contrib["weeks"]):
        days = week.get("contributionDays") or []
        if not days:
            continue
        first = days[0].get("date", "")
        month = first[:7]
        if month and month != current:
            current = month
            x = LEFT_PAD + wi * STEP
            labels.append(
                f'<text x="{x}" y="16" class="month">{_short_month(first)}</text>'
            )
    return "\n".join(labels)


def render_day_labels() -> str:
    rows = {"Mon": 1, "Wed": 3, "Fri": 5}
    parts = []
    for name, row in rows.items():
        y = TOP_PAD + row * STEP + 9
        parts.append(f'<text x="0" y="{y}" class="day">{name}</text>')
    return "\n".join(parts)


def render_stats_row(contrib: dict, card_width: int) -> str:
    best = contrib.get("best", {}) or {}
    best_str = "—"
    if best.get("count"):
        suffix = f" · {_format_day(best['date'])}" if best.get("date") else ""
        best_str = f'{best["count"]}{suffix}'

    items = [
        ("Contributions", f'{contrib.get("total", 0):,}'),
        ("Current streak", f'{contrib.get("current", 0)} days'),
        ("Longest streak", f'{contrib.get("longest", 0)} days'),
        ("Best day", best_str),
    ]
    col_w = card_width / 4
    parts = []
    for i, (label, value) in enumerate(items):
        x = int(i * col_w + 18)
        parts.append(
            f'<text x="{x}" y="{STATS_Y}" class="stat-num">{value}</text>'
        )
        parts.append(
            f'<text x="{x}" y="{STATS_Y + 16}" class="stat-lbl">{label}</text>'
        )
    return "\n".join(parts)


def _polar(cx: float, cy: float, r: float, deg: float):
    a = math.radians(deg)
    return cx + r * math.cos(a), cy + r * math.sin(a)


def _donut_segment(cx, cy, r_out, r_in, start, end, color):
    large = 1 if (end - start) > 180 else 0
    x1, y1 = _polar(cx, cy, r_out, start)
    x2, y2 = _polar(cx, cy, r_out, end)
    x3, y3 = _polar(cx, cy, r_in, end)
    x4, y4 = _polar(cx, cy, r_in, start)
    return (
        f'<path d="M{x1:.2f},{y1:.2f} '
        f"A{r_out},{r_out} 0 {large} 1 {x2:.2f},{y2:.2f} "
        f"L{x3:.2f},{y3:.2f} "
        f'A{r_in},{r_in} 0 {large} 0 {x4:.2f},{y4:.2f} Z" fill="{color}"/>'
    )


def render_donut(langs_sorted: list, top_n: int = 6):
    items = list(langs_sorted[:top_n])
    other_prop = sum(l.get("prop", 0) for l in langs_sorted[top_n:])
    if other_prop > 0.01:
        items.append({"name": "Other", "prop": other_prop, "color": "#6e7681"})

    cx, cy, r_out, r_in = 86, 104, 66, 42
    start = -90.0
    segments = []
    legend = []
    ly = 44
    for it in items:
        frac = (it.get("prop", 0) or 0) / 100.0
        end = start + frac * 360.0
        color = it.get("color") or "#6e7681"
        if frac >= 0.999:
            mid = (r_out + r_in) / 2
            segments.append(
                f'<circle cx="{cx}" cy="{cy}" r="{mid:.2f}" fill="none" '
                f'stroke="{color}" stroke-width="{r_out - r_in}"/>'
            )
        elif frac > 0:
            segments.append(
                _donut_segment(cx, cy, r_out, r_in, start, end, color)
            )
        legend.append(
            f'<rect x="186" y="{ly - 9}" width="10" height="10" rx="2" '
            f'fill="{color}"/>'
            f'<text x="202" y="{ly}" class="lang-name">{it["name"]}</text>'
            f'<text x="448" y="{ly}" class="lang-pct" text-anchor="end">'
            f'{it.get("prop", 0):.1f}%</text>'
        )
        start = end
        ly += 22

    return "\n".join(segments), "\n".join(legend), len(items)


def generate_output_folder() -> None:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)


async def generate_overview(s: Stats) -> None:
    output = (TEMPLATES_DIR / "overview.svg").read_text()
    contrib = await s.contributions
    n_weeks = len(contrib["weeks"]) or 53
    card_width = LEFT_PAD + n_weeks * STEP + 14
    card_height = STATS_Y + 30

    output = re.sub(r"{{ name }}", await s.name, output)
    output = re.sub(r"{{ card_width }}", str(card_width), output)
    output = re.sub(r"{{ card_height }}", str(card_height), output)
    output = re.sub(r"{{ divider_x2 }}", str(card_width - 14), output)
    output = re.sub(r"{{ month_labels }}", render_month_labels(contrib), output)
    output = re.sub(r"{{ day_labels }}", render_day_labels(), output)
    output = re.sub(r"{{ heatmap_cells }}", render_heatmap_cells(contrib), output)
    output = re.sub(r"{{ stats_row }}", render_stats_row(contrib, card_width), output)

    generate_output_folder()
    (GENERATED_DIR / "overview.svg").write_text(output)


async def generate_languages(s: Stats) -> None:
    output = (TEMPLATES_DIR / "languages.svg").read_text()
    langs_sorted = await s.languages_sorted
    segments, legend, n = render_donut(langs_sorted)

    output = re.sub(r"{{ segments }}", segments, output)
    output = re.sub(r"{{ legend }}", legend, output)
    output = re.sub(r"{{ lang_count }}", str(len(langs_sorted)), output)

    generate_output_folder()
    (GENERATED_DIR / "languages.svg").write_text(output)


async def main() -> None:
    access_token = os.getenv("ACCESS_TOKEN")
    if not access_token:
        raise Exception("A personal access token is required to proceed!")
    user = os.getenv("GITHUB_ACTOR")
    if user is None:
        raise RuntimeError("Environment variable GITHUB_ACTOR must be set.")

    exclude_repos = os.getenv("EXCLUDED")
    excluded_repos = (
        {x.strip() for x in exclude_repos.split(",")} if exclude_repos else None
    )
    exclude_langs = os.getenv("EXCLUDED_LANGS")
    excluded_langs = (
        {x.strip() for x in exclude_langs.split(",")} if exclude_langs else None
    )

    async with aiohttp.ClientSession() as session:
        s = Stats(
            user,
            access_token,
            session,
            exclude_repos=excluded_repos,
            exclude_langs=excluded_langs,
        )
        await asyncio.gather(generate_overview(s), generate_languages(s))
