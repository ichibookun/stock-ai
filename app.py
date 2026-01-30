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

# --- JST設定 & 自動日付取得 ---
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
    ["🏠 市場ダッシュボード", "💎 お宝発掘 (一括採点)", "🔍 個別詳細分析"],
    key="mode_selection_v13_2"
)

if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
    st.sidebar.success("🔑 API認証済み")
else:
    api_key = st.sidebar.text_input("Gemini APIキー", type="password")

st.sidebar.markdown("---")
st.sidebar.info("Ver 13.2: Smart Date Search")

# --- AIモデル接続 (自動選択) ---
def get_model_and_name(key):
    try:
        genai.configure(api_key=key)
        all_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        if not all_models: return None, "No Models"
        
        exclude = ["2.0", "2.5", "experimental", "exp"]
        safe_models = [m for m in all_models if not any(ex in m for ex in exclude)]
        
        target = next((m for m in safe_models if "1.5-flash" in m), None)
        if not target: target = next((m for m in safe_models if "1.5-pro" in m), safe_models[0] if safe_models else all_models[0])
        
        return genai.GenerativeModel(target), target
    except Exception as e: return None, str(e)

if api_key:
    model, m_name = get_model_and_name(api_key)
    if model: st.sidebar.caption(f"🤖 Connected: {m_name}")
    else: st.sidebar.error("接続エラー")

# 個別設定
if mode == "🔍 個別詳細分析":
    st.sidebar.subheader("🎨 チャート設定")
    show_bollinger = st.sidebar.checkbox("ボリンジャーバンド", value=True)
    show_ichimoku = st.sidebar.checkbox("一目均衡表", value=True)
    
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
def safe_get(info, keys, default=None):
    for k in keys:
        if info.get(k) is not None: return info.get(k)
    return default

def calculate_scores(hist, info):
    if hist.empty: return 0, 0, 50
    latest = hist.iloc[-1]
    price = latest['Close']
    
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

# --- ニュース取得機能（スマート検索版） ---
def get_news(code, name):
    ddgs = DDGS()
    news_list = []
    
    # 1. 自動で「今年の年号」を取得
    now = get_current_time_jst()
    this_year = now.year          # 例: 2026
    last_year = this_year - 1     # 例: 2025 (念のため)
    
    # 2. 検索クエリの作成 (年号を自動挿入)
    queries = [
        # カブタンなどの速報サイトを優先
        f"site:kabutan.jp {code} 決算 {this_year}",
        f"site:nikkei.com {code} 業績 {this_year}",
        # 一般検索でも年号を指定して古い記事を弾く
        f"{code} {name} 決算短信 {this_year}年",
        f"{code} {name} 業績修正 {this_year}年"
    ]
    
    # 3. 検索実行
    for q in queries:
        try:
            # max_resultsを増やして「最新」が埋もれないようにする
            results = ddgs.text(q, region='jp-jp', timelimit='w', max_results=5)
            if results:
                for r in results:
                    title = r.get('title', '')
                    body = r.get('body', '')
                    link = r.get('href', '')
                    
                    # 重複排除
                    if not any(title in existing for existing in news_list):
                        # ニュースリストに追加
                        news_list.append(f"【{r.get('source','Web')}】{title}: {body[:80]}...")
        except: pass
        time.sleep(0.3)

    if not news_list:
        return "（直近の決算関連ニュースが検索で見つかりませんでした）", []
    
    return "\n".join(news_list[:10]), news_list # リストも返す

# --- メイン UI ---
st.title("🦅 Deep Dive Investing AI Pro (Ver 13.2)")

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
        except: st.error("Market Data Error")
    st.divider()
    st.subheader("🏆 監視銘柄ランキング")
    h = st.session_state['history']
    if h:
        r = sorted([{'c':c,'n':d['name'],'p':d['price'],'s':d.get('oneil',0)+d.get('graham',0)} for c,d in h.items()], key=lambda x:x['s'], reverse=True)
        for i in r[:3]:
            with st.container(border=True):
                ca, cb, cc = st.columns([2,3,1])
                ca.markdown(f"**{i['n']}** ({i['c']})"); cb.metric("Score", f"{i['s']}", f"¥{i['p']:,.0f}"); cb.progress(min(i['s'],200)/200)
                if cc.button("Go", key=f"g_{i['c']}"): st.session_state['target_code']=i['c']; st.success("移動します")
    else: st.info("履歴なし")

