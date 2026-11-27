"""Render the digest and send it through Gmail SMTP (or write it to out/ when email isn't set up)."""
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
BAND_RULES = ["70%+ fit, 4+ skills", "50%+ fit", "below 50% or no skills listed"]


def _ago(job: Job, now: datetime) -> str:
    if not job.posted_at:
        return "posting date unknown"
    hours = max(0, (now - job.posted_at).total_seconds() / 3600)
    approx = "" if job.posted_exact else "~"
    if hours < 48:
        return f"posted {approx}{int(hours)}h ago"
    return f"posted {approx}{int(hours // 24)}d ago"


def render(jobs: list[Job], now: datetime, extra: int, catch_up: bool) -> tuple[str, str, str]:
    top = jobs[0]
    kind = "catch-up: " if catch_up else ""
    subject = f"Job Finder {kind}{len(jobs) + extra} new match{'es' if len(jobs) + extra != 1 else ''} · top: {top.title} @ {top.company}"
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
<p style="color:#555">{len(jobs) + extra} new job{'s' if len(jobs) + extra != 1 else ''} that passed your rules. Recently funded startups come first,
then the rest grouped by fit (strong, good, other) with the most recently posted first inside each group.
Fit = share of the posting's skills found on your resume (required skills count double). Crowding is an estimate.</p>
<table style="width:100%;border-collapse:collapse">{''.join(rows_html)}</table>{more}
<p style="color:#aaa;font-size:11px">Sent by your job-finder · {now.strftime('%Y-%m-%d %H:%M UTC')}</p></body></html>"""
    text_body = "\n".join(rows_txt) + (f"\n+{extra} more not shown" if extra else "")
    return subject, html_body, text_body


def send(subject: str, html_body: str, text_body: str, now: datetime) -> bool:
    """Returns True if emailed. Without credentials, writes out/digest-*.html and returns False."""
    sender, to, password = (os.environ.get(k, "").strip() for k in ("EMAIL_FROM", "EMAIL_TO", "GMAIL_APP_PASSWORD"))
    if not (sender and to and password):
        out = ROOT / "out"
        out.mkdir(exist_ok=True)
        path = out / f"digest-{now.strftime('%Y%m%d-%H%M')}.html"
        path.write_text(html_body)
        print(f"[dry-run] email not configured; digest written to {path}")
        return False
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, sender, to
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=30) as s:
        s.login(sender, password)
        s.send_message(msg)
    return True
