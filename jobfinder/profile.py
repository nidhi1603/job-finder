"""Build your skills profile from a resume file (.tex/.md/.txt).

    python -m jobfinder.profile path/to/resume.tex

Writes profile.local.json (git-ignored) and prints the comma-separated list to paste into
the PROFILE_SKILLS GitHub secret.
"""
import json
import re
import sys
from pathlib import Path

from .skills import detect

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    text = Path(sys.argv[1]).read_text(errors="ignore")
    text = re.sub(r"(?m)%.*$", "", text)                          # LaTeX comments
    text = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?", " ", text)      # LaTeX commands
    text = text.replace("\\&", "&").replace("{", " ").replace("}", " ")
    skills = sorted(detect(text))
    (ROOT / "profile.local.json").write_text(json.dumps({"skills": skills}, indent=1))
    print(f"{len(skills)} skills -> profile.local.json\n")
    print(",".join(skills))


if __name__ == "__main__":
    main()
