import json,os,tempfile,time,threading,unittest
from pathlib import Path
os.chdir(Path(__file__).resolve().parent)
from common_runtime import configure_tk
configure_tk()
import tkinter as tk
from tkinter import ttk
import navalhitrecorder as app
from naval_countries import CountryOverview,load_countries,show_report_window,show_comparison
from detail_storage import DetailWriter

def widgets(root):
    for child in root.winfo_children():
        yield child
        yield from widgets(child)

class WindowTests(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk();self.root.withdraw();self.tmp=tempfile.TemporaryDirectory();self.folder=Path(self.tmp.name)
    def tearDown(self):
        self.root.destroy()
        for worker in threading.enumerate():
            if worker.name in ('naval-history-worker','naval-details-worker'):worker.join(timeout=5)
        self.tmp.cleanup()
    def wait(self,condition):
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            self.root.update()
            if condition():return
            time.sleep(.02)
        self.fail('UI worker did not finish')
    def save(self):
        a=dict(id='a',name='艦A',country=1,tag='GER');b=dict(id='b',name='艦B',country=2,tag='SOV');c=dict(id='c',name='艦C',country=3,tag='ENG')
        pairs=[]
        for src,dst,n,h,kind in [(a,b,4,2,'heavy'),(b,a,4,1,'heavy'),(a,b,10,4,'air'),(c,b,2,1,'heavy')]:
            pairs.append(dict(kind=kind,channel='heavy' if kind=='heavy' else 'carrier_mission',context='battle',source=src,target=dst,events=1,
                attempts=n,hits=h,damage_measured=1,str_loss_raw=str(h*100000),org_loss_raw=str(h*200000)))
        samples=[dict(p,sequence=i+1,hit=True,planes=10,successes=4,damage_status='measured') for i,p in enumerate(pairs)]
        doc=dict(version='test',mode='both',status='停止済み',started_at='test',updated_at='test',details=dict(pairs=pairs,samples=samples,stats={},damage_enabled=True))
        app.save_report(self.folder,[10,4,6,1,10,4,0,0,0,0],doc)
        return doc
    def open(self):
        w=show_report_window(self.root,self.folder);view=next(x for x in widgets(w) if isinstance(x,CountryOverview))
        self.wait(lambda:not view.busy);return w,view
    def test_automatic_split_and_third_country_not_mixed(self):
        self.save();w,v=self.open()
        self.assertFalse(any(isinstance(x,ttk.Combobox) for x in widgets(w)))
        self.assertFalse(any(isinstance(x,ttk.Radiobutton) for x in widgets(w)))
        self.assertEqual(v.match_key,(1,2));self.assertIn('ドイツ',v.panels[0].cget('text'));self.assertIn('ソ連',v.panels[1].cget('text'))
        left=[v.trees[0].item(r,'values') for r in v.trees[0].get_children()]
        self.assertEqual([r[1] for r in left],['2','4'])
        self.assertEqual(v.trees[1].item(v.trees[1].get_children()[0],'values')[1],'1')
        v.match_tree.selection_set('1');self.root.update();self.assertEqual(v.match_key,(2,3));self.assertIn('イギリス',v.panels[1].cget('text'))
        self.assertEqual(len(v.rows),1)
    def test_detail_tabs_and_directional_sql_paging(self):
        doc=self.save();base=doc['details']['pairs'][0]
        doc['details']['pairs']=[dict(base,source=dict(base['source'],id=str(i))) for i in range(1201)]+[doc['details']['pairs'][1]]
        writer=DetailWriter(self.folder);doc['details']=writer.apply(doc['details'],dict(doc,counts=app.metrics([10,4,6,1,10,4,0,0,0,0])));writer.close()
        app.save_report(self.folder,[10,4,6,1,10,4,0,0,0,0],doc)
        w,v=self.open();v.tabs.select(1);self.root.update()
        self.assertEqual(len(v.trees[0].get_children()),100);self.assertEqual(len(v.trees[1].get_children()),1)
        v.move(0,99);self.assertEqual(len(v.trees[0].get_children()),1);self.assertEqual(v.pages[0],12)
        v.tabs.select(3);self.root.update();self.assertEqual(len(v.rows),3)
    def test_legacy_whole_totals_remain_readable(self):
        doc=self.save();doc.pop('details');app.save_report(self.folder,[10,4,6,1,10,4,0,0,0,0],doc)
        w,v=self.open();self.assertIsNone(v.match_key)
        self.assertEqual(len(v.trees[0].get_children()),2)
        self.assertEqual(v.trees[0].item(v.trees[0].get_children()[0],'values')[1],'未記録')
    def test_main_overview_refresh_and_close(self):
        self.save();w=tk.Toplevel(self.root);v=CountryOverview(w);v.pack();v.refresh(self.folder);self.wait(lambda:not v.busy)
        self.assertEqual(len(v.matches),2);v.refresh();w.destroy();self.root.update()
    def test_air_examples_show_five_per_direction_and_open_tk_trace(self):
        doc=self.save();examples=[]
        for reverse in (False,True):
            p=doc['details']['samples'][2];a=p['source'];b=p['target']
            if reverse:a,b=b,a
            rows=[dict(p,sequence=3000+j,source=a,target=b) for j in range(5)]
            for e in rows:
                power='299' if reverse else '299000'
                e['air_trace']={'complete':True,'upstream':{'attack':power,'attack_build':{'complete':True,'wings':[
                  {'index':1,'assigned_planes':10,'cached_attack':'2600000','total_factor':'115000','attack_before_disruption':'299000',
                   'disruption_factor':'100' if reverse else '100000','disruption_raw':'51640827' if reverse else '0'}]}},'values':{}}
            examples.append(dict(source_country=a['country'],target_country=b['country'],seen=9000,examples=rows))
        doc['details']['air_examples']={'buckets':examples,'limit':5,'stats':{}}
        app.save_report(self.folder,[10,4,6,1,10,4,0,0,0,0],doc)
        w,v=self.open();v.tabs.select(4);self.root.update()
        self.assertEqual([len(t.get_children()) for t in v.trees],[5,5])
        self.assertIn('9,000',v.page_labels[0].get())
        self.assertEqual({p['source']['country'] for (i,r),p in v.rows.items() if i==0},{1})
        self.assertEqual({p['source']['country'] for (i,r),p in v.rows.items() if i==1},{2})
        v.trees[1].selection_set(v.trees[1].get_children()[0]);v.drill(1);self.root.update()
        self.assertTrue(any(isinstance(x,tk.Text) and '集約済み対艦攻撃：0.00299' in x.get('1.0','end') for x in widgets(w)))
        self.assertFalse(hasattr(v,'air_compare_button'))
        self.assertEqual(str(v.trees[0].cget('selectmode')),'browse')
        notebooks=[x for x in widgets(w) if isinstance(x,ttk.Notebook) and x is not v.tabs]
        self.assertEqual([notebooks[-1].tab(t,'text') for t in notebooks[-1].tabs()],['計算の順序','保存された数値'])
    def test_history_comparison_has_automatic_country_directions(self):
        from test_history import trial
        from session_history import show_history,save_notes
        a=trial(self.folder,'a',2,country=1);b=trial(self.folder,'b',7,country=5,sqlite=True)
        save_notes(a,name='設計A');save_notes(b,name='設計B')
        w=show_comparison(self.root,[a,b]);tree=next(x for x in widgets(w) if isinstance(x,ttk.Treeview))
        self.wait(lambda:len(tree.get_children())==2)
        self.assertFalse(any(isinstance(x,ttk.Combobox) for x in widgets(w)))
        self.assertEqual(sorted(tree.set(r,'str') for r in tree.get_children()),['2','7'])
        self.assertTrue(all('→' in tree.set(r,'flow') for r in tree.get_children()))
        history=show_history(self.root,self.folder);ht=next(x for x in widgets(history) if isinstance(x,ttk.Treeview))
        self.wait(lambda:len(ht.get_children())==2);ht.selection_set(ht.get_children()[0]);self.root.update()
        button=next(x for x in widgets(history) if isinstance(x,ttk.Button) and x.cget('text')=='選択した記録を開く');button.invoke()
        report=next(x for x in widgets(history) if isinstance(x,CountryOverview));self.wait(lambda:not report.busy)
        self.assertIsNotNone(report.match_key)

    def test_first_aircraft_tab_and_return_to_damage_table(self):
        from air_participants import ParticipantView
        doc=self.save()
        aircraft=dict(status='complete',regional_observed=True,registration_observed=True,naval_complete=True,
                      rows=[dict(country=1,tag='JAP',category='carrier_bomber',registered=77,candidate=77,naval_ready=77,naval_assigned=77),
                            dict(country=2,tag='USA',category='carrier_fighter',registered=30,candidate=30,escort=30)])
        (self.folder/'air_participants.json').write_text(json.dumps(aircraft),encoding='utf-8')
        doc['air_participants']=dict(status='complete',storage='air_participants.json',row_count=2)
        app.save_report(self.folder,[10,4,6,1,10,4,0,0,0,0],doc)
        w,v=self.open();v.tabs.select(5);self.root.update()
        self.assertIsInstance(v.participant_view,ParticipantView)
        tree=v.participant_view.tree;rows=[tree.item(r,'values') for r in tree.get_children()]
        self.assertEqual(len(rows),10);self.assertTrue(any(r[0]=='日本 (JAP)' and r[1]=='この国の総数' and r[2]=='77' for r in rows))
        self.assertFalse(v.body.winfo_ismapped());v.tabs.select(0);self.root.update()
        self.assertEqual(len(v.rows),3)

    def test_old_aircraft_record_is_unknown_not_zero(self):
        self.save();w,v=self.open();v.tabs.select(5);self.root.update()
        self.assertIn('旧記録',v.participant_view.caption.get())
        self.assertEqual(len(v.participant_view.tree.get_children()),0)

if __name__=='__main__':unittest.main()
