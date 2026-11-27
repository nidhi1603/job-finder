# job-finder

A personal job finder for new-grad AI/ML, software, data and research roles in the US. Every hour it reads
companies' own job boards (Greenhouse, Lever, Ashby, Workable, Workday, iCIMS, Oracle Recruiting Cloud), the career
sites of Amazon, Apple, Microsoft, Google, TikTok and IBM, and the job pages of recently funded startups. It keeps only fresh entry-level jobs
you can actually take, scores how well each one matches your resume, and adds the new ones to a private Google
Sheet that doubles as your application tracker, with an email for strong matches and one each morning. The point is
to catch jobs within hours of posting, before they reach LinkedIn and fill up with applicants.

## How it works

1. **Company list** (`data/boards.json`, kept up to date by `discover.yml`, daily): job boards linked from the
   [SimplifyJobs new-grad list](https://github.com/SimplifyJobs/New-Grad-Positions), plus a sweep of
   ATS board links in [Common Crawl](https://commoncrawl.org)'s public URL index (re-swept every 30 days,
   `data/candidates.json`). Each board is probed, and only live boards with US jobs are kept. Probe results
   (`data/probes.json`) are re-checked every 45 days, and a run that hits its time budget saves its progress so
   the next run continues.
2. **Recently funded startups** (`data/funded.json`, refreshed daily by `funding.yml`): startups that raised
   money in the last 6 months, from Y Combinator batches, SEC Form D filings (tech and health-tech, $1M+ sold)
   and TechCrunch funding headlines. Each one is matched to a job board through careers links on its own website
   (or its Y Combinator jobs page), with exact-name guesses on Greenhouse/Lever/Ashby/Workable as a fallback.
   SEC asks automated clients for a contact email; the workflow passes the `EMAIL_FROM` secret.
3. **Big companies** (`jobfinder/bigtech.py`): Amazon, Apple, Microsoft, Google (early-career roles), TikTok, IBM,
   Oracle and JPMorgan Chase are read directly every hour. Meta is not included because metacareers.com blocks
   automated access.
4. **Runs** (`poll.yml`, at :17 and :47 past each hour because GitHub's scheduler often starts runs late or
   skips them): funded startups, big companies and new-grad-list companies are checked every run; broad-sweep
   boards every 4th half-hour slot. Workday gets its own slow lane because it rate-limits bursts.
5. **Rules** (`jobfinder/rules.py`, one editable file). A job has to pass all of these:
   - US location (remote, hybrid or onsite)
   - A target title family
   - Posted in the last 15 days
   - No senior-level title
   - A stated experience minimum of 2 years or less
   - No security clearance
   - No US-citizens-only or green-card-only requirement
   - Internships only if they accept recent graduates
   - Not PhD-only (a PhD required with no master's, bachelor's or equivalent-experience route)
   - Doesn't ask the candidate to pay (training, placement or registration fees, deposits, employment bonds)

   Two kinds of note are added:
   - **Flags**: no sponsorship, degree level, recruiting agency hiring for a client, training-and-placement
     programs (check them for fees).
   - **Boosts**: "new grad", "recent graduate", "early career".
6. **Scores**:
   - **Fit**: the share of the posting's detected skills that appear in your skills list. Required skills count
     double. Skills your list implies count (TypeScript implies JavaScript, FastAPI implies REST APIs). Words in
     almost every posting (security, monitoring, systems design) don't count either way.
   - **Crowding**: an estimate from job age, company size (open jobs on its board), whether the job is on the
     SimplifyJobs list, and reposts.
7. **Tracker sheet** (`tracker/Code.gs`): every new match becomes a row in a private Google Sheet. You set its
   Status (New, Applied, Interviewing, Offer, Rejected, Skipped); "Applied on" fills itself in, and a Companies tab
   lists every company you applied to. A job posted in several cities is one row. New jobs at a company you already
   applied to say so.
8. **Email**:
   - **Alert**, right away: strong fits (70%+ with 4+ skills), and good fits (50%+ with 3+ skills) at recently funded
     startups or aimed at new grads.
   - **Morning summary**, once a day at the first run after 8am Eastern (`SUMMARY_HOUR`, `SUMMARY_TZ`): what
     arrived, the best ones still marked New, and how many you applied to this week.
   - Without the sheet set up (or if it can't be reached), each run emails every new match instead, so nothing is lost.
9. **No repeats**: `data/seen.json` (job keys and dates only) lives on the `state` branch.

## Setup (once)

Repo **Settings → Secrets and variables → Actions**:

| Name | Kind | Value |
|---|---|---|
| `PROFILE_SKILLS` | secret | comma-separated skills (`python -m jobfinder.profile resume.tex` prints it) |
| `EMAIL_FROM` | secret | the Gmail address that sends the alerts |
| `EMAIL_TO` | secret | where alerts go (can be the same address) |
| `GMAIL_APP_PASSWORD` | secret | a 16-character Gmail app password (below) |
| `SHEET_URL` | secret | the tracker's web app link (below) |
| `SHEET_SECRET` | secret | a random string; the same value goes in `SECRET` in the script |
| `MIN_FIT` | variable | minimum fit % to keep (unset = 0) |
| `SUMMARY_HOUR`, `SUMMARY_TZ` | variables | morning summary time (default 8, `America/New_York`) |

**Gmail app password:** turn on 2-Step Verification for the sending Google account. Then go to
<https://myaccount.google.com/apppasswords>, create one named "job-finder", and paste the 16 characters into
`GMAIL_APP_PASSWORD`.

**Tracker sheet:**
1. Create a blank Google Sheet.
2. Open **Extensions → Apps Script**, delete what's there, and paste in `tracker/Code.gs` with your
   `SHEET_SECRET` value in place of `PASTE_SECRET_HERE`. Save.
3. Click **Deploy → New deployment**, choose type **Web app**, set *Execute as: Me* and *Who has access: Anyone*, then
   **Deploy**. Google asks you to authorize the script; because it's your own unpublished script it shows "Google
   hasn't verified this app": choose **Advanced → Go to (project name)**.
4. Copy the **Web app URL** (ends in `/exec`) into the `SHEET_URL` secret.
5. Run **Actions → poll → Run workflow** with **backfill** ticked to load the last 15 days into the sheet.

"Anyone" only means the job finder can reach the script without a Google login. Every request has to carry the
secret, and the sheet itself stays private to your account.

**First run:** go to **Actions → poll → Run workflow**. Until the email secrets exist, runs only log what they
found and nothing is marked as sent.

## Local use

```bash
pip install -r requirements.txt
python -m jobfinder.profile path/to/resume.tex     # writes profile.local.json (git-ignored)
python -m jobfinder.discover --budget-min 20       # update data/boards.json (stops after 20 minutes)
python -m jobfinder.run --dry-run                  # writes out/digest-*.html, sends nothing, saves nothing
pytest -q
```

## Known limits

- The rules are keyword-based. Some companies' "Engineer II" is entry level, and "degree or equivalent
  experience" isn't distinguished.
- Not covered: Meta (blocks automated access), Taleo, SuccessFactors, ADP, Cisco and other custom career sites.
- IBM's feed only has a short summary of each job, so its rules and fit score work on less text.
- TikTok's feed has no posting dates, so the first catch-up includes all its current matching roles.
- Workday shows "Posted N Days Ago" in its lists. The exact date comes from the job's detail page.
- The GitHub scheduler is best-effort, so runs can start late or occasionally be skipped.
