import subprocess,sys,unittest
from pathlib import Path
import frida
from navalhitrecorder import source

class DamageTests(unittest.TestCase):
    def setUp(self):
        self.child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(180)'])
        self.session=frida.attach(self.child.pid)
        code=source({'test':True,'details':True,'mode':'both'})
        for name in ('test_details_fixture.js','test_damage_fixture.js'):code+='\n'+Path(name).read_text(encoding='utf-8')
        self.script=self.session.create_script(code);self.script.load()
    def tearDown(self):
        self.script.unload();self.session.detach();self.child.terminate();self.child.wait(timeout=10)
    def check_damage(self,kind):
        r=self.script.exports_sync.damage(kind);d=r['first'];p=d['pairs'][0]
        self.assertEqual((p['str_loss_raw'],p['org_loss_raw'],p['damage_measured']),('700000','300000',5))
        self.assertEqual([e['str_loss_raw'] for e in d['samples']],['500000','0','0','100000','100000'])
        self.assertTrue(all(e['damage_status']=='measured' for e in d['samples']))
        self.assertEqual(d['damage_stats'],dict(read_errors=0,unmatched_calls=0,unfinished=0))
        self.assertEqual(r['empty']['pairs'],[]);self.assertEqual(r['empty']['samples'],[])
        self.assertEqual(r['health'],['750000','375000']);self.assertEqual(r['scopes'],0)
        self.script.exports_sync.stop()
    def test_heavy_actual_clamped_loss_and_multiple_shots(self):self.check_damage('heavy')
    def test_air_actual_clamped_loss_and_multiple_groups(self):self.check_damage('air')
    def test_invalid_healing_wrong_target_and_missing_scope(self):
        d=self.script.exports_sync.damageerrors()
        self.assertEqual(d['damage_stats'],dict(read_errors=2,unmatched_calls=1,unfinished=3))
        self.assertEqual(d['pairs'][0]['damage_measured'],0)
        self.assertTrue(all(e['damage_status']=='unavailable' for e in d['samples']))
    def test_nested_attacks_do_not_double_count(self):
        r=self.script.exports_sync.damagenested();p=r['details']['pairs'][0]
        self.assertEqual((p['str_loss_raw'],p['org_loss_raw'],p['damage_measured']),('300000','150000',2))
        self.assertEqual(r['scopes'],0)
    def test_convoy_reference_and_different_fields(self):
        d=self.script.exports_sync.damageconvoy();p=d['pairs'][0]
        self.assertEqual(p['target']['kind'],'convoy')
        self.assertEqual((p['str_loss_raw'],p['org_loss_raw']),('200000','50000'))
        self.assertEqual(d['damage_stats']['read_errors'],0)
    def test_pending_delta_is_replaced_and_stop_marks_unknown(self):
        r=self.script.exports_sync.damagepending()
        self.assertEqual(r['before']['samples'][0]['damage_status'],'pending')
        self.assertEqual(r['after']['samples'][0]['str_loss_raw'],'123456')
        self.assertEqual(r['after']['pairs'][0]['damage_measured'],1)
        self.assertEqual(r['stopped']['samples'][0]['damage_status'],'unavailable')
        self.assertEqual(r['stopped']['pairs'][0]['damage_measured'],1)

if __name__=='__main__':unittest.main()
