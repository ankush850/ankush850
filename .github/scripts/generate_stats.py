#!/usr/bin/env python3
"""Self-hosted GitHub profile stats generator.

Queries only public GitHub REST endpoints (auth optional, via the workflow's
built-in GITHUB_TOKEN - no API keys / PATs required) and renders dark + light
SVG cards for the profile README.

Outputs (into --outdir):
  stats-{dark,light}.svg       Stars, forks, repos, followers, contributions, streak
  langs-{dark,light}.svg       Top languages bar (bytes across public repos)
  activity-{dark,light}.svg    Last 4 weeks of contributions (calendar grid)
  trophies-{dark,light}.svg    Milestone trophies computed from live stats
"""

import argparse
import datetime
import json
import sys
import urllib.request

API = "https://api.github.com"
CONTRIB_CAP = 6  # max contributions per day shown in activity grid


# ---------------------------------------------------------------- data layer
def gh_get(path, token):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "profile-stats-workflow",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(API + path, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # rate limit / network - caller degrades gracefully
        print(f"warn: GET {path} failed: {exc}", file=sys.stderr)
        return None


def gather(user, token):
    data = {"user": {}, "repos": [], "events": []}

    me = gh_get(f"/users/{user}", token)
    if me is None:
        raise SystemExit(f"fatal: could not fetch user {user}")
    data["user"] = me

    for page in range(1, 5):  # up to 400 public repos
        batch = gh_get(f"/users/{user}/repos?per_page=100&page={page}&sort=updated", token)
        if not batch:
            break
        data["repos"].extend(batch)
        if len(batch) < 100:
            break

    for page in range(1, 4):  # events API keeps ~last 90 days / 300 events
        batch = gh_get(f"/users/{user}/events?per_page=100&page={page}", token)
        if not batch:
            break
        data["events"].extend(batch)

    return data


def day_counts(events):
    """contributions per calendar day from public event types."""
    weights = {
        "PushEvent": 1,
        "PullRequestEvent": 2,
        "IssuesEvent": 2,
        "IssueCommentEvent": 1,
        "CreateEvent": 1,
        "PullRequestReviewEvent": 2,
        "ReleaseEvent": 3,
    }
    counts = {}
    for ev in events:
        w = weights.get(ev.get("type", ""), 0)
        if not w:
            continue
        day = (ev.get("created_at") or "")[:10]
        if day:
            counts[day] = counts.get(day, 0) + w
    return counts


def streaks(counts):
    """(current, longest) day streaks, oldest->newest."""
    if not counts:
        return 0, 0
    days = sorted(counts)
    longest = cur = 1
    for prev, day in zip(days, days[1:]):
        gap = (datetime.date.fromisoformat(day) - datetime.date.fromisoformat(prev)).days
        cur = cur + 1 if gap == 1 else 1
        longest = max(longest, cur)
    today = datetime.date.today()
    if datetime.date.fromisoformat(days[-1]) < today - datetime.timedelta(days=1):
        cur = 0  # streak broken
    return cur, longest


# ------------------------------------------------------------- rendering
def esc(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


THEMES = {
    "dark": {
        "bg_from": "#1a1b27", "bg_to": "#16161e", "fg": "#c0caf5", "muted": "#7aa2f7",
        "icon": "#bb9af7", "grid": "#2a2e44", "track": "#24283b",
    },
    "light": {
        "bg_from": "#ffffff", "bg_to": "#f6f8fa", "fg": "#24292f", "muted": "#0969da",
        "icon": "#8250df", "grid": "#d0d7de", "track": "#eaeef2",
    },
}

FONT = "font-family='Segoe UI,Ubuntu,Noto Sans,Helvetica,Arial,sans-serif'"

STAT_ICONS = {  # tiny 16x16 stroke-abstract glyphs, drawn by hand
    "stars": "M8 1.8l1.9 3.9 4.3.6-3.1 3 .7 4.3L8 11.6l-3.8 2 .7-4.3-3.1-3 4.3-.6z",
    "forks": "M4 2.5a1.5 1.5 0 110 3 1.5 1.5 0 010-3zm8 0a1.5 1.5 0 110 3 1.5 1.5 0 010-3zM4 5.5v2c0 1.5 1 2.5 2.5 2.5h3C11 10 12 9 12 7.5v-2M8 10v3.5",
    "repos": "M3 2.5h10v11H3zM5.5 5.5h5M5.5 8h5M5.5 10.5h3",
    "followers": "M8 8a2.6 2.6 0 100-5.2A2.6 2.6 0 008 8zm-5 5.5a5 5 0 0110 0",
    "contribs": "M8 2.5v11M2.5 8h11M4.4 4.4l7.2 7.2M11.6 4.4L4.4 11.6",
    "streak": "M8 14c3-2.5 4.5-5 4.5-7.5C12.5 3.5 8 1 8 1s-1 3-2.5 4.5S3.5 11 8 14z",
}


def svg_doc(width, height, theme):
    t = THEMES[theme]
    return (
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' "
        f"viewBox='0 0 {width} {height}' role='img'>"
        f"<defs><linearGradient id='g' x1='0' y1='0' x2='1' y2='1'>"
        f"<stop offset='0' stop-color='{t['bg_from']}'/><stop offset='1' stop-color='{t['bg_to']}'/>"
        f"</linearGradient></defs>"
        f"<rect width='{width}' height='{height}' rx='12' fill='url(#g)' stroke='{t['grid']}' stroke-width='1'/>"
    )


def text(x, y, size, fill, content, weight="normal", anchor="start"):
    return (f"<text x='{x}' y='{y}' font-size='{size}' fill='{fill}' font-weight='{weight}' "
            f"text-anchor='{anchor}' {FONT}>{esc(content)}</text>")


def icon(path, x, y, color):
    return (f"<svg x='{x}' y='{y}' width='16' height='16' viewBox='0 0 16 16'>"
            f"<path d='{path}' fill='none' stroke='{color}' stroke-width='1.3' "
            f"stroke-linecap='round' stroke-linejoin='round'/></svg>")


def render_stats(data, theme):
    t = THEMES[theme]
    u = data["user"]
    counts = day_counts(data["events"])
    cur, best = streaks(counts)
    stars = sum(r.get("stargazers_count", 0) for r in data["repos"])
    forks = sum(r.get("forks_count", 0) for r in data["repos"])
    stats = [
        ("stars", "Stars", stars),
        ("forks", "Forks", forks),
        ("repos", "Repositories", u.get("public_repos", 0)),
        ("followers", "Followers", u.get("followers", 0)),
        ("contribs", "Contributions*", sum(counts.values())),
        ("streak", "Streak", f"{cur}d (best {best}d)"),
    ]
    w, h = 460, 150
    out = [svg_doc(w, h, theme)]
    out.append(text(24, 34, 16, t["fg"], f"{u.get('login', '')} · Profile Stats", weight="bold"))
    for i, (key, label, val) in enumerate(stats):
        col, row = i % 3, i // 3
        x, y = 24 + col * 150, 62 + row * 46
        out.append(icon(STAT_ICONS[key], x, y - 12, t["icon"]))
        out.append(text(x + 22, y, 15, t["fg"], val, weight="bold"))
        out.append(text(x + 22, y + 16, 11, t["muted"], label))
    out.append(text(24, 143, 9, t["grid"], "*recent public events (API window)"))
    out.append("</svg>")
    return "".join(out)


LANG_COLORS = {
    "python": "#3572a5", "javascript": "#f1e05a", "typescript": "#3178c6",
    "html": "#e34c26", "css": "#663399", "jupyter notebook": "#da5b86",
    "java": "#b07219", "c++": "#f34b7d", "c": "#555555", "go": "#00add8",
    "rust": "#dea584", "shell": "#89e051", "vue": "#41b883", "kotlin": "#a97ee0",
}


def top_languages(data, token):
    totals = {}
    repos = [r for r in data["repos"] if not r.get("fork")]
    # Language info already ships on repo objects? No - fetch per repo, cap calls.
    for r in repos[:30]:
        langs = gh_get(f"/repos/{r['full_name']}/languages", token) or {}
        for lang, size in langs.items():
            totals[lang] = totals.get(lang, 0) + size
    if not totals:  # fall back to repo-list language field
        for r in repos:
            lang = r.get("language")
            if lang:
                totals[lang] = totals.get(lang, 0) + 1
    return sorted(totals.items(), key=lambda kv: -kv[1])[:6]


def render_langs(languages, theme):
    t = THEMES[theme]
    total = sum(v for _, v in languages) or 1
    w, h = 460, 60 + len(languages) * 26 + 20
    out = [svg_doc(w, h, theme)]
    out.append(text(24, 34, 16, t["fg"], "Top Languages", weight="bold"))
    for i, (lang, size) in enumerate(languages):
        y = 58 + i * 26
        pct = size / total * 100
        color = LANG_COLORS.get(lang.lower(), t["muted"])
        bar_w = max(4, pct / 100 * (w - 320))
        out.append(f"<rect x='150' y='{y - 10}' width='{w - 320}' height='10' rx='5' fill='{t['track']}'/>")
        out.append(f"<rect x='150' y='{y - 10}' width='{bar_w:.0f}' height='10' rx='5' fill='{color}'/>")
        out.append(text(24, y, 12, t["fg"], lang))
        out.append(text(w - 24, y, 12, t["muted"], f"{pct:.1f}%", anchor="end"))
    out.append("</svg>")
    return "".join(out)


def render_activity(data, theme):
    t = THEMES[theme]
    counts = day_counts(data["events"])
    today = datetime.date.today()
    start = today - datetime.timedelta(days=27)  # 4 weeks, Mon-aligned grid 7x4
    cols, rows = 28, 4
    cell = 14
    w, h = 40 + cols * cell, 96
    out = [svg_doc(w, h, theme)]
    out.append(text(20, 32, 16, t["fg"], "Activity · last 4 weeks", weight="bold"))
    for d in range(cols * rows):
        day = start + datetime.timedelta(days=d)
        n = counts.get(day.isoformat(), 0)
        if not n:
            fill, opacity = t["grid"], 0.4
        else:
            fill, opacity = t["muted"], min(0.25 + n / CONTRIB_CAP * 0.75, 1.0)
        x = 20 + (d % cols) * cell
        y = 46 + (d // cols) * cell
        out.append(f"<rect x='{x}' y='{y}' width='{cell - 3}' height='{cell - 3}' rx='2' "
                   f"fill='{fill}' fill-opacity='{opacity:.2f}'/>")
    out.append("</svg>")
    return "".join(out)


TROPHIES = [
    ("Stars", lambda s: s["stars"], [(1, "\u2605"), (10, "\u2605"), (50, "\u2605"), (100, "\u2605")]),
    ("Repos", lambda s: s["repos"], [(5, "\u2691"), (10, "\u2691"), (25, "\u2691"), (50, "\u2691")]),
    ("Followers", lambda s: s["followers"], [(5, "\u2666"), (10, "\u2666"), (25, "\u2666"), (50, "\u2666")]),
    ("Contribs", lambda s: s["contribs"], [(50, "\u2699"), (100, "\u2699"), (250, "\u2699"), (500, "\u2699")]),
]
TIER_COLORS = ["#d0d7de", "#f1e05a", "#c0c0c0", "#cd7f32"]


def render_trophies(stats, theme):
    t = THEMES[theme]
    w, h = 460, 130
    out = [svg_doc(w, h, theme)]
    out.append(text(24, 34, 16, t["fg"], "Trophies", weight="bold"))
    for i, (label, getter, tiers) in enumerate(TROPHIES):
        val = getter(stats)
        rank = sum(1 for thr, _ in tiers if val >= thr)
        x = 24 + i * 108
        glyph = tiers[rank - 1][1] if rank else "\u25cb"
        color = TIER_COLORS[rank - 1] if rank else t["grid"]
        out.append(f"<circle cx='{x + 22}' cy='72' r='22' fill='none' stroke='{color}' stroke-width='2.5'/>")
        out.append(text(x + 22, 79, 22, color, glyph, anchor="middle"))
        out.append(text(x + 22, 108, 11, t["fg"], label, anchor="middle"))
        out.append(text(x + 22, 122, 10, t["muted"], f"{val} · {rank}/4", anchor="middle"))
    out.append("</svg>")
    return "".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", required=True)
    ap.add_argument("--token", default="")
    ap.add_argument("--outdir", default="dist")
    args = ap.parse_args()

    data = gather(args.user, args.token)
    u = data["user"]
    stars = sum(r.get("stargazers_count", 0) for r in data["repos"])
    counts = day_counts(data["events"])
    stats = {
        "stars": stars,
        "repos": u.get("public_repos", 0),
        "followers": u.get("followers", 0),
        "contribs": sum(counts.values()),
    }
    languages = top_languages(data, args.token)

    import os
    os.makedirs(args.outdir, exist_ok=True)
    for theme in ("dark", "light"):
        files = {
            "stats": render_stats(data, theme),
            "langs": render_langs(languages, theme),
            "activity": render_activity(data, theme),
            "trophies": render_trophies(stats, theme),
        }
        for name, svg in files.items():
            path = os.path.join(args.outdir, f"{name}-{theme}.svg")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(svg)
            print("wrote", path)


if __name__ == "__main__":
    main()
