import streamlit as st
import google.generativeai as genai
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from duckduckgo_search import DDGS # 念のため残すがメインでは使わない
import time
import re
import datetime
import json
import os

# --- ページ設定 ---
st.set_page_config(page_title="Deep Dive Investing AI Pro", layout="wide")

# --- JST設定 ---
JST = datetime.timezone(datetime.timedelta(hours=9))
def get_current_time_jst(): return datetime.datetime.now(JST)

# --- 履歴管理 ---
HISTORY_FILE = 'stock_history.json'
def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f: return json.load(f)
        except: return {}
    return {}
def save_history(data):
    try:
        with open(HISTORY_FILE, 'w') as f: json.dump(data, f)
    except: pass

# --- 初期化 ---
if 'history' not in st.session_state: st.session_state['history'] = load_history()
if 'target_code' not in st.session_state: st.session_state['target_code'] = None
if 'screener_codes' not in st.session_state: st.session_state['screener_codes'] = "6758, 7203, 9984"

# --- サイドバー ---
st.sidebar.title("🦅 Deep Dive Pro")
mode = st.sidebar.radio(
    "モード選択", 
    ["🏠 市場ダッシュボード", "💎 お宝発掘 (スクリーニング)", "📊 ファンダ＆テクニカル分析"],
    key="mode_selection_v15"
)

if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
    st.sidebar.success("🔑 API認証済み")
else:
    api_key = st.sidebar.text_input("Gemini APIキー", type="password")

st.sidebar.markdown("---")
st.sidebar.info("Ver 15.0: Fundamental Fusion")

# --- AIモデル接続 (安定版固定) ---
def get_model(key):
    try:
        genai.configure(api_key=key)
        # 安定性を重視し、最新の試験版ではなく1.5系を自動探索
        all_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        if not all_models: return None
        
        # 1.5-flash または 1.5-pro を優先
        exclude = ["2.0", "2.5", "experimental"]
        safe = [m for m in all_models if not any(ex in m for ex in exclude)]
        
        target = next((m for m in safe if "1.5-flash" in m), None)
        if not target: target = next((m for m in safe if "1.5-pro" in m), safe[0] if safe else None)
        
        return genai.GenerativeModel(target) if target else None
    except: return None

# --- 関数群 ---
def safe_get(info, keys, default=None):
    for k in keys:
        if info.get(k) is not None: return info.get(k)
    return default

# ファンダメンタルズ分析用データ取得
def get_fundamentals(tk, info):
    # infoから主要指標を取得
    roe = safe_get(info, ['returnOnEquity'], 0)
    roa = safe_get(info, ['returnOnAssets'], 0)
    profit_margin = safe_get(info, ['profitMargins'], 0)
    revenue_growth = safe_get(info, ['revenueGrowth'], 0)
    debt_to_equity = safe_get(info, ['debtToEquity'], 0)
    current_ratio = safe_get(info, ['currentRatio'], 0)
    
    # バリュエーション
    per = safe_get(info, ['forwardPE', 'trailingPE'], 0)
    pbr = safe_get(info, ['priceToBook'], 0)
    div_yield = safe_get(info, ['dividendYield'], 0)
    
    return {
        "ROE": roe, "ROA": roa, "ProfitMargin": profit_margin,
        "RevGrowth": revenue_growth, "DebtEquity": debt_to_equity, "CurrentRatio": current_ratio,
        "PER": per, "PBR": pbr, "DivYield": div_yield
    }

