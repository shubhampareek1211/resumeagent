#!/usr/bin/env python3
"""Inspect Git index blobs, not working-tree files, before publication."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def check():
    tracked = [p for p in git('ls-files', '-z').decode().split('\0') if p]
    approved = set(git('show', ':public-files.txt').decode().splitlines())
    issues = []
    patterns = {
        'credential-like token': rb'(?i)(?<![A-Za-z0-9_])(?:ntn_|secret_|gh[pousr]_)[A-Za-z0-9_]{20,}',
        'private key': rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
        'local home path': rb'/(?:Users|home)/[A-Za-z0-9_.-]+/',
        'phone number': rb'(?<!\d)\d{3}[-.]\d{3}[-.]\d{4}(?!\d)',
    }
    for path in tracked:
        if path not in approved:
            issues.append(f'{path}: absent from reviewed public-files.txt')
        parts = Path(path).parts
        if (Path(path).name.startswith('.env.') and Path(path).name != '.env.example') or any(part in {'.env', '.venv', '.state', 'references', 'inputs', 'outputs', '.claude', '.codex'} for part in parts) or path.endswith(('.pdf', '.docx', '.png', '.jpg', '.jpeg', '.pyc')) or path in {'applications.md', 'truth_ledger.md', 'bullet_bank.md', 'profile.local.json', 'cv.md'}:
            issues.append(f'{path}: private/generated path cannot be published')
        mode = git('ls-files', '-s', '--', path).split()[0]
        if mode != b'100644' and mode != b'100755':
            issues.append(f'{path}: symlinks/submodules are not permitted')
        data = git('show', ':' + path)
        if b'\0' in data:
            issues.append(f'{path}: binary file is not permitted')
        for label, pattern in patterns.items():
            if re.search(pattern, data):
                issues.append(f'{path}: {label} detected (value redacted)')
        for email in re.findall(rb'[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})', data):
            if email.lower() not in {b'example.com', b'example.org', b'example.net'}:
                issues.append(f'{path}: non-example email address detected (value redacted)')
    if set(tracked) != approved:
        issues.append('public-files.txt must exactly match tracked paths')
    if issues:
        print('\n'.join(issues))
        return 1
    print(f'Public tree verified: {len(tracked)} reviewed text files; no private paths or detected credentials.')
    return 0


if __name__ == '__main__':
    raise SystemExit(check())
