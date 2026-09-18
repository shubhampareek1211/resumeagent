"""Regression tests: real local LaTeX/PDF tools, mocked Notion network writes."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'checks'))
import applications as apps
import sync_applications_to_notion as sync
import ats_check as ats
import preflight

HEADER = '## Active\n\n| Date | Company | Role | Resume file | Cover letter | Status |\n|---|---|---|---|---|---|\n\n## Earlier\nHistorical notes\n'
SCHEMA = {'Company': 'title', 'Role': 'rich_text', 'Date': 'date', 'Resume file': 'rich_text',
          'Cover letter': 'rich_text', 'Status': 'select', 'Application ID': 'rich_text'}


def row(**updates):
    value = {'Company': 'Example', 'Role': 'ML Engineer', 'Date': '2026-09-17',
             'Resume file': 'shared_resume', 'Cover letter': '—', 'Status': 'Draft'}
    value.update(updates)
    value['Application ID'] = apps.application_id(value)
    return value


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'applications.md'
        self.path.write_text(HEADER)

    def log(self, company='Example', role='ML Engineer', name='shared_resume', **kw):
        return apps.log_application(self.path, company, role, name, 'resume', **kw)

    def test_reuse_resume_across_companies_roles_and_dates(self):
        first = self.log(day='2026-09-17')
        self.log(company='Second')
        self.log(role='Data Engineer')
        self.log(day='2026-09-18')
        rows = apps.read_manifest(self.path)[3]
        self.assertEqual(len(rows), 4)
        self.assertEqual(len({r['Application ID'] for _, r in rows}), 4)
        self.assertIn(first['Application ID'], {r['Application ID'] for _, r in rows})

    def test_rebuild_updates_file_preserves_identity_and_status(self):
        first = self.log(day='2026-09-17')
        self.path.write_text(self.path.read_text().replace('| Draft |', '| Interview |'))
        rebuilt = self.log(name='updated_cv')
        self.assertEqual(first['Application ID'], rebuilt['Application ID'])
        self.assertEqual(rebuilt['Status'], 'Interview')
        self.assertEqual(len(apps.read_manifest(self.path)[3]), 1)

    def test_cover_letter_attaches_to_same_application(self):
        first = self.log()
        updated = apps.log_application(self.path, 'Example', 'ML Engineer', 'letter', 'cover-letter')
        self.assertEqual(first['Application ID'], updated['Application ID'])
        self.assertEqual(updated['Resume file'], 'shared_resume')
        self.assertEqual(updated['Cover letter'], 'letter')

    def test_ambiguous_rebuild_requires_id(self):
        first = self.log(day='2026-09-17')
        self.log(day='2026-09-18')
        with self.assertRaises(ValueError): self.log()
        rebuilt = self.log(identity=first['Application ID'])
        self.assertEqual(rebuilt['Date'], '2026-09-17')

    def test_legacy_row_migration_keeps_data(self):
        self.path.write_text(HEADER.replace('\n\n## Earlier', '\n| 2026-06-03 | Old | Engineer | missing | — | Applied |\n\n## Earlier'))
        before = apps.read_manifest(self.path)[3][0][1]
        self.log()
        after = apps.read_manifest(self.path)[3][0][1]
        self.assertEqual(before, after)
        self.assertIn('Historical notes', self.path.read_text())

    def test_standalone_migration_is_idempotent_and_preserves_all_fields(self):
        self.path.write_text(HEADER.replace('\n\n## Earlier', '\n| 2026-06-03 | Old | Engineer | missing | — | Applied |\n\n## Earlier'))
        before = apps.read_manifest(self.path)[3][0][1]
        apps.migrate_manifest(self.path)
        migrated = self.path.read_text()
        self.assertIn('Application ID', migrated)
        self.assertEqual(apps.read_manifest(self.path)[3][0][1], before)
        apps.migrate_manifest(self.path)
        self.assertEqual(self.path.read_text(), migrated)

    def test_malformed_rows_not_silently_dropped(self):
        self.path.write_text(HEADER.replace('\n\n## Earlier', '\n| invalid row |\n\n## Earlier'))
        with self.assertRaises(ValueError): apps.read_manifest(self.path)


class NotionTests(unittest.TestCase):
    def setUp(self):
        self.client = SimpleNamespace(data_sources=SimpleNamespace(query=Mock(), update=Mock()),
                                      pages=SimpleNamespace(create=Mock(), update=Mock()))

    def test_lookup_uses_identity_and_all_legacy_dimensions(self):
        self.client.data_sources.query.side_effect = [{'results': []}, {'results': []}]
        value = row()
        self.assertIsNone(sync.find_existing(self.client, 'db', value, SCHEMA))
        filters = [call.kwargs['filter'] for call in self.client.data_sources.query.call_args_list]
        self.assertEqual(filters[0]['property'], 'Application ID')
        self.assertEqual(filters[1]['and'], [
            {'property': 'Company', 'title': {'equals': 'Example'}},
            {'property': 'Role', 'rich_text': {'equals': 'ML Engineer'}},
            {'property': 'Date', 'date': {'equals': '2026-09-17'}}])
        self.assertNotIn('Resume file', str(filters))

    def test_both_lookup_failures_propagate(self):
        for responses in ([TimeoutError()], [{'results': []}, TimeoutError()]):
            with self.subTest(responses=responses):
                self.client.data_sources.query.side_effect = responses
                with self.assertRaises(TimeoutError): sync.find_existing(self.client, 'db', row(), SCHEMA)

    def test_ambiguous_pages_stop_sync(self):
        self.client.data_sources.query.return_value = {'results': [{'id': 'a'}, {'id': 'b'}]}
        with self.assertRaises(ValueError): sync.find_existing(self.client, 'db', row(), SCHEMA)

    def test_legacy_match_migrates_and_renamed_company_type_supported(self):
        schema = dict(SCHEMA, Company='rich_text', Name='title')
        page = {'id': 'legacy', 'properties': {}}
        self.client.data_sources.query.side_effect = [{'results': []}, {'results': [page]}]
        self.assertEqual(sync.find_existing(self.client, 'db', row(), schema), page)
        self.assertIn('rich_text', self.client.data_sources.query.call_args.kwargs['filter']['and'][0])
        props = sync.build_notion_props(row(), schema)
        self.assertIn('Application ID', props)

    def run_main(self, temporary, args, values):
        with patch.object(sync, 'ROOT', temporary), patch.object(sync, 'load_dotenv'), \
             patch.object(sync, 'migrate_manifest'), \
             patch.object(sync, 'parse_active_table', return_value=values), \
             patch.object(sync, 'get_ds_id_and_schema', return_value=('db', dict(SCHEMA), 'Test', True)), \
             patch('notion_client.Client', return_value=self.client), \
             patch.dict(os.environ, NOTION_TOKEN='mock-token', NOTION_DB_ID='0' * 32), \
             patch.object(sys, 'argv', ['sync'] + args + ['--sleep', '0']), contextlib.redirect_stdout(io.StringIO()):
            return sync.main()

    def test_live_failure_never_creates_and_retry_clears_pending(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.client.data_sources.query.side_effect = [ {'results': []}, TimeoutError() ]
            self.assertEqual(self.run_main(root, ['--live'], [row()]), 1)
            self.client.pages.create.assert_not_called()
            self.assertEqual(apps.sync_state(root)[row()['Application ID']]['status'], 'failed')
            self.client.data_sources.query.side_effect = [{'results': []}, {'results': []}]
            self.assertEqual(self.run_main(root, ['--live', '--pending'], [row()]), 0)
            self.client.pages.create.assert_called_once()
            self.assertEqual(apps.sync_state(root)[row()['Application ID']]['status'], 'synced')

    def test_retry_after_uncertain_create_updates_existing_id(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.client.data_sources.query.side_effect = [{'results': []}, {'results': []}]
            self.client.pages.create.side_effect = TimeoutError()
            self.assertEqual(self.run_main(root, ['--live'], [row()]), 1)
            self.client.data_sources.query.side_effect = [{'results': [{'id': 'created-before-timeout'}]}]
            self.assertEqual(self.run_main(root, ['--live', '--pending'], [row()]), 0)
            self.client.pages.create.assert_called_once()
            self.assertEqual(self.client.pages.update.call_args.kwargs['page_id'], 'created-before-timeout')

    def test_identity_schema_added_once_for_legacy_database(self):
        schema = {k: v for k, v in SCHEMA.items() if k != 'Application ID'}
        sync.ensure_identity_property(self.client, 'db', schema, True)
        sync.ensure_identity_property(self.client, 'db', schema, True)
        self.client.data_sources.update.assert_called_once_with(
            data_source_id='db', properties={'Application ID': {'rich_text': {}}})

    def test_dry_run_lookup_error_is_nonzero_and_no_writes(self):
        self.client.data_sources.query.side_effect = TimeoutError()
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.run_main(Path(d), ['--dry-run'], [row()]), 1)
            self.assertFalse((Path(d) / '.state').exists())
        self.client.pages.create.assert_not_called()
        self.client.pages.update.assert_not_called()

    def test_exact_id_filter_does_not_sync_other_rows(self):
        first, second = row(), row(Role='Data Engineer')
        self.client.data_sources.query.side_effect = [{'results': []}, {'results': []}]
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.run_main(Path(d), ['--live', '--application-id', first['Application ID']], [first, second]), 0)
        self.client.pages.create.assert_called_once()
        self.assertEqual(self.client.pages.create.call_args.kwargs['properties']['Role']['rich_text'][0]['text']['content'], 'ML Engineer')

    def test_incompatible_schema_rejected(self):
        with self.assertRaises(ValueError): sync.validate_schema(dict(SCHEMA, Date='rich_text'))


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='resume-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('scripts', 'checks'):
            shutil.copytree(ROOT / name, self.root / name, ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copy(ROOT / 'build.sh', self.root / 'build.sh')
        shutil.copy(ROOT / 'profile.example.json', self.root / 'profile.example.json')
        (self.root / '.venv').symlink_to(ROOT / '.venv', target_is_directory=True)
        self.out = self.root / 'folder/outputs'
        (self.out / 'checks').mkdir(parents=True)
        (self.root / 'applications.md').write_text(HEADER)
        self.source = r'\documentclass{article}\begin{document}Python\end{document}'

    def build(self, name, *args):
        return subprocess.run(['bash', str(self.root / 'build.sh'), '--type', 'resume', name, *args], capture_output=True, text=True)

    def put(self, name='test_cv', keywords='Python\n'):
        (self.out / f'{name}.tex').write_text(self.source)
        if keywords is not None: (self.out / f'checks/{name}_keywords.txt').write_text(keywords)

    def test_type_is_required(self):
        result = subprocess.run(['bash', str(self.root / 'build.sh'), 'test_cv', '--local-only'], capture_output=True)
        self.assertEqual(result.returncode, 2)

    def test_missing_keywords_blocks_publication_and_logging(self):
        self.put(keywords=None)
        result = self.build('test_cv', 'Example', 'Engineer', '--local-only')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Required JD keywords missing', result.stderr)
        self.assertFalse((self.out / 'pdfs/test_cv.pdf').exists())
        self.assertEqual((self.root / 'applications.md').read_text(), HEADER)

    def test_cv_name_gets_full_lint(self):
        self.put()
        result = self.build('test_cv', '--local-only')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('E2 sections: missing', result.stdout)
        self.assertFalse((self.out / 'pdfs/test_cv.pdf').exists())

    def test_explicit_cover_letter_works_and_logs_cover_column(self):
        self.put()
        result = subprocess.run(['bash', str(self.root / 'build.sh'), '--type', 'cover-letter', 'test_cv', 'Example', 'Engineer', '--local-only'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        value = apps.read_manifest(self.root / 'applications.md')[3][0][1]
        self.assertEqual(value['Resume file'], '—')
        self.assertEqual(value['Cover letter'], 'test_cv')
        self.assertEqual(apps.sync_state(self.root)[value['Application ID']]['status'], 'pending')

    def put_sample_resume(self):
        shutil.copy(ROOT / 'examples/sample_resume.tex', self.out / 'real_cv.tex')
        shutil.copy(ROOT / 'examples/sample_keywords.txt', self.out / 'checks/real_cv_keywords.txt')

    def test_sample_resume_passes_pdf_gates_under_cv_filename(self):
        self.put_sample_resume()
        result = self.build('real_cv', '--local-only')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('ATS coverage passed', result.stdout)
        self.assertTrue((self.out / 'pdfs/real_cv.pdf').exists())

    def test_failed_rebuild_preserves_previous_verified_pdf(self):
        self.put_sample_resume()
        first = self.build('real_cv', '--local-only')
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        original = (self.out / 'pdfs/real_cv.pdf').read_bytes()
        (self.out / 'real_cv.tex').write_text('invalid latex')
        self.assertNotEqual(self.build('real_cv', '--local-only').returncode, 0)
        self.assertEqual((self.out / 'pdfs/real_cv.pdf').read_bytes(), original)

    def test_sync_failure_preserves_pdf_and_retry_state(self):
        self.put_sample_resume()
        # Replace only network entry point; run the actual compiler, lint, ATS and logger.
        (self.root / 'scripts/sync_applications_to_notion.py').write_text('raise SystemExit(1)\n')
        result = self.build('real_cv', 'Example', 'Engineer')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertTrue((self.out / 'pdfs/real_cv.pdf').exists())
        value = apps.read_manifest(self.root / 'applications.md')[3][0][1]
        self.assertEqual(apps.sync_state(self.root)[value['Application ID']]['status'], 'failed')
        self.assertIn('Notion sync FAILED', result.stderr)

    def test_full_build_invokes_sync_for_only_logged_id(self):
        self.put_sample_resume()
        (self.root / 'scripts/sync_applications_to_notion.py').write_text(
            'import json, sys\nfrom pathlib import Path\n'
            'from applications import mark_sync\n'
            'root = Path(__file__).resolve().parent.parent\n'
            'assert sys.argv[1:3] == ["--live", "--application-id"]\n'
            'assert len(sys.argv) == 4\n'
            'mark_sync(root, sys.argv[3], "synced")\n')
        result = self.build('real_cv', 'Example', 'Engineer')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        value = apps.read_manifest(self.root / 'applications.md')[3][0][1]
        self.assertEqual(apps.sync_state(self.root)[value['Application ID']]['status'], 'synced')
        self.assertIn('Notion synced', result.stdout)

    def test_ats_excludes_comments_urls_and_unused_macros(self):
        source = r'''\documentclass{article}
\usepackage{hyperref}
\newcommand{\unused}{Snowflake}
\begin{document}
Python % Kubernetes
\href{https://example.com/Azure}{Portfolio}
\end{document}'''
        path = self.out / 'hidden.tex'
        path.write_text(source)
        result = subprocess.run(['pdflatex', '-interaction=nonstopmode', '-halt-on-error', '-no-shell-escape', str(path)], cwd=self.out, capture_output=True)
        self.assertEqual(result.returncode, 0)
        text = ats.extract_pdf_text(self.out / 'hidden.pdf')
        self.assertTrue(ats.covered('Python', text))
        for keyword in ('Kubernetes', 'Azure', 'Snowflake'):
            self.assertFalse(ats.covered(keyword, text))
        (self.out / 'checks/hidden_keywords.txt').write_text('Kubernetes\nAzure\nSnowflake\n')
        result = subprocess.run([sys.executable, str(self.root / 'checks/ats_check.py'), 'hidden', '--pdf', str(self.out / 'hidden.pdf')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('0/3', result.stdout)


class DependencyTests(unittest.TestCase):
    def test_missing_dependencies_fail_preflight(self):
        with patch.object(preflight.importlib.util, 'find_spec', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'PyMuPDF.*notion-client'):
                preflight.check_dependencies()

    def test_pdf_keyword_normalization_and_boundaries(self):
        self.assertTrue(ats.covered('Machine Learning', 'Machine\n Learning'))
        self.assertTrue(ats.covered('Retrieval-Augmented Generation', 'Retrieval‑Augmented Generation'))
        self.assertTrue(ats.covered('C++|C#', 'C#'))
        self.assertFalse(ats.covered('AI', 'training'))
        self.assertFalse(ats.covered('Go', 'good'))


if __name__ == '__main__':
    unittest.main()
