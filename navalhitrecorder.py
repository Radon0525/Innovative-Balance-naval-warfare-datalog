"""Naval heavy-gun and air-strike telemetry. Local collection, no game-state edits."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import queue
import signal
import sys
import threading
import time
import uuid

BASE=Path(__file__).resolve().parent
from common_runtime import process_path, atomic_text, percent, configure_tk
from naval_details import show_report_window, latest_report, channel_text
from detail_storage import DetailWriter

MODES={'both':'大型砲 ＋ 航空攻撃','heavy':'大型砲のみ','air':'航空攻撃のみ'}
KEYS=['heavy_attempts','heavy_hits','heavy_misses','air_groups','air_planes',
      'air_successes','air_zero_groups','ignored_light','ignored_torpedo','measurement_errors']

def utc(): return datetime.now(timezone.utc).isoformat()

def source(config):
    return ('const CONFIG='+json.dumps(config)+';\nconst COUNTER_SOURCE='+
            json.dumps((BASE/'counter.c').read_text(encoding='utf-8'))+';\n'+
            (BASE/'damage.js').read_text(encoding='utf-8')+'\n'+
            (BASE/'details.js').read_text(encoding='utf-8')+'\n'+
            (BASE/'air_trace.js').read_text(encoding='utf-8')+'\n'+
            (BASE/'air_attack_build.js').read_text(encoding='utf-8')+'\n'+
            (BASE/'air_participants.js').read_text(encoding='utf-8')+'\n'+
            (BASE/'agent.js').read_text(encoding='utf-8'))

def profile_for(path):
    with Path(path).open('rb') as f:
        digest=hashlib.file_digest(f,'sha256').hexdigest()
    for p in json.loads((BASE/'profiles.json').read_text(encoding='utf-8')):
        if p['sha256']==digest:return p
    raise RuntimeError('未対応の実行ファイルです。計測は開始しません。\nSHA-256: '+digest)

def metrics(counts):
    if len(counts)!=len(KEYS) or any(type(x) is not int or x<0 for x in counts):
        raise ValueError('集計形式が不正です')
    data=dict(zip(KEYS,counts))
    if counts[0]!=counts[1]+counts[2] or counts[5]>counts[4] or counts[6]>counts[3]:
        raise ValueError('集計値の整合性が失われました')
    data['heavy_hit_rate']=counts[1]/counts[0] if counts[0] else None
    data['air_success_rate']=counts[5]/counts[4] if counts[4] else None
    data['air_average_successes_per_group']=counts[5]/counts[3] if counts[3] else None
    return data

def save_report(folder,counts,meta):
    values=metrics(counts)
    document=dict(meta,counts=values)
    atomic_text(folder/'summary.json',json.dumps(document,ensure_ascii=False,indent=2)+'\n')
    heavy_selected=meta['mode']!='air'; air_selected=meta['mode']!='heavy'
    def row(label,value):return f'<tr><th>{html.escape(label)}</th><td>{value}</td></tr>'
    heavy=''.join(row(k,v) for k,v in [
        ('射撃判定数',f'{counts[0]:,}'),('命中数',f'{counts[1]:,}'),
        ('不命中数',f'{counts[2]:,}'),('命中率',percent(values['heavy_hit_rate']))])
    air=''.join(row(k,v) for k,v in [
        ('攻撃グループ数',f'{counts[3]:,}'),('対空等を通過した延べ参加機数',f'{counts[4]:,}'),
        ('延べ攻撃成功機数',f'{counts[5]:,}'),('参加機数に対する成功割合',percent(values['air_success_rate'])),
        ('成功0機のグループ数',f'{counts[6]:,}')])
    message=html.escape(meta.get('error',''))
    content=f'''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Naval Hit Recorder — 海戦の命中記録</title>
<style>body{{margin:0;background:#101b2a;color:#e7eef7;font:16px system-ui}}main{{max-width:1040px;margin:auto;padding:40px 24px}}h1{{font-size:32px;margin:8px 0}}h2{{font-size:21px}}.tag{{color:#7dd3fc;letter-spacing:.15em}}.meta,.note{{color:#b7c6d8;line-height:1.8}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:20px;margin:28px 0}}section{{background:#1a2a3d;border:1px solid #34455a;border-radius:14px;padding:22px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:13px 0;border-bottom:1px solid #34455a}}th{{text-align:left;font-weight:400}}td{{text-align:right;font-variant-numeric:tabular-nums;font-size:19px}}.muted{{opacity:.65}}.error{{color:#fca5a5;white-space:pre-wrap}}a{{color:#7dd3fc}}</style>
<main><div class="tag">NAVAL HIT RECORDER</div><h1>海戦の命中記録</h1>
<p class="meta">{html.escape(meta['version'])} · {html.escape(MODES[meta['mode']])}<br>
状態：{html.escape(meta['status'])}<br>開始：{html.escape(meta['started_at'])}<br>最終保存：{html.escape(meta.get('updated_at','—'))}</p>
<p class="error">{message}</p><div class="grid">
<section><h2>大型砲（重砲）</h2>{'<table>'+heavy+'</table>' if heavy_selected else '<p class="muted">このセッションでは収集していません。</p>'}
<p class="note">命中抽選に到達した大型砲の射撃判定を数えます。実際の砲弾の個数や砲門数、ダメージ発生回数ではありません。</p></section>
<section><h2>航空攻撃 → 艦艇</h2>{'<table>'+air+'</table>' if air_selected else '<p class="muted">このセッションでは収集していません。</p>'}
<p class="note">艦載機・外部参加航空隊が海戦の対艦攻撃処理へ到達した際の記録です。各機の独立した命中抽選ではなく、グループで計算された成功機数を読みます。</p></section></div>
<p>計測異常：{counts[9]:,} 回</p><p class="note">大型砲から除外した軽砲判定：{counts[7]:,} 回 ／ 艦船魚雷判定：{counts[8]:,} 回</p>
<p class="note">このHTMLは全体集計のエクスポートです。艦別・国別・発進元別の詳細は操作画面の「結果・詳細」で確認できます。
航空機数は出撃のたびに加算する延べ数で、対空等で全滅して成功数計算に届かなかったグループは含みません。
対地攻撃・空対空戦・全ての港湾攻撃経路を含む集計ではありません。命中してもダメージが0になる場合があります。</p>
<p class="note">CSVは実時間5秒ごとの累積値です。行を合計せず、最新行か前後の差を使ってください。
途中でセーブをロードする場合は停止して新しい記録を開始してください。複数PCの同じ試合の記録を足すと重複する可能性があります。
このHTMLは自動更新しません。</p><p><a href="checkpoints.csv">CSVを開く</a> · <a href="summary.json">集計データを開く</a></p></main></html>'''
    atomic_text(folder/'report.html',content)

class Recorder:
    def __init__(self,notify=lambda event:None):
        self.notify=notify
        self.stop_event=threading.Event()
        self.folder=None

    def run(self,pid=None,mode='both',interval=5,details=True,recording_name='',first_airplanes=True):
        import frida
        session=script=None; meta=None; counts=[0]*len(KEYS); failure=None;detail_writer=None
        detached=threading.Event(); agent_errors=queue.Queue()
        try:
            if mode not in MODES:raise ValueError('収集対象が不正です')
            device=frida.get_local_device()
            found=[p for p in device.enumerate_processes() if p.name.lower()=='hoi4.exe' and (pid is None or p.pid==pid)]
            if len(found)!=1:
                raise RuntimeError('HOI4を1つ起動してから「収集開始」を押してください。\n複数起動時はCLIの --pid で指定できます。')
            pid=found[0].pid; exe=process_path(pid); profile=profile_for(exe)
            census=bool(first_airplanes and mode!='heavy' and profile.get('air_participant_layout'))
            profile=dict(profile,mode=mode,details=details,first_airplanes=census)
            self.folder=BASE/'recordings'/(datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6])
            self.folder.mkdir(parents=True)
            from session_history import save_notes
            save_notes(self.folder,name=recording_name.strip(),notes='')
            meta={'version':profile['version'],'exe':str(exe),'sha256':profile['sha256'],
                  'pid':pid,'mode':mode,'started_at':utc(),'status':'準備中',
                  'interval_seconds':interval,'format_version':3,'details_enabled':details,'session_id':self.folder.name,'edition':'standard',
                  'scope':'All observed calls in this process; heavy gun decisions and naval-air successful-plane calculation',
                  'checkpoint_semantics':'Cumulative since attach. Do not sum rows.'}
            meta['first_airplanes_enabled']=census
            save_report(self.folder,counts,meta)
            session=device.attach(pid)
            session.on('detached',lambda *args:detached.set())
            script=session.create_script(source(profile))
            def on_message(msg,data):
                if msg['type']=='error':agent_errors.put(msg.get('stack',msg.get('description','agent error')))
            script.on('message',on_message); script.load()
            if not agent_errors.empty():raise RuntimeError(agent_errors.get())
            if details:detail_writer=DetailWriter(self.folder)
            started=time.monotonic(); meta['status']='収集中'
            self.notify({'status':'収集中','version':profile['version'],'folder':str(self.folder)})
            with (self.folder/'checkpoints.csv').open('w',encoding='utf-8-sig',newline='') as file:
                writer=csv.writer(file); writer.writerow(['utc','elapsed_seconds',*KEYS])
                def checkpoint(final=False):
                    nonlocal counts
                    new=list(map(int,script.exports_sync.stop() if final else script.exports_sync.snapshot()))
                    metrics(new)
                    if any(a<b for a,b in zip(new,counts)):raise RuntimeError('累積値が減少したため収集を停止しました')
                    counts=new; meta['updated_at']=utc()
                    meta['elapsed_seconds']=round(time.monotonic()-started,3)
                    if final:meta['ended_at']=meta['updated_at']
                    if census:
                        aircraft=script.exports_sync.airparticipants()
                        if aircraft.get('status') in ('complete','partial') and 'rows' in aircraft:
                            aircraft_rows=len(aircraft['rows'])
                            atomic_text(self.folder/'air_participants.json',json.dumps(aircraft,ensure_ascii=False,indent=2)+'\n')
                            script.exports_sync.ackairparticipants()
                            aircraft={k:v for k,v in aircraft.items() if k!='rows'}
                            aircraft.update(storage='air_participants.json',row_count=aircraft_rows)
                        meta['air_participants']=aircraft
                    if details:
                        delta=script.exports_sync.detailsdelta()
                        meta['details']=detail_writer.apply(delta,dict(meta,counts=metrics(counts)))
                    writer.writerow([meta['updated_at'],round(time.monotonic()-started,3),*counts])
                    file.flush();os.fsync(file.fileno())
                    save_report(self.folder,counts,meta)
                    self.notify({'counts':counts,'details':meta.get('details'),'folder':str(self.folder)})
                checkpoint()
                while not self.stop_event.wait(interval):
                    if detached.is_set():
                        meta['status']='ゲーム終了・切断（最終保存分まで）';break
                    if not agent_errors.empty():raise RuntimeError(agent_errors.get())
                    checkpoint()
                if not detached.is_set():
                    meta['status']='停止済み';checkpoint(final=True)
        except Exception as exc:
            failure=str(exc)
            if meta:meta.update(status='エラー（最終保存分まで）',error=failure)
        finally:
            if script:
                try:script.unload()
                except Exception:pass
            if session:
                try:session.detach()
                except Exception:pass
            if detail_writer:detail_writer.close()
            if meta:
                meta.setdefault('ended_at',utc())
                try:save_report(self.folder,counts,meta)
                except Exception as exc:failure=f'{failure or "保存エラー"}: {exc}'
            self.notify({'done':True,'error':failure,'folder':str(self.folder) if self.folder else None,
                         'status':meta['status'] if meta else '開始できませんでした'})
        return failure is None

def gui(initial_mode='both',smoke_test=False):
    os.chdir(BASE)
    configure_tk()
    import tkinter as tk
    from tkinter import ttk,messagebox
    root=tk.Tk();root.title('Naval Hit Recorder — 海戦の命中記録')
    root.geometry('1060x850');root.minsize(900,750)
    # Match combat-recorder: native Windows ttk theme and system colors.
    style=ttk.Style(root)
    style.configure('Title.TLabel',font=('',20,'bold'))
    style.configure('Metric.TLabel',font=('',14),padding=8)
    frame=ttk.Frame(root,padding=24);frame.pack(fill='both',expand=True)
    ttk.Label(frame,text='海戦の命中記録',style='Title.TLabel').pack(anchor='w')
    ttk.Label(frame,text='HOI4を起動 → 収集開始 → 試合 → 停止・保存',padding=(0,10)).pack(anchor='w')
    mode=tk.StringVar(value=MODES[initial_mode])
    setup=ttk.Frame(frame);setup.pack(fill='x',pady=6)
    selector=ttk.Combobox(setup,textvariable=mode,values=list(MODES.values()),state='readonly',width=24)
    selector.pack(side='left')
    ttk.Label(setup,text='次の試合名（任意）').pack(side='left',padx=8)
    recording_name=tk.StringVar();name_entry=ttk.Entry(setup,textvariable=recording_name,width=35);name_entry.pack(side='left')
    status=tk.StringVar(value='待機中 · 対応：確認済み1.19.2 / 1.19.3')
    ttk.Label(frame,textvariable=status,wraplength=760).pack(anchor='w',pady=8)
    from side_overview import SideOverview
    overview=SideOverview(frame);overview.pack(fill='x',pady=8)
    errors=tk.StringVar(value='計測異常：0回')
    ttk.Label(frame,textvariable=errors).pack(anchor='w',pady=6)
    details_enabled=tk.BooleanVar(value=True)
    detail_check=ttk.Checkbutton(frame,text='艦別・発進元別の詳細も記録する',variable=details_enabled)
    detail_check.pack(anchor='w',pady=4)
    first_airplanes=tk.BooleanVar(value=True)
    participant_check=ttk.Checkbutton(frame,text='初回の航空機数を記録（取得後は追加観測を終了）',variable=first_airplanes)
    participant_check.pack(anchor='w',pady=2)
    detail_status=tk.StringVar(value='詳細：収集開始後に保存します。')
    ttk.Label(frame,textvariable=detail_status,justify='left',wraplength=760).pack(anchor='w',pady=8)
    ttk.Label(frame,text='対戦国を自動集計し、両国の命中・ダメージを左右に表示します。\n航空の成功機数はグループ単位です。実時間5秒おきに自動保存します。\n詳細計測を有効にすると負荷が増えます。実戦・長時間・マルチ同期は未検証です。',wraplength=760).pack(anchor='w',pady=10)
    events=queue.Queue();active=[None];last_folder=[latest_report(BASE)];closing=[False];last_counts=[[0]*10]
    def selected():return next(key for key,value in MODES.items() if value==mode.get())
    def display(counts):
        metrics(counts);last_counts[0]=counts
        errors.set(f'全体の計測異常：{counts[9]:,}回')
    display([0]*10)
    if last_folder[0]:overview.refresh(last_folder[0])
    buttons=ttk.Frame(frame);buttons.pack(anchor='w',pady=12)
    def start():
        active[0]=Recorder(events.put);display([0]*10);overview.reset()
        start_button.config(state='disabled');stop_button.config(state='normal');selector.config(state='disabled')
        detail_check.config(state='disabled');participant_check.config(state='disabled');detail_status.set('詳細を準備中…' if details_enabled.get() else '詳細：無効')
        name_entry.config(state='disabled')
        status.set('実行ファイルを確認して接続中…')
        threading.Thread(target=active[0].run,kwargs={'mode':selected(),'details':details_enabled.get(),'recording_name':recording_name.get(),'first_airplanes':first_airplanes.get()},daemon=False).start()
    def stop():
        if active[0]:active[0].stop_event.set();status.set('保存して停止中…')
    def result():
        if last_folder[0]:show_report_window(root,last_folder[0],*overview.selection())
        else:messagebox.showinfo('収集結果','保存された結果はまだありません。',parent=root)
    def folder():
        if last_folder[0]:os.startfile(last_folder[0])
    start_button=ttk.Button(buttons,text='収集開始',command=start);start_button.pack(side='left',padx=(0,8))
    stop_button=ttk.Button(buttons,text='停止・保存',command=stop,state='disabled');stop_button.pack(side='left',padx=8)
    result_button=ttk.Button(buttons,text='結果・詳細',command=result);result_button.pack(side='left',padx=8)
    folder_button=ttk.Button(buttons,text='保存先を開く',command=folder,state='normal' if last_folder[0] else 'disabled');folder_button.pack(side='left',padx=8)
    def participants():
        if last_folder[0]:
            from air_participants import show_participants
            show_participants(root,last_folder[0])
        else:messagebox.showinfo('初回の航空機数','保存された記録はまだありません。',parent=root)
    ttk.Button(buttons,text='初回の航空機数',command=participants).pack(side='left',padx=8)
    from session_history import show_history
    ttk.Button(buttons,text='過去の記録・比較',command=lambda:show_history(root,BASE)).pack(side='left',padx=8)
    def poll():
        while not events.empty():
            event=events.get()
            if event.get('folder'):
                last_folder[0]=event['folder'];result_button.config(state='normal');folder_button.config(state='normal')
            if 'status' in event:status.set(event['status'])
            if 'counts' in event:
                display(event['counts']);overview.refresh(last_folder[0])
            if event.get('details'):
                d=event['details']
                detail_status.set(f"組合せ {d.get('pair_count',0):,}件 · 読取エラー {d['stats']['read_errors']:,}回 · 上限超過 {d['stats']['pair_overflow']:,}回")
            if event.get('done'):
                active[0]=None;start_button.config(state='normal');stop_button.config(state='disabled');selector.config(state='readonly')
                detail_check.config(state='normal');participant_check.config(state='normal')
                name_entry.config(state='normal')
                if event.get('error') and not smoke_test:messagebox.showerror('海戦の命中記録',event['error'])
                if closing[0]:root.destroy();return
        root.after(200,poll)
    def close():
        if active[0]:closing[0]=True;stop()
        else:root.destroy()
    root.protocol('WM_DELETE_WINDOW',close);root.after(200,poll)
    if smoke_test:
        root.withdraw();root.update_idletasks()
        assert root.winfo_reqwidth()<=1060 and root.winfo_reqheight()<=850, 'Default window is smaller than its contents'
        root.after(300,root.destroy)
    root.mainloop()

def main():
    parser=argparse.ArgumentParser(description='HOI4 naval heavy-gun / air-strike recorder')
    parser.add_argument('--mode',choices=list(MODES),default='both')
    parser.add_argument('--cli',action='store_true');parser.add_argument('--pid',type=int)
    parser.add_argument('--check',type=Path);parser.add_argument('--ui-check',action='store_true')
    parser.add_argument('--no-details',action='store_true',help='CLI: disable ship-level detail recording')
    parser.add_argument('--name',default='',help='CLI: name this recording / trial')
    parser.add_argument('--no-first-airplanes',action='store_true',help='Disable the one-update aircraft census')
    args=parser.parse_args()
    if args.check:print(json.dumps(profile_for(args.check),ensure_ascii=False,indent=2));return 0
    if args.cli:
        recorder=Recorder(lambda event:print(json.dumps(event,ensure_ascii=False),flush=True))
        signal.signal(signal.SIGINT,lambda *args:recorder.stop_event.set())
        return 0 if recorder.run(pid=args.pid,mode=args.mode,details=not args.no_details,recording_name=args.name,first_airplanes=not args.no_first_airplanes) else 1
    gui(args.mode,args.ui_check);return 0
if __name__=='__main__':sys.exit(main())
