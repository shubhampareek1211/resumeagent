# ResumeAgent

A local, agent-assisted resume tailoring workflow: validate a one-page PDF, track
applications, and sync application metadata to your own Notion database.

**Your data stays in ignored local files.** The repository contains reusable code,
configuration examples and a fictional test resume—not anyone's real resume,
application history, contact information or credentials.

This is a command-line workflow, not a hosted service or an autonomous job-submission
bot. Your chosen AI coding assistant reads the job description and authors LaTeX;
the scripts handle validation, tracking and Notion synchronization. There is no
bundled LLM API or model fine-tuning. Review any AI-authored claims before applying.

## Quick start

Supported: macOS, Linux, and Windows through WSL2. Python 3.10+ and a POSIX shell
are required. Native Windows is not supported because file locks use `fcntl`.

1. Fork this repository and clone your fork, then `cd resumeagent`.
2. Install Python, LaTeX and PDF extraction tools:

   ```sh
   # Ubuntu / WSL2
   sudo apt-get update
   sudo apt-get install -y python3 python3-venv make texlive-latex-extra texlive-fonts-recommended poppler-utils

   # macOS with Homebrew (restart the terminal after installing MacTeX)
   brew install python poppler
   brew install --cask mactex-no-gui
   ```

3. Bootstrap the private workspace:

   ```sh
   ./scripts/setup.sh
   # For a specific interpreter, e.g. on macOS:
   # RESUMEAGENT_PYTHON=python3.12 ./scripts/setup.sh
   ```

   Setup installs pinned dependencies, creates ignored private files if absent, and
   verifies system tools. It does not overwrite existing profile, history or secrets.

4. Run the fictional demo without credentials:

   ```sh
   make demo
   ```

   Output: `folder/outputs/pdfs/sample_resume.pdf`. The demo expects the untouched
   example profile; run it before replacing the profile with your own contact tokens.

5. Add your own baseline at `references/current_resume.pdf`; edit
   `profile.local.json`, `truth_ledger.md` and `bullet_bank.md` locally. Put job
   descriptions under `inputs/`. None of these files should be committed.

6. Follow [Notion setup](docs/NOTION_SETUP.md) if you want syncing. Offline builds
   do not require Notion credentials or a database.

## Tailor and build

Ask your coding assistant to follow `folder/CLAUDE.md` and tailor your reference to
an input job description. A reusable prompt is in `folder/prompts/workflow.md`.
Provide:

- `folder/outputs/<name>.tex`: the job-specific resume source.
- `folder/outputs/checks/<name>_keywords.txt`: one keyword per line, `~` for preferred,
  and `|` for aliases. At least one required keyword is mandatory.

```sh
# Validate, publish locally, log one application, and sync it to Notion
./build.sh --type resume example_role "Example Company" "Software Developer"

# Build and log locally, leaving Notion pending
./build.sh --type resume example_role "Example Company" "Software Developer" --local-only

# Only build the PDF; do not log an application
./build.sh --type resume example_role --local-only

# Attach a one-page cover letter to the same company/role application
./build.sh --type cover-letter example_letter "Example Company" "Software Developer"
```

The required `--type` prevents filename-based validation bypasses. Resumes must
pass structural lint, a one-page check, single-line experience/project bullets,
profile settings, and >=80% required keyword coverage **from the rendered PDF text**.
Cover letters receive the one-page check. Publication replaces the final PDF only
after validation. Build staging files are deleted; failures preserve the previous PDF.
Missing dependencies or required keyword files stop the build.

`profile.local.json` controls allowed header tokens, maximum skill-category lines,
minimum page fill (0–1), adjacent terms needing qualified wording, and forbidden
terms. These are configurable checks, not proof that a claim is true. Supported
section orders and the expected LaTeX conventions are in `folder/CLAUDE.md`.

## Track and retry

`applications.md` is the local source of truth. A persistent Application ID is
independent of the attached filename. Reusing a resume across employers or roles
creates separate records. A unique company/role rebuild keeps the same ID/date/status.
For a new application date use `--date YYYY-MM-DD`; if multiple records match,
select `--application-id UUID` or a date explicitly.

```sh
# Read-only preview for one application
.venv/bin/python scripts/sync_applications_to_notion.py --dry-run --application-id UUID

# Retry failed/pending syncs without recompiling
.venv/bin/python scripts/sync_applications_to_notion.py --live --pending
```

A sync failure makes the build exit nonzero and leaves the ready PDF plus durable
retry state in `.state/notion_sync.json`. Direct sync defaults to dry-run; unfiltered
`--live` processes every Active row. `--single` is a broad substring filter; prefer
Application ID for an exact selection. Status flows **from local Markdown to Notion**;
changes made only in Notion can be overwritten on the next sync.

## Architecture and publication policy

See [detailed architecture](docs/ARCHITECTURE.md) for modules, data flow, identity,
failure handling, trust boundaries and the public/private file matrix.

| Published | Local only |
| --- | --- |
| Scripts, validation, tests, fictional examples | Reference PDFs and job descriptions |
| README, architecture, Notion guide | Contact/profile data, truth ledger, bullet bank |
| CI/release workflows, dependency pins | LaTeX outputs, PDFs, application history |
| Empty credential template | `.env`, Notion token/database ID, retry state |

`public-files.txt` is an explicit reviewed inventory. CI checks Git's staged/index
blobs against it, rejects private paths and binaries, and scans for common secrets,
real-email patterns, phone numbers and home-directory paths. This is defense in depth,
not a guarantee that arbitrary personal prose can be detected. Review every staged diff.
Do not force-add ignored files. Do not put private data in issues or pull requests.

## CI/CD and contributing

```sh
.venv/bin/python -m pip install -r requirements-dev.txt
make test
make check   # includes staged-file privacy validation
```

Pull requests and pushes to `main` run clean-clone setup, static checks, tests,
a fictional PDF build, and a runtime dependency audit on Python 3.10 and 3.12.
Tests mock Notion; CI has no Notion credentials and uploads no PDFs. Actions are
pinned to commit SHAs; Dependabot proposes weekly dependency/action updates.

Version tags (`v*`) trigger the same verification before publishing a GitHub Release
containing only a source archive and SHA-256 checksum. No user data, virtual environment
or generated PDF is bundled. No app server is deployed: the deliverable is local software.
See [contributing and release instructions](CONTRIBUTING.md) and [security policy](SECURITY.md).

## Limitations

- Job PDF extraction and tailoring require an assistant/manual authoring. Scanned
  PDFs may require local OCR. No resume-to-LaTeX conversion is automatically guaranteed.
- Keyword coverage is a relevance proxy, not an employer ATS score or interview guarantee.
- Notion receives metadata and filenames, not PDF uploads or a submitted job application.
- One Notion data source per database is supported. Duplicate remote matches stop sync.
- File locks coordinate one machine; separate machines need external coordination.
- `-no-shell-escape` limits TeX command execution but is not a complete sandbox. Compile
  only reviewed LaTeX; untrusted TeX may read local files. AI services may receive content
  you share with them even though this repository itself runs locally.

Distributed under the [MIT license](LICENSE).