# モード1: スクリーニング
elif mode == "💎 お宝発掘 (一括採点)":
    st.header("💎 お宝銘柄ハンター")
    def set_pre(c): st.session_state['screener_codes'] = c
    c1, c2, c3 = st.columns(3)
    if c1.button("🇯🇵 日経"): set_pre("7203, 6758, 9984, 8035, 6861, 6098, 4063, 6902, 7974, 9432")
    if c2.button("💰 高配当"): set_pre("8306, 8316, 2914, 8058, 8001, 8002, 9433, 9434, 4503, 5401")
    if c3.button("🚀 半導体"): set_pre("8035, 6146, 6920, 6723, 6857, 7729, 6963, 6526, 6702, 6752")
    
    with st.form("sc"):
        txt = st.text_area("コード (カンマ区切り)", key="screener_codes")
        btn = st.form_submit_button("🛡️ スキャン")
    
    if btn:
        cds = [x.strip() for x in txt.replace("、",",").split(",") if x.strip()]
        res = []; prog = st.progress(0); st_txt = st.empty()
        for i, c in enumerate(cds):
            st_txt.text(f"Scanning {c}...")
            try:
                if re.match(r'\d{4}', c):
                    tk = yf.Ticker(f"{c}.T"); h = tk.history(period="1y")
                    if not h.empty:
                        o, g, rsi = calculate_scores(h, tk.info)
                        _, cr, km = calculate_technicals(h)
                        j = "🏆" if o>=80 else "💎" if g>=80 else ""
                        res.append({"コード":c, "銘柄":tk.info.get('longName',c), "株価":f"{h['Close'].iloc[-1]:,.0f}", "成長":o, "割安":g, "RSI":round(rsi,1), "判定":cr, "注目":j})
                time.sleep(0.5); prog.progress((i+1)/len(cds))
            except: pass
        st_txt.empty(); prog.empty()
        if res:
            df = pd.DataFrame(res).sort_values(by=["成長","割安"], ascending=False)
            st.dataframe(df.style.apply(lambda s: ['background-color:#2e4a33' if v>=80 else '' for v in s], subset=["成長","割安"]), use_container_width=True)

