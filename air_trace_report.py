"""Present recorded calculation operands; never invent missing historical values."""
from decimal import Decimal
import json
import tkinter as tk
from tkinter import ttk
from naval_details import channel_text

def number(value):
    if value is None:return '未記録'
    return format(Decimal(str(value))/100000,'f').rstrip('0').rstrip('.') if int(value)%100000 else str(int(value)//100000)

def attack_build_explanation(data):
    if not data:return ['\n集約前の内訳：この記録では未収録です。新しい記録から航空隊ごとの内訳を表示します。']
    f=lambda k:number(data.get(k))
    lines=['\n1-A. 航空隊の対艦攻撃を集約する計算',
      '各航空隊の機数配分を四捨五入し、火力に機数と妨害係数を掛けた合計を、配分機数の合計で割ります。単純な全機の火力合計ではありません。']
    for r in data.get('wings',[]):
        rf=lambda k:number(r.get(k))
        optional=lambda k:rf(k) if k in r else ('未記録' if data.get('error') or r.get('error') else '0（この分岐は未適用）')
        lines.extend([f"\n航空隊 {r['index']}：配分 {r.get('assigned_planes','未記録')}機",
          f"使用可能機数 {r.get('ready_planes','未記録')} × 攻撃群の機数 {r.get('group_planes','未記録')} ÷ 集約対象の使用可能機数 {rf('eligible_planes_scaled')} → 丸め前 {rf('allocation_before_round')} → 四捨五入",
          f"任務用能力キャッシュの対艦攻撃 {rf('cached_attack')} × 内部換算0.1 → 切捨て" + (f" → 港湾任務係数 {rf('port_attack_factor')} を乗算・切捨て" if 'port_attack_factor' in r else '') + f" = {rf('scaled_attack')}",
          f"火力係数の内訳：1 ＋ エース {optional('ace_bonus')} ＋ 国 {optional('country_bonus')} ＋ 任務 {optional('mission_bonus')}",
          f"さらに経験値 {optional('experience')} × 経験補正 {optional('experience_bonus')}（切捨て）、天候値 {optional('weather')} × 天候補正 {optional('weather_bonus')}（切捨て）を加算 → 係数 {rf('total_factor')}",
          f"{rf('scaled_attack')} × {rf('total_factor')} → 切捨て = 妨害前の対艦攻撃 {rf('attack_before_disruption')}",
          f"保存されている妨害量：{rf('disruption_raw')}"])
        if 'disruption_denominator' in r:
            lines.extend([
              f"妨害耐性：対空攻撃 {rf('disruption_attack')} × 定義係数 {rf('disruption_attack_factor')}、対空防御 {rf('disruption_defence')} × 定義係数 {rf('disruption_defence_factor')}、基準で割った速度 {rf('disruption_speed')} × 定義係数 {rf('disruption_speed_factor')}",
              '各積を切捨て、各々に1を足し、3つを順に乗算・切捨て。最後に配分機数を掛けます。',
              f"妨害計算の分母 = {rf('disruption_denominator')}。妨害量 ÷ 分母 → 切捨て = {rf('disruption_ratio')}（分母0／異常値なら内部値4294967295）",
              f"ゲームの固定小数点平方根処理 → {rf('disruption_root')}。通常の実数計算とは丸めが異なります。",
              f"1 − 平方根の結果 × 約0.31625553447 → 制限前の火力係数 {rf('disruption_preclamp')}（正確な整数変換は下記参照）",
              '整数変換（符号付き整数）：x = 平方根の内部整数 × 100000、h = (x × −7646589624380956197) >> 64、q = h >> 17、制限前内部値 = 100000 + q + (q < 0 ? 1 : 0)。異常値は下限へ。'])
        elif r.get('disruption_raw')=='0':lines.append('妨害量0のため、妨害耐性・平方根計算を省略して火力係数1。')
        else:lines.append('妨害計算の途中値は未記録、または任務・機数・対空防御の条件によって途中計算を省略しています。')
        lines.extend([
          f"ゲームが返した妨害後の火力係数 {rf('disruption_factor')}（下限0.001・上限1）",
          f"{rf('attack_before_disruption')} × {r.get('assigned_planes','未記録')}機 → 切捨て → 妨害係数 {rf('disruption_factor')} を乗算 → 切捨て = この航空隊の寄与 {rf('attack_contribution')}"])
        if r.get('disruption_factor')=='100':lines.append('火力係数が下限0.001に達しています。妨害前火力の0.1%が集約へ入ります。')
        if r.get('error'):lines.append('取得エラー：'+r['error'])
    lines.extend([f"\n全航空隊の寄与合計 {f('attack_sum')} ÷ 配分機数合計 {data.get('assigned_planes','未記録')}機 → 切捨て = 平均火力 {f('average_attack')}"])
    if data.get('carrier_country_applied'):
        lines.append(f"平均火力 × (1 ＋ 国の空母対艦攻撃補正 {f('carrier_country_bonus')}) → 切捨て = {f('after_carrier_country')}")
    else:lines.append(f"この経路の国の空母対艦攻撃補正は未適用。火力 {f('after_carrier_country')}")
    if data.get('external'):lines.append(f"外部任務の火力係数 {f('external_factor')} を乗算 → 切捨て")
    lines.append(f"集約の最終対艦攻撃：{f('final_attack')}")
    if data.get('omitted_wings'):lines.append(f"航空隊内訳の上限超過：{data['omitted_wings']}隊。合計値には全隊を含みます。")
    if data.get('error'):lines.append('取得エラー：'+data['error'])
    if not data.get('complete'):lines.append('集約処理は未完了です。途中値だけで最終火力を判断しないでください。')
    return lines

def explanation(event):
    trace=event.get('air_trace')
    title=f"攻撃 #{event.get('sequence','?')}　{event['source']['name']} → {event['target']['name']}\n{channel_text(event['channel'])}\n記録時刻：{event.get('recorded_at','未記録')}\n"
    if not trace:return title+'\nこの記録には計算過程が保存されていません。更新後に新しく記録してください。'
    v=trace.get('values',{});u=trace.get('upstream',{});f=lambda k:number(v.get(k));uf=lambda k:number(u.get(k))
    lines=[title,'数値はゲームで観測した値です。内部では 100000 = 1 の整数を使用します。',
      '以下の「切捨て」は各整数除算で小数部分を0方向へ落とす処理です。丸める位置も計算結果に影響します。',
      '記録範囲：攻撃群への集約済み能力値・参加数 → 成功機数 → 対空軽減 → クリティカル → ダメージ適用。',
      '航空隊の能力キャッシュ以前の機体設計の加算内訳、CAP・撃墜数自体の内部抽選、攻撃対象の選択過程は未収録です。',
      '\n1. 攻撃に到達するまで',
      f"攻撃群の機数：{u.get('initial_planes','未記録')}、出撃参加係数：{uf('participation')}",
      f"集約済み対艦攻撃：{uf('attack')}、集約済み照準：{uf('targetting')}"]
    lines.extend(attack_build_explanation(u.get('attack_build')))
    if u:
        if u.get('external'):lines.append('外部任務：この処理での海戦参加効率補正はスキップ。')
        else:lines.append(f"海戦参加効率を0〜1に制限：{uf('efficiency')} → 機数×効率を四捨五入：{u.get('effective_planes','未記録')}機")
        lines.extend([f"迎撃前 {u.get('before_cap','未記録')}機 − CAP側の除外・損失 {u.get('cap_losses','未記録')}機 − 対空撃墜 {u.get('aa_losses','未記録')}機 = 攻撃判定へ {event['planes']}機",
          f"空母補正：{'適用' if u.get('carrier_bonus') else 'この経路では不適用'}、係数 {f('carrier_multiplier')} → 補正後の対艦攻撃 {f('attack')}"])
    else:lines.append('この攻撃には前段の記録がありません。')
    lines.extend(['\n2. 成功機数の計算',
      f"照準 {f('targetting')} × 照準補正 {f('targetting_modifier')} → 切捨て → 定義係数 {f('targetting_to_amount')} を乗算 → 切捨て → 0〜1に制限 = {f('probability')}",
      f"{event['planes']}機 × {f('probability')} × 乱数 {f('hit_random')} → 丸め前 {f('round_input')}機",
      f"丸め前の値を四捨五入 → 成功 {event['successes']}機（機体ごとの独立した命中抽選ではありません）"])
    if event['successes']==0:
        lines.append('成功機数が0のため、以降の軽減・クリティカル・ダメージ計算は実行されません。')
    else:
        lines.extend(['\n3. 対空によるダメージ軽減',
          f"艦隊側対空 {f('aa_fleet')} ＋ 対象艦の対空 = 合計 {f('aa_sum')}",
          f"合計対空 ^ 指数 {f('aa_exponent')} = ゲームのべき乗処理の結果 {f('aa_power')}",
          f"上記 × 軽減係数 {f('aa_multiplier')} → 切捨て → 0〜上限 {f('aa_cap')} に制限 = 軽減率 {f('reduction')}（合計対空が0以下なら0）",
          f"1機あたり：対艦攻撃 {f('attack')} × (1 − {f('reduction')}) → 切捨て",
          f"成功 {event['successes']}機を乗算 → 基礎ダメージ {f('base_damage')}",
          f"耐久：{f('base_damage')} × 定義係数 {f('damage_to_str')} → 切捨て = {f('base_str')}",
          f"指揮統制：{f('base_damage')} × 定義係数 {f('damage_to_org')} → 切捨て = {f('base_org')}",
          '\n4. クリティカル判定',
          f"対象の信頼性 {f('reliability')} を上限1に制限。信頼性不足分 = 1 − min(1,信頼性)",
          f"(1 ＋ {f('critical_chance_bonus')}) × {f('critical_chance_base')} → 切捨て → 信頼性不足分を乗算 → 切捨て = {f('critical_base_threshold')}",
          f"上記 × max(0, 1 − 補正 {f('critical_modifier')}) → 切捨て。基準値が正なら下限0.001を適用 = しきい値 {f('critical_threshold')}",
          f"乱数 {f('critical_random')} < しきい値 {f('critical_threshold')} を判定",
          f"倍率が1より大きいクリティカル分岐：{'実行' if v.get('critical_active') else '実行なし'}"])
        if 'aa_sum' in v and int(v['aa_sum'])<=0:lines.append('合計対空が0以下のため、べき乗計算は実行されていません。')
        if v.get('critical_active'):
            lines.extend([f"成立時の倍率：1 ＋ (信頼性不足分 × {f('critical_damage')} → 切捨て) ÷ 成功機数 → 切捨て = {f('critical_factor')}（内部の異常値処理も観測値に含む）",'\n5. 特殊クリティカルの分岐',
              f"対象条件による除外：{('あり' if v['special_gate_blocked'] else 'なし') if 'special_gate_blocked' in v else '対象未解決／未記録'}",
              f"特殊係数 {f('special_parameter')} × 対象艦の係数 {f('special_ship_factor')} → 切捨て = {f('special_numerator')}",
              f"信頼性 {f('special_reliability')} で除算 → しきい値 {f('special_threshold')}。信頼性≦0またはしきい値≧1なら抽選を省略。",
              f"特殊乱数 {f('special_random')} < しきい値（抽選した場合のみ）",
              f"特殊効果を適用：{'はい' if v.get('special_handled') else 'いいえ'}"])
            if v.get('special_handled'):
                lines.extend([f"効果候補 {v.get('effect_count','未記録')}件、重み合計 {f('effect_weight_sum')}。乱数 {f('effect_random')} × 重み合計を切捨て、候補順に重みを引いて最初に負になる候補を選択。",
                  '候補の重み：'+', '.join(f"#{p['index']+1}={number(p['weight'])}" for p in v.get('effect_candidates',[])),
                  f"選択された候補：{'#'+str(v['effect_selected']+1) if v.get('effect_selected',-1)>=0 else '未記録／一覧の上限外'}",
                  f"耐久：{f('base_str')} × {f('effect_str_multiplier')} → 切捨て ＋ {f('effect_str_add')} = {f('special_str')}",
                  f"指揮統制：{f('base_org')} × {f('effect_org_multiplier')} → 切捨て ＋ {f('effect_org_add')} = {f('special_org')}"])
                if v.get('effect_candidates_truncated'):lines.append('候補一覧は256件を超えたため省略があります。')
            else:lines.append(f"特殊効果が適用されなければ、耐久・指揮統制の基礎ダメージに倍率 {f('critical_factor')} を掛け、それぞれ切捨て。")
        lines.extend(['\n6. 計算結果と実際の減少',f"適用前の計算ダメージ：耐久 {f('final_str')}、指揮統制 {f('final_org')}"])
    for a in trace.get('applications',[]):
        for key,label in [('str','耐久'),('org','指揮統制')]:
            lines.append(f"{label}：適用前 {number(a.get('before_'+key))}、渡したダメージ {number(a.get('calculated_'+key))} → 適用後 {number(a.get('after_'+key))}。実減少 {number(a.get('actual_'+key))}")
    if event.get('damage_status')=='measured':lines.append(f"実減少の合計：耐久 {number(event.get('str_loss_raw'))}、指揮統制 {number(event.get('org_loss_raw'))}")
    else:lines.append('実減少：未確定または取得不能。0としては扱いません。')
    lines.append('残量・上下限処理などにより、計算ダメージと実減少は一致しないことがあります。')
    if trace.get('error'):lines.append('取得エラー：'+trace['error'])
    if not trace.get('complete'):lines.append('攻撃処理が完了する前の保存です。更新後に確認してください。')
    return '\n'.join(lines)

def show_trace(parent,event):
    w=tk.Toplevel(parent);w.title('艦載機：攻撃の計算過程');w.geometry('960x760')
    tabs=ttk.Notebook(w);tabs.pack(fill='both',expand=True,padx=12,pady=12)
    for label,content in [('計算の順序',explanation(event)),('保存された数値',json.dumps(event,ensure_ascii=False,indent=2))]:
        frame=ttk.Frame(tabs);tabs.add(frame,text=label)
        text=tk.Text(frame,wrap='word',padx=12,pady=12,font='TkDefaultFont')
        scroll=ttk.Scrollbar(frame,command=text.yview);scroll.pack(side='right',fill='y')
        text.configure(yscrollcommand=scroll.set);text.pack(fill='both',expand=True)
        text.insert('1.0',content);text.configure(state='disabled')

def examples_for(details,flow):
    data=details.get('air_examples') or {}
    bucket=next((b for b in data.get('buckets',[]) if (b['source_country'],b['target_country'])==tuple(flow)),{})
    return sorted(bucket.get('examples',[]),key=lambda p:p['sequence']),bucket.get('seen',0),data
