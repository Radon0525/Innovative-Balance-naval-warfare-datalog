"""One folder per recording, editable annotations, and independent trial comparisons."""
import json
import os
import queue
import threading
import uuid
from datetime import datetime
from pathlib import Path
from naval_details import channel_text,loss_text,rate

def read_notes(folder):
    path=Path(folder)/'session.json'
    if not path.exists():return {}
    result=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(result,dict):raise ValueError('試合メモの形式が不正です')
    return result

def save_notes(folder,**changes):
    folder=Path(folder);data=read_notes(folder)
    data.update(changes)
    if len(data.get('name',''))>200 or len(data.get('notes',''))>4000:
        raise ValueError('試合名は200文字、設計メモは4000文字以内で入力してください。')
    path=folder/'session.json';temp=folder/('session-'+uuid.uuid4().hex+'.tmp')
    try:
        with temp.open('w',encoding='utf-8') as f:
            f.write(json.dumps(data,ensure_ascii=False,indent=2)+'\n');f.flush();os.fsync(f.fileno())
        os.replace(temp,path)
    finally:
        if temp.exists():temp.unlink()
    return data

def session_name(folder):
    notes=read_notes(folder)
    return notes.get('name') or Path(folder).name

def local_time(value):
    try:return datetime.fromisoformat(value).astimezone().strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError,TypeError):return value or '—'

def period(doc):
    return f"{local_time(doc.get('started_at'))} ～ {local_time(doc.get('ended_at') or doc.get('updated_at'))}"

def list_sessions(base):
    records=[];errors=[]
    for path in (Path(base)/'recordings').glob('*/summary.json'):
        try:
            doc=json.loads(path.read_text(encoding='utf-8'));notes=read_notes(path.parent)
            records.append(dict(folder=path.parent,name=notes.get('name') or path.parent.name,notes=notes.get('notes',''),
                started=doc.get('started_at',''),period=period(doc),status=doc.get('status',''),version=doc.get('version',''),
                mode=doc.get('mode','both'),counts=doc['counts']))
        except (OSError,ValueError,KeyError,TypeError) as exc:errors.append(f'{path.parent.name}: {exc}')
    return sorted(records,key=lambda r:(r['started'],r['folder'].name),reverse=True),errors

def comparison_data(folders,countries,side):
    from paged_details import load_view
    results=[]
    for folder,country in zip(folders,countries):
        reader,doc,choices,rows=load_view(folder,country if side!='all' else None,False,side)
        d=doc.get('details') or {};warning=''
        if side=='all' and d.get('channels'):
            rows=[dict(p,channel=k) for k,p in d['channels'].items()]
        if side!='all' and country is None:warning='自軍の国を選択してください'
        elif side!='all' and not d:warning='国別の詳細が未記録'
        elif side!='all' and country not in choices.values():warning='選択国の記録なし'
        elif not rows:warning='この条件の攻撃記録なし'
        if d.get('stats',{}).get('pair_overflow'):warning+=' 組合せ上限により国別の一部が未収録'
        if d.get('stats',{}).get('read_errors') or any(d.get('damage_stats',{}).values()):warning+=' 未測定・識別エラーあり'
        results.append(dict(folder=Path(folder),name=session_name(folder),notes=read_notes(folder).get('notes',''),
            doc=doc,choices=choices,rows=rows,warning=warning.strip()))
    return results

def run_job(window,job,done):
    """No Tk calls on the worker; destroyed windows discard their queued results."""
    result=queue.Queue()
    def work():
        try:result.put((job(),None))
        except Exception as exc:result.put((None,exc))
    threading.Thread(target=work,daemon=True,name='naval-history-worker').start()
    state={'after':None,'closed':False}
    def poll():
        if state['closed']:return
        try:value,error=result.get_nowait()
        except queue.Empty:state['after']=window.after(50,poll)
        else:
            window.unbind('<Destroy>',binding);done(value,error)
    def close(event):
        if event.widget is window:
            state['closed']=True
            if state['after']:window.after_cancel(state['after'])
    binding=window.bind('<Destroy>',close,add='+');state['after']=window.after(50,poll)

def make_table(parent,columns,height=14,selectmode='browse'):
    from tkinter import ttk
    frame=ttk.Frame(parent);frame.pack(fill='both',expand=True)
    frame.columnconfigure(0,weight=1);frame.rowconfigure(0,weight=1)
    tree=ttk.Treeview(frame,columns=[c[0] for c in columns],show='headings',height=height,selectmode=selectmode)
    for key,label,width in columns:tree.heading(key,text=label);tree.column(key,width=width,minwidth=70,stretch=False)
    x=ttk.Scrollbar(frame,orient='horizontal',command=tree.xview);y=ttk.Scrollbar(frame,orient='vertical',command=tree.yview)
    tree.configure(xscrollcommand=x.set,yscrollcommand=y.set)
    tree.grid(row=0,column=0,sticky='nsew');x.grid(row=1,column=0,sticky='ew');y.grid(row=0,column=1,sticky='ns')
    return tree

def show_comparison(parent,folders):
    from naval_countries import show_comparison as show
    return show(parent,folders)

