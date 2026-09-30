"""Native Tk result windows and pure aggregation, including older saved sessions."""
import json
from pathlib import Path

CHANNELS={'heavy':'大型砲', 'carrier_battle':'艦載機・海戦参加',
          'carrier_mission':'空母発進・外部Naval Strike', 'land_mission':'基地航空・外部対艦攻撃',
          'port_air':'港湾攻撃', 'unknown_air':'航空・経路不明'}
CONTEXTS={'battle':'海戦中','temporary':'海戦外の艦隊','port':'港湾','unknown':'不明'}

def channel_text(key):return CHANNELS.get(key,key)
def rate(h,n):return f'{h/n:.2%}' if n else '—'
def latest_report(base):
    reports=list((Path(base)/'recordings').glob('*/summary.json'))
    return max(reports,key=lambda p:p.stat().st_mtime).parent if reports else None

def direction(pair,country):
    if country is None:return '全体'
    a=pair['source'].get('country');b=pair['target'].get('country')
    if a==country:return '自軍の攻撃'
    if b==country and a is not None and a>0:return '相手 → 自軍'
    if a is None or b is None or a<=0 or b<=0:return '所属不明'
    return 'その他の国同士'

def aggregate(pairs,country=None):
    groups={}
    for p in pairs:
        key=(direction(p,country),p['channel'])
        row=groups.setdefault(key,{'events':0,'attempts':0,'hits':0})
        for field in ('events','attempts','hits'):row[field]+=p[field]
        if 'damage_measured' in p:
            row['damage_measured']=row.get('damage_measured',0)+p['damage_measured']
            for field in ('str_loss_raw','org_loss_raw'):
                row[field]=str(int(row.get(field,0))+int(p.get(field,0)))
    return groups

def loss_text(row,field):
    status=row.get('damage_status')
    if status=='pending':return '処理中'
    if status=='unavailable':return '未測定'
    if status!='measured' and 'damage_measured' not in row:return '未記録'
    if status!='measured' and not row['damage_measured'] and row.get('events',0):return '未測定'
    whole,fraction=divmod(int(row.get(field,0)),100000)
    text=f'{whole:,}.{fraction:05d}'.rstrip('0').rstrip('.')
    if status!='measured' and row['damage_measured']<row['events']:text+='（一部）'
    return text

def country_choices(pairs):
    examples={};tags={}
    for p in pairs:
        for field in ('source','target'):
            entity=p[field];country=entity.get('country')
            if country is not None and country>0:
                examples.setdefault(country,[])
                if entity.get('tag'):tags[country]=entity['tag']
                if entity['name'] not in examples[country] and len(examples[country])<2:
                    examples[country].append(entity['name'])
    return {f"{tags.get(country,f'国 #{country}')}（{' / '.join(names)}）":country for country,names in sorted(examples.items())}

def show_report_window(parent,folder,initial_country=None,initial_side='all'):
    from naval_countries import show_report_window as show
    return show(parent,folder,initial_country,initial_side)
