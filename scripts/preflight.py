"""Check dependencies before creating or publishing any artifacts."""
import importlib.util
import shutil
import sys


def check_dependencies(notion=True):
    missing = [name for name in ('pdflatex', 'pdftotext') if not shutil.which(name)]
    for module, package in [('fitz', 'PyMuPDF')] + ([('notion_client', 'notion-client')] if notion else []):
        if importlib.util.find_spec(module) is None:
            missing.append(package)
    if missing:
        raise RuntimeError('Missing dependencies: ' + ', '.join(missing) +
                           '. Run ./scripts/setup.sh; install TeX Live and Poppler (see README) for system commands.')


if __name__ == '__main__':
    try:
        check_dependencies()
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        sys.exit(2)
    print('Dependencies ready.')