def show_history(parent,base):
    import tkinter as tk
    from tkinter import ttk,messagebox,filedialog
    from naval_details import show_report_window
    window=tk.Toplevel(parent);window.title('過去の記録・比較');window.geometry('1180x790')
    frame=ttk.Frame(window,padding=16);frame.pack(fill='both',expand=True)
    ttk.Label(frame,text='1回の「収集開始」～「停止・保存」が1つの試合記録です。',font=('',14,'bold')).pack(anchor='w')
    ttk.Label(frame,text='記録名・設計メモを付け、過去の結果を個別に開けます。比較する試合をチェックして「選んだ試合を比較」を押してください。').pack(anchor='w',pady=8)
    tree=make_table(frame,[('pick','比較',65),('name','試合名',230),('period','記録期間',310),('status','状態',180),('mode','収集対象',150),('notes','設計メモ',350)])
    state={'records':[],'page':0,'picked':set(),'rows':{},'busy':False}
    status=tk.StringVar();ttk.Label(frame,textvariable=status,wraplength=1120).pack(anchor='w',pady=4)
    pager=ttk.Frame(frame);pager.pack(fill='x')
    def page(delta):state['page']+=delta;draw()
    prev=ttk.Button(pager,text='前のページ',command=lambda:page(-1));prev.pack(side='left')
    page_label=tk.StringVar();ttk.Label(pager,textvariable=page_label).pack(side='left',padx=12)
    nxt=ttk.Button(pager,text='次のページ',command=lambda:page(1));nxt.pack(side='left')
    edit=ttk.Frame(frame);edit.pack(fill='x',pady=8)
    ttk.Label(edit,text='試合名').grid(row=0,column=0,sticky='w')
    name=tk.StringVar();ttk.Entry(edit,textvariable=name,width=65).grid(row=0,column=1,sticky='ew')
    ttk.Label(edit,text='設計メモ').grid(row=1,column=0,sticky='nw')
    notes=tk.Text(edit,height=3,width=80);notes.grid(row=1,column=1,sticky='ew');edit.columnconfigure(1,weight=1)
    def selected():
        sel=tree.selection();return state['rows'].get(sel[0]) if sel else None
    def select(event=None):
        item=selected();name.set(item['name'] if item else '')
        notes.delete('1.0','end')
        if item:notes.insert('1.0',item['notes'])
    tree.bind('<<TreeviewSelect>>',select)
    def draw():
        items=state['records'];count=len(items);state['page']=max(0,min(state['page'],max(0,(count-1)//50)))
        tree.delete(*tree.get_children());state['rows'].clear()
        for item in items[state['page']*50:(state['page']+1)*50]:
            row=tree.insert('','end',values=('✓' if item['folder'] in state['picked'] else '□',item['name'],item['period'],item['status'],
                {'both':'大型砲＋航空','heavy':'大型砲','air':'航空'}.get(item['mode'],item['mode']),item['notes'].replace('\n',' / ')))
            state['rows'][row]=item
        page_label.set(f"{state['page']+1} / {max(1,(count+49)//50)}ページ · {count}記録 · 比較選択 {len(state['picked'])}件")
        prev.configure(state='normal' if state['page'] else 'disabled');nxt.configure(state='normal' if (state['page']+1)*50<count else 'disabled')
        select()
    def load():
        if state['busy']:return
        state['busy']=True;status.set('履歴を読み込み中…')
        def done(result,error):
            state['busy']=False
            if error:status.set(str(error));return
            records,errors=result;state['records']=records
            state['picked'].intersection_update(r['folder'] for r in records)
            status.set(f'読込できない記録：{len(errors)}件'+(' · '+errors[0] if errors else ''));draw()
        run_job(window,lambda:list_sessions(base),done)
    def toggle(event=None):
        if event is not None:
            if tree.identify_column(event.x)!='#1':return
            row=tree.identify_row(event.y)
            if row:tree.selection_set(row)
        item=selected()
        if not item:return
        key=item['folder']
        if key in state['picked']:state['picked'].remove(key)
        elif len(state['picked'])>=6:messagebox.showinfo('試合の比較','一度に比較できるのは6試合までです。',parent=window);return
        else:state['picked'].add(key)
        row=tree.selection()[0];tree.set(row,'pick','✓' if key in state['picked'] else '□')
        page_label.set(f"{state['page']+1} / {max(1,(len(state['records'])+49)//50)}ページ · {len(state['records'])}記録 · 比較選択 {len(state['picked'])}件")
    tree.bind('<ButtonRelease-1>',toggle)
    def open_selected(event=None):
        item=selected()
        if item:show_report_window(window,item['folder'])
    tree.bind('<Double-1>',open_selected)
    def save():
        item=selected()
        if not item:return
        try:save_notes(item['folder'],name=name.get().strip(),notes=notes.get('1.0','end-1c'))
        except (OSError,ValueError) as exc:messagebox.showerror('メモを保存できません',str(exc),parent=window);return
        load()
    def compare():
        folders=[r['folder'] for r in state['records'] if r['folder'] in state['picked']]
        if len(folders)<2:messagebox.showinfo('試合の比較','比較する試合を2～6件チェックしてください。',parent=window);return
        show_comparison(window,folders)
    def browse():
        folder=filedialog.askdirectory(parent=window,title='summary.jsonが入った記録フォルダーを選択')
        if folder:show_report_window(window,folder)
    buttons=ttk.Frame(frame);buttons.pack(fill='x',pady=6)
    for label,command in [('選択した記録を開く',open_selected),('比較に追加／解除',toggle),('選んだ試合を比較',compare),
                          ('試合名・メモを保存',save),('一覧を更新',load),('別の保存先を開く',browse)]:
        ttk.Button(buttons,text=label,command=command).pack(side='left',padx=3)
    load();return window
