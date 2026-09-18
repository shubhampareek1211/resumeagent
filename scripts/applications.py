"""Application identity, atomic manifest edits, and durable sync status."""
from contextlib import contextmanager
from datetime import date
import fcntl
import json
from pathlib import Path
import re
import tempfile
import os
import uuid

ROOT = Path(__file__).resolve().parent.parent
FIELDS = ['Date', 'Company', 'Role', 'Resume file', 'Cover letter', 'Status', 'Application ID']


def norm(value):
    return ' '.join(value.split()).casefold()


def application_id(row):
    explicit = row.get('Application ID', '').strip()
    if explicit:
        return str(uuid.UUID(explicit))
    key = json.dumps([norm(row[k]) for k in ('Company', 'Role', 'Date')])
    return str(uuid.uuid5(uuid.NAMESPACE_URL, 'resumeagent:' + key))


@contextmanager
def locked(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_manifest(path):
    lines = path.read_text(encoding='utf-8').splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith('## Active')), None)
    end = next((i for i, line in enumerate(lines) if line.startswith('## Earlier')), None)
    if start is None or end is None or end <= start:
        raise ValueError('Manifest requires ordered ## Active and ## Earlier sections')
    rows = []
    header = None
    for i in range(start + 1, end):
        line = lines[i].strip()
        if not line.startswith('|'):
            continue
        cells = [c.strip() for c in line.strip('|').split('|')]
        if cells[0] == 'Date':
            header = cells
            if cells not in (FIELDS, FIELDS[:6]):
                raise ValueError('Unexpected application table columns')
            continue
        if re.fullmatch(r'[-:\s|]+', '|'.join(cells)):
            continue
        if header is None or len(cells) != len(header):
            raise ValueError(f'Malformed application row at line {i + 1}')
        row = dict(zip(header, cells))
        date.fromisoformat(row['Date'])
        row['Application ID'] = application_id(row)
        rows.append((i, row))
    ids = [row['Application ID'] for _, row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate application identity in manifest; resolve before syncing')
    return lines, start, end, rows


def write_manifest(path, lines, start, end, rows):
    table = ['| ' + ' | '.join(FIELDS) + ' |', '|' + '|'.join(['---'] * len(FIELDS)) + '|']
    table += ['| ' + ' | '.join(r[k] for k in FIELDS) + ' |' for r in rows]
    notes = [line for line in lines[start + 1:end] if line.strip() and not line.lstrip().startswith('|')]
    atomic_write(path, '\n'.join(lines[:start + 1] + [''] + notes + [''] + table + [''] + lines[end:]) + '\n')


def migrate_manifest(path):
    """Persist deterministic IDs for old rows without changing their six existing fields."""
    with locked(path.parent / '.state/applications.lock'):
        lines, start, end, indexed = read_manifest(path)
        if not any('Application ID' in line for line in lines[start:end] if line.startswith('| Date |')):
            write_manifest(path, lines, start, end, [r for _, r in indexed])


def log_application(path, company, role, name, document_type, day=None, identity=None):
    for value in (company, role, name):
        if not value.strip() or any(c in value for c in '|\n\r'):
            raise ValueError('Application fields must be nonempty and cannot contain pipes or newlines')
    if day:
        date.fromisoformat(day)
    with locked(path.parent / '.state/applications.lock'):
        lines, start, end, indexed = read_manifest(path)
        rows = [r for _, r in indexed]
        if identity:
            identity = str(uuid.UUID(identity))
            matches = [r for r in rows if r['Application ID'] == identity]
            if len(matches) != 1:
                raise ValueError('Application ID must identify an existing application')
            row = matches[0]
            if norm(row['Company']) != norm(company) or norm(row['Role']) != norm(role):
                raise ValueError('Application ID does not match Company and Role')
            if day and row['Date'] != day:
                raise ValueError('Application ID does not match Date')
        else:
            matches = [r for r in rows if norm(r['Company']) == norm(company) and norm(r['Role']) == norm(role)
                       and (day is None or r['Date'] == day)]
            if len(matches) > 1:
                raise ValueError('Multiple applications match; specify --application-id or --date')
            row = matches[0] if matches else dict(zip(FIELDS[:6], [day or date.today().isoformat(), company, role, '—', '—', 'Draft']))
            if not matches:
                row['Application ID'] = application_id(row)
                rows.append(row)
        row['Resume file' if document_type == 'resume' else 'Cover letter'] = name
        write_manifest(path, lines, start, end, rows)
        return dict(row)


def sync_state(root):
    path = root / '.state/notion_sync.json'
    return json.loads(path.read_text()) if path.exists() else {}


def mark_sync(root, identity, status, error=None):
    with locked(root / '.state/status.lock'):
        state = sync_state(root)
        state[identity] = {'status': status}
        if error:
            state[identity]['error'] = error
        atomic_write(root / '.state/notion_sync.json', json.dumps(state, indent=2) + '\n')
