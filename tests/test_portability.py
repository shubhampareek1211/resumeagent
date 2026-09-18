"""Verify private initialization and the publication boundary using synthetic data."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import init_local
import profile_config
import check_public_tree


class LocalSetupTests(unittest.TestCase):
    def test_init_is_idempotent_and_preserves_secrets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for filename in ('.env.example', 'profile.example.json'):
                shutil.copy(ROOT / filename, root / filename)
            with contextlib.redirect_stdout(io.StringIO()):
                init_local.initialize(root)
                (root / '.env').write_text('PRIVATE_VALUE=keep-local\n')
                init_local.initialize(root)
            self.assertEqual((root / '.env').read_text(), 'PRIVATE_VALUE=keep-local\n')
            self.assertTrue((root / 'folder/outputs/checks').is_dir())
            self.assertIn('Application ID', (root / 'applications.md').read_text())
            self.assertEqual((root / 'profile.local.json').stat().st_mode & 0o777, 0o600)

    def test_profile_is_per_user_and_validated(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copy(ROOT / 'profile.example.json', root / 'profile.example.json')
            profile = profile_config.load_profile(root)
            profile['header_tokens'] = ['Another', 'Example']
            (root / 'profile.local.json').write_text(json.dumps(profile))
            self.assertEqual(profile_config.load_profile(root)['header_tokens'], ['Another', 'Example'])
            profile['min_fill_ratio'] = 2
            (root / 'profile.local.json').write_text(json.dumps(profile))
            with self.assertRaises(ValueError): profile_config.load_profile(root)


class PublicationTests(unittest.TestCase):
    def scan(self, content, filename='sample.txt', working_content=None):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            (root / 'public-files.txt').write_text('public-files.txt\n' + filename + '\n')
            (root / filename).write_text(content)
            subprocess.run(['git', 'add', '.'], cwd=root, check=True)
            if working_content is not None:
                (root / filename).write_text(working_content)
            with patch.object(check_public_tree, 'ROOT', root), contextlib.redirect_stdout(io.StringIO()):
                return check_public_tree.check()

    def test_safe_example_allowed(self):
        self.assertEqual(self.scan('A fictional email: casey@example.com'), 0)

    def test_private_path_rejected_even_if_inventory_includes_it(self):
        self.assertEqual(self.scan('no secret needed', '.env'), 1)

    def test_staged_secret_detected_after_working_copy_cleanup(self):
        self.assertEqual(self.scan('ntn_' + 'a' * 32, working_content='cleaned working copy'), 1)

    def test_nonexample_contact_rejected(self):
        self.assertEqual(self.scan('candidate' + '@' + 'private.invalid'), 1)


if __name__ == '__main__':
    unittest.main()
