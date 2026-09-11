import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'skills/hypeproof-keeper/scripts/check_context.py'
spec = importlib.util.spec_from_file_location('keeper', SCRIPT)
keeper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(keeper)


def item(**overrides):
    return dict(id='one', key='program.date', value='September 16', owner='owner', source='decision.md',
                status='active', verified_at='2026-09-01', review_after='2026-09-10', **{}) | overrides


class CrewTests(unittest.TestCase):
    def run_audit(self, items):
        return keeper.audit({'version': 1, 'items': items}, date(2026, 9, 11))

    def test_deadline_boundary_and_inactive_history(self):
        self.assertEqual(self.run_audit([item()])['overdue_count'], 1)
        self.assertEqual(self.run_audit([item(review_after='2026-09-11')])['overdue_count'], 0)
        for state in ['closed', 'superseded']:
            self.assertEqual(self.run_audit([item(status=state)])['overdue_count'], 0)

    def test_conflict_keeps_both_sources(self):
        report = self.run_audit([item(), item(id='two', value='September 17', source='second.md')])
        self.assertEqual(report['conflict_count'], 1)
        self.assertEqual(report['findings'][-1]['sources'], ['decision.md', 'second.md'])
        self.assertEqual(self.run_audit([item(), item(id='two')])['conflict_count'], 0)

    def test_invalid_input_is_not_clean(self):
        for items in [[item(), item()], [item(owner='')], [item(status='maybe')],
                      [item(verified_at='2027-01-01')], [item(review_after='bad')],
                      [item(review_after='2026-08-01')]]:
            with self.subTest(items=items), self.assertRaises(ValueError):
                self.run_audit(items)

    def test_cli_preserves_input_and_rejects_broken_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'register.json'
            payload = json.dumps({'version': 1, 'items': [item()]})
            path.write_text(payload)
            result = subprocess.run([sys.executable, str(SCRIPT), str(path), '--as-of', '2026-09-11'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout)['overdue_count'], 1)
            self.assertEqual(path.read_text(), payload)
            path.write_text('{broken')
            result = subprocess.run([sys.executable, str(SCRIPT), str(path), '--as-of', '2026-09-11'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, '')

    def test_skill_discovery_links(self):
        for name in ['scout', 'compass', 'forge', 'lens', 'keeper']:
            canonical = ROOT / f'skills/hypeproof-{name}/SKILL.md'
            for host in ['.agents', '.claude']:
                self.assertEqual((ROOT / host / f'skills/hypeproof-{name}/SKILL.md').resolve(), canonical)
                self.assertTrue(canonical.is_file())


if __name__ == '__main__':
    unittest.main()
