#!/usr/bin/env python3
"""Build, validate, publish, log, and sync one application; never infer type from name."""
import argparse
from datetime import date
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from applications import locked, log_application, mark_sync
from preflight import check_dependencies

ROOT = Path(__file__).resolve().parent.parent


def run(command, **kwargs):
    return subprocess.run(command, check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--type', required=True, choices=['resume', 'cover-letter'], dest='document_type')
    parser.add_argument('name')
    parser.add_argument('company', nargs='?')
    parser.add_argument('role', nargs='?')
    parser.add_argument('--local-only', action='store_true', help='build locally; if logged, leave Notion sync pending')
    parser.add_argument('--application-id', help='rebuild an existing application by its persistent ID')
    parser.add_argument('--date', help='YYYY-MM-DD; explicitly create/select a separate application date')
    args = parser.parse_args()
    name = args.name.removesuffix('.tex')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', name) or '..' in name:
        parser.error('name must contain only letters, digits, dot, underscore or hyphen; no paths')
    if bool(args.company) != bool(args.role) or (not args.local_only and not args.company):
        parser.error('Company and Role are required together; omit only with --local-only')
    if (args.application_id or args.date) and not args.company:
        parser.error('--application-id and --date require Company and Role')
    for value in (args.company, args.role):
        if value is not None and (not value.strip() or any(c in value for c in '|\r\n')):
            parser.error('Company and Role cannot be blank or contain pipes/newlines')
    if args.date:
        date.fromisoformat(args.date)
    check_dependencies(notion=not args.local_only)
    out = ROOT / 'folder/outputs'
    source = out / f'{name}.tex'
    if not source.is_file():
        raise ValueError(f'Source not found: {source}')
    # Missing/empty keyword evidence is a hard failure before compilation.
    if args.document_type == 'resume':
        keywords = out / 'checks' / f'{name}_keywords.txt'
        if not keywords.is_file() or not any(line.strip() and not line.lstrip().startswith(('#', '~'))
                                              for line in keywords.read_text().splitlines()):
            raise ValueError(f'Required JD keywords missing: {keywords}')
    row = None
    with locked(ROOT / '.state/build.lock'):
        # Stage each build separately; a failed build never replaces the last verified PDF.
        with tempfile.TemporaryDirectory(prefix='.build-', dir=out) as temporary:
            stage = Path(temporary)
            result = subprocess.run(['pdflatex', '-interaction=nonstopmode', '-halt-on-error',
                                     '-no-shell-escape', f'-output-directory={stage}', '--', str(source)],
                                    cwd=out, capture_output=True, text=True)
            pdf = stage / f'{name}.pdf'
            if result.returncode or not pdf.is_file():
                print('\n'.join(result.stdout.splitlines()[-30:]), file=sys.stderr)
                raise RuntimeError('LaTeX compilation failed; no new PDF published')
            import fitz
            with fitz.open(pdf) as document:
                if document.page_count != 1:
                    raise ValueError(f'Expected 1 page, got {document.page_count}; no new PDF published')
            if args.document_type == 'resume':
                run([sys.executable, str(ROOT / 'checks/lint_resume.py'), name, '--pdf', str(pdf)])
                run([sys.executable, str(ROOT / 'checks/ats_check.py'), name, '--pdf', str(pdf)])
            destination = out / 'pdfs' / f'{name}.pdf'
            destination.parent.mkdir(exist_ok=True)
            os.replace(pdf, destination)
        print(f'PDF validated and published: {destination}', flush=True)
        if args.company:
            row = log_application(ROOT / 'applications.md', args.company, args.role, name,
                                  args.document_type, args.date, args.application_id)
            mark_sync(ROOT, row['Application ID'], 'pending')
            print(f'Application logged: {row["Application ID"]}', flush=True)
    if row and not args.local_only:
        command = [sys.executable, str(ROOT / 'scripts/sync_applications_to_notion.py'),
                   '--live', '--application-id', row['Application ID']]
        result = subprocess.run(command)
        if result.returncode:
            mark_sync(ROOT, row['Application ID'], 'failed', 'Sync did not complete')
            print('PDF ready; Notion sync FAILED. Retry: .venv/bin/python scripts/sync_applications_to_notion.py --live --pending', file=sys.stderr)
            return 1
        print('Complete: PDF ready, application logged, Notion synced.')
    elif row:
        print('Local build complete. Notion sync PENDING (--local-only).')
    else:
        print('Local PDF build complete; no application logged (--local-only).')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (RuntimeError, ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f'Build failed: {exc}', file=sys.stderr)
        sys.exit(1)
