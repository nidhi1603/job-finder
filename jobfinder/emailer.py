"""Render emails and send them through Gmail SMTP (or write them to out/ when email isn't set up).

Three kinds: the full digest (no tracker sheet), the strong-match alert, and the morning summary.
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


def render(jobs: list[Job], now: datetime, extra: int, catch_up: bool, kind: str = "digest",
           sheet_url: str = "", others: int = 0) -> tuple[str, str, str]:
    """kind="digest": every match (no tracker sheet). kind="alert": only strong matches; the rest went to the sheet."""
    top = jobs[0]
    if kind == "alert":
        subject = f"{_plural(len(jobs), 'strong match', 'strong matches')} · top: {top.title} @ {top.company}"
        intro = (f"New postings that fit you well. Apply within 24 hours for the best odds, then mark them Applied in "
                 f"your tracker." + (f" {_plural(others, 'other new job')} went to the tracker without an email." if others else ""))
    else:
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


GROUP_ORDER = {"Funded": 0, "Strong": 1, "Good": 2, "Other": 3}


def render_summary(d: dict, now: datetime) -> tuple[str, str, str]:
    """Morning email from the tracker sheet: what arrived since the last summary, what's still untouched, and
    how many applications you've sent."""
    rows = d.get("rows") or []
    counts = Counter(r.get("group") or "Other" for r in rows)
    fresh = [r for r in rows if (r.get("status") or "New") == "New"]
    fresh.sort(key=lambda r: (GROUP_ORDER.get(r.get("group"), 9), -(r.get("fit") or 0)))
    top = fresh[:10]
    week, total = d.get("applied_week", 0), d.get("applied_total", 0)
    strong = counts["Strong"] + counts["Funded"]
    subject = f"Morning summary: {_plural(len(rows), 'new job')}" + (f", {strong} strong" if strong else "") + f" · {week} applied this week"
    parts = ", ".join(f"{counts[g]} {g.lower()}" for g in ("Funded", "Strong", "Good", "Other") if counts[g])
    lines_html, lines_txt = [], []
    for r in top:
        fit = f"{r['fit']}%" if r.get("fit") is not None else "?"
        meta = " · ".join(x for x in (r.get("company"), (r.get("location") or "")[:60], f"fit {fit}", r.get("group"), r.get("posted") and f"posted {r['posted']}") if x)
        lines_html.append(f'<li style="margin:6px 0"><a href="{html.escape(r.get("url") or "")}" style="color:#1a56db;text-decoration:none;'
                          f'font-weight:600">{html.escape(r.get("title") or "")}</a><br><span style="color:#555;font-size:13px">'
                          f'{html.escape(meta)}</span>'
                          + (f'<br><span style="color:#777;font-size:12px">{html.escape(r["flags"][:160])}</span>' if r.get("flags") else "")
                          + "</li>")
        lines_txt.append(f"- {r.get('title')} | {meta}\n  {r.get('url')}")
    url = d.get("url", "")
    since_txt = f"{_plural(len(rows), 'new job')} since the last summary" + (f" ({parts})" if parts else "") + "."
    html_body = f"""<html><body style="font-family:-apple-system,Segoe UI,Arial,sans-serif;max-width:720px;margin:auto">
<h2 style="margin-bottom:4px">Good morning</h2>
<p style="color:#333">{html.escape(since_txt)} You applied to <b>{week}</b> in the last 7 days ({total} in all).</p>
{_button(url, "Open your tracker")}
{"<h3>Still marked New, best first</h3><ul style='padding-left:18px'>" + "".join(lines_html) + "</ul>" if top else "<p>Nothing new is waiting for you.</p>"}
{f"<p style='color:#777'>{len(fresh) - len(top)} more are in the tracker.</p>" if len(fresh) > len(top) else ""}
<p style="color:#aaa;font-size:11px">Sent by your job-finder · {now.strftime('%Y-%m-%d %H:%M UTC')}</p></body></html>"""
    text_body = (f"{since_txt} You applied to {week} in the last 7 days ({total} in all).\n\n"
                 + ("Still marked New, best first:\n" + "\n".join(lines_txt) if top else "Nothing new is waiting for you.")
                 + (f"\n\nYour tracker: {url}" if url else ""))
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
