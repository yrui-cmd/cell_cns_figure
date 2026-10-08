"""Local-only credential resolution; no real keys or external API calls."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import credentials as k
import client as c


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.default = self.root / 'route-customer.txt'
        self.shared = self.root / 'xiaomiao_api.txt'
        self.patch = patch.object(k, 'shared_config_path', return_value=self.shared)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def key(self, path, value='img_live_test.fake'):
        path.write_text('API_Key="' + value + '"', encoding='utf-8')
        return path.resolve()

    def test_reuses_shared_config_without_disclosing_token(self):
        expected = self.key(self.shared)
        output = io.StringIO()
        with patch.object(c, 'DEFAULT_KEY', self.default), patch.object(sys, 'argv', ['client.py', 'discover-key']), contextlib.redirect_stdout(output):
            self.assertEqual(c.main(), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result['credential_file'], str(expected))
        self.assertTrue(result['local_only'])
        self.assertNotIn('img_live_', output.getvalue())

    def test_explicit_and_existing_default_take_priority(self):
        self.key(self.shared, 'img_live_shared.fake')
        expected = self.key(self.default)
        self.assertEqual(k.resolve_credential(self.default), expected)
        explicit = self.key(self.root / 'explicit.txt', 'img_live_explicit.fake')
        self.assertEqual(k.resolve_credential(self.default, explicit), explicit)

    def test_missing_explicit_does_not_switch_accounts(self):
        self.key(self.shared)
        with self.assertRaises(k.CredentialError):
            k.resolve_credential(self.default, self.root / 'missing.txt')

    def test_broken_existing_default_does_not_switch_accounts(self):
        self.key(self.shared)
        self.default.write_text('broken', encoding='utf-8')
        with self.assertRaises(k.CredentialError):
            k.resolve_credential(self.default)

    def test_unique_other_route_can_be_reused(self):
        expected = self.key(self.root / 'cell-figure-plus-customer.txt')
        self.key(self.root / 'figure_pro-customer.txt')
        self.assertEqual(k.resolve_credential(self.default), expected)

    def test_different_other_keys_require_selection(self):
        self.key(self.root / 'cell-figure-plus-customer.txt')
        self.key(self.root / 'figure_pro-customer.txt', 'img_live_another.fake')
        with self.assertRaises(k.CredentialError):
            k.resolve_credential(self.default)

    def test_missing_empty_and_trial_keys_are_not_accepted(self):
        with self.assertRaises(k.CredentialError):
            k.resolve_credential(self.default)
        for value in ('', 'jexp_trial', 'invalid key'):
            self.key(self.shared, value)
            with self.assertRaises(k.CredentialError):
                k.resolve_credential(self.default)

    @unittest.skipUnless(os.name == 'nt', 'Windows DPAPI')
    def test_existing_dpapi_format_remains_readable(self):
        k.save_token(self.default, 'img_live_test.fake')
        self.assertEqual(k.read_token(self.default), 'img_live_test.fake')
        self.assertEqual(k.resolve_credential(self.default), self.default.resolve())


if __name__ == '__main__':
    unittest.main()
