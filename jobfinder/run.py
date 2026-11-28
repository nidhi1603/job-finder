"""Daily run (overnight): read every job board, apply rules, score, add new matches to your tracker sheet, send
one morning email, save state.

    python -m jobfinder.run                      # the daily run
    python -m jobfinder.run --skip-if-ran-today  # what the backup schedules use: do nothing if today's run happened
    python -m jobfinder.run --all                # read 15 days back instead of since the last run
    python -m jobfinder.run --backfill           # load the last 15 days into the tracker sheet, no email
    python -m jobfinder.run --dry-run            # no email, no sheet, no state save; writes out/digest-*.html

With the tracker sheet set up (SHEET_URL + SHEET_SECRET), new matches go to the sheet and the email lists the strong
ones in full. Without it (or if the sheet can't be reached), the email lists every new match.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import time
from collections import Counter
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from . import emailer, sheet
from .bigtech import BIGTECH_BOARDS
from .filters import annotate, detail_rules, prefilter
from .funding import funded_boards
from .models import Board, Job
from .scoring import fit_band, load_profile, norm_title, order_jobs, score_crowd, score_fit
from .sources import HTTP_STATS, fetch_detail, list_board, make_client, make_limits
from .state import State
from .text import now_utc, parse_iso
from .urls import match_id, parse_ats_url

ROOT = Path(__file__).resolve().parent.parent
BOARDS = ROOT / "data" / "boards.json"
SIMPLIFY_URL = "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/.github/scripts/listings.json"
MAX_EMAIL_JOBS = 150       # full-digest mode (no tracker sheet)
MAX_PICKS = 40             # jobs shown in full in the daily email when the sheet holds the rest


def load_boards() -> list[Board]:
    return [Board(**b) for b in json.loads(BOARDS.read_text())]


_TIER_RANK = {"funded": 0, "bigtech": 1, "newgrad": 2, "broad": 3}


def merge_boards(boards: list[Board]) -> list[Board]:
    """One entry per board; a board listed in several places keeps its highest-priority tier."""
    best: dict[tuple[str, str], Board] = {}
    for b in boards:
        k = (b.ats, b.token)
        if k not in best or _TIER_RANK.get(b.tier, 9) < _TIER_RANK.get(best[k].tier, 9):
            best[k] = Board(b.ats, b.token, b.name or (best[k].name if k in best else ""), b.tier)
    return list(best.values())


async def simplify_match_ids(client: httpx.AsyncClient) -> set[str]:
    """Job IDs currently on the SimplifyJobs new-grad list (a crowding signal)."""
    try:
        r = await client.get(SIMPLIFY_URL, timeout=60)
        listings = r.json()
    except Exception as e:
        print(f"warning: SimplifyJobs list unavailable ({e}); crowding ignores it this run")
        return set()
    ids = set()
    for x in listings:
        parsed = parse_ats_url(x.get("url") or "")
        if parsed:
            mid = match_id(*parsed)
            if mid:
                ids.add(mid)
    return ids


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]{3,}", (text or "").lower()))


def merge_cities(jobs: list[Job]) -> list[Job]:
    """One entry for the same job posted in several cities: same company and title, and the same location or
    a near-identical description. Different roles that share a title (an agency's clients, say) stay separate."""
    out: list[Job] = []
    groups: dict[tuple[str, str], list[tuple[Job, set[str], set[str]]]] = {}
    for j in jobs:
        k = (j.company.lower().strip(), norm_title(j.title))
        words, loc = _words(j.text), j.location.lower().strip()
        for first, first_words, locs in groups.get(k, []):
            same_text = (not words and not first_words) or (
                words and first_words and len(words & first_words) / len(words | first_words) >= 0.8)
            if loc in locs or same_text:
                if loc and loc not in locs:
                    locs.add(loc)
                    first.location = f"{first.location} | {j.location}"
                break
        else:
            groups.setdefault(k, []).append((j, words, {loc}))
            out.append(j)
    return out


def is_pick(job: Job) -> bool:
    """Shown in full in the daily email: a strong fit, or a good fit at a recently funded startup or aimed at new grads."""
    band = fit_band(job)
    return band == 0 or (band == 1 and bool(job.funding or job.boosts))


def local_today(now) -> str:
    return now.astimezone(ZoneInfo(os.environ.get("LOCAL_TZ") or "America/New_York")).strftime("%Y-%m-%d")


def send_daily_email(unique: list[Job], sheet_url: str, state: State, now) -> bool:
    """One email per run: counts, the picks in full, and application stats from the sheet."""
    since = state.meta.get("last_daily_at") or (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    info = sheet.summary(since) or {}
    picks = [j for j in unique if is_pick(j)][:MAX_PICKS] or unique[:10]
    subject, html_body, text_body = emailer.render_daily(unique, picks, info, sheet_url or info.get("url", ""), now)
    sent = emailer.send(subject, html_body, text_body, now)
    print(("emailed: " if sent else "not emailed: ") + subject)
    return sent


async def run(args) -> None:
    t0 = time.time()
    now = now_utc()
    if os.environ.get("GITHUB_ACTIONS") and not all(os.environ.get(k) for k in ("EMAIL_FROM", "EMAIL_TO", "GMAIL_APP_PASSWORD")):
        print("Email secrets (EMAIL_FROM, EMAIL_TO, GMAIL_APP_PASSWORD) aren't set yet, so this run is skipped. See README → Setup.")
        return
    profile = load_profile()
    min_fit = int(os.environ.get("MIN_FIT") or 0)
    funded, funding_labels = funded_boards()
    boards = merge_boards(funded + BIGTECH_BOARDS + load_boards())
    state = State.load()
    today = local_today(now)
    if args.skip_if_ran_today and state.meta.get("last_daily") == today:
        print(f"Today's run ({today}) already happened; this backup run does nothing.")
        return
    catch_up = state.is_empty()
    full = args.all or catch_up or args.backfill
    selected = boards                       # once a day, so every board is read every run
    if args.limit:
        selected = selected[: args.limit]
    last_run = parse_iso(state.meta.get("last_run"))
    # Workday only shows "Posted N Days Ago"; read back far enough to cover the gap since the last run.
    window_days = 15 if (full or not last_run) else min(15, int((now - last_run).total_seconds() // 86400) + 2)
    stats: Counter = Counter()

    async with make_client() as client:
        limits = make_limits(args.concurrency)
        simplify_task = asyncio.create_task(simplify_match_ids(client))
        lists = await asyncio.gather(*(list_board(client, b, limits, window_days) for b in selected))
        names = {(b.ats, b.token): b.name for b in selected if b.name}

        candidates: dict[str, Job] = {}
        for job_list in lists:
            stats["boards_with_jobs"] += bool(job_list)
            for job in job_list:
                stats["jobs_listed"] += 1
                if (job.key in state and not args.backfill) or job.key in candidates:
                    stats["already_seen"] += 1
                    continue
                reason = prefilter(job, now)
                if reason:
                    stats["drop:" + reason] += 1
                    continue
                job.company = names.get((job.ats, job.board), job.company) or job.company
                candidates[job.key] = job

        need = [j for j in candidates.values() if j.needs_detail]
        await asyncio.gather(*(fetch_detail(client, j, limits) for j in need))
        simplify_ids = await simplify_task

    passed: list[Job] = []
    for job in candidates.values():
        if job.needs_detail and not job.text:
            stats["detail-unavailable"] += 1
            continue          # retry next run
        if prefilter(job, now):          # detail may have refined date/location
            state.mark(job, "f:after-detail", now)
            stats["drop:after-detail"] += 1
            continue
        reason = detail_rules(job)
        if reason:
            state.mark(job, "f:" + reason, now)
            stats["drop:" + reason] += 1
            continue
        annotate(job)
        job.funding = funding_labels.get((job.ats, job.board), "")
        score_fit(job, profile)
        mid = match_id(job.ats, job.board, job.job_id)
        score_crowd(job, now, on_simplify=bool(mid and mid in simplify_ids), reposted=state.was_reposted(job))
        if job.fit is not None and job.fit < min_fit:
            state.mark(job, "l", now)
            stats["below-fit-floor"] += 1
            continue
        passed.append(job)

    passed = order_jobs(passed)
    unique = merge_cities(passed)
    stats["passed"] = len(passed)
    stats["after-merging-cities"] = len(unique)

    email_ready = all(os.environ.get(k) for k in ("EMAIL_FROM", "EMAIL_TO", "GMAIL_APP_PASSWORD")) and not args.dry_run
    if not email_ready:
        os.environ.pop("GMAIL_APP_PASSWORD", None)        # emailer then writes out/*.html instead of sending
    use_sheet = sheet.configured() and not args.dry_run
    delivered = False

    if use_sheet:
        res = sheet.add_jobs(unique)
        if res is not None:
            delivered = True
            print(f"tracker: {res['added']} new rows")
            for j in unique:
                if res["annotations"].get(j.key):
                    j.flags.insert(0, res["annotations"][j.key])
            if not args.backfill:
                send_daily_email(unique, res.get("url", ""), state, now)
        else:
            print("tracker sheet failed, so this run emails the full list instead (nothing is lost)")

    if not delivered and unique and not args.backfill:
        shown, extra = unique[:MAX_EMAIL_JOBS], max(0, len(unique) - MAX_EMAIL_JOBS)
        subject, html_body, text_body = emailer.render(shown, now, extra, catch_up)
        delivered = emailer.send(subject, html_body, text_body, now)
        print(("emailed: " if delivered else "not emailed: ") + subject)

    if not args.dry_run and (delivered or not unique):
        state.meta["last_daily"] = today
        state.meta["last_daily_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    if delivered:
        for job in passed:
            state.mark(job, "s" if use_sheet else "e", now)
    if (email_ready or use_sheet) and not args.dry_run:
        state.save(now)
    else:
        print("state not saved (dry run, or neither email nor the tracker sheet is set up)")

    print(f"boards checked: {len(selected)} (reading {window_days} days back) in {time.time() - t0:.0f}s")
    if HTTP_STATS:
        print("rate limiting (429 answers / boards given up on), by host group:")
        for k, v in sorted(HTTP_STATS.items(), key=lambda kv: -kv[1])[:15]:
            print(f"  {k}: {v}")
    for k, v in sorted(stats.items()):
        print(f"  {k}: {v}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--all", action="store_true", help="read 15 days back instead of since the last run")
    p.add_argument("--skip-if-ran-today", action="store_true", help="do nothing if today's run already happened")
    p.add_argument("--backfill", action="store_true", help="load the last 15 days into the tracker sheet, no email")
    p.add_argument("--dry-run", action="store_true", help="no email, no sheet, no state save")
    p.add_argument("--limit", type=int, default=0, help="only the first N boards (testing)")
    p.add_argument("--concurrency", type=int, default=32)
    args = p.parse_args()
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
