import subprocess,sys,unittest
from pathlib import Path
import frida
from navalhitrecorder import source
from naval_details import aggregate,direction,country_choices

class DetailedNativeTests(unittest.TestCase):
    def setUp(self):
        self.child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(180)'])
        self.session=frida.attach(self.child.pid)
        self.script=self.session.create_script(source({'test':True,'details':True,'mode':'both'})+'\n'+Path('test_details_fixture.js').read_text(encoding='utf-8'))
        self.script.load()
    def tearDown(self):
        self.script.unload();self.session.detach();self.child.terminate();self.child.wait(timeout=10)
    def test_contexts_and_names(self):
        d=self.script.exports_sync.readers()
        self.assertEqual(d['stats']['events'],9)
        self.assertEqual(d['channels']['heavy'],{'events':3,'attempts':3,'hits':1})
        self.assertEqual(d['channels']['carrier_mission'],{'events':2,'attempts':90,'hits':10})
        self.assertEqual(d['channels']['carrier_battle']['hits'],25)
        self.assertEqual(d['channels']['land_mission']['hits'],3)
        self.assertEqual(d['channels']['port_air']['hits'],2)
        self.assertEqual(d['channels']['unknown_air']['hits'],1)
        gun=d['pairs'][0]
        self.assertEqual(gun['source']['name'],'大和');self.assertEqual(gun['target']['name'],'Iowa')
        self.assertEqual(direction(gun,1),'自軍の攻撃');self.assertEqual(direction(gun,2),'相手 → 自軍')
        self.assertEqual(aggregate(d['pairs'],1)[('自軍の攻撃','heavy')]['hits'],1)
        self.assertIn(1,country_choices(d['pairs']).values())
        self.assertEqual(d['stats']['read_errors'],1)
    def test_actual_hook_preserves_result_and_direction(self):
        r=self.script.exports_sync.hooked()
        self.assertEqual(r['results'],[1,0,1]);self.assertEqual(list(map(int,r['counts'][:3])),[3,2,1])
        pairs=r['details']['pairs'];self.assertEqual(len(pairs),2)
        self.assertEqual(pairs[0]['source']['name'],'大和');self.assertEqual(pairs[1]['source']['name'],'Iowa')
        self.assertEqual(r['details']['stats']['read_errors'],0)
        self.script.exports_sync.stop()
    def test_limits_preserve_channel_totals(self):
        d=self.script.exports_sync.overflow()
        self.assertEqual(len(d['pairs']),20000);self.assertEqual(d['stats']['pair_overflow'],2)
        self.assertEqual(d['channels']['heavy']['hits'],20002)
        self.assertEqual(len(d['samples']),2000);self.assertEqual(d['stats']['sample_omitted'],18002)
    def test_air_hook_and_invalid_denominator(self):
        r=self.script.exports_sync.hookedair()
        self.assertEqual(r['results'],[5,5]);self.assertEqual(list(map(int,r['counts'][3:7])),[1,100,5,0])
        self.assertEqual(int(r['counts'][9]),1)
        self.assertEqual(r['details']['channels']['carrier_mission'],{'events':1,'attempts':100,'hits':5})
        self.assertEqual(r['details']['pairs'][0]['source']['name'],'翔鶴')
        self.assertEqual(r['details']['stats']['read_errors'],0)
        self.script.exports_sync.stop()
    def test_country_tags(self):
        d=self.script.exports_sync.tags()
        self.assertEqual(d['pairs'][0]['source']['tag'],'JAP')
        self.assertTrue(any(k.startswith('JAP') for k in country_choices(d['pairs'])))

if __name__=='__main__':unittest.main()
