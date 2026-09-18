#!/usr/bin/env python3
"""Package only the committed source after public-tree validation."""
import hashlib
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent


def main():
    subprocess.run([sys.executable, str(ROOT / 'scripts/check_public_tree.py')], check=True)
    # An index different from HEAD must never pass a HEAD archive using another tree's scan.
    subprocess.run(['git', 'diff', '--exit-code', '--cached', 'HEAD'], cwd=ROOT, check=True)
    sha = subprocess.check_output(['git', 'rev-parse', '--short=12', 'HEAD'], cwd=ROOT, text=True).strip()
    out = ROOT / 'dist'
    out.mkdir(exist_ok=True)
    archive = out / f'resumeagent-{sha}.tar.gz'
    subprocess.run(['git', 'archive', '--format=tar.gz', '--prefix=resumeagent/', f'--output={archive}', 'HEAD'], cwd=ROOT, check=True)
    (out / 'SHA256SUMS').write_text(f'{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n')
    print(f'Packaged reviewed commit {sha}.')


if __name__ == '__main__':
    main()
