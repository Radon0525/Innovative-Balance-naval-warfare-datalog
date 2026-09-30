import csv,json,tempfile,unittest
from pathlib import Path
from detail_storage import DetailReader,DetailWriter
from naval_details import aggregate,loss_text
from paged_details import export_pairs

def pair(i):
    return dict(kind='heavy',channel='heavy',context='battle',source=dict(id=f's{i}',name='艦',country=i%2+1),
                target=dict(id='t',name='相手',country=3),events=2,attempts=2,hits=1,
                damage_measured=2,str_loss_raw='900719925474099301',org_loss_raw='123456')

class StorageTests(unittest.TestCase):
    def test_sides_match_legacy_sql_pages_and_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            own=pair(0);enemy=dict(pair(1),target=dict(id='our',name='自軍',country=1))
            third=dict(pair(3),target=dict(id='third',name='第三国',country=4))
            unknown=dict(enemy,source=dict(id='unknown',name='所属不明',country=None))
            same=dict(own,target=dict(id='self',name='自軍',country=1))
            pairs=[own,enemy,third,unknown,same]
            samples=[dict(p,sequence=i+1) for i,p in enumerate(pairs)]
            legacy=DetailReader(folder,{'details':dict(pairs=pairs,samples=samples)})
            writer=DetailWriter(folder);meta=writer.apply(dict(pairs=pairs,samples=samples),{});writer.close()
            database=DetailReader(folder,{'details':meta})
            for reader in (legacy,database):
                self.assertEqual(reader.page('heavy',country=1,side='own')[1],2)
                rows,count,page=reader.page('heavy',999,50,1,side='enemy')
                self.assertEqual((count,page),(1,0));self.assertEqual(rows[0]['source']['country'],2)
                self.assertEqual(reader.page('samples',country=1,side='enemy')[1],1)
                self.assertEqual(reader.page('heavy',side='enemy')[1],0)
                export_pairs(reader,folder/'enemy.csv',1,side='enemy')
                with (folder/'enemy.csv').open(encoding='utf-8-sig',newline='') as f:export=list(csv.reader(f))
                self.assertEqual(len(export),2);self.assertEqual(export[1][0],'相手 → 自軍')
    def test_bounded_pages_incremental_updates_and_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);writer=DetailWriter(folder)
            doc={'status':'収集中','details':writer.apply({'pairs':[pair(i) for i in range(20000)],'samples':[]},{'status':'収集中'})}
            reader=DetailReader(folder,doc)
            rows,count,page=reader.page('heavy',99999,250,1,True)
            self.assertEqual((len(rows),count,page),(250,10000,39))
            before=writer.db.total_changes
            changed=dict(pair(2),str_loss_raw='900719925474099302')
            writer.apply({'pairs':[changed],'samples':[]},doc)
            self.assertEqual(writer.db.total_changes-before,2) # One pair and metadata, not 20,000 rewrites.
            self.assertNotIn('pairs',reader.latest_document()['details'])
            self.assertEqual(len(reader.page('heavy')[0]),100)
            export_pairs(reader,folder/'all.csv',1,True)
            with (folder/'all.csv').open(encoding='utf-8-sig',newline='') as f:export=list(csv.reader(f))
            self.assertEqual(len(export),10001)
            self.assertEqual(export[1][7],'9,007,199,254,740.99301')
            writer.close()
            self.assertFalse((folder/'details.sqlite3-wal').exists())

    def test_rollback_samples_and_missing_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);writer=DetailWriter(folder)
            p=pair(0);sample=dict(p,sequence=1,damage_status='pending')
            meta=writer.apply({'pairs':[p],'samples':[sample]},{});reader=DetailReader(folder,{'details':meta})
            with self.assertRaises(KeyError):writer.apply({'pairs':[dict(p,hits=2),{}]}, {})
            self.assertEqual(reader.page('heavy')[0][0]['hits'],1)
            sample.update(damage_status='measured',str_loss_raw='0',org_loss_raw='0')
            writer.apply({'samples':[sample]},{});self.assertEqual(reader.page('samples')[0][0]['damage_status'],'measured')
            writer.close()
        with tempfile.TemporaryDirectory() as tmp:
            reader=DetailReader(tmp,{'details':{'storage':'details.sqlite3'}})
            with self.assertRaises(Exception):reader.page('heavy')
            self.assertFalse((Path(tmp)/'details.sqlite3').exists())

    def test_exact_damage_and_legacy(self):
        p=pair(1);a=aggregate([p,p])[('全体','heavy')]
        self.assertEqual(a['str_loss_raw'],'1801439850948198602')
        self.assertEqual(loss_text(a,'org_loss_raw'),'2.46912')
        self.assertEqual(loss_text({},'str_loss_raw'),'未記録')
        self.assertEqual(loss_text({'damage_status':'unavailable'},'str_loss_raw'),'未測定')
        self.assertEqual(loss_text(dict(p,damage_measured=1),'str_loss_raw'),'9,007,199,254,740.99301（一部）')
        self.assertEqual(loss_text({'damage_status':'measured','str_loss_raw':'0'},'str_loss_raw'),'0')

if __name__=='__main__':unittest.main()
