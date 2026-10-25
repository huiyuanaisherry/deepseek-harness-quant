"""UI catalog fixture and navigation contract; no external requests."""
import importlib.util
import json
from pathlib import Path
import unittest
from deck.model_settings import ModelSettings

spec = importlib.util.spec_from_file_location('settings_fixture', Path(__file__).with_name('run_settings_fixture.py'))
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class SettingsUITests(unittest.TestCase):
    def test_native_key_default_and_removal(self):
        transport = fixture.FixtureTransport()
        service = ModelSettings(transport)
        self.assertEqual(service.describe()['providers'][0]['models'], [])
        service.save({'provider': 'deepseek', 'apiKey': 'synthetic-key', 'expectedRevision': 4})
        catalog = service.describe()
        self.assertEqual(catalog['providers'][0]['models'][0]['id'], 'deepseek-chat')
        self.assertNotIn('synthetic-key', json.dumps(catalog))
        service.set_default({'provider': 'deepseek', 'model': 'deepseek-chat', 'expectedRevision': 2})
        self.assertEqual(service.describe()['defaultModel']['provider'], 'deepseek')
        service.remove_key({'provider': 'deepseek'})
        self.assertFalse(service.describe()['providers'][0]['credential']['configured'])

    def test_partial_save_advances_revision_without_key(self):
        service = ModelSettings(fixture.FixtureTransport(partial=True))
        result = service.save({'provider': 'deepseek', 'apiKey': 'synthetic-key', 'expectedRevision': 4})
        self.assertTrue(result['partial'])
        self.assertEqual(service.describe()['providers'][0]['revision'], result['revision'])
        self.assertFalse(service.describe()['providers'][0]['credential']['configured'])

    def test_navigation_template_matches_and_includes_settings(self):
        root = Path(__file__).resolve().parents[1] / 'config'
        value = json.loads((root / 'navigation.json').read_text())
        self.assertEqual(value, json.loads((root / 'navigation.json.example').read_text()))
        self.assertTrue(any(row['url'] == '/settings' for row in value['more']))