def calculate_technicals(hist):
    # MA
    hist['SMA5'] = hist['Close'].rolling(5).mean()
    hist['SMA25'] = hist['Close'].rolling(25).mean()
    hist['SMA75'] = hist['Close'].rolling(75).mean()
    
    # Bollinger
    hist['std20'] = hist['Close'].rolling(20).std()
    hist['SMA20'] = hist['Close'].rolling(20).mean()
    hist['Upper'] = hist['SMA20'] + (hist['std20'] * 2)
    hist['Lower'] = hist['SMA20'] - (hist['std20'] * 2)

    # Ichimoku
    h9 = hist['High'].rolling(9).max(); l9 = hist['Low'].rolling(9).min()
    tenkan = (h9 + l9) / 2
    h26 = hist['High'].rolling(26).max(); l26 = hist['Low'].rolling(26).min()
    kijun = (h26 + l26) / 2
    hist['SpanA'] = ((tenkan + kijun) / 2).shift(26)
    hist['SpanB'] = ((hist['High'].rolling(52).max() + hist['Low'].rolling(52).min()) / 2).shift(26)
    
    # 判定ロジック
    curr = hist.iloc[-1]
    prev = hist.iloc[-2]
    
    # MA Cross
    cross = "特になし"
    if pd.notna(prev['SMA5']):
        if prev['SMA5'] < prev['SMA25'] and curr['SMA5'] > curr['SMA25']: cross = "ゴールデンクロス(短)"
        elif prev['SMA25'] < prev['SMA75'] and curr['SMA25'] > curr['SMA75']: cross = "ゴールデンクロス(長)"
        elif prev['SMA5'] > prev['SMA25'] and curr['SMA5'] < curr['SMA25']: cross = "デッドクロス(短)"
    
    # Kumo
    kumo = "雲の中"
    sa, sb = hist['SpanA'].iloc[-1], hist['SpanB'].iloc[-1]
    cp = curr['Close']
    if pd.notna(sa) and pd.notna(sb):
        if cp > max(sa, sb): kumo = "雲上抜け (強気)"
        elif cp < min(sa, sb): kumo = "雲下抜け (弱気)"
    
    # RSI (14)
    delta = hist['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    hist['RSI'] = 100 - (100 / (1 + rs))
    rsi_val = hist['RSI'].iloc[-1]

    return hist, cross, kumo, rsi_val

# --- メイン UI ---
st.title("🦅 Deep Dive Investing AI Pro (Ver 15.0)")

# モード0: ダッシュボード
if mode == "🏠 市場ダッシュボード":
    st.header("📈 Market Dashboard")
    c1, c2, c3 = st.columns(3)
    with st.spinner("Loading..."):
        try:
            nk = yf.Ticker("^N225").history(period="2d")
            if not nk.empty: c1.metric("日経平均", f"{nk['Close'].iloc[-1]:,.0f}", f"{nk['Close'].iloc[-1]-nk['Close'].iloc[-2]:+.0f}")
            uj = yf.Ticker("JPY=X").history(period="2d")
            if not uj.empty: c2.metric("ドル円", f"{uj['Close'].iloc[-1]:.2f}", f"{uj['Close'].iloc[-1]-uj['Close'].iloc[-2]:+.2f}")
            c3.info(get_current_time_jst().strftime('%Y/%m/%d %H:%M'))
        except: st.error("Data Error")
    st.divider()
    st.subheader("🏆 監視銘柄履歴")
    h = st.session_state['history']
    if h:
        # 新しい履歴形式に対応 (なければスキップ)
        valid_items = [d for d in h.values() if 'price' in d]
        for i in valid_items[-3:]: # 最新3件
             st.success(f"{i['name']} : {i['price']:,.0f}円 (保存時)")
    else: st.info("履歴なし")

# モード1: お宝発掘
elif mode == "💎 お宝発掘 (スクリーニング)":
    st.header("💎 ファンダメンタルズ・ハンター")
    st.info("💡 財務データに基づく「事実」のみでスクリーニングします (AI不使用)")
    
    def set_pre(c): st.session_state['screener_codes'] = c
    c1, c2, c3 = st.columns(3)
    if c1.button("🇯🇵 主力・大型"): set_pre("7203, 6758, 9984, 8035, 6861, 6098, 4063, 6902, 7974, 9432")
    if c2.button("💰 高配当・バリュー"): set_pre("8306, 8316, 2914, 8058, 8001, 8002, 9433, 9434, 4503, 5401")
    if c3.button("🚀 グロース・半導体"): set_pre("8035, 6146, 6920, 6723, 6857, 7729, 6963, 6526, 6702, 6752")
    
    with st.form("sc"):
        txt = st.text_area("コード (カンマ区切り)", key="screener_codes")
        btn = st.form_submit_button("🛡️ スキャン実行")
    
    if btn:
        cds = [x.strip() for x in txt.replace("、",",").split(",") if x.strip()]
        res = []; prog = st.progress(0); st_txt = st.empty()
        for i, c in enumerate(cds):
            st_txt.text(f"Analyzing {c}...")
            try:
                if re.match(r'\d{4}', c):
                    tk = yf.Ticker(f"{c}.T")
                    inf = tk.info
                    h = tk.history(period="3mo")
                    if not h.empty:
                        f = get_fundamentals(tk, inf)
                        # スコアリング (簡易版)
                        score = 0
                        if f['ROE'] > 0.08: score += 20 # ROE 8%以上
                        if f['ProfitMargin'] > 0.10: score += 20 # 利益率10%以上
                        if f['RevGrowth'] > 0.05: score += 20 # 売上成長5%以上
                        if f['PBR'] < 1.5: score += 20 # PBR 1.5倍以下
                        
                        res.append({
                            "コード": c, "銘柄": inf.get('longName',c), 
                            "ROE": f"{f['ROE']*100:.1f}%", 
                            "利益率": f"{f['ProfitMargin']*100:.1f}%",
                            "PBR": f"{f['PBR']:.2f}倍",
                            "総合点": score
                        })
                time.sleep(0.2); prog.progress((i+1)/len(cds))
            except: pass
        st_txt.empty(); prog.empty()
        if res:
            df = pd.DataFrame(res).sort_values(by="総合点", ascending=False)
            st.dataframe(df, use_container_width=True)

# モード2: ファンダ＆テクニカル詳細
elif mode == "📊 ファンダ＆テクニカル分析":
    with st.form('find'):
        q = st.text_input("銘柄コード/名", placeholder="例: 6758")
        sub = st.form_submit_button("🔍 詳細分析開始", type="primary")
    
    if sub:
        if not api_key: st.error("APIキーが必要です"); st.stop()
        tgt = None
        if re.fullmatch(r'\d{4}', q.strip()): tgt = q.strip()
        else:
            with st.spinner("銘柄特定中..."):
                m = get_model(api_key)
                if m:
                    try:
                        r = m.generate_content(f"日本株「{q}」のコード(4桁)のみ。")
                        found = re.search(r'\d{4}', r.text)
                        if found: tgt = found.group(0)
                    except: pass
        if tgt: st.session_state['target_code'] = tgt
        else: st.error("銘柄が見つかりませんでした")

    if st.session_state['target_code']:
        code = st.session_state['target_code']
        model = get_model(api_key)
        
        with st.spinner(f"財務データ＆チャート分析中... {code}"):
            try:
                tk = yf.Ticker(f"{code}.T")
                hist = tk.history(period="2y")
                info = tk.info
                
                if hist.empty: st.error("データ取得エラー"); st.stop()
                
                # データ計算
                fund = get_fundamentals(tk, info)
                hist, cross, kumo, rsi = calculate_technicals(hist)
                price = hist['Close'].iloc[-1]
                
                # 履歴保存
                st.session_state['history'][code] = {'name': info.get('longName', code), 'timestamp': datetime.datetime.now().strftime('%Y-%m-%d'), 'price': price}
                save_history(st.session_state['history'])
                
                # --- 表示 ---
                st.header(f"{info.get('longName', code)} ({code})")
                
                # 1. 重要指標バッジ
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("現在株価", f"{price:,.0f}円")
                c2.metric("ROE (稼ぐ力)", f"{fund['ROE']*100:.1f}%")
                c3.metric("PER (割安度)", f"{fund['PER']:.1f}倍")
                c4.metric("RSI (過熱感)", f"{rsi:.1f}")
                
                st.divider()
                
                # 2. ファンダメンタルズ可視化
                st.subheader("📊 財務健康診断 (Financial Health)")
                f_col1, f_col2 = st.columns(2)
                
                with f_col1:
                    # 収益性グラフ
                    fin_df = tk.financials.T.sort_index().tail(3) if tk.financials is not None else pd.DataFrame()
                    if not fin_df.empty:
                        fig_pl = go.Figure()
                        if 'Total Revenue' in fin_df.columns:
                            fig_pl.add_trace(go.Bar(x=fin_df.index, y=fin_df['Total Revenue'], name='売上高', marker_color='#3498db'))
                        if 'Net Income' in fin_df.columns:
                            fig_pl.add_trace(go.Bar(x=fin_df.index, y=fin_df['Net Income'], name='純利益', marker_color='#e74c3c'))
                        fig_pl.update_layout(title="業績推移 (売上・利益)", height=300, margin=dict(l=20,r=20,t=40,b=20), template="plotly_dark")
                        st.plotly_chart(fig_pl, use_container_width=True)
                    else: st.warning("詳細な財務データがありません")

                with f_col2:
                    # 効率性・安全性メーター
                    st.write("#### 主要指標")
                    st.write(f"- **営業利益率**: {fund['ProfitMargin']*100:.1f}% (高いほど本業が強い)")
                    st.write(f"- **自己資本比率**: {(1/(1+fund['DebtEquity']))*100:.1f}% (高いほど潰れにくい)")
                    st.write(f"- **PBR**: {fund['PBR']:.2f}倍 (1倍割れは解散価値以下)")
                    st.write(f"- **配当利回り**: {fund['DivYield']*100:.2f}%")

                st.divider()

                # 3. テクニカル分析 & AI総合判断
                st.subheader("🤖 AIストラテジストの総合判断")
                
                if model:
                    # AIに渡すのは「ニュース」ではなく「確定した数字」
                    prompt = f"""
                    あなたはプロの機関投資家です。以下の「事実データ」に基づき、論理的な投資判断を下してください。
                    曖昧なニュースは排除し、数字とチャート形状のみで判断します。

                    【対象銘柄】{info.get('longName')} ({code})
                    【現在値】{price}円

                    【ファンダメンタルズ (企業の基礎体力)】
                    - ROE (自己資本利益率): {fund['ROE']*100:.1f}%  (8%以上が優良の目安)
                    - 営業利益率: {fund['ProfitMargin']*100:.1f}%
                    - PER (株価収益率): {fund['PER']:.1f}倍
                    - PBR (株価純資産倍率): {fund['PBR']:.2f}倍
                    - 配当利回り: {fund['DivYield']*100:.2f}%

                    【テクニカル (株価の勢い)】
                    - 移動平均線判定: {cross}
                    - 一目均衡表判定: {kumo}
                    - RSI (14日): {rsi:.1f} (30以下は売られすぎ、70以上は買われすぎ)

                    【指示】
                    1. **財務分析**: ROEや利益率から、この企業に「稼ぐ力」があるか判定せよ。
                    2. **割安性**: PER/PBRを見て、今の株価は安いか高いか判定せよ。
                    3. **タイミング**: テクニカル指標に基づき、今仕掛けるべきか待つべきか結論を出せ。
                    """
                    
                    try:
                        with st.spinner("AIが財務諸表とチャートを分析中..."):
                            resp = model.generate_content(prompt)
                            st.markdown(resp.text)
                    except Exception as e:
                        st.error(f"AI分析エラー: {e}")
                
                # 4. チャート表示 (最後に見やすく)
                st.subheader("📈 株価チャート")
                d_hist = hist.tail(150)
                fig = go.Figure()
                # 雲
                fig.add_trace(go.Scatter(x=d_hist.index, y=d_hist['SpanA'], line=dict(width=0), showlegend=False, hoverinfo='skip'))
                fig.add_trace(go.Scatter(x=d_hist.index, y=d_hist['SpanB'], line=dict(width=0), name='雲', fill='tonexty', fillcolor='rgba(0,200,200,0.2)'))
                # ボリンジャー
                if show_bollinger:
                    fig.add_trace(go.Scatter(x=d_hist.index, y=d_hist['Upper'], line=dict(width=1, color='gray', dash='dot'), name='+2σ'))
                    fig.add_trace(go.Scatter(x=d_hist.index, y=d_hist['Lower'], line=dict(width=1, color='gray', dash='dot'), name='-2σ'))
                # ローソク
                fig.add_trace(go.Candlestick(x=d_hist.index, open=d_hist['Open'], high=d_hist['High'], low=d_hist['Low'], close=d_hist['Close'], name='株価'))
                # MA
                fig.add_trace(go.Scatter(x=d_hist.index, y=d_hist['SMA25'], line=dict(color='orange'), name='25MA'))
                fig.add_trace(go.Scatter(x=d_hist.index, y=d_hist['SMA75'], line=dict(color='skyblue'), name='75MA'))
                
                fig.update_layout(height=500, xaxis_rangeslider_visible=False, template="plotly_dark")
                st.plotly_chart(fig, use_container_width=True)

            except Exception as e: st.error(f"分析エラー: {e}")
