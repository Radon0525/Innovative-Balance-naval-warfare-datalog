import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from common_runtime import configure_tk
configure_tk()
import frida
from navalhitrecorder import source
from detail_storage import DetailWriter,DetailReader
from air_trace_report import explanation,number,examples_for,show_trace

class TraceTests(unittest.TestCase):
    def setUp(self):
        self.child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(180)'])
        self.session=frida.attach(self.child.pid)
        code=source({'test':True,'details':True,'mode':'both'})
        for name in ('test_details_fixture.js','test_damage_fixture.js','test_air_trace_fixture.js','test_air_attack_build_fixture.js'):code+='\n'+Path(name).read_text(encoding='utf-8')
        self.script=self.session.create_script(code);self.script.load()
    def tearDown(self):
        self.script.exports_sync.stop();self.script.unload();self.session.detach();self.child.terminate();self.child.wait(timeout=10)
    def test_reservoir_is_directional_bounded_and_spans_late_events(self):
        d=self.script.exports_sync.reservoir();self.assertEqual(len(d['buckets']),2)
        for b in d['buckets']:
            self.assertEqual(b['seen'],10000);self.assertEqual(len(b['examples']),5)
            seq=[e['sequence'] for e in b['examples']];self.assertEqual(len(set(seq)),5);self.assertTrue(any(n>2000 for n in seq))
            self.assertTrue(all(e['source']['country']==b['source_country'] for e in b['examples']))
    def test_native_arguments_calculated_damage_overkill_and_sql_roundtrip(self):
        d=self.script.exports_sync.traceattack();e=d['air_examples']['buckets'][0]['examples'][0];t=e['air_trace']
        self.assertTrue(t['complete']);self.assertNotIn('error',t)
        self.assertEqual(t['values']['attack'],'200000');self.assertEqual(t['values']['round_input'],'250000')
        self.assertEqual(t['applications'],[dict(calculated_str='900000',calculated_org='450000',before_str='500000',before_org='200000',after_str='0',after_org='0',actual_str='500000',actual_org='200000')])
        self.assertEqual(e['str_loss_raw'],'500000');self.assertEqual(e['org_loss_raw'],'200000')
        with tempfile.TemporaryDirectory() as folder:
            writer=DetailWriter(folder);meta=writer.apply(d,{});writer.close()
            reader=DetailReader(folder,{'details':meta});saved=reader.latest_document()['details']
            events,seen,_=examples_for(saved,(1,2));self.assertEqual(seen,1);self.assertEqual(events,[e])
            self.assertEqual(examples_for(saved,(2,1))[0],[])
        text=explanation(e);self.assertIn('渡したダメージ 9',text);self.assertIn('実減少 5',text)
        import tkinter as tk
        root=tk.Tk();root.withdraw()
        try:show_trace(root,e);root.update();self.assertEqual(len(root.winfo_children()),1)
        finally:root.destroy()
    def test_special_critical_operands(self):
        v=self.script.exports_sync.tracebranches()['values']
        self.assertTrue(v['critical_active']);self.assertTrue(v['special_handled'])
        self.assertEqual(v['effect_str_multiplier'],'200000');self.assertEqual(v['final_str'],'250000')
    def test_legacy_and_zero_success_explanations(self):
        e=dict(source={'name':'A'},target={'name':'B'},channel='carrier_battle',planes=10,successes=0,damage_status='measured',str_loss_raw='0',org_loss_raw='0')
        self.assertIn('保存されていません',explanation(e))
        e['air_trace']={'values':{},'complete':True}
        self.assertIn('実行されません',explanation(e));self.assertNotIn('3. 対空',explanation(e))
        self.assertEqual([number(x) for x in ('0','100','123456','-100000')],['0','0.001','1.23456','-1'])
    def test_aggregation_preserves_wing_inputs_and_thousandfold_disruption(self):
        from air_trace_report import attack_build_explanation
        low=self.script.exports_sync.attackbuild(True);d=low['data']
        self.assertEqual(low['result'],'299');self.assertEqual(low['scopes'],0)
        self.assertTrue(d['complete']);self.assertNotIn('error',d)
        self.assertEqual(d['assigned_planes'],100);self.assertEqual(d['attack_sum'],'29900')
        self.assertEqual([r['assigned_planes'] for r in d['wings']],[20,80])
        self.assertEqual([r['attack_contribution'] for r in d['wings']],['5980','23920'])
        for r in d['wings']:
            self.assertEqual(r['cached_attack'],'2600000');self.assertEqual(r['attack_before_disruption'],'299000')
            self.assertEqual(r['disruption_factor'],'100')
            self.assertLess(int(r['disruption_preclamp']),100)
            self.assertEqual(r['disruption_defence_factor'],'150000')
            self.assertEqual(r['disruption_denominator'],str(r['assigned_planes']*1000000))
        text='\n'.join(attack_build_explanation(d))
        self.assertIn('妨害前の対艦攻撃 2.99',text);self.assertIn('最終対艦攻撃：0.00299',text)
        self.assertIn('制限前の火力係数',text);self.assertIn('固定小数点平方根',text)
    def test_aggregation_external_and_country_modifiers(self):
        r=self.script.exports_sync.attackbuild(False,True,100000);d=r['data']
        self.assertEqual(d['average_attack'],'299000')
        self.assertEqual(d['carrier_country_bonus'],'100000')
        self.assertEqual(d['after_carrier_country'],'598000')
        self.assertEqual(d['external_factor'],'50000');self.assertEqual(r['result'],'299000')

if __name__=='__main__':unittest.main()
