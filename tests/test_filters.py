from datetime import timedelta

from jobfinder.filters import phd_only, detail_rules, location_class, min_years_required, prefilter, split_sections, title_family
from jobfinder.models import Job
from jobfinder.text import now_utc, parse_workday_posted
from jobfinder.urls import parse_ats_url

NOW = now_utc()


def job(title="Software Engineer", location="New York, NY", text="", days=1, **kw):
    return Job(ats="greenhouse", board="acme", job_id="1", company="Acme", title=title, location=location,
               url="https://x", posted_at=NOW - timedelta(days=days), text=text, **kw)


def test_title_families():
    assert title_family("Machine Learning Engineer, New Grad") == "AI/ML"
    assert title_family("Software Engineer I") == "Software"
    assert title_family("Data Scientist") == "Data"
    assert title_family("Applied Scientist Intern") == "Research"
    assert title_family("AI Sales Engineer") is None
    assert title_family("Product Manager") is None


def test_prefilter_drops_senior_old_foreign():
    assert prefilter(job("Senior Software Engineer"), NOW) == "senior-title"
    assert prefilter(job("Software Engineer II"), NOW) == "senior-title"
    assert prefilter(job("Staff ML Engineer"), NOW) == "senior-title"
    assert prefilter(job(days=20), NOW) == "too-old"
    assert prefilter(job(location="Bengaluru, India"), NOW) == "non-us"
    assert prefilter(job(location="Bangalore, IN"), NOW) == "non-us"
    assert prefilter(job(location="London | New York, NY"), NOW) is None
    assert prefilter(job("Software Engineer, New Grad 2026"), NOW) is None


def test_location_class():
    assert location_class("Remote - US") == "US"
    assert location_class("San Francisco, CA") == "US"
    assert location_class("Toronto, ON") == "non-US"
    assert location_class("Remote") == "unknown"
    assert location_class("US, CA, Santa Clara") == "US"


def test_years_of_experience():
    assert min_years_required("3+ years of professional software experience") == 3
    assert min_years_required("0-2 years of experience in ML") == 0
    assert min_years_required("1-3 years of industry experience") == 1
    assert min_years_required("Bachelor's with 3+ years of experience, or Master's with 1+ year of experience.") == 1
    assert min_years_required("4-year degree in CS. Two years of hands-on experience with Python.") == 2
    assert min_years_required("Strong Python skills") is None
    bullets = ("Basic Qualifications:\n- 3+ years of professional software development experience\n"
               "- 2+ years of design experience\n- 1+ years of software development engineer experience")
    assert min_years_required(bullets) == 3


def test_detail_rules():
    assert detail_rules(job(text="Requirements:\n- 5+ years of experience building APIs")) == "yoe"
    assert detail_rules(job(text="Must be a U.S. citizen with an active Secret clearance.")) == "clearance"
    assert detail_rules(job(text="U.S. citizenship is required for this role.")) == "citizenship"
    assert detail_rules(job(text="This role requires U.S. citizens or green card holders.")) == "citizenship"
    assert detail_rules(job("Software Engineer Intern", text="Must be currently enrolled in a degree program.")) == "enrolled-student"
    assert detail_rules(job("Software Engineer Intern",
                            text="Currently pursuing or recently graduated with a BS/MS in CS.")) is None
    assert detail_rules(job("ML Engineer Intern", text="Summer internship for strong students.")) == "intern-no-recent-grads"
    assert detail_rules(job(text="New grad role. 0-2 years of experience. We are unable to sponsor visas.")) is None
    assert detail_rules(job(location="Remote", text="Work from anywhere in Europe.")) == "location-unclear"
    assert detail_rules(job(location="Remote", text="Remote within the United States.")) is None


def test_sections():
    req, pref = split_sections("About us\nWe build things.\nRequirements:\n- Python\n- SQL\nNice to have:\n- Rust\n")
    assert "Python" in req and "Rust" not in req and "Rust" in pref


def test_workday_posted():
    assert parse_workday_posted("Posted Today", NOW)[1] == 0
    assert parse_workday_posted("Posted Yesterday", NOW)[1] == 1
    assert parse_workday_posted("Posted 30+ Days Ago", NOW)[1] == 31


def test_parse_ats_url():
    assert parse_ats_url("https://job-boards.greenhouse.io/anthropic/jobs/5456619008") == ("greenhouse", "anthropic", "5456619008")
    assert parse_ats_url("https://jobs.lever.co/palantir/6ed76ce8-4156-4b60-b120-403538bd66cd/apply")[:2] == ("lever", "palantir")
    assert parse_ats_url("https://apply.workable.com/scitec/j/66E4D7E6C6/apply") == ("workable", "scitec", "66E4D7E6C6")
    wd = parse_ats_url("https://toyota.wd503.myworkdayjobs.com/en-US/tmna/job/Plano-Texas/Software-Engineer_10325070")
    assert wd == ("workday", "toyota.wd503.myworkdayjobs.com|toyota|tmna", "/job/Plano-Texas/Software-Engineer_10325070")


