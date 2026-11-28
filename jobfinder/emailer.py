"""Render emails and send them through Gmail SMTP (or write them to out/ when email isn't set up).

Two kinds: the daily email (with the tracker sheet: counts plus the best new jobs in full) and the full digest
(every new match, used when the sheet isn't set up or can't be reached).
"""
from __future__ import annotations

import html
import os
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

from collections import Counter

from .models import Job
from .scoring import BANDS, crowd_label, fit_band

ROOT = Path(__file__).resolve().parent.parent
BAND_RULES = ["70%+ fit, 4+ skills", "50%+ fit, 3+ skills", "below 50%, or too few skills listed to tell"]


def _ago(job: Job, now: datetime) -> str:
    if not job.posted_at:
        return "posting date unknown"
    hours = max(0, (now - job.posted_at).total_seconds() / 3600)
    approx = "" if job.posted_exact else "~"
    if hours < 48:
        return f"posted {approx}{int(hours)}h ago"
    return f"posted {approx}{int(hours // 24)}d ago"


def _plural(n: int, word: str, many: str = "") -> str:
    return f"{n} {word if n == 1 else (many or word + 's')}"


def _button(url: str, label: str) -> str:
    return (f'<p style="margin:16px 0"><a href="{html.escape(url)}" style="background:#1a56db;color:#fff;padding:9px 16px;'
            f'border-radius:6px;text-decoration:none;font-weight:600">{html.escape(label)}</a></p>') if url else ""


def render(jobs: list[Job], now: datetime, extra: int, catch_up: bool, sheet_url: str = "",
           subject: str = "", intro: str = "") -> tuple[str, str, str]:
    """Every job in `jobs` in full, grouped (funded startups, then strong / good / other fit, newest first)."""
    top = jobs[0]
    if not subject:
        label = "catch-up: " if catch_up else ""
        subject = f"Job Finder {label}{len(jobs) + extra} new match{'es' if len(jobs) + extra != 1 else ''} · top: {top.title} @ {top.company}"
        intro = (f"{len(jobs) + extra} new job{'s' if len(jobs) + extra != 1 else ''} that passed your rules. Recently funded "
                 f"startups come first, then the rest grouped by fit (strong, good, other) with the most recently posted first "
                 f"inside each group.")
    rows_html, rows_txt = [], []
    group_of = lambda j: "funded" if j.funding else fit_band(j)   # noqa: E731
    counts = Counter(group_of(j) for j in jobs)
    current = None
    for j in jobs:
        group = group_of(j)
        if group != current:
            current = group
            n = counts[group]
            if group == "funded":
                label = f"Recently funded startups (raised in the last 6 months) · {n} job{'s' if n != 1 else ''}, best fit then newest"
            else:
                label = f"{BANDS[group]} ({BAND_RULES[group]}) · {n} job{'s' if n != 1 else ''}, newest first"
            rows_html.append(f'<tr><td style="padding:18px 0 4px;font-size:13px;font-weight:700;color:#111;'
                             f'text-transform:uppercase;letter-spacing:.04em;border-bottom:2px solid #111">{html.escape(label)}</td></tr>')
            rows_txt.append(f"\n== {label} ==")
        fit = f"{j.fit}% ({len(j.matched)}/{j.skills_total} skills)" if j.fit is not None else "? (no skills listed)"
        crowd = f"{crowd_label(j.crowd)} crowding" + (f" ({', '.join(j.crowd_reasons)})" if j.crowd_reasons else "")
        badges = "".join(
            f'<span style="background:{"#fde2e1" if f.startswith("No sponsor") else "#e8eefc"};border-radius:4px;'
            f'padding:1px 6px;margin-right:4px;font-size:12px">{html.escape(f)}</span>' for f in j.flags)
        boost = (f'<span style="background:#e3f6e8;border-radius:4px;padding:1px 6px;margin-right:4px;font-size:12px">'
                 f'★ {html.escape(j.boosts[0])}</span>') if j.boosts else ""
        if j.funding:
            boost = (f'<span style="background:#fff3cd;border-radius:4px;padding:1px 6px;margin-right:4px;font-size:12px">'
                     f'💰 {html.escape(j.funding)}</span>') + boost
        yoe = f" · asks {j.min_yoe}+ yrs" if j.min_yoe else ""
        rows_html.append(f"""
<tr><td style="padding:12px 0;border-bottom:1px solid #eee">
  <div style="font-size:16px;font-weight:600"><a href="{html.escape(j.url)}" style="color:#1a56db;text-decoration:none">{html.escape(j.title)}</a></div>
  <div style="color:#333;margin:2px 0">{html.escape(j.company)} · {html.escape(j.location[:120] or 'location n/a')}</div>
  <div style="color:#555;font-size:13px;margin:2px 0"><b>Fit {fit}</b> · {_ago(j, now)} · {html.escape(crowd)}{yoe}</div>
  <div style="margin:4px 0">{boost}{badges}</div>
  <div style="color:#555;font-size:12px">✓ {html.escape(', '.join(j.matched) or '—')}</div>
  <div style="color:#999;font-size:12px">✗ {html.escape(', '.join(j.missing[:10]) or '—')}</div>
</td></tr>""")
        rows_txt.append(f"- {j.title} @ {j.company} ({j.location[:60]}) | fit {fit} | {_ago(j, now)} | {crowd}"
                        f"{' | ' + j.funding if j.funding else ''}"
                        f"{' | ' + '; '.join(j.flags) if j.flags else ''}\n  {j.url}")
    more = f"<p style='color:#777'>+{extra} more lower-ranked matches not shown.</p>" if extra else ""
    html_body = f"""<html><body style="font-family:-apple-system,Segoe UI,Arial,sans-serif;max-width:720px;margin:auto">
<p style="color:#555">{html.escape(intro)} Fit = share of the posting's skills found on your resume (required skills count
double). Crowding is an estimate.</p>{_button(sheet_url, "Open your tracker")}
<table style="width:100%;border-collapse:collapse">{''.join(rows_html)}</table>{more}{_button(sheet_url, "Open your tracker")}
<p style="color:#aaa;font-size:11px">Sent by your job-finder · {now.strftime('%Y-%m-%d %H:%M UTC')}</p></body></html>"""
    text_body = intro + "\n" + "\n".join(rows_txt) + (f"\n+{extra} more not shown" if extra else "") + (
        f"\n\nYour tracker: {sheet_url}" if sheet_url else "")
    return subject, html_body, text_body


