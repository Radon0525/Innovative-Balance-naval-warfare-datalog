import json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
import navalhitrecorder as app
from session_history import list_sessions,read_notes,save_notes,comparison_data
from detail_storage import DetailWriter

def trial(base,key,hits,country=1,sqlite=False):
    folder=Path(base)/'recordings'/key;folder.mkdir(parents=True)
    p=dict(kind='heavy',channel='heavy',context='battle',source=dict(id='a',name='大和',country=country),
        target=dict(id='b',name='相手',country=9),events=10,attempts=10,hits=hits,zero_groups=10-hits,
        damage_measured=10,str_loss_raw=str(hits*100000),org_loss_raw=str(hits*200000))
    d=dict(pairs=[p],samples=[],channels={'heavy':p},stats=dict(read_errors=0,pair_overflow=0),damage_enabled=True)
    doc=dict(version='test',mode='heavy',status='停止済み',started_at='2026-09-28T10:00:00+00:00',
        updated_at='2026-09-28T10:05:00+00:00',ended_at='2026-09-28T10:05:00+00:00',details=d)
    if sqlite:
        writer=DetailWriter(folder);doc['details']=writer.apply(d,dict(doc,counts=app.metrics([10,hits,10-hits,0,0,0,0,0,0,0])));writer.close()
    app.save_report(folder,[10,hits,10-hits,0,0,0,0,0,0,0],doc)
    return folder

class HistoryTests(unittest.TestCase):
    def test_annotations_preserve_measurements_and_legacy_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            a=trial(tmp,'a',2);b=trial(tmp,'b',7,sqlite=True)
            before=(a/'summary.json').read_bytes()
            save_notes(a,name='装甲A',notes='主砲変更前\n速力30');save_notes(a,notes='主砲変更後')
            self.assertEqual(read_notes(a)['name'],'装甲A');self.assertEqual((a/'summary.json').read_bytes(),before)
            rows,errors=list_sessions(tmp);self.assertEqual(len(rows),2);self.assertEqual(errors,[])
            self.assertIn('装甲A',[r['name'] for r in rows]);self.assertIn('b',[r['name'] for r in rows])
            bad=Path(tmp)/'recordings'/'broken';bad.mkdir();(bad/'summary.json').write_text('bad')
            rows,errors=list_sessions(tmp);self.assertEqual(len(rows),2);self.assertEqual(len(errors),1)
            with self.assertRaises(ValueError):save_notes(a,name='a'*201)
            self.assertEqual(read_notes(a)['name'],'装甲A')

    def test_compare_does_not_merge_and_country_ids_are_per_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            a=trial(tmp,'a',2,country=1);b=trial(tmp,'b',7,country=5,sqlite=True)
            results=comparison_data([a,b],[1,5],'own')
            self.assertEqual([r['rows'][0]['hits'] for r in results],[2,7])
            self.assertEqual([r['rows'][0]['str_loss_raw'] for r in results],['200000','700000'])
            self.assertEqual(comparison_data([b],[1],'own')[0]['rows'],[])
            self.assertIn('選択国',comparison_data([b],[1],'own')[0]['warning'])
            self.assertEqual(comparison_data([a],[None],'own')[0]['rows'],[])

    def test_two_recordings_are_independent_and_end_dates_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            device=Mock();process=Mock();process.name='hoi4.exe';process.pid=1;device.enumerate_processes.return_value=[process]
            script=device.attach.return_value.create_script.return_value
            script.exports_sync.snapshot.return_value=['0']*10
            script.exports_sync.detailsdelta.return_value=dict(pairs=[],samples=[],stats={},channels={})
            folders=[]
            with patch('frida.get_local_device',return_value=device),patch.object(app,'BASE',Path(tmp)),\
                patch.object(app,'process_path',return_value=Path('hoi4.exe')),patch.object(app,'source',return_value='test'),\
                patch.object(app,'profile_for',return_value=dict(version='test',sha256='test')):
                for hits in (2,7):
                    script.exports_sync.stop.return_value=list(map(str,[10,hits,10-hits,0,0,0,0,0,0,0]))
                    rec=app.Recorder();rec.stop_event.set()
                    self.assertTrue(rec.run(recording_name=f'設計{hits}'));folders.append(rec.folder)
            self.assertNotEqual(*folders)
            docs=[json.loads((p/'summary.json').read_text(encoding='utf-8')) for p in folders]
            self.assertEqual([d['counts']['heavy_hits'] for d in docs],[2,7])
            self.assertTrue(all(d['ended_at'] and d['elapsed_seconds']>=0 for d in docs))
            self.assertEqual([read_notes(p)['name'] for p in folders],['設計2','設計7'])

if __name__=='__main__':unittest.main()
