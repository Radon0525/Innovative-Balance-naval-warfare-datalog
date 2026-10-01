"""Automatically discovered country matchups; no user-owned-country assumption."""
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk,messagebox,filedialog
from country_names import country_name
from detail_storage import DetailReader
from naval_details import channel_text,loss_text,rate,CHANNELS
from session_history import session_name,period,run_job,make_table

def add_totals(total,p):
    for key in ('events','attempts','hits'):total[key]=total.get(key,0)+p[key]
    if 'damage_measured' in p:
        total['damage_measured']=total.get('damage_measured',0)+p['damage_measured']
        for key in ('str_loss_raw','org_loss_raw'):total[key]=str(int(total.get(key,0))+int(p.get(key,0)))

def load_countries(folder):
    folder=Path(folder);doc=json.loads((folder/'summary.json').read_text(encoding='utf-8'))
    reader=DetailReader(folder,doc);latest=reader.latest_document()
    if doc.get('updated_at','')>=latest.get('updated_at',''):latest.update({k:doc[k] for k in ('status','ended_at','error') if k in doc})
    from air_participants import resolve_document
    latest=resolve_document(folder,latest)
    reader.details=latest.get('details') or {};matches={};tags={}
    for p in reader.iter_pairs():
        a=p['source'].get('country') or 0;b=p['target'].get('country') or 0;key=tuple(sorted((a,b)))
        for entity in (p['source'],p['target']):
            if entity.get('tag'):tags[entity.get('country')]=entity['tag']
        item=matches.setdefault(key,{'key':key,'directions':[{},{}],'events':0})
        index=0 if (a,b)==key else 1
        add_totals(item['directions'][index].setdefault(p['channel'],{}),p);item['events']+=p['events']
    items=sorted(matches.values(),key=lambda m:(-m['events'],m['key']))
    return reader,latest,items,tags,session_name(folder)

