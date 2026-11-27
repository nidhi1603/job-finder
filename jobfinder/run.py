"""Hourly run: read job feeds, apply rules, score, email new matches, save state.

    python -m jobfinder.run            # normal hourly run
    python -m jobfinder.run --all      # check every board this run
    python -m jobfinder.run --dry-run  # don't email or save state; write out/digest-*.html
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import time
from collections import Counter
from pathlib import Path

import httpx

from . import emailer
from .bigtech import BIGTECH_BOARDS
from .filters import annotate, detail_rules, prefilter
from .funding import funded_boards
from .models import Board, Job
from .scoring import load_profile, order_jobs, score_crowd, score_fit
from .sources import fetch_detail, list_board, make_client, make_limits
from .state import State
from .text import now_utc, parse_iso
from .urls import match_id, parse_ats_url

ROOT = Path(__file__).resolve().parent.parent
BOARDS = ROOT / "data" / "boards.json"
SIMPLIFY_URL = "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/.github/scripts/listings.json"
BROAD_BUCKETS = 4          # each broad-sweep board is checked every 4th hour
MAX_EMAIL_JOBS = 150


def load_boards() -> list[Board]:
    return [Board(**b) for b in json.loads(BOARDS.read_text())]


EVERY_RUN = {"newgrad", "bigtech", "funded"}   # the broad sweep is split across 4 hours
_TIER_RANK = {"funded": 0, "bigtech": 1, "newgrad": 2, "broad": 3}


def merge_boards(boards: list[Board]) -> list[Board]:
    """One entry per board; a board listed in several places keeps its highest-priority tier."""
    best: dict[tuple[str, str], Board] = {}
    for b in boards:
        k = (b.ats, b.token)
        if k not in best or _TIER_RANK.get(b.tier, 9) < _TIER_RANK.get(best[k].tier, 9):
            best[k] = Board(b.ats, b.token, b.name or (best[k].name if k in best else ""), b.tier)
    return list(best.values())


def bucket(board: Board) -> int:
    return int(hashlib.md5(f"{board.ats}:{board.token}".encode()).hexdigest(), 16) % BROAD_BUCKETS


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
    catch_up = state.is_empty()
    if args.all or catch_up:
        selected = boards
    else:
        b_now = now.hour % BROAD_BUCKETS
        selected = [b for b in boards if b.tier in EVERY_RUN or bucket(b) == b_now]
    if args.limit:
        selected = selected[: args.limit]
    last_run = parse_iso(state.meta.get("last_run"))
    # Workday only shows "Posted N Days Ago"; read back far enough to cover the gap since the last run.
    window_days = 15 if (catch_up or args.all or not last_run) else min(15, int((now - last_run).total_seconds() // 86400) + 2)
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
                if job.key in state or job.key in candidates:
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
    unique, seen_listing = [], set()
    for j in passed:              # same company + title + location posted under several req IDs
        listing = (j.company.lower(), j.title.lower().strip(), j.location.lower().strip())
        if listing not in seen_listing:
            seen_listing.add(listing)
            unique.append(j)
    shown, extra = unique[:MAX_EMAIL_JOBS], max(0, len(unique) - MAX_EMAIL_JOBS)
    stats["passed"] = len(passed)

    email_ready = all(os.environ.get(k) for k in ("EMAIL_FROM", "EMAIL_TO", "GMAIL_APP_PASSWORD")) and not args.dry_run
    sent = False
    if shown:
        subject, html_body, text_body = emailer.render(shown, now, extra, catch_up)
        if not email_ready:
            os.environ.pop("GMAIL_APP_PASSWORD", None)
        sent = emailer.send(subject, html_body, text_body, now)
        print(("emailed: " if sent else "not emailed: ") + subject)
    if sent:
        for job in passed:
            state.mark(job, "e", now)
    if email_ready:
        state.save(now)
    else:
        print("state not saved (dry run or email not set up), so the first real run still sends the full catch-up")

    print(f"boards checked: {len(selected)} ({'all' if args.all or catch_up else 'hourly slice'}) in {time.time() - t0:.0f}s")
    for k, v in sorted(stats.items()):
        print(f"  {k}: {v}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--all", action="store_true", help="check every board this run")
    p.add_argument("--dry-run", action="store_true", help="no email, no state save")
    p.add_argument("--limit", type=int, default=0, help="only the first N boards (testing)")
    p.add_argument("--concurrency", type=int, default=32)
    args = p.parse_args()
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
