# job-finder

A personal job finder for new-grad AI/ML, software, data and research roles in the US. Every hour it reads
companies' own job boards (Greenhouse, Lever, Ashby, Workable, Workday). It keeps only fresh entry-level jobs
you can actually take, scores how well each one matches your resume, and emails you the new ones. The point is
to catch jobs within hours of posting, before they reach LinkedIn and fill up with applicants.

## How it works

1. **Company list** (`data/boards.json`, refreshed monthly by `discover.yml`): job boards linked from the
   [SimplifyJobs new-grad list](https://github.com/SimplifyJobs/New-Grad-Positions), plus a sweep of
   ATS board links in [Common Crawl](https://commoncrawl.org)'s public URL index. Each board is probed, and only
   live boards with US jobs are kept.
2. **Hourly run** (`poll.yml`): new-grad-list companies are checked every hour, and the broad-sweep boards
   every 4th hour. Workday gets its own slow lane because it rate-limits bursts.
3. **Rules** (`jobfinder/rules.py`, one editable file). A job has to pass all of these:
   - US location (remote, hybrid or onsite)
   - A target title family
   - Posted in the last 15 days
   - No senior-level title
   - A stated experience minimum of 2 years or less
   - No security clearance
   - No US-citizens-only or green-card-only requirement
   - Internships only if they accept recent graduates
   - Not PhD-only (a PhD required with no master's, bachelor's or equivalent-experience route)

   Two kinds of note are added:
   - **Flags**: no sponsorship, degree level.
   - **Boosts**: "new grad", "recent graduate", "early career".
4. **Scores**:
   - **Fit**: the share of the posting's detected skills that appear in your skills list. Required skills count double.
   - **Crowding**: an estimate from job age, company size (open jobs on its board), whether the job is on the
     SimplifyJobs list, and reposts.
5. **Email**: one digest per run, sent only when something new passed, best fit first. The very first run
   sends a catch-up of the last 15 days.
6. **No repeats**: `data/seen.json` (job keys and dates only) lives on the `state` branch.

## Setup (once)

Repo **Settings → Secrets and variables → Actions**:

| Name | Kind | Value |
|---|---|---|
| `PROFILE_SKILLS` | secret | comma-separated skills (`python -m jobfinder.profile resume.tex` prints it) |
| `EMAIL_FROM` | secret | the Gmail address that sends the alerts |
| `EMAIL_TO` | secret | where alerts go (can be the same address) |
| `GMAIL_APP_PASSWORD` | secret | a 16-character Gmail app password (below) |
| `MIN_FIT` | variable | minimum fit % to email (leave unset = 0 for the first catch-up) |

**Gmail app password:** turn on 2-Step Verification for the sending Google account. Then go to
<https://myaccount.google.com/apppasswords>, create one named "job-finder", and paste the 16 characters into
`GMAIL_APP_PASSWORD`.

**First run:** go to **Actions → poll → Run workflow**. Until the email secrets exist, runs only log what they
found and nothing is marked as sent.

## Local use

```bash
pip install -r requirements.txt
python -m jobfinder.profile path/to/resume.tex     # writes profile.local.json (git-ignored)
python -m jobfinder.discover --crawls 1            # rebuild data/boards.json
python -m jobfinder.run --dry-run                  # writes out/digest-*.html, sends nothing, saves nothing
pytest -q
```

## Known limits

- The rules are keyword-based. Some companies' "Engineer II" is entry level, and "degree or equivalent
  experience" isn't distinguished.
- iCIMS, ADP, Taleo, SuccessFactors and custom career sites aren't covered.
- Workday shows "Posted N Days Ago" in its lists. The exact date comes from the job's detail page.
- The GitHub scheduler is best-effort, so runs can start late or occasionally be skipped.