class CountryOverview(ttk.Frame):
    def __init__(self,parent,details=False):
        super().__init__(parent);self.details=details;self.folder=None;self.busy=False;self.pending=False;self.generation=0
        self.reader=None;self.matches=[];self.tags={};self.match_key=None;self.match_page=0;self.pages=[0,0];self.rows={}
        self.caption=tk.StringVar(value='記録された対戦国を自動で表示します。')
        ttk.Label(self,textvariable=self.caption,wraplength=1100).pack(anchor='w',pady=4)
        self.match_frame=ttk.Frame(self)
        self.match_tree=ttk.Treeview(self.match_frame,columns=('match','events'),show='headings',height=3)
        self.match_tree.heading('match',text='対戦国（選択すると両国の結果を表示）');self.match_tree.heading('events',text='記録数')
        self.match_tree.column('match',width=600);self.match_tree.column('events',width=100)
        self.match_tree.pack(fill='x');self.match_tree.bind('<<TreeviewSelect>>',self.choose)
        nav=ttk.Frame(self.match_frame);nav.pack(fill='x')
        ttk.Button(nav,text='対戦国一覧：前へ',command=lambda:self.move_matches(-1)).pack(side='left')
        ttk.Button(nav,text='次へ',command=lambda:self.move_matches(1)).pack(side='left')
        self.match_label=tk.StringVar();ttk.Label(nav,textvariable=self.match_label).pack(side='left',padx=8)
        self.tab='summary'
        if details:
            self.tabs=ttk.Notebook(self,height=1);self.tabs.pack(fill='x',pady=5)
            for title in ('国別集計','艦 → 艦の砲撃','航空攻撃・Naval Strike','個別判定の例','艦載機の計算（各国5件）','初回の航空機数'):self.tabs.add(ttk.Frame(self.tabs),text=title)
            self.tabs.bind('<<NotebookTabChanged>>',self.change_tab)
        self.body=ttk.Frame(self);self.body.pack(fill='both',expand=True)
        self.body.columnconfigure(0,weight=1,uniform='countries');self.body.columnconfigure(1,weight=1,uniform='countries');self.body.rowconfigure(0,weight=1)
        self.panels=[];self.trees=[];self.page_labels=[]
        for i in range(2):
            panel=ttk.LabelFrame(self.body,text='国情報を待っています',padding=6);panel.grid(row=0,column=i,sticky='nsew',padx=3)
            self.panels.append(panel)
            tree=make_table(panel,[('label','攻撃の種類 / 艦 → 艦',220),('str','耐久ダメージ',115),('org','指揮統制ダメージ',130),
                ('n','判定 / 参加機',110),('hits','命中 / 成功機',115),('rate','割合',90)],height=10 if details else 6)
            self.trees.append(tree)
            if not details:
                for key,width in [('label',100),('str',80),('org',85),('n',60),('hits',60),('rate',55)]:tree.column(key,width=width,minwidth=40)
            tree.bind('<Double-1>',lambda e,index=i:self.drill(index))
            if details:
                nav=ttk.Frame(panel);nav.pack(fill='x')
                ttk.Button(nav,text='前へ',command=lambda index=i:self.move(index,-1)).pack(side='left')
                label=tk.StringVar();self.page_labels.append(label);ttk.Label(nav,textvariable=label).pack(side='left',padx=6)
                ttk.Button(nav,text='次へ',command=lambda index=i:self.move(index,1)).pack(side='left')
        self.note=tk.StringVar(value='国名・命中・耐久／指揮統制ダメージは、記録内の攻撃から自動集計します。')
        self.note_label=ttk.Label(self,textvariable=self.note,wraplength=1100,justify='left');self.note_label.pack(anchor='w',pady=4)
        if details:
            from air_participants import ParticipantView
            self.participant_view=ParticipantView(self)
    def selection(self):return None,'all'
    def reset(self):
        self.generation+=1;self.folder=None;self.reader=None;self.matches=[];self.pending=False;self.match_key=None
        for tree in self.trees:tree.delete(*tree.get_children())
        self.match_frame.pack_forget();self.caption.set('新しい記録を準備中…')
    def refresh(self,folder=None):
        if folder:self.folder=folder
        if not self.folder:return
        self.generation+=1;self.pending=True;self.start_worker()
    def start_worker(self):
        if self.busy or not self.pending:return
        self.busy=True;self.pending=False;generation=self.generation;folder=self.folder
        def done(result,error):
            self.busy=False
            if generation==self.generation:
                if error:self.note.set(f'記録を読み込めません：{error}')
                else:
                    self.reader,doc,self.matches,self.tags,name=result;self.document=doc
                    self.caption.set(f'この記録：{name} · {doc.get("status","")}\n{period(doc)}')
                    if self.match_key not in [m['key'] for m in self.matches]:self.match_key=self.matches[0]['key'] if self.matches else None
                    self.show_matches();self.draw()
                    d=doc.get('details') or {};s=d.get('stats',{})
                    text='左国 → 右国の攻撃を左に、右国 → 左国の攻撃を右に表示。複数国の記録は対戦国ごとに分けます。'
                    if not self.matches:text='国別の攻撃記録がまだありません。国情報のない旧記録からは国別結果を復元できません。'
                    if s.get('pair_overflow') or s.get('read_errors') or any(d.get('damage_stats',{}).values()):text+=' 注意：未収録・未測定の詳細があります。'
                    if self.tab not in ('air_examples','air_participants'):self.note.set(text)
            self.start_worker()
        run_job(self,lambda:load_countries(folder),done)
    def name(self,country):return country_name(country,self.tags.get(country))
    def show_matches(self):
        if len(self.matches)>1:self.match_frame.pack(fill='x',before=self.tabs if self.details else self.body,pady=4)
        else:self.match_frame.pack_forget()
        self.match_page=max(0,min(self.match_page,max(0,(len(self.matches)-1)//50)))
        self.match_tree.delete(*self.match_tree.get_children())
        for j,m in enumerate(self.matches[self.match_page*50:(self.match_page+1)*50]):
            self.match_tree.insert('','end',iid=str(self.match_page*50+j),values=(self.name(m['key'][0])+' ⇔ '+self.name(m['key'][1]),m['events']))
        self.match_label.set(f'{self.match_page+1} / {max(1,(len(self.matches)+49)//50)}ページ · {len(self.matches)}組')
    def move_matches(self,delta):self.match_page+=delta;self.show_matches()
    def choose(self,event=None):
        selected=self.match_tree.selection()
        if selected:self.match_key=self.matches[int(selected[0])]['key'];self.pages=[0,0];self.draw()
    def change_tab(self,event=None):
        self.tab=['summary','heavy','air','samples','air_examples','air_participants'][self.tabs.index(self.tabs.select())];self.pages=[0,0];self.draw()
        if self.tab not in ('air_examples','air_participants'):self.note.set('左国 → 右国の攻撃を左に、右国 → 左国の攻撃を右に表示。各行の内訳はダブルクリックで開きます。')
    def move(self,index,delta):self.pages[index]+=delta;self.draw()
    def draw(self):
        self.rows.clear()
        if self.details:
            if self.tab=='air_participants':
                self.body.pack_forget();self.participant_view.pack(fill='both',expand=True,before=self.note_label)
                self.participant_view.set_document(getattr(self,'document',{}));self.note.set('この記録の初回だけを表示します。過去の試合とは合算しません。');return
            self.participant_view.pack_forget();self.body.pack(fill='both',expand=True,before=self.note_label)
        for tree in self.trees:
            tree.configure(selectmode='browse')
            tree.delete(*tree.get_children())
        if self.match_key is None:
            self.panels[0].configure(text='全体（国別の攻撃記録なし）');self.panels[1].configure(text='国別表示には新しい攻撃記録が必要です')
            doc=getattr(self,'document',{});c=doc.get('counts',{})
            if self.tab=='summary' and c:
                for name,n,h in [('大型砲',c['heavy_attempts'],c['heavy_hits']),('航空攻撃',c['air_planes'],c['air_successes'])]:
                    self.trees[0].insert('','end',values=(name,'未記録','未記録',n,h,rate(h,n)))
            return
        match=next(m for m in self.matches if m['key']==self.match_key)
        for i,tree in enumerate(self.trees):
            a,b=self.match_key if i==0 else self.match_key[::-1]
            self.panels[i].configure(text=f'{self.name(a)} → {self.name(b)}')
            if self.tab=='summary':
                order=list(CHANNELS)
                rows=[dict(r,channel=ch) for ch,r in sorted(match['directions'][i].items(),key=lambda item:order.index(item[0]) if item[0] in order else len(order))];count=len(rows);page=0
            elif self.tab=='air_examples':
                from air_trace_report import examples_for
                rows,seen,data=examples_for(self.reader.details,(a,b));count=len(rows);page=0
            else:rows,count,page=self.reader.page(self.tab,self.pages[i],100,flow=(a,b))
            self.pages[i]=page
            if self.details:self.page_labels[i].set(f'{page+1}/{max(1,(count+99)//100)} · {count:,}件')
            if self.tab=='air_examples':
                self.page_labels[i].set(f'全{seen:,}攻撃群から抽選 {count}件')
                self.note.set('各国から抽選した計算例です。行をダブルクリックすると計算過程を開きます。'+(' 国組数の上限による未収録があります。' if data.get('stats',{}).get('flow_overflow') else ''))
                if data.get('stats',{}).get('read_errors'):self.note.set(self.note.get()+' 途中の数値の取得に失敗した攻撃があります。')
            for p in rows:
                if self.tab=='summary':label=channel_text(p['channel']);n=p['attempts'];h=p['hits']
                else:
                    label=p['source']['name']+' → '+p['target']['name']
                    if self.tab in ('samples','air_examples'):
                        label=f"#{p['sequence']} {label}";n=1 if p['kind']=='heavy' else p['planes'];h=int(p.get('hit',False)) if p['kind']=='heavy' else p['successes']
                    else:n=p['attempts'];h=p['hits']
                row=tree.insert('','end',values=(label,loss_text(p,'str_loss_raw'),loss_text(p,'org_loss_raw'),n,h,rate(h,n)))
                self.rows[(i,row)]=p
            if not rows:tree.insert('','end',values=('艦載機の抽選記録なし（旧記録は非対応）' if self.tab=='air_examples' else 'この方向の攻撃記録なし','—','—','—','—','—'))
    def drill(self,index):
        selected=self.trees[index].selection();p=self.rows.get((index,selected[0])) if selected else None
        if not p:return
        if self.tab=='air_examples':
            from air_trace_report import show_trace
            show_trace(self,p);return
        w=tk.Toplevel(self);w.title('国別・攻撃の内訳');w.geometry('750x460')
        text=channel_text(p['channel'])+'\n'
        if 'source' in p:text+=p['source']['name']+' → '+p['target']['name']+'\n'+p['source']['id']+' → '+p['target']['id']+'\n'
        text+=f"耐久ダメージ：{loss_text(p,'str_loss_raw')}\n指揮統制ダメージ：{loss_text(p,'org_loss_raw')}\n"
        if 'attempts' in p:text+=f"回数：{p['events']} / 判定・参加機：{p['attempts']} / 命中・成功機：{p['hits']}\n"
        if 'damage_measured' in p:text+=f"ダメージ測定済み：{p['damage_measured']}回\n"
        if 'context' in p:
            from naval_details import CONTEXTS
            text+='状況：'+CONTEXTS.get(p['context'],p['context'])+'\n'
        if 'sequence' in p:text+=f"命中しきい値：{p.get('threshold','—')}\n比較乱数：{p.get('random_scaled','—')}"
        ttk.Label(w,text=text,wraplength=710,padding=20,justify='left').pack(anchor='w')

def show_report_window(parent,folder,*unused):
    window=tk.Toplevel(parent);window.title('海戦の結果・詳細 — 国別');window.geometry('1260x850');window.minsize(1000,720)
    view=CountryOverview(window,details=True);view.pack(fill='both',expand=True,padx=12,pady=10)
    buttons=ttk.Frame(window);buttons.pack(fill='x',padx=12,pady=8)
    ttk.Button(buttons,text='最新の保存内容に更新',command=view.refresh).pack(side='left')
    def export():
        if not view.reader:return
        path=filedialog.asksaveasfilename(parent=window,title='この記録の国別・艦別集計を保存',defaultextension='.csv',filetypes=[('CSV','*.csv')])
        if path:
            from paged_details import export_pairs
            run_job(window,lambda:export_pairs(view.reader,path),lambda result,error:messagebox.showerror('保存エラー',str(error),parent=window) if error else view.note.set('全対戦国・全ページの艦別集計をCSV保存しました。'))
    ttk.Button(buttons,text='全対戦国のCSV保存',command=export).pack(side='left',padx=8)
    def history():
        from session_history import show_history
        show_history(window,Path(folder).parent.parent)
    ttk.Button(buttons,text='過去の記録・比較',command=history).pack(side='left',padx=8)
    ttk.Button(buttons,text='閉じる',command=window.destroy).pack(side='right')
    view.refresh(folder);return window

def show_comparison(parent,folders):
    window=tk.Toplevel(parent);window.title('試合ごとの国別比較');window.geometry('1250x790')
    frame=ttk.Frame(window,padding=16);frame.pack(fill='both',expand=True)
    ttk.Label(frame,text='各試合の国と攻撃方向を自動表示します。試合間の値は合算しません。',font=('',13,'bold')).pack(anchor='w')
    note=tk.StringVar(value='比較を読み込み中…');ttk.Label(frame,textvariable=note,wraplength=1190).pack(anchor='w',pady=8)
    tree=make_table(frame,[('trial','試合名',170),('flow','攻撃国 → 相手国',300),('channel','攻撃の種類',190),
        ('str','耐久ダメージ',130),('org','指揮統制ダメージ',145),('n','判定 / 参加機',110),('hits','命中 / 成功機',115),
        ('rate','割合',90),('period','記録期間',300),('status','状態',190),('notes','設計メモ',350)])
    state={'rows':[],'page':0,'busy':False}
    nav=ttk.Frame(frame);nav.pack(fill='x',pady=8);label=tk.StringVar()
    def draw():
        rows=state['rows'];state['page']=max(0,min(state['page'],max(0,(len(rows)-1)//100)))
        tree.delete(*tree.get_children())
        for row in rows[state['page']*100:(state['page']+1)*100]:tree.insert('','end',values=row)
        label.set(f"{state['page']+1}/{max(1,(len(rows)+99)//100)}ページ · {len(rows)}件")
    def move(delta):state['page']+=delta;draw()
    ttk.Button(nav,text='前へ',command=lambda:move(-1)).pack(side='left');ttk.Label(nav,textvariable=label).pack(side='left',padx=8)
    ttk.Button(nav,text='次へ',command=lambda:move(1)).pack(side='left')
    def load():
        if state['busy']:return
        state['busy']=True
        def work():
            from session_history import read_notes
            result=[]
            for folder in folders:
                _,doc,matches,tags,name=load_countries(folder);notes=read_notes(folder).get('notes','')
                if not matches:result.append([name,'国情報なし','—','未記録','未記録','—','—','—',period(doc),doc.get('status',''),notes])
                for match in matches:
                    for index,direction in enumerate(match['directions']):
                        a,b=match['key'] if index==0 else match['key'][::-1]
                        flow=country_name(a,tags.get(a))+' → '+country_name(b,tags.get(b))
                        for channel,p in direction.items():result.append([name,flow,channel_text(channel),loss_text(p,'str_loss_raw'),loss_text(p,'org_loss_raw'),
                            p['attempts'],p['hits'],rate(p['hits'],p['attempts']),period(doc),doc.get('status',''),notes])
            return result
        def done(rows,error):
            state['busy']=False
            if error:note.set(str(error));return
            state['rows']=rows;draw();note.set('各国の戦果を攻撃方向別に表示。期間・対戦国・設計メモを確認して比較してください。')
        run_job(window,work,done)
    ttk.Button(nav,text='最新の保存内容に更新',command=load).pack(side='right')
    load();return window
