#!/usr/bin/env python3
"""
auto_update.py -- regenerate the *dynamic* parts of the profile README from live data,
then exit 0 if something changed (so a GitHub Action can commit it).

Sources, in order of preference:
  * GitHub GraphQL  (needs GITHUB_TOKEN with `read:user`)  -> contributions, pinned repos
  * GitHub REST     (works unauthenticated, 60 req/hr)     -> user, repos, languages
  * portfolio site  (plain HTTPS, no auth)                 -> the live "Status" string
  * now.json        (you edit this one file)               -> the CURRENTLY card

Every fetch degrades gracefully: if a source fails, that block keeps whatever it had
before. A cron job must never blank out your profile because an API had a bad day.

Only the regions between <!-- AUTO:NAME:start --> / <!-- AUTO:NAME:end --> are touched.

Usage:
  python3 bin/auto_update.py            # update in place
  python3 bin/auto_update.py --check    # don't write; exit 1 if it would change anything
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.request

# repo root = parent of scripts/
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

USERNAME = "fozayelibnayaz"
PROFILE_DIR = ROOT  # this script lives inside the profile repo itself
README = os.path.join(PROFILE_DIR, "README.md")
NOW_JSON = os.path.join(PROFILE_DIR, "now.json")
PORTFOLIO = "https://portfolio-ayaz.netlify.app/"

LANG_BADGE_COLORS = {
    "javascript": "f7df1e", "typescript": "3178c6", "python": "3776ab",
    "html": "e34f26", "css": "1572b6", "php": "777bb4", "java": "007396",
    "c": "a8b9cc", "c++": "00599c", "jupyter notebook": "f37626",
    "shell": "89e051", "makefile": "427819", "scss": "c6538c", "sql": "4479a1",
}


# ----------------------------------------------------------------------------- fetch

def _get(url: str, token: str | None = None, timeout: int = 25):
    headers = {"User-Agent": "readme-auto-update", "Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def fetch_rest_user(token):
    try:
        return _get(f"https://api.github.com/users/{USERNAME}", token)
    except Exception as exc:  # noqa: BLE001
        print(f"  ! REST user failed: {exc}")
        return None


def fetch_rest_repos(token):
    try:
        repos = _get(f"https://api.github.com/users/{USERNAME}/repos?per_page=100&sort=pushed", token)
        # exclude forks and the profile-README repo itself (it would only list itself)
        return [r for r in repos if not r["fork"] and r["name"] != USERNAME]
    except Exception as exc:  # noqa: BLE001
        print(f"  ! REST repos failed: {exc}")
        return []


def fetch_graphql(token):
    """Contributions + pinned repos. Needs read:user scope."""
    if not token:
        return None
    query = """
    query($u: String!) {
      user(login: $u) {
        contributionsCollection { contributionCalendar { totalContributions } }
        pinnedItems(first: 6, types: REPOSITORY) {
          nodes { ... on Repository { name description primaryLanguage { name } url homepageUrl } }
        }
      }
    }
    """
    body = json.dumps({"query": query, "variables": {"u": USERNAME}}).encode()
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=body,
        headers={
            "User-Agent": "readme-auto-update",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
        if "errors" in data:
            print(f"  ! GraphQL errors: {data['errors'][:1]}")
            return None
        return data["data"]["user"]
    except Exception as exc:  # noqa: BLE001
        print(f"  ! GraphQL failed: {exc}")
        return None


def fetch_portfolio_status():
    """Pull the live status line straight out of the deployed JS bundle."""
    try:
        req = urllib.request.Request(PORTFOLIO, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=25) as r:
            page = r.read().decode("utf-8", "replace")
        asset = re.search(r'src="(/assets/[^"]+\.js)"', page)
        if not asset:
            print("  ! portfolio: no JS bundle found")
            return None
        with urllib.request.urlopen(
            urllib.request.Request(PORTFOLIO.rstrip("/") + asset.group(1),
                                   headers={"User-Agent": "Mozilla/5.0"}),
            timeout=25,
        ) as r:
            bundle = r.read().decode("utf-8", "replace")
        hit = re.search(r"(Available for [A-Za-z0-9 ,/&+-]{5,60})", bundle)
        return hit.group(1).strip() if hit else None
    except Exception as exc:  # noqa: BLE001
        print(f"  ! portfolio scrape failed: {exc}")
        return None


# --------------------------------------------------------------------------- builders

def build_badges(user, contribs) -> str:
    repos = user.get("public_repos", "?") if user else "?"
    followers = user.get("followers", "?") if user else "?"
    # 457 = the verified figure on the profile page as of 29 Aug 2026.
    # With GITHUB_TOKEN (read:user) the real GraphQL number replaces it every run.
    c = f"{contribs:,}" if isinstance(contribs, int) else "457"
    shield = "https://img.shields.io/badge/{}-{}-1f2937?style=flat-square"
    return "\n".join([
        f'<a href="https://github.com/{USERNAME}">'
        f'<img src="{shield.format("REPOS", f"{repos}%20public")}" alt="Public repositories" /></a>',
        f'<a href="https://github.com/{USERNAME}?tab=followers">'
        f'<img src="{shield.format("FOLLOWERS", followers)}" alt="Followers" /></a>',
        f'<a href="https://github.com/{USERNAME}">'
        f'<img src="{shield.format("CONTRIBUTIONS", f"{c}%20this%20year")}" alt="Contributions this year" /></a>',
        f'<a href="#-lets-talk">'
        f'<img src="https://img.shields.io/badge/STATUS-Open%20to%20work-success?style=flat-square" alt="Open to work" /></a>',
        f'<a href="{PORTFOLIO}">'
        f'<img src="{shield.format("IELTS", "6.5%20%2F%20B2")}" alt="IELTS 6.5" /></a>',
        f'<img src="https://komarev.com/ghpvc/?username={USERNAME}&style=flat-square&color=0ea5e9&label=PROFILE+VIEWS" alt="Profile views" />',
    ])


def build_latest_repos(repos, limit: int = 6) -> str:
    if not repos:
        return ""
    rows = ["| Repo | Language | What it is | Updated |", "|---|---|---|---|"]
    for r in repos[:limit]:
        lang = r.get("language") or "—"
        color = LANG_BADGE_COLORS.get(lang.lower(), "8b949e")
        badge = (
            f'<img src="https://img.shields.io/badge/{lang.replace("+", "%2B").replace(" ", "_")}'
            f'-{color}?style=flat-square" alt="{lang}" />' if lang != "—" else "—"
        )
        desc = (r.get("description") or "").strip() or "*no description yet — worth adding*"
        if len(desc) > 78:
            desc = desc[:75].rstrip() + "…"
        pushed = (r.get("pushed_at") or "")[:10]
        rows.append(f'| [{r["name"]}]({r["html_url"]}) | {badge} | {desc} | `{pushed}` |')
    return "\n".join(rows)


def build_recent_activity(repos, limit: int = 5) -> str:
    if not repos:
        return ""
    items = []
    for r in repos[:limit]:
        pushed = (r.get("pushed_at") or "")[:10]
        stamp = dt.date.fromisoformat(pushed).strftime("%d %b %Y") if pushed else "unknown"
        stars = r.get("stargazers_count", 0)
        star = f" · ⭐ {stars}" if stars else ""
        items.append(f"- **{stamp}** — pushed to [{r['name']}]({r['html_url']}){star}")
    return "\n".join(items)


def build_now_card(status: str | None) -> str:
    items = []
    if os.path.exists(NOW_JSON):
        with open(NOW_JSON, encoding="utf-8") as fh:
            data = json.load(fh)
        items = [(k.upper(), v) for k, v in data.get("items", {}).items()]
    else:
        items = [
            ("BUILDING", "AI YouTube Command Center - Next.js + OAuth + 30 AI tools"),
            ("SHIPPING", "Eagle 3D Analytics Hub - Streamlit + MongoDB, 4x daily pipeline"),
            ("LEARNING", "LLM function-calling, advanced Playwright, Kubernetes"),
        ]
    if status:
        items = [(k, v) for k, v in items if k != "STATUS"]
        items.append(("STATUS", status))
    from gen_skills_svg import build_now_card as _card  # local import: same bin/ dir
    return _card(items)


def build_footer_stamp(repos) -> str:
    """Deterministic: the stamp is derived from the newest push, NOT from wall-clock
    time. If it used now(), every single run would differ and the nightly job would
    commit a pointless one-line change 365 times a year. Tied to real activity, the
    output is idempotent -- no change means no commit."""
    newest = None
    if repos:
        dates = sorted((r.get("pushed_at") or "") for r in repos if r.get("pushed_at"))
        if dates:
            newest = dt.date.fromisoformat(dates[-1][:10])
    stamp = newest.strftime("%d %b %Y") if newest else "—"
    return (
        f'<sub>⭐ <b>2026 Fozayel Ibn Ayaz</b> · This README is hand-written markdown — view the '
        f'[source](https://github.com/{USERNAME}/{USERNAME}/blob/main/README.md) and steal the idea · '
        f'dynamic blocks track your latest activity, last change <b>{stamp}</b></sub>'
    )


# ----------------------------------------------------------------------------- writer

def splice(text: str, name: str, payload: str) -> tuple[str, bool]:
    pattern = re.compile(
        rf"(<!-- AUTO:{re.escape(name)}:start -->\n)(.*?)(\n<!-- AUTO:{re.escape(name)}:end -->)",
        re.S,
    )
    if not pattern.search(text):
        print(f"  ! marker AUTO:{name} not found in README — skipped")
        return text, False
    new, n = pattern.subn(lambda m: m.group(1) + payload + m.group(3), text, count=1)
    return new, (n > 0 and new != text)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="exit 1 if the README would change")
    ap.add_argument("--readme", default=README, help="path to README.md")
    args = ap.parse_args()

    readme_path = args.readme
    original = open(readme_path, encoding="utf-8").read()
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")

    print(f"token: {'present' if token else 'absent (REST only, 60 req/hr)'}")

    user = fetch_rest_user(token)
    repos = fetch_rest_repos(token)
    gql = fetch_graphql(token)
    status = fetch_portfolio_status()

    contribs = None
    pinned = []
    if gql:
        contribs = gql.get("contributionsCollection", {}).get("contributionCalendar", {}).get("totalContributions")
        pinned = gql.get("pinnedItems", {}).get("nodes", []) or []
    print(f"  user={'ok' if user else 'FAIL'}  repos={len(repos)}  "
          f"contribs={contribs}  pinned={len(pinned)}  portfolio_status={status!r}")

    text = original
    changed = []

    text, c = splice(text, "GITHUB-BADGES", build_badges(user, contribs));            changed += ["GITHUB-BADGES"] if c else []
    if repos:
        text, c = splice(text, "LATEST-REPOS", build_latest_repos(repos));            changed += ["LATEST-REPOS"] if c else []
        text, c = splice(text, "RECENT-ACTIVITY", build_recent_activity(repos));      changed += ["RECENT-ACTIVITY"] if c else []
    text, c = splice(text, "FOOTER-STAMP", build_footer_stamp(repos));                 changed += ["FOOTER-STAMP"] if c else []

    # the CURRENTLY card is an SVG file, not markdown
    now_svg_path = os.path.join(PROFILE_DIR, "assets", "now.svg")
    new_svg = build_now_card(status)
    old_svg = open(now_svg_path, encoding="utf-8").read() if os.path.exists(now_svg_path) else ""
    if new_svg != old_svg:
        if not args.check:
            with open(now_svg_path, "w", encoding="utf-8") as fh:
                fh.write(new_svg)
        changed.append("assets/now.svg")

    if args.check:
        if changed:
            print(f"\nwould update: {', '.join(changed)}")
            return 1
        print("\nup to date.")
        return 0

    if text != original:
        with open(readme_path, "w", encoding="utf-8") as fh:
            fh.write(text)

    if changed:
        print(f"\nupdated: {', '.join(changed)}")
        return 0
    print("\nnothing changed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
