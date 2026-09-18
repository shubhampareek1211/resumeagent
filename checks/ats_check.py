#!/usr/bin/env python3
"""ATS keyword-coverage check for a tailored resume.

Usage:  .venv/bin/python checks/ats_check.py <name_without_extension>

Reads folder/outputs/checks/<name>_keywords.txt — the JD keywords written down
during tailoring (one keyword per line, top ~20 from the JD):

    Python
    RAG|Retrieval-Augmented Generation     <- aliases separated by |
    ~Azure                                 <- leading ~ marks a PREFERRED keyword
    # comment lines are ignored

A keyword counts as covered if it (or any alias) appears in the extracted PDF text
(case-insensitive). Required coverage must reach THRESHOLD to pass (exit 0).
"""

import argparse
import re
import subprocess
import unicodedata
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS = ROOT / "folder" / "outputs"
THRESHOLD = 0.80  # required-keyword coverage to pass


def normalize_text(text):
    text = unicodedata.normalize("NFKC", text).replace("\u00ad", "")
    text = text.translate(str.maketrans({"‐": "-", "–": "-", "—": "-", "‑": "-", "−": "-", "’": "'", "‘": "'"}))
    return " ".join(text.split())


def extract_pdf_text(pdf):
    result = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True)
    if result.returncode or not result.stdout.strip():
        raise ValueError("PDF text extraction failed or returned no text")
    return normalize_text(result.stdout)


def covered(keyword, text):
    text = normalize_text(text)
    # P0 fix: whole-term match via lookarounds so 'AI' doesn't match
    # 'training' and 'Go' doesn't match 'good'. Works for symbols too
    # ('C++', 'C#', 'Node.js') where \b would fail at the edge.
    for alias in keyword.split("|"):
        alias = normalize_text(alias)
        if not alias:
            continue
        pat = r"(?<!\w)" + re.escape(alias) + r"(?!\w)"
        if re.search(pat, text, re.I):
            return True
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('name')
    parser.add_argument('--pdf', type=Path, help='exact staged PDF to score')
    args = parser.parse_args()
    name = args.name.removesuffix('.tex')
    if (not name or ".." in name or "/" in name
            or not re.fullmatch(r"[A-Za-z0-9._-]+", name)
            or name.startswith(("-", "."))):
        print(f"❌ invalid name {name!r} — letters, digits, dot, underscore, hyphen only")
        sys.exit(2)
    tex_path = OUTPUTS / f"{name}.tex"
    kw_path = OUTPUTS / "checks" / f"{name}_keywords.txt"
    if not tex_path.exists():
        print(f"❌ {tex_path} not found")
        sys.exit(2)
    if not kw_path.exists():
        print(f"⚠️  no keywords file at {kw_path} — write the JD keywords there "
              "during tailoring so coverage can be scored")
        sys.exit(2)

    pdf = args.pdf or OUTPUTS / "pdfs" / f"{name}.pdf"
    try:
        text = extract_pdf_text(pdf)
    except (OSError, ValueError) as exc:
        print(f"ATS CHECK FAILED: {exc}")
        sys.exit(1)
    required, preferred = [], []
    for line in kw_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        is_pref = line.startswith("~")
        clean = line.lstrip("~").strip()
        if not clean:
            continue
        (preferred if is_pref else required).append(clean)

    if not required:
        print("❌ no required keywords in keywords file — write the JD's top ~20 "
              "keywords there during tailoring (lines starting with ~ are preferred-only)")
        sys.exit(1)
    miss_req = [k for k in required if not covered(k, text)]
    miss_pref = [k for k in preferred if not covered(k, text)]
    ratio = (len(required) - len(miss_req)) / len(required)

    print(f"ATS coverage — required: {len(required) - len(miss_req)}/{len(required)} "
          f"({ratio:.0%}) · preferred: {len(preferred) - len(miss_pref)}/{len(preferred)}")
    for k in miss_req:
        print(f"❌ missing required keyword: {k}")
    for k in miss_pref:
        print(f"⚠️  missing preferred keyword: {k}")

    if ratio < THRESHOLD:
        print(f"\nATS CHECK FAILED — required coverage {ratio:.0%} < {THRESHOLD:.0%}. "
              "Work missing keywords into Skills/bullets (only if truth_ledger-backed).")
        sys.exit(1)
    print("✅ ATS coverage passed")


if __name__ == "__main__":
    main()