# モード2: 個別詳細 (スマート検索版)
elif mode == "🔍 個別詳細分析":
    with st.form('find'):
        q = st.text_input("銘柄コード/名", placeholder="例: 6758")
        sub = st.form_submit_button("🔍 分析開始", type="primary")
    
    if sub:
        if not api_key: st.error("APIキーが必要です"); st.stop()
        tgt = None
        if re.fullmatch(r'\d{4}', q.strip()): tgt = q.strip()
        else:
            with st.spinner("コード検索..."):
                m, _ = get_model_and_name(api_key)
                if m:
                    try:
                        r = m.generate_content(f"日本株「{q}」のコード(4桁)のみ。")
                        found = re.search(r'\d{4}', r.text)
                        if found: tgt = found.group(0)
                    except: pass
        if tgt: st.session_state['target_code'] = tgt
        else: st.error("不明な銘柄")

    if st.session_state['target_code']:
        code = st.session_state['target_code']
        model, m_name = get_model_and_name(api_key)
        now = get_current_time_jst().strftime("%Y-%m-%d %H:%M")
        
        with st.spinner(f"分析中... {code}"):
            try:
                tk = yf.Ticker(f"{code}.T"); h = tk.history(period="2y"); inf = tk.info
                if h.empty: st.error("データなし"); st.stop()
                
                h, cross, kumo = calculate_technicals(h)
                oneil, graham, rsi = calculate_scores(h, inf)
                price = h['Close'].iloc[-1]
                
                st.sidebar.subheader("🏢 Info")
                st.sidebar.write(f"業種: {safe_get(inf,['sector'],'-')}")
                if safe_get(inf,['website']): st.sidebar.link_button("公式HP", inf['website'])
                
                # ニュース取得 (年号自動挿入 & リスト取得)
                news_text, raw_news_list = get_news(code, inf.get('longName', code))
                
                st.header(f"{inf.get('longName', code)} ({code})")
                
                t1, t2 = st.tabs(["📝 レポート & ニュース", "📈 チャート"])
                
                with t1:
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("株価", f"{price:,.0f}円", f"{(price-h.iloc[-2]['Close'])/h.iloc[-2]['Close']*100:+.2f}%")
                    c2.metric("RSI", f"{rsi:.1f}")
                    c3.metric("成長スコア", f"{oneil}")
                    c4.metric("割安スコア", f"{graham}")
                    
                    st.subheader("📰 決算・重要ニュース分析")
                    
                    # ユーザーに「何が見つかったか」を見せる (デバッグ用にもなる)
                    with st.expander("🔍 AIが取得したニュース一覧 (クリックで展開)"):
                        if raw_news_list:
                            for n in raw_news_list:
                                st.caption(n)
                        else:
                            st.warning("直近のニュースが見つかりませんでした。")

                    if model:
                        prompt = f"""
                        あなたは日本株のプロです。現在日時: {now}
                        
                        対象: {inf.get('longName')} ({code})
                        
                        【取得した最新ニュース】
                        {news_text}
                        
                        【厳守事項】
                        1. **ニュースの日付を厳しくチェックせよ**。記事に「2024年」や「1年前」の記述がある場合、それは「過去のニュース」として扱い、決して「最新決算」として解説しないこと。
                        2. もしニュースリストに「2026年」や「直近数日」の記事が無ければ、「最新の決算情報は検索で見つかりませんでした」と正直に答えること。嘘をつかないこと。
                        
                        指示:
                        1. **最新決算**: ニュースに基づき、今期の業績（増益・減益など）を解説。
                        2. **市場反応**: 株価への影響予測。
                        3. **売買判断**: スコア(成長{oneil}/割安{graham})とテクニカル({cross}/{kumo})に基づく助言。
                        """
                        try:
                            resp = model.generate_content(prompt)
                            st.markdown(resp.text)
                        except Exception as e: st.error(f"AI Error: {e}")
                    else: st.warning("AI未接続")

                with t2:
                    st.info(f"Technical: {cross} / {kumo}")
                    d = h.tail(150)
                    fig = go.Figure()
                    if show_ichimoku:
                        fig.add_trace(go.Scatter(x=d.index, y=d['SpanA'], line=dict(width=0), showlegend=False, hoverinfo='skip'))
                        fig.add_trace(go.Scatter(x=d.index, y=d['SpanB'], line=dict(width=0), name='雲', fill='tonexty', fillcolor='rgba(0,200,200,0.2)'))
                    if show_bollinger:
                        fig.add_trace(go.Scatter(x=d.index, y=d['Upper'], line=dict(width=1, color='gray', dash='dot'), name='+2σ'))
                        fig.add_trace(go.Scatter(x=d.index, y=d['Lower'], line=dict(width=1, color='gray', dash='dot'), name='-2σ'))
                    fig.add_trace(go.Candlestick(x=d.index, open=d['Open'], high=d['High'], low=d['Low'], close=d['Close'], name='株価'))
                    fig.add_trace(go.Scatter(x=d.index, y=d['SMA25'], line=dict(color='orange'), name='25MA'))
                    fig.add_trace(go.Scatter(x=d.index, y=d['SMA75'], line=dict(color='skyblue'), name='75MA'))
                    fig.update_layout(height=500, xaxis_rangeslider_visible=False, template="plotly_dark")
                    st.plotly_chart(fig, use_container_width=True)

            except Exception as e: st.error(f"エラー: {e}")
