import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import navalhitrecorder as app

SAMPLE=[10,2,8,3,151,26,1,7,8,0]

class AppTests(unittest.TestCase):
    def test_denominators(self):
        data=app.metrics(SAMPLE)
        self.assertEqual(data['heavy_hit_rate'],.2)
        self.assertEqual(data['air_success_rate'],26/151)
        self.assertIsNone(app.metrics([0]*10)['air_success_rate'])
        with self.assertRaises(ValueError):app.metrics([1]*10)

    def test_unrecognized_binary(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'unknown.exe';path.write_bytes(b'unknown')
            with self.assertRaises(RuntimeError):app.profile_for(path)

    def test_reports_and_unselected_channel(self):
        with tempfile.TemporaryDirectory() as folder:
            app.save_report(Path(folder),SAMPLE,{'version':'test','mode':'heavy','status':'停止済み','started_at':'test'})
            doc=json.loads((Path(folder)/'summary.json').read_text(encoding='utf-8'))
            self.assertEqual(doc['counts']['heavy_hits'],2)
            self.assertIn('このセッションでは収集していません',(Path(folder)/'report.html').read_text(encoding='utf-8'))

    def test_lifecycle(self):
        with tempfile.TemporaryDirectory() as folder:
            device=Mock();p=Mock();p.name='hoi4.exe';p.pid=1
            device.enumerate_processes.return_value=[p]
            session=device.attach.return_value;script=session.create_script.return_value
            script.exports_sync.snapshot.return_value=['0']*10
            script.exports_sync.stop.return_value=list(map(str,SAMPLE))
            script.exports_sync.detailsdelta.return_value={'schema_version':2,'stats':{'events':13,'read_errors':0,'pair_overflow':0,'sample_omitted':0},'pairs':[],'samples':[],'channels':{},'pair_limit':20000,'sample_limit':2000}
            aircraft={'status':'complete','rows':[{'country':1,'category':'carrier_bomber','naval_ready':77}]}
            script.exports_sync.airparticipants.side_effect=[aircraft,dict(status='complete',storage='air_participants.json',row_count=1)]
            events=[]
            def notify(event):
                events.append(event)
                if event.get('status')=='収集中':recorder.stop_event.set()
            recorder=app.Recorder(notify)
            with patch('frida.get_local_device',return_value=device),patch.object(app,'BASE',Path(folder)),\
                 patch.object(app,'process_path',return_value=Path('hoi4.exe')),\
                 patch.object(app,'profile_for',return_value={'version':'test','sha256':'test','air_participant_layout':{'version':1}}),\
                 patch.object(app,'source',return_value='test'):
                self.assertTrue(recorder.run())
            doc=json.loads((recorder.folder/'summary.json').read_text(encoding='utf-8'))
            self.assertEqual(doc['status'],'停止済み')
            self.assertEqual(doc['counts']['air_successes'],26)
            self.assertEqual(doc['air_participants']['row_count'],1);self.assertNotIn('rows',doc['air_participants'])
            self.assertEqual(json.loads((recorder.folder/'air_participants.json').read_text(encoding='utf-8')),aircraft)
            script.exports_sync.ackairparticipants.assert_called_once()
            with (recorder.folder/'checkpoints.csv').open(encoding='utf-8-sig',newline='') as file:rows=list(csv.reader(file))
            self.assertEqual(len(rows),3)
            self.assertEqual(list(map(int,rows[-1][2:])),SAMPLE)
            script.unload.assert_called_once();session.detach.assert_called_once()

    def test_no_game_no_attach(self):
        device=Mock();device.enumerate_processes.return_value=[]
        events=[]
        with patch('frida.get_local_device',return_value=device):
            self.assertFalse(app.Recorder(events.append).run())
        device.attach.assert_not_called()
        self.assertIsNone(events[-1]['folder'])
        self.assertIn('HOI4を1つ',events[-1]['error'])

if __name__=='__main__':unittest.main(verbosity=2)
