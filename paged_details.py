"""Native result window: bounded pages and background aggregation / CSV export."""
import csv
import json
import queue
import threading
from pathlib import Path
from detail_storage import DetailReader
from naval_details import aggregate,channel_text,country_choices,direction,loss_text,rate,CONTEXTS

def load_view(folder,country=None,only_ours=False,side='all'):
    from session_history import session_name
    doc=json.loads((Path(folder)/'summary.json').read_text(encoding='utf-8'))
    reader=DetailReader(folder,doc)
    latest=reader.latest_document()
    if doc.get('updated_at','')>=latest.get('updated_at',''):
        latest.update({k:doc[k] for k in ('status','error','ended_at','elapsed_seconds','session_id') if k in doc})
    reader.document=latest;reader.details=latest.get('details') or {}
    latest['session_name']=session_name(folder)
    choices=country_choices(reader.iter_pairs())
    summary=[dict(r,side=side,channel=ch) for (side,ch),r in
             sorted(aggregate(reader.iter_pairs(country=country,only_ours=only_ours,side=side),country).items())]
    if 'details' not in latest and side=='all':
        c=latest['counts']
        summary=[dict(side='全体',channel='heavy',events=c['heavy_attempts'],attempts=c['heavy_attempts'],hits=c['heavy_hits']),
                 dict(side='全体',channel='unknown_air',events=c['air_groups'],attempts=c['air_planes'],hits=c['air_successes'])]
    return reader,latest,choices,summary

def export_pairs(reader,path,country=None,only_ours=False,side='all'):
    with open(path,'w',encoding='utf-8-sig',newline='') as file:
        writer=csv.writer(file)
        writer.writerow(['方向','種類','状況','攻撃元','攻撃元ID','攻撃先','攻撃先ID','耐久ダメージ','指揮統制ダメージ','測定済み回数','回数','判定数または参加機','命中または成功機','割合','攻撃元の国','攻撃先の国','成功0の回数'])
        for p in reader.iter_pairs(country=country,only_ours=only_ours,side=side):
            writer.writerow([direction(p,country),channel_text(p['channel']),CONTEXTS.get(p['context'],p['context']),
                p['source']['name'],p['source']['id'],p['target']['name'],p['target']['id'],loss_text(p,'str_loss_raw'),
                loss_text(p,'org_loss_raw'),p.get('damage_measured','未記録'),p['events'],p['attempts'],p['hits'],rate(p['hits'],p['attempts']),
                p['source'].get('country'),p['target'].get('country'),p.get('zero_groups',0)])

def show_report_window(parent,folder,*args):
    from naval_countries import show_report_window as show
    return show(parent,folder,*args)
