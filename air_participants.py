"""Small native tables for a one-update aircraft census, including old records."""
import json
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from country_names import country_name
from detail_storage import DetailReader
from session_history import make_table

CATEGORIES = {
    'carrier_bomber': '空母・対艦任務機（艦攻）',
    'carrier_fighter': '空母・制空／迎撃機（艦戦）',
    'land_fighter': '陸上基地・制空／迎撃機',
    'land_bomber': '陸上基地・対艦任務機',
    'other': 'その他・複数任務・発進元不明',
}
FIELDS = ('registered', 'candidate', 'engaged_wing_planes', 'escort',
          'naval_ready', 'naval_assigned', 'shot_allocated_raw')
STATES = {'disabled': 'この記録では初回機数の収集が無効です。',
          'waiting_naval_update': '初回の海戦航空処理を待っています。',
          'waiting_regional_update': '海戦を観測しました。同じ地域の航空更新を待っています。',
          'not_observed': '停止までに対象の海戦航空処理を観測できませんでした。',
          'complete': '初回の機数を取得済み。追加の機数観測は終了しました。',
          'partial': '初回の機数は一部のみ取得しました。未観測・上限・読取失敗を確認してください。'}

def time_text(value):
    if not value: return '未観測'
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(
            timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M:%S JST')
    except ValueError: return value

def load_document(folder):
    folder = Path(folder)
    doc = json.loads((folder / 'summary.json').read_text(encoding='utf-8'))
    latest = DetailReader(folder, doc).latest_document()
    # The summary can be newer than the last detail checkpoint after an error.
    return resolve_document(folder, doc if doc.get('updated_at', '') >= latest.get('updated_at', '') else latest)

@lru_cache(maxsize=4)
def _saved_census(path, modified, size):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def resolve_document(folder, document):
    data = document.get('air_participants') or {}
    if data.get('storage') != 'air_participants.json': return document
    try:
        path = Path(folder) / 'air_participants.json'; stat = path.stat()
        data = _saved_census(str(path.resolve()), stat.st_mtime_ns, stat.st_size)
    except (OSError, ValueError):
        data = dict(data, status='partial', rows=[], error='保存された機数ファイルを読み込めません。記録フォルダー全体をコピーしてください。')
    return dict(document, air_participants=data)

def participant_totals(data):
    """Rows are unique wings; different stages remain independent columns."""
    groups = {}; countries = {}
    for row in data.get('rows', []):
        country = row.get('country') or 0
        category = row.get('category') if row.get('category') in CATEGORIES else 'other'
        countries.setdefault(country, row.get('tag'))
        values = groups.setdefault((country, category), {f: 0 for f in FIELDS})
        for field in FIELDS: values[field] += int(row.get(field, 0))
    result = []
    for country in sorted(countries):
        total = {f: 0 for f in FIELDS}
        for category in CATEGORIES:
            if category == 'other' and (country, category) not in groups: continue
            values = groups.get((country, category), {f: 0 for f in FIELDS})
            result.append(dict(country=country, tag=countries[country], category=category, **values))
            for field in FIELDS: total[field] += values[field]
        result.append(dict(country=country, tag=countries[country], category='total', **total))
    return result

def value_text(data, row, field):
    if field in ('registered', 'escort') and not data.get('registration_observed'): return '未観測'
    if field in ('candidate', 'engaged_wing_planes', 'shot_allocated_raw') and not data.get('regional_observed'): return '未観測'
    if field.startswith('naval_') and not data.get('naval_complete'): return '途中'
    number = int(row.get(field, 0))
    if field == 'shot_allocated_raw':
        whole, fraction = divmod(number, 100000)
        text = f'{whole:,}.{fraction:05d}'.rstrip('0').rstrip('.')
    else: text = f'{number:,}'
    return text + '（一部）' if data.get('status') == 'partial' else text

def description(data):
    if not data: return 'この旧記録には初回の航空機数が保存されていません。新しく収集してください。'
    text = STATES.get(data.get('status'), '機数の状態は不明です。')
    if data.get('error'): text += '\n' + data['error']
    if data.get('rows'):
        text += '\n海戦：' + time_text(data.get('naval_started_at')) + ' ～ ' + time_text(data.get('naval_ended_at'))
        association = {'same_air_update': '同じ航空更新内', 'preceding_air_update': '直前の地域航空更新',
                       'following_air_update': '海戦観測後の最初の地域航空更新'}.get(data.get('association'), '未観測')
        text += '\n地域空戦・護衛：' + association + ' · ' + time_text(data.get('regional_started_at'))
        if data.get('region') is not None: text += f' · 地域 #{data["region"]}'
        stats = data.get('stats', {})
        names = {'read_errors': '読取失敗', 'omitted_regions': '地域上限で除外', 'omitted_wings': '航空隊上限で除外',
                 'omitted_groups': '攻撃群上限で除外', 'overlapping_updates': '更新の重複'}
        if any(stats.values()): text += '\n取得状況：' + ' / '.join(f'{names.get(key, key)} {value}件' for key, value in stats.items() if value)
    return text

class ParticipantView(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.caption = tk.StringVar()
        ttk.Label(self, textvariable=self.caption, wraplength=1120, justify='left').pack(anchor='w', pady=6)
        self.tree = make_table(self, [
            ('country', '国', 140), ('role', '発進元・実行任務', 240),
            ('registered', '地域登録機数', 115), ('candidate', '空戦候補機数', 115),
            ('engaged_wing_planes', '空戦へ進んだ隊の対象機数', 190),
            ('escort', '護衛値が正の隊の機数', 175), ('naval_ready', '海戦航空隊の使用可能機数', 190),
            ('naval_assigned', '海戦の配分機数（延べ）', 170),
            ('shot_allocated_raw', '射撃割当（延べ機換算）', 175)], height=12)
        self.rows = []; self.page = 0; self.data = {}
        nav = ttk.Frame(self); nav.pack(fill='x', pady=6)
        ttk.Button(nav, text='前へ', command=lambda: self.move(-1)).pack(side='left')
        self.page_label = tk.StringVar(); ttk.Label(nav, textvariable=self.page_label).pack(side='left', padx=8)
        ttk.Button(nav, text='次へ', command=lambda: self.move(1)).pack(side='left')
        ttk.Label(self, text='機体の設計名ではなく、発進元と処理中の任務で分類します。地域の候補には同じ地域の別の海戦・航空隊も入り得ます。\n'
                  '機数は航空隊単位で重複を除きます。各列は処理段階が違うため、列同士を足しません。\n'
                  '「空戦へ進んだ隊」は空戦計算に到達した航空隊の対象機数で、全機が射撃したという意味ではありません。\n'
                  '射撃割当と海戦配分は延べ値です。「護衛値が正」は地域の護衛集計時点で護衛値を持った航空隊です。',
                  wraplength=1120, justify='left').pack(anchor='w', pady=5)

    def set_document(self, document):
        self.data = document.get('air_participants') or {}
        self.caption.set(description(self.data)); self.rows = participant_totals(self.data); self.draw()

    def move(self, amount): self.page += amount; self.draw()

    def draw(self):
        self.page = max(0, min(self.page, max(0, (len(self.rows) - 1) // 100)))
        self.tree.delete(*self.tree.get_children())
        for row in self.rows[self.page * 100:(self.page + 1) * 100]:
            role = 'この国の総数' if row['category'] == 'total' else CATEGORIES[row['category']]
            self.tree.insert('', 'end', values=(country_name(row['country'], row['tag']), role,
                             *(value_text(self.data, row, field) for field in FIELDS)))
        self.page_label.set(f'{self.page + 1}/{max(1, (len(self.rows) + 99) // 100)}ページ · {len(self.rows)}行')

def show_participants(parent, folder):
    window = tk.Toplevel(parent); window.title('初回の航空機数 — 国別'); window.geometry('1220x740')
    view = ParticipantView(window); view.pack(fill='both', expand=True, padx=12, pady=10)
    def refresh(): view.set_document(load_document(folder))
    buttons = ttk.Frame(window); buttons.pack(fill='x', padx=12, pady=8)
    ttk.Button(buttons, text='最新の保存内容に更新', command=refresh).pack(side='left')
    ttk.Button(buttons, text='閉じる', command=window.destroy).pack(side='right')
    refresh(); return window