def test_phd_only():
    assert phd_only("Research Scientist", "Requirements:\n- PhD in Computer Science or related field")
    assert phd_only("Research Scientist, PhD New Grad", "Strong publication record in ML.")
    assert not phd_only("Research Scientist", "MS or PhD in Computer Science")
    assert not phd_only("Applied Scientist", "PhD preferred. Strong Python.")
    assert not phd_only("ML Engineer", "PhD in ML, or equivalent practical experience")
    assert not phd_only("Data Scientist", "Bachelor's degree in a quantitative field")
    assert detail_rules(job("Research Scientist", text="Qualifications:\n- PhD in Machine Learning")) == "phd-only"


def test_order_jobs_band_then_newest():
    from jobfinder.scoring import order_jobs

    def scored(name, fit, skills, hours):
        j = job(name)
        j.fit, j.skills_total, j.posted_at = fit, skills, NOW - timedelta(hours=hours)
        return j

    jobs = [scored("strong-4h", 80, 10, 4), scored("good-1h", 60, 8, 1), scored("strong-2h", 75, 6, 2),
            scored("thin-100", 100, 2, 0.5), scored("weak-1h", 30, 9, 1)]
    # a 100% fit on only 2 skills is too thin for the Good band, so it sorts with the other matches (newest first)
    assert [j.title for j in order_jobs(jobs)] == ["strong-2h", "strong-4h", "good-1h", "thin-100", "weak-1h"]


def test_new_url_parsers():
    assert parse_ats_url("https://careers-capbluecross.icims.com/jobs/5306/intern/job") == ("icims", "careers-capbluecross.icims.com", "5306")
    assert parse_ats_url("https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/210512345") == \
        ("oraclecloud", "jpmc.fa.oraclecloud.com|CX_1001", "210512345")
    assert parse_ats_url("https://www.amazon.jobs/en/jobs/10614480/software-development-engineer") == ("amazon", "amazon", "10614480")
    assert parse_ats_url("https://jobs.apple.com/en-us/details/200696384/ar-vr-software-engineer") == ("apple", "apple", "200696384")


def test_funding_helpers():
    from jobfinder.funding import FUND_NAME, RAISE, clean_name, key_of, yc_batches
    from datetime import date
    assert clean_name("Acme Robotics, Inc.") == "Acme Robotics"
    assert key_of("Acme Robotics, Inc.") == "acmerobotics"
    assert FUND_NAME.search("AT SPV 1026 a Series of CGF2026 LLC")
    assert FUND_NAME.search("Slow Rush Ventures, LP - Series 2")
    assert not FUND_NAME.search("Acme Robotics")
    m = RAISE.search("Spend management platform Payhawk announces $280M raise, 2B valuation")
    assert m and m.group("name") == "Payhawk"
    m = RAISE.search("Fauna Robotics raises $30M Series A to build home robots")
    assert m and m.group("name") == "Fauna Robotics"
    codes = [c for c, _ in yc_batches(date(2026, 11, 27), date(2026, 5, 29))]
    assert "S26" in codes and "F26" in codes and "W26" not in codes


# ---------------------------------------------------------------- fixes after the first catch-up email

def test_more_senior_titles_and_canada():
    assert prefilter(job("Mid-Level AI Engineer"), NOW) == "senior-title"
    assert prefilter(job("Managers, Data Science & Analytics"), NOW) == "senior-title"
    assert location_class("British Columbia") == "non-US"
    assert location_class("Vancouver, BC") == "non-US"
    assert location_class("Calgary, Alberta") == "non-US"
    assert location_class("Columbia, MD") == "US"
    assert location_class("Washington, DC") == "US"


def test_candidate_fees_drop_but_agencies_stay():
    from jobfinder.filters import annotate, charges_candidates
    assert charges_candidates("Candidates must pay a one-time training fee of $500 before placement.")
    assert charges_candidates("A refundable deposit of $1,000 is required.")
    assert charges_candidates("There is a bond period of 18 months.")
    assert not charges_candidates("We never charge candidates a placement fee.")
    assert not charges_candidates("There is no registration fee.")
    assert not charges_candidates("Experience with bond trading and fixed income.")
    agency = job(text="Raydar is recruiting for this role on behalf of our client. Python, SQL.")
    assert detail_rules(agency) is None
    annotate(agency)
    assert "Agency (hiring for a client)" in agency.flags
    assert detail_rules(job(text="Our OPT program: candidates will pay a nominal fee for marketing.")) == "charges-candidates"


def test_tiktok_date_from_job_id():
    from jobfinder.bigtech import tiktok_created
    assert str(tiktok_created("7695929967028750645").date()) == "2026-10-12"
    assert str(tiktok_created(7112323775379343623).date()) == "2022-06-23"
    assert tiktok_created("not-a-number") is None


