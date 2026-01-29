import streamlit as st
import google.generativeai as genai
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from duckduckgo_search import DDGS
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

# 【修正】keyを指定して重複エラーを防止
mode = st.sidebar.radio(
    "モード選択", 
    ["🏠 市場ダッシュボード", "💎 お宝発掘 (一括採点)", "🔍 個別詳細分析"],
    key="main_mode_select"
)

if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
    st.sidebar.success("🔑 API認証済み")
else:
    api_key = st.sidebar.text_input("Gemini APIキー", type="password")

st.sidebar.markdown("---")
st.sidebar.info("Ver 12.3: Clean Install")

# 個別分析用設定
if mode == "🔍 個別詳細分析":
    st.sidebar.subheader("🎨 チャート設定")
    show_bollinger = st.sidebar.checkbox("ボリンジャーバンド", value=True)
    show_ichimoku = st.sidebar.checkbox("一目均衡表", value=True)
    
    # 履歴ボタン
    history = st.session_state['history']
    if history:
        st.sidebar.subheader("🕒 最近の履歴")
        sorted_codes = sorted(history.keys(), key=lambda x: history[x].get('timestamp', ''), reverse=True)
        for c in sorted_codes[:5]:
            d = history[c]
            if st.sidebar.button(f"{d['name']} ({c})", key=f"side_{c}"):
                st.session_state['target_code'] = c
                st.rerun()
        if st.sidebar.button("履歴クリア"):
            if os.path.exists(HISTORY_FILE): os.remove(HISTORY_FILE)
            st.session_state['history'] = {}
            st.rerun()

# --- 関数群 ---
def get_model(key):
    try:
        genai.configure(api_key=key)
        # 1. 利用可能なモデル名を取得
        all_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        
        # 2. "1.5-flash" を含むモデルを優先的に探す
        target_model = next((m for m in all_models if "1.5-flash" in m), None)
        
        # 3. なければ "gemini-pro" にする
        if not target_model:
            target_model = "models/gemini-pro"
            
        return genai.GenerativeModel(target_model)
    except:
        return None

def safe_get(info, keys, default=None):
    for k in keys:
        if info.get(k) is not None: return info.get(k)
    return default

