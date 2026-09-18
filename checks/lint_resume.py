#!/usr/bin/env python3
"""Lint a resume .tex + built PDF against the house rules in folder/CLAUDE.md.

Usage:  .venv/bin/python checks/lint_resume.py <name_without_extension>

Checks (ERROR = exit 1; WARN = printed, exit stays 0):
  tex source:
    E1  header center block contains only the approved name/contact tokens
    E2  required sections present and in order
    E3  Skills section has at most MAX_SKILLS_LINES bold category lines
    E4  Experience entries are strict reverse-chronological by start date
    E5  approved \\setlist spacing line present; no negative itemsep
    E6  profile-specific forbidden terms are absent
    W1  profile-specific adjacent terms use transparent framing
  built PDF:
    E8  every Experience/Projects bullet fits on ONE printed line (no wraps)
    E9  exactly 1 page
    E10 page is filled (text reaches the bottom FILL_THRESHOLD of the page)
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS = ROOT / "folder" / "outputs"

sys.path.insert(0, str(ROOT / "scripts"))
from profile_config import load_profile

PROFILE = load_profile()
MAX_SKILLS_LINES = PROFILE["max_skills_lines"]
FILL_THRESHOLD = PROFILE["min_fill_ratio"]
APPROVED_HEADER_TOKENS = set(PROFILE["header_tokens"])
SECTION_ORDER = ["Education", "Skills", "Experience", "Projects", "Certifications"]
APPROVED_SETLIST = (
    r"\setlist[itemize]{itemsep=2pt, leftmargin=11pt, topsep=2pt, parsep=0pt, partopsep=0pt}"
)
ADJACENT_FRAMING = ("equivalent", "exposure", "interest")
MONTHS = {m: i for i, m in enumerate(
    "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}

errors, warnings = [], []


def err(msg):
    errors.append(msg)


def warn(msg):
    warnings.append(msg)


def section_block(tex, name):
    """Return the source between \\section{name} and the next \\section (or end)."""
    m = re.search(r"\\section\{" + name + r"\}(.*?)(?=\\section\{|\\end\{document\})",
                  tex, re.S)
    return m.group(1) if m else ""


def check_header(tex):
    m = re.search(r"\\begin\{center\}(.*?)\\end\{center\}", tex, re.S)
    if not m:
        err("E1 header: no \\begin{center} block found")
        return
    body = m.group(1)
    # keep the display text of \href{url}{text}, drop the url
    body = re.sub(r"\\href\{[^}]*\}\{([^}]*)\}", r"\1", body)
    body = re.sub(r"\\(LARGE|textbar|\\)", " ", body)
    body = re.sub(r"[{}|]", " ", body)
    extra = [t for t in body.split() if t not in APPROVED_HEADER_TOKENS]
    if extra:
        err(f"E1 header: unexpected content in header block (no taglines/summaries): {extra}")


def check_sections(tex):
    found = re.findall(r"\\section\{([^}]*)\}", tex)
    # Certifications may live as a bold line inside Skills instead of its own section.
    skills_name = "Technical Skills" if "Technical Skills" in found else "Skills"
    order = (["Education", "Experience", "Projects", "Technical Skills", "Certifications"]
             if skills_name == "Technical Skills" else SECTION_ORDER)
    certs_in_skills = bool(re.search(r"\\textbf\{Certifications:?\}", section_block(tex, skills_name)))
    required = [s for s in order
                if not (s == "Certifications" and certs_in_skills)]
    missing = [s for s in required if s not in found]
    if missing:
        err(f"E2 sections: missing {missing}")
    present = [s for s in found if s in order]
    if present != [s for s in order if s in present]:
        err(f"E2 sections: out of order — found {found}, expected order {order}")


def check_skills(tex):
    block = section_block(tex, "Technical Skills") or section_block(tex, "Skills")
    n = len(re.findall(r"^\\textbf\{", block, re.M))
    if n > MAX_SKILLS_LINES:
        err(f"E3 skills: {n} category lines (max {MAX_SKILLS_LINES})")


def check_timeline(tex):
    block = section_block(tex, "Experience")
    starts = re.findall(r"\\textit\{([A-Z][a-z]{2}) (\d{4}) *(?:--|–|—)", block)
    unknown = sorted({m for m, _ in starts if m not in MONTHS})
    if unknown:
        warn(f"W timeline: unrecognized month abbrev {unknown} — check manually")
    valid = [(m, y) for m, y in starts if m in MONTHS]
    keys = [int(y) * 12 + MONTHS[m] for m, y in valid]
    if len(keys) < 2:
        warn("W timeline: fewer than 2 dated Experience entries found — check manually")
    elif any(a < b for a, b in zip(keys, keys[1:])):
        err(f"E4 timeline: Experience not reverse-chronological — start dates {valid}")


def check_preamble(tex):
    if APPROVED_SETLIST not in tex:
        err("E5 preamble: approved \\setlist spacing line missing or modified")
    if re.search(r"itemsep\s*=\s*-", tex):
        err("E5 preamble: negative itemsep found (causes overlapping bullets)")


def check_truth(tex):
    plain = "\n".join(l for l in tex.splitlines() if not l.lstrip().startswith("%"))
    for term in PROFILE["forbidden_terms"]:
        if re.search(re.escape(term), plain, re.I):
            err("E6 truth: a locally forbidden claim appears in the source; check profile.local.json")
    for term in PROFILE["adjacent_terms"]:
        term = term.strip()
        if not term or term.startswith("#"):
            continue
        pat = r"\b" + re.escape(term) + r"\b"
        for i, line in enumerate(plain.splitlines(), 1):
            if re.search(pat, line, re.I) and \
                    not any(f in line.lower() for f in ADJACENT_FRAMING):
                warn(f"W1 truth: adjacent term '{term}' without transparent framing (line {i})")


def find_pdf(name):
    # The build passes --pdf for its isolated staging file. Standalone checks prefer
    # the last published PDF over historical loose artifacts.
    for p in (OUTPUTS / "pdfs" / f"{name}.pdf", OUTPUTS / f"{name}.pdf"):
        if p.exists():
            return p
    return None


def check_pdf(name, pdf_path=None):
    pdf = pdf_path if pdf_path is not None else find_pdf(name)
    if pdf is None:
        err("E9 pdf: no built PDF found in outputs/ or outputs/pdfs/ — build first")
        return

    try:
        import fitz
    except ImportError:
        err("E9 pdf: PyMuPDF (fitz) not installed — run: pip install PyMuPDF")
        return
    try:
        doc = fitz.open(pdf)
    except Exception as e:
        err(f"E9 pdf: cannot open {pdf.name} ({e})")
        return
    try:
        if doc.page_count != 1:
            err(f"E9 pdf: {doc.page_count} pages (must be 1)")
            return
        page = doc[0]
        bottom = max((b[3] for b in page.get_text("blocks")), default=0)
        fill = bottom / page.rect.height
        if fill < FILL_THRESHOLD:
            err(f"E10 pdf: page only {fill:.0%} full (need ≥ {FILL_THRESHOLD:.0%}) — "
                "add content per the page budget, don't leave whitespace")
    finally:
        doc.close()

    try:
        proc = subprocess.run(["pdftotext", "-layout", str(pdf), "-"],
                              capture_output=True, text=True)
    except FileNotFoundError:
        err("E8 bullets: `pdftotext` not found (install poppler) — cannot verify one-line bullets")
        return
    if proc.returncode != 0:
        err(f"E8 bullets: `pdftotext` failed (exit {proc.returncode}) — cannot verify one-line bullets")
        return
    text = proc.stdout
    lines = text.splitlines()
    region, wrapped = False, []
    for i, line in enumerate(lines):
        s = line.strip()
        if s == "Experience":
            region = True
        elif s in ("Certifications", "Skills", "Technical Skills"):
            region = False
        elif region and line and line[0].isspace() and s:
            prev = next((l.strip() for l in reversed(lines[:i]) if l.strip()), "")
            wrapped.append(f"  …{prev[-50:]}\n   ↳ {s}")
    if wrapped:
        err("E8 bullets: wrapped (multi-line) bullets found — every Experience/Projects "
            "bullet must fit ONE printed line:\n" + "\n".join(wrapped))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('name')
    parser.add_argument('--pdf', type=Path, help='exact staged PDF to validate')
    args = parser.parse_args()
    name = args.name.removesuffix('.tex')
    if (not name or ".." in name or "/" in name
            or not re.fullmatch(r"[A-Za-z0-9._-]+", name)
            or name.startswith(("-", "."))):
        print(f"❌ invalid name {name!r} — letters, digits, dot, underscore, hyphen only")
        sys.exit(2)
    tex_path = OUTPUTS / f"{name}.tex"
    if not tex_path.exists():
        print(f"❌ {tex_path} not found")
        sys.exit(2)
    tex = tex_path.read_text()

    check_header(tex)
    check_sections(tex)
    check_skills(tex)
    check_timeline(tex)
    check_preamble(tex)
    check_truth(tex)
    check_pdf(name, args.pdf)

    for w in warnings:
        print(f"⚠️  {w}")
    if errors:
        for e in errors:
            print(f"❌ {e}")
        print(f"\nLINT FAILED — {len(errors)} error(s), {len(warnings)} warning(s)")
        sys.exit(1)
    print(f"✅ lint passed ({len(warnings)} warning(s))")


if __name__ == "__main__":
    main()
