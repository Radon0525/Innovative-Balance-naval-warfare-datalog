import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import frida
from navalhitrecorder import source
from air_participants import participant_totals, value_text, description, load_document
from detail_storage import DetailWriter

BASE = Path(__file__).resolve().parent

class FirstCensusTests(unittest.TestCase):
    def setUp(self):
        self.child = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(180)'])
        self.session = frida.attach(self.child.pid)
        code = source({'test': True, 'details': False, 'mode': 'air'})
        for name in ('test_details_fixture.js', 'test_air_participants_fixture.js'):
            code += '\n' + (BASE / name).read_text(encoding='utf-8')
        self.script = self.session.create_script(code); self.errors = []
        self.script.on('message', lambda msg, _: self.errors.append(msg) if msg['type'] == 'error' else None)
        self.script.load()

    def tearDown(self):
        self.script.exports_sync.stop(); self.script.unload(); self.session.detach()
        self.child.terminate(); self.child.wait(timeout=10)
        self.assertEqual(self.errors, [])

    def test_native_two_countries_dedup_and_hooks_detach(self):
        result = self.script.exports_sync.census(); data = result['first']
        self.assertEqual(data['status'], 'complete'); self.assertEqual(data['association'], 'preceding_air_update')
        self.assertFalse(data['hooks_active']); self.assertEqual(result['remaining_hooks'], 0)
        self.assertEqual(result['first'], result['after'])
        self.assertEqual(len(data['rows']), 7); self.assertEqual(data['naval_groups'], 2)
        self.assertEqual(data['candidate_calls'], 2); self.assertEqual(data['pair_calls'], 3)
        totals = {row['country']: row for row in participant_totals(data) if row['category'] == 'total'}
        self.assertEqual([totals[n]['registered'] for n in (1, 2)], [112, 175])
        self.assertEqual([totals[n]['candidate'] for n in (1, 2)], [112, 175])
        self.assertEqual([totals[n]['escort'] for n in (1, 2)], [35, 55])
        self.assertEqual([totals[n]['naval_ready'] for n in (1, 2)], [77, 80])
        self.assertEqual([totals[n]['naval_assigned'] for n in (1, 2)], [77, 80])
        self.assertEqual([totals[n]['shot_allocated_raw'] for n in (1, 2)], [800000, 600000])
        self.assertEqual({row['category'] for row in data['rows']}, {'carrier_bomber', 'carrier_fighter', 'land_fighter', 'land_bomber'})
        self.assertTrue(any(row['normal'] and row['automatic'] for row in data['rows']))
        with tempfile.TemporaryDirectory() as folder:
            doc = {'updated_at': '2026-10-01', 'air_participants': data}
            writer = DetailWriter(folder); details = writer.apply({'pairs': [], 'samples': []}, doc); writer.close()
            (Path(folder) / 'summary.json').write_text(json.dumps(dict(doc, details=details)), encoding='utf-8')
            self.assertEqual(load_document(folder)['air_participants'], data)

    def test_same_update(self):
        data = self.script.exports_sync.census('same')['first']
        self.assertEqual(data['association'], 'same_air_update'); self.assertEqual(data['status'], 'complete')

    def test_waits_for_region_and_keeps_first_naval_update(self):
        result = self.script.exports_sync.census('following')
        self.assertEqual(result['waiting']['status'], 'waiting_regional_update')
        self.assertEqual(result['result']['association'], 'following_air_update')
        self.assertEqual(result['result']['status'], 'complete')

    def test_stop_without_air_update_preserves_unknown(self):
        data = self.script.exports_sync.census('partial')
        self.assertEqual(data['status'], 'partial'); self.assertFalse(data['regional_observed'])
        row = participant_totals(data)[0]
        self.assertEqual(value_text(data, row, 'registered'), '未観測')
        self.assertEqual(value_text(data, row, 'candidate'), '未観測')
        self.assertTrue(value_text(data, row, 'naval_assigned').endswith('（一部）'))

    def test_read_failure_is_partial_and_never_silently_zero(self):
        data = self.script.exports_sync.census('bad_count')['first']
        self.assertEqual(data['status'], 'partial'); self.assertGreater(data['stats']['read_errors'], 0)
        self.assertIn('一部', value_text(data, participant_totals(data)[0], 'registered'))

    def test_no_event_and_old_record(self):
        data = self.script.exports_sync.census('stop_empty')
        self.assertEqual(data['status'], 'not_observed'); self.assertFalse(data['hooks_active'])
        self.assertEqual(data['rows'], []); self.assertIn('旧記録', description({}))

    def test_acknowledgement_removes_repeated_payload_and_stop_keeps_complete(self):
        data = self.script.exports_sync.census()['first']
        self.assertTrue(self.script.exports_sync.ackairparticipants())
        header = self.script.exports_sync.airparticipants()
        self.assertNotIn('rows', header); self.assertEqual(header['row_count'], len(data['rows']))
        self.assertEqual(header['storage'], 'air_participants.json')
        self.script.exports_sync.stop()
        self.assertEqual(self.script.exports_sync.airparticipants()['status'], 'complete')
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'summary.json').write_text(json.dumps({'air_participants': header}), encoding='utf-8')
            self.assertEqual(load_document(folder)['air_participants']['status'], 'partial')
            (Path(folder) / 'air_participants.json').write_text(json.dumps(data), encoding='utf-8')
            self.assertEqual(load_document(folder)['air_participants'], data)

    def test_limits_are_explicit(self):
        data = self.script.exports_sync.census('limit')['first']
        self.assertEqual(data['status'], 'partial'); self.assertGreater(data['stats']['omitted_wings'], 0)
        self.assertEqual(data['limits']['vector'], 1)

    def test_unknown_base_is_never_assumed_land(self):
        data = self.script.exports_sync.census('unknown_origin')['first']
        totals = {(r['country'], r['category']): r for r in participant_totals(data)}
        self.assertEqual(totals[(1, 'land_fighter')]['registered'], 0)
        self.assertEqual(totals[(1, 'other')]['registered'], 15)

if __name__ == '__main__': unittest.main()
