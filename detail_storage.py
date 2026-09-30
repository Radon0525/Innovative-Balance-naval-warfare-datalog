"""Incremental, bounded detailed storage and paged reads; legacy JSON remains readable."""
import json
import sqlite3
from pathlib import Path

DATABASE='details.sqlite3'

def pair_key(p):
    return json.dumps([p['channel'],p['context'],p['source']['id'],p['source'].get('country'),
                       p['target']['id'],p['target'].get('country')],ensure_ascii=False,separators=(',',':'))

class DetailWriter:
    def __init__(self,folder):
        self.db=sqlite3.connect(Path(folder)/DATABASE,timeout=10)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS pairs (
            id TEXT PRIMARY KEY, kind TEXT, source_country INTEGER, target_country INTEGER,
            attempts INTEGER, data TEXT NOT NULL);
          CREATE INDEX IF NOT EXISTS pairs_kind_order ON pairs(kind,attempts DESC,id);
          CREATE INDEX IF NOT EXISTS pairs_source ON pairs(source_country);
          CREATE INDEX IF NOT EXISTS pairs_target ON pairs(target_country);
          CREATE TABLE IF NOT EXISTS samples (
            sequence INTEGER PRIMARY KEY, source_country INTEGER, target_country INTEGER,data TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS metadata (id INTEGER PRIMARY KEY CHECK(id=1),data TEXT NOT NULL);
        ''')
    def apply(self,details,document):
        meta={k:v for k,v in details.items() if k not in ('pairs','samples','delta')}
        meta['storage']=DATABASE
        with self.db:
            self.db.executemany('''INSERT INTO pairs VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
              kind=excluded.kind,source_country=excluded.source_country,target_country=excluded.target_country,
              attempts=excluded.attempts,data=excluded.data''',
              ((pair_key(p),p['kind'],p['source'].get('country'),p['target'].get('country'),p['attempts'],
                json.dumps(p,ensure_ascii=False,separators=(',',':'))) for p in details.get('pairs',[])))
            self.db.executemany('''INSERT INTO samples VALUES(?,?,?,?) ON CONFLICT(sequence) DO UPDATE SET
              source_country=excluded.source_country,target_country=excluded.target_country,data=excluded.data''',
              ((p['sequence'],p['source'].get('country'),p['target'].get('country'),
                json.dumps(p,ensure_ascii=False,separators=(',',':'))) for p in details.get('samples',[])))
            meta['pair_count']=self.db.execute('SELECT count(*) FROM pairs').fetchone()[0]
            meta['sample_count']=self.db.execute('SELECT count(*) FROM samples').fetchone()[0]
            saved=dict(document,details=meta)
            self.db.execute('INSERT OR REPLACE INTO metadata VALUES(1,?)',(json.dumps(saved,ensure_ascii=False),))
        return meta
    def close(self):
        self.db.close()

class DetailReader:
    """Short read transactions so a window left open cannot grow the recorder's WAL."""
    def __init__(self,folder,document):
        self.folder=Path(folder);self.document=document
        self.details=document.get('details') or {}
        self.database=self.folder/DATABASE if self.details.get('storage')==DATABASE else None
    def connect(self):
        # Never create an empty database when a recording has been moved incorrectly.
        db=sqlite3.connect(self.database.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)
        db.execute('PRAGMA query_only=ON')
        return db
    def latest_document(self):
        if not self.database:return self.document
        db=self.connect()
        try:return json.loads(db.execute('SELECT data FROM metadata WHERE id=1').fetchone()[0])
        finally:db.close()
    def _where(self,kind,country,only_ours,side='all',flow=None):
        clauses=[];args=[]
        if flow is not None:
            clauses.append('(COALESCE(source_country,0)=? AND COALESCE(target_country,0)=?)');args.extend(flow)
        if side not in ('all','own','enemy'):raise ValueError('Invalid side')
        if side!='all':
            if country is None:clauses.append('0')
            elif side=='own':clauses.append('source_country=?');args.append(country)
            else:
                clauses.append('(target_country=? AND source_country>0 AND source_country<>?)');args.extend([country,country])
        if kind:clauses.append('kind=?');args.append(kind)
        if only_ours and country is not None:
            clauses.append('(source_country=? OR target_country=?)');args.extend([country,country])
        return (' WHERE '+' AND '.join(clauses) if clauses else ''),args
    def iter_pairs(self,kind=None,country=None,only_ours=False,side='all',flow=None):
        if self.database:
            where,args=self._where(kind,country,only_ours,side,flow)
            db=self.connect()
            try:
                for (text,) in db.execute('SELECT data FROM pairs'+where+' ORDER BY attempts DESC,id',args):yield json.loads(text)
            finally:db.close()
        else:
            for p in sorted(self.details.get('pairs',[]),key=lambda p:-p['attempts']):
                if self._visible(p,kind,country,only_ours,side,flow):yield p
    @staticmethod
    def _visible(p,kind,country,only_ours,side='all',flow=None):
        if flow is not None and (p['source'].get('country') or 0,p['target'].get('country') or 0)!=tuple(flow):return False
        if side not in ('all','own','enemy'):raise ValueError('Invalid side')
        if side!='all':
            if country is None:return False
            source=p['source'].get('country');target=p['target'].get('country')
            if side=='own' and source!=country:return False
            if side=='enemy' and not (target==country and source is not None and source>0 and source!=country):return False
        return (not kind or p['kind']==kind) and (not only_ours or country is None or
            p['source'].get('country')==country or p['target'].get('country')==country)
    def page(self,tab,page=0,size=100,country=None,only_ours=False,side='all',flow=None):
        if size not in (50,100,250):raise ValueError('Invalid page size')
        sample=tab=='samples';kind=None if sample else tab
        table='samples' if sample else 'pairs'
        if self.database:
            where,args=self._where(kind,country,only_ours,side,flow)
            db=self.connect()
            try:
                # Count and page use one short snapshot, never held across user interaction.
                db.execute('BEGIN')
                count=db.execute('SELECT count(*) FROM '+table+where,args).fetchone()[0]
                page=max(0,min(page,max(0,(count-1)//size)))
                order='sequence' if sample else 'attempts DESC,id'
                rows=[json.loads(r[0]) for r in db.execute('SELECT data FROM '+table+where+' ORDER BY '+order+' LIMIT ? OFFSET ?',[*args,size,page*size])]
            finally:db.close()
        else:
            rows=self.details.get('samples',[]) if sample else self.details.get('pairs',[])
            rows=[p for p in rows if self._visible(p,kind,country,only_ours,side,flow)]
            rows=sorted(rows,key=(lambda p:p['sequence']) if sample else (lambda p:-p['attempts']))
            count=len(rows);page=max(0,min(page,max(0,(count-1)//size)));rows=rows[page*size:(page+1)*size]
        return rows,count,page