def test_fit_needs_enough_skills_and_ignores_vague_words():
    from jobfinder.scoring import fit_band, score_fit, with_implied
    from jobfinder.skills import detect
    assert "JavaScript" in with_implied({"TypeScript"}) and "REST APIs" in with_implied({"FastAPI"})
    assert "REST APIs" not in detect("You'll work with the rest of the team on scalable systems.")
    assert "REST APIs" in detect("Build RESTful APIs in Python.")
    one = job(text="Requirements:\n- SQL")
    score_fit(one, {"SQL"})
    assert one.fit == 100 and fit_band(one) == 2          # one skill isn't enough to call it a fit
    three = job(text="Requirements:\n- Python\n- SQL\n- Spark\n- security and monitoring")
    score_fit(three, {"Python", "SQL"})
    assert three.skills_total == 3 and fit_band(three) == 1   # security/monitoring don't count either way


def test_merge_cities_and_picks():
    from jobfinder.run import is_pick, merge_cities
    text = "Build recommendation models with PyTorch for e-commerce search and ranking at scale."
    a = job("Machine Learning Engineer", "San Jose, CA", text)
    b = job("Machine Learning Engineer", "Seattle, WA", text)
    b.job_id = "2"
    c = job("Machine Learning Engineer", "Boston, MA", "Our client is a fintech company. Kafka, Java, Spring, payments.")
    c.job_id = "3"
    merged = merge_cities([a, b, c])
    assert len(merged) == 2 and merged[0].location == "San Jose, CA | Seattle, WA"
    strong = job(text="Requirements:\n- Python\n- SQL\n- PyTorch\n- AWS")
    from jobfinder.scoring import score_fit
    score_fit(strong, {"Python", "SQL", "PyTorch", "AWS"})
    assert is_pick(strong)


def test_daily_email():
    from jobfinder.emailer import render_daily
    from jobfinder.scoring import score_fit
    j = job(text="Requirements:\n- Python\n- SQL\n- PyTorch\n- AWS")
    score_fit(j, {"Python", "SQL", "PyTorch", "AWS"})
    other = job("Data Scientist", text="Requirements:\n- R")
    score_fit(other, {"Python"})
    info = {"applied_week": 3, "applied_total": 9}
    subject, html_body, text_body = render_daily([j, other], [j], info, "https://docs.google.com/x", NOW)
    assert subject == "Today's jobs: 2 new matches, 1 strong · top: Software Engineer @ Acme"
    assert "Open your tracker" in html_body and "The other 1 job is in your tracker" in text_body
    subject, _, text_body = render_daily([], [], info, "", NOW)
    assert subject == "Today's jobs: nothing new · 3 applied this week" and "No new matches" in text_body


def test_sheet_row_shape():
    from jobfinder.sheet import job_row
    j = job(text="Requirements:\n- Python")
    j.flags = ["No sponsorship"]
    row = job_row(j)
    assert row["key"] == "greenhouse:acme:1" and row["group"] == "Other" and row["flags"] == "No sponsorship"
    assert row["posted"] == j.posted_at.strftime("%Y-%m-%d")


def test_slow_lanes_by_shared_host():
    from jobfinder.sources import _lane, host_group
    assert _lane("workday", "acme.wd5.myworkdayjobs.com|acme|Ext") == "workday:wd5"
    assert _lane("workday", "wd1.myworkdaysite.com|wf|Jobs") == "workday:wd1"
    assert _lane("ycjobs", "fluxcap") == "ycjobs" and _lane("greenhouse", "acme") == "default"
    assert host_group("https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/Ext/jobs") == "workday:wd5"
    assert host_group("https://www.ycombinator.com/companies/x/jobs") == "ycombinator"


def test_send_without_credentials_writes_a_file(tmp_path, monkeypatch):
    from jobfinder import emailer
    for k in ("EMAIL_FROM", "EMAIL_TO", "GMAIL_APP_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(emailer, "ROOT", tmp_path)
    assert emailer.send("s", "<p>hi</p>", "hi", NOW) is False
    assert list((tmp_path / "out").glob("digest-*.html"))


def test_run_module_calls_exist():
    # every emailer/sheet function run.py calls must exist (catches a deleted helper before it reaches GitHub)
    import re
    from pathlib import Path
    from jobfinder import emailer, sheet
    src = Path(__file__).resolve().parent.parent.joinpath("jobfinder/run.py").read_text()
    for mod, name in re.findall(r"\b(emailer|sheet)\.([a-z_]+)\(", src):
        assert hasattr({"emailer": emailer, "sheet": sheet}[mod], name), f"{mod}.{name} is missing"


def test_send_daily_email_end_to_end(monkeypatch):
    from jobfinder import emailer, run, sheet
    from jobfinder.scoring import score_fit
    from jobfinder.state import State
    sent = {}
    monkeypatch.setattr(sheet, "summary", lambda since: {"rows": [], "applied_week": 2, "applied_total": 5, "url": "u"})
    monkeypatch.setattr(emailer, "send", lambda subject, h, t, now: sent.update(subject=subject) or True)
    j = job(text="Requirements:\n- Python\n- SQL\n- PyTorch\n- AWS")
    score_fit(j, {"Python", "SQL", "PyTorch", "AWS"})
    assert run.send_daily_email([j], "https://sheet", State(), NOW) is True
    assert sent["subject"].startswith("Today's jobs: 1 new match, 1 strong")
    assert run.send_daily_email([], "https://sheet", State(), NOW) is True
    assert sent["subject"] == "Today's jobs: nothing new · 2 applied this week"