def render_daily(new_jobs: list[Job], picks: list[Job], info: dict, sheet_url: str, now: datetime) -> tuple[str, str, str]:
    """The morning email: what arrived since yesterday, the best of it in full, and your application counts."""
    from .sheet import group_of
    groups = Counter(group_of(j) for j in new_jobs)
    strong = sum(1 for j in new_jobs if fit_band(j) == 0)
    week, total = info.get("applied_week", 0), info.get("applied_total", 0)
    applied = f"You applied to {week} in the last 7 days ({total} in all)."
    if not new_jobs:
        subject = f"Today's jobs: nothing new · {week} applied this week"
        text = f"No new matches since yesterday. {applied}"
        html_body = f"""<html><body style="font-family:-apple-system,Segoe UI,Arial,sans-serif;max-width:720px;margin:auto">
<p style="color:#333">{html.escape(text)}</p>{_button(sheet_url, "Open your tracker")}
<p style="color:#aaa;font-size:11px">Sent by your job-finder · {now.strftime('%Y-%m-%d %H:%M UTC')}</p></body></html>"""
        return subject, html_body, text + (f"\n\nYour tracker: {sheet_url}" if sheet_url else "")
    parts = ", ".join(f"{groups[g]} {g.lower()}" for g in ("Funded", "Strong", "Good", "Other") if groups[g])
    subject = (f"Today's jobs: {_plural(len(new_jobs), 'new match', 'new matches')}" + (f", {strong} strong" if strong else "")
               + f" · top: {picks[0].title} @ {picks[0].company}")
    shown = ("Below are the strong matches, plus good fits at recently funded startups or aimed at new grads."
             if any(fit_band(j) == 0 or j.funding or j.boosts for j in picks) else
             "No strong matches today, so here are the best of the rest.")
    rest = len(new_jobs) - len(picks)
    intro = (f"{_plural(len(new_jobs), 'new job')} since yesterday ({parts}). {applied} {shown}"
             + (f" The other {_plural(rest, 'job')} {'is' if rest == 1 else 'are'} in your tracker." if rest > 0 else "")
             + " Mark the ones you apply to as Applied.")
    return render(picks, now, 0, False, sheet_url=sheet_url, subject=subject, intro=intro)