def calculate_scores(hist, info):
    if hist.empty: return 0, 0, 50
    latest = hist.iloc[-1]
    price = latest['Close']
    
    # オニール
    oneil = 0
    high52 = safe_get(info, ['fiftyTwoWeekHigh'])
    if high52:
        dist = (high52 - price) / high52 * 100
        if dist < 10: oneil += 40
        elif dist < 20: oneil += 20
    else: oneil += 20
    vol_mean = hist['Volume'].rolling(20).mean().iloc[-1]
    if latest['Volume'] > vol_mean: oneil += 30
    sma25 = hist['Close'].rolling(25).mean().iloc[-1]
    if price > sma25: oneil += 30
    
    # グレアム
    graham = 0
    eps = safe_get(info, ['forwardEps', 'trailingEps'])
    if eps and eps > 0:
        per = price / eps
        if 0 < per < 15: graham += 30
        elif 0 < per < 25: graham += 15
    else: graham += 15
    bps = safe_get(info, ['bookValue'])
    if bps and bps > 0:
        pbr = price / bps
        if 0 < pbr < 1.0: graham += 20
        elif 0 < pbr < 1.5: graham += 10
    else: graham += 10
    div = safe_get(info, ['dividendRate', 'dividendYield'])
    if div:
        yld = div * 100 if div < 1 else (div / price * 100)
        if yld > 3.5: graham += 30
        elif yld > 2.5: graham += 15
    
    delta = hist['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean().iloc[-1]
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean().iloc[-1]
    rsi = 100 - (100 / (1 + gain / loss)) if loss != 0 else 50
    if rsi < 30: graham += 20
    elif rsi < 40: graham += 10
    
    return oneil, graham, rsi

def calculate_technicals(hist):
    hist['SMA5'] = hist['Close'].rolling(5).mean()
    hist['SMA25'] = hist['Close'].rolling(25).mean()
    hist['SMA75'] = hist['Close'].rolling(75).mean()
    hist['std20'] = hist['Close'].rolling(20).std()
    hist['SMA20'] = hist['Close'].rolling(20).mean()
    hist['Upper'] = hist['SMA20'] + (hist['std20'] * 2)
    hist['Lower'] = hist['SMA20'] - (hist['std20'] * 2)

    h9 = hist['High'].rolling(9).max(); l9 = hist['Low'].rolling(9).min()
    tenkan = (h9 + l9) / 2
    h26 = hist['High'].rolling(26).max(); l26 = hist['Low'].rolling(26).min()
    kijun = (h26 + l26) / 2
    hist['SpanA'] = ((tenkan + kijun) / 2).shift(26)
    hist['SpanB'] = ((hist['High'].rolling(52).max() + hist['Low'].rolling(52).min()) / 2).shift(26)
    
    curr = hist.iloc[-1]
    prev = hist.iloc[-2]
    cross = "なし"
    if pd.notna(prev['SMA5']) and pd.notna(prev['SMA25']):
        if prev['SMA5'] < prev['SMA25'] and curr['SMA5'] > curr['SMA25']: cross = "Gクロス(短)"
        elif prev['SMA25'] < prev['SMA75'] and curr['SMA25'] > curr['SMA75']: cross = "Gクロス(長)"
        elif prev['SMA5'] > prev['SMA25'] and curr['SMA5'] < curr['SMA25']: cross = "Dクロス(短)"
        elif prev['SMA25'] > prev['SMA75'] and curr['SMA25'] < curr['SMA75']: cross = "Dクロス(長)"
    
    kumo = "雲中"
    sa, sb = hist['SpanA'].iloc[-1], hist['SpanB'].iloc[-1]
    cp = curr['Close']
    if pd.notna(sa) and pd.notna(sb):
        if cp > max(sa, sb): kumo = "雲上抜け"
        elif cp < min(sa, sb): kumo = "雲下抜け"
        
    return hist, cross, kumo

def get_news(code, name):
    ddgs = DDGS()
    txt = ""
    qs = [f"{code} {name} 決算短信 発表", f"{code} {name} 業績修正 速報", f"{code} {name} カブタン 決算"]
    for q in qs:
        try:
            res = ddgs.text(q, region='jp-jp', timelimit='d', max_results=3)
            if res:
                for r in res:
                    if r['title'] not in txt: txt += f"【速報】{r['title']} ({r['body'][:60]}...)\n"
        except: pass
        if len(txt) > 200: break
    if not txt:
        try:
            res = ddgs.text(f"{code} {name} 決算 ニュース", region='jp-jp', timelimit='w', max_results=5)
            if res:
                txt += "【直近】\n"
                for r in res:
                    if r['title'] not in txt: txt += f"- {r['title']} ({r['body'][:50]}...)\n"
        except: pass
    return txt if txt else "直近の重要ニュースなし"

# --- メイン UI ---
st.title("🦅 Deep Dive Investing AI Pro (Ver 12.3)")

# ==========================================
# モード0: 🏠 市場ダッシュボード
# ==========================================
if mode == "🏠 市場ダッシュボード":
    st.header("📈 Market Dashboard")
    col_m1, col_m2, col_m3 = st.columns(3)
    with st.spinner("市場データ取得中..."):
        try:
            nk = yf.Ticker("^N225").history(period="2d")
            if not nk.empty:
                p = nk['Close'].iloc[-1]; d = p - nk['Close'].iloc[-2]
                col_m1.metric("🇯🇵 日経平均", f"{p:,.0f}", f"{d:+.0f}")
            uj = yf.Ticker("JPY=X").history(period="2d")
            if not uj.empty:
                p = uj['Close'].iloc[-1]; d = p - uj['Close'].iloc[-2]
                col_m2.metric("🇺🇸/🇯🇵 ドル円", f"{p:.2f}", f"{d:+.2f}")
            col_m3.info(f"現在: {get_current_time_jst().strftime('%m/%d %H:%M')}")
        except: st.error("市場データ取得失敗")
    st.divider()
    st.subheader("🏆 あなたの監視銘柄")
    history = st.session_state['history']
    if history:
        ranked = []
        for c, d in history.items():
            s = d.get('oneil', 0) + d.get('graham', 0)
            ranked.append({'c': c, 'n': d['name'], 'p': d['price'], 's': s})
        ranked.sort(key=lambda x: x['s'], reverse=True)
        for item in ranked[:3]:
            with st.container(border=True):
                c1, c2, c3 = st.columns([2, 3, 1])
                c1.markdown(f"### {item['n']}")
                c1.caption(f"Code: {item['c']}")
                c2.metric("総合スコア", f"{item['s']}点", f"¥{item['p']:,.0f}")
                c2.progress(min(item['s'], 200)/200)
                if c3.button("詳細", key=f"d_{item['c']}"):
                    st.session_state['target_code'] = item['c']
                    st.success("個別詳細分析へ移動してください")
    else: st.info("履歴がありません")

# ==========================================
# モード1: 💎 お宝発掘
# ==========================================
elif mode == "💎 お宝発掘 (一括採点)":
    st.header("💎 お宝銘柄ハンター")
    st.info("💡 AIを使わないため、制限に関係なく動作します")
    
    def set_preset(codes): st.session_state['screener_codes'] = codes

    c1, c2, c3 = st.columns(3)
    if c1.button("🇯🇵 日経・人気"): set_preset("7203, 6758, 9984, 8035, 6861, 6098, 4063, 6902, 7974, 9432")
    if c2.button("💰 高配当"): set_preset("8306, 8316, 2914, 8058, 8001, 8002, 9433, 9434, 4503, 5401")
    if c3.button("🚀 半導体"): set_preset("8035, 6146, 6920, 6723, 6857, 7729, 6963, 6526, 6702, 6752")

    with st.form("screener"):
        codes_str = st.text_area("銘柄コード (カンマ区切り)", key="screener_codes")
        btn = st.form_submit_button("🛡️ スキャン開始", type="primary")
    
    if btn:
        codes = [c.strip() for c in codes_str.replace("、", ",").split(",") if c.strip()]
        if not codes: st.warning("コードを入力してください")
        else:
            res = []
            prog = st.progress(0)
            txt = st.empty()
            for i, c in enumerate(codes):
                txt.text(f"分析中... {c}")
                try:
                    if re.match(r'\d{4}', c):
                        tk = yf.Ticker(f"{c}.T"); hist = tk.history(period="1y")
                        if not hist.empty:
                            info = tk.info
                            os, gs, rsi = calculate_scores(hist, info)
                            hist, cr, km = calculate_technicals(hist)
                            j = ""
                            if os >= 80: j += "🏆成長 "
                            if gs >= 80: j += "💎割安 "
                            res.append({
                                "コード": c, "銘柄名": info.get('longName',c), "株価": f"{hist['Close'].iloc[-1]:,.0f}円",
                                "成長": os, "割安": gs, "RSI": round(rsi,1), "判定": cr, "有望度": j
                            })
                    time.sleep(0.5)
                    prog.progress((i+1)/len(codes))
                except: pass
            txt.empty(); prog.empty()
            if res:
                df = pd.DataFrame(res).sort_values(by=["成長", "割安"], ascending=False)
                def hl(s): return ['background-color: #2e4a33' if v >= 80 else '' for v in s]
                st.dataframe(df.style.apply(hl, subset=["成長", "割安"]), use_container_width=True)
            else: st.error("データなし")

# ==========================================
# モード2: 🔍 個別詳細分析
# ==========================================
elif mode == "🔍 個別詳細分析":
    with st.form('search'):
        q = st.text_input("銘柄コード/名", placeholder="例: 6758")
        sub = st.form_submit_button("🔍 分析開始", type="primary")

    if sub:
        if not api_key: st.error("APIキーが必要です"); st.stop()
        tgt = None
        if re.fullmatch(r'\d{4}', q.strip()): tgt = q.strip()
        else:
            with st.spinner("銘柄特定中..."):
                model = get_model(api_key)
                if model:
                    try:
                        resp = model.generate_content(f"日本株「{q}」のコード(4桁)のみ。")
                        m = re.search(r'\d{4}', resp.text)
                        if m: tgt = m.group(0)
                    except: pass
        if tgt: st.session_state['target_code'] = tgt
        else: st.error("銘柄が見つかりませんでした")

    if st.session_state['target_code']:
        code = st.session_state['target_code']
        model = get_model(api_key)
        now_str = get_current_time_jst().strftime("%Y-%m-%d %H:%M")
        
        with st.spinner(f"コード【{code}】を分析中..."):
            try:
                tk = yf.Ticker(f"{code}.T"); hist = tk.history(period="2y"); info = tk.info
                if hist.empty: st.error("データ取得失敗"); st.stop()
                
                hist, cross, kumo = calculate_technicals(hist)
                oneil, graham, rsi = calculate_scores(hist, info)
                price = hist['Close'].iloc[-1]
                chg = ((price - hist.iloc[-2]['Close']) / hist.iloc[-2]['Close']) * 100
                name = info.get('longName', code)
                
                st.sidebar.subheader("🏢 企業情報")
                st.sidebar.write(f"業種: {safe_get(info, ['sector'], '-')}")
                url = safe_get(info, ['website'])
                if url: st.sidebar.link_button("公式HP", url)

                st.session_state['history'][code] = {'name': name, 'timestamp': now_str, 'price': price, 'oneil': oneil, 'graham': graham}
                save_history(st.session_state['history'])
                
                st.header(f"{name} ({code})")
                
                t1, t2, t3 = st.tabs(["📝 レポート", "📈 チャート", "📊 財務"])
                
                with t1:
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("株価", f"{price:,.0f}円", f"{chg:+.2f}%")
                    c2.metric("RSI", f"{rsi:.1f}")
                    c3.metric("成長スコア", f"{oneil}点")
                    c4.metric("割安スコア", f"{graham}点")
                    
                    st.subheader("🤖 AI分析")
                    try:
                        news = get_news(code, name)
                        prompt = f"""
                        あなたはプロ投資家。日時「{now_str}」。
                        銘柄: {name} ({code}), 株価: {price}円
                        ニュース: {news}
                        スコア: 成長{oneil}, 割安{graham}
                        指示: 決算評価、スコア背景、売買戦略。
                        """
                        if model:
                            try:
                                resp = model.generate_content(prompt)
                                st.markdown(resp.text)
                            except Exception as e:
                                st.warning("⚠️ AI混雑中ですが、チャート等は正常です")
                                st.error(f"詳細: {e}")
                        else: st.warning("モデル接続不可")
                    except: st.error("ニュース取得エラー")

                with t2:
                    st.info(f"{cross} / {kumo}")
                    dh = hist.tail(150)
                    fig = go.Figure()
                    if show_ichimoku:
                        fig.add_trace(go.Scatter(x=dh.index, y=dh['SpanA'], line=dict(width=0), showlegend=False, hoverinfo='skip'))
                        fig.add_trace(go.Scatter(x=dh.index, y=dh['SpanB'], line=dict(width=0), name='雲', fill='tonexty', fillcolor='rgba(0,200,200,0.2)'))
                    if show_bollinger:
                        fig.add_trace(go.Scatter(x=dh.index, y=dh['Upper'], line=dict(width=1, color='gray', dash='dot'), name='+2σ'))
                        fig.add_trace(go.Scatter(x=dh.index, y=dh['Lower'], line=dict(width=1, color='gray', dash='dot'), name='-2σ'))
                    fig.add_trace(go.Candlestick(x=dh.index, open=dh['Open'], high=dh['High'], low=dh['Low'], close=dh['Close'], name='株価'))
                    fig.add_trace(go.Scatter(x=dh.index, y=dh['SMA25'], line=dict(color='orange'), name='25MA'))
                    fig.add_trace(go.Scatter(x=dh.index, y=dh['SMA75'], line=dict(color='skyblue'), name='75MA'))
                    fig.update_layout(height=500, xaxis_rangeslider_visible=False, template="plotly_dark")
                    st.plotly_chart(fig, use_container_width=True)

                with t3:
                    try:
                        fin = tk.financials
                        if fin is not None and not fin.empty:
                            fin = fin.T.sort_index().tail(4)
                            figf = go.Figure()
                            if 'Total Revenue' in fin.columns: figf.add_trace(go.Bar(x=fin.index, y=fin['Total Revenue'], name='売上'))
                            if 'Net Income' in fin.columns: figf.add_trace(go.Bar(x=fin.index, y=fin['Net Income'], name='利益'))
                            figf.update_layout(title="業績推移", template="plotly_dark", height=400)
                            st.plotly_chart(figf, use_container_width=True)
                            csv = hist.to_csv().encode('utf-8')
                            st.download_button("CSV保存", csv, f"{code}.csv", "text/csv")
                        else: st.info("財務データなし")
                    except: st.error("財務エラー")

            except: st.error("エラー発生")
