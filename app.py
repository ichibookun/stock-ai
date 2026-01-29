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

# --- サイドバー ---
st.sidebar.title("🦅 Deep Dive Pro")
if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
    st.sidebar.success("🔑 API認証済み")
else:
    api_key = st.sidebar.text_input("Gemini APIキー", type="password")
st.sidebar.markdown("---")
st.sidebar.info("Ver 9.0: Financial Visuals")

# 履歴表示
history = st.session_state['history']
if history:
    sorted_codes = sorted(history.keys(), key=lambda x: history[x].get('timestamp', ''), reverse=True)
    st.sidebar.subheader("🕒 最近の履歴")
    for c in sorted_codes[:5]:
        d = history[c]
        if st.sidebar.button(f"{d['name']} ({c})", key=f"h_{c}"):
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
        models = [m for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        target = "models/gemini-1.5-flash"
        if not any(m.name == target for m in models):
             target = next((m.name for m in models if 'flash' in m.name), "models/gemini-pro")
        return genai.GenerativeModel(target)
    except: return None

def safe_get(info, keys, default=None):
    for k in keys:
        if info.get(k) is not None: return info.get(k)
    return default

def calculate_scores(hist, info):
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
    
    curr = hist.iloc[-1]
    prev = hist.iloc[-2]
    
    cross = "特になし"
    if pd.notna(prev['SMA5']) and pd.notna(prev['SMA25']):
        if prev['SMA5'] < prev['SMA25'] and curr['SMA5'] > curr['SMA25']: cross = "ゴールデンクロス (短期)"
        elif prev['SMA25'] < prev['SMA75'] and curr['SMA25'] > curr['SMA75']: cross = "ゴールデンクロス (長期)"
        elif prev['SMA5'] > prev['SMA25'] and curr['SMA5'] < curr['SMA25']: cross = "デッドクロス (短期)"
        elif prev['SMA25'] > prev['SMA75'] and curr['SMA25'] < curr['SMA75']: cross = "デッドクロス (長期)"

    h9 = hist['High'].rolling(9).max(); l9 = hist['Low'].rolling(9).min()
    tenkan = (h9 + l9) / 2
    h26 = hist['High'].rolling(26).max(); l26 = hist['Low'].rolling(26).min()
    kijun = (h26 + l26) / 2
    hist['SpanA'] = ((tenkan + kijun) / 2).shift(26)
    hist['SpanB'] = ((hist['High'].rolling(52).max() + hist['Low'].rolling(52).min()) / 2).shift(26)
    
    kumo = "雲の中"
    sa, sb = hist['SpanA'].iloc[-1], hist['SpanB'].iloc[-1]
    cp = curr['Close']
    if pd.notna(sa) and pd.notna(sb):
        if cp > max(sa, sb): kumo = "雲上抜け (強気)"
        elif cp < min(sa, sb): kumo = "雲下抜け (弱気)"
        
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

# --- UI ---
st.title("🦅 Deep Dive Investing AI Pro (Ver 9.0)")

with st.form('search'):
    q = st.text_input("銘柄コード/名", placeholder="例: 6758 (エンターで実行)")
    submitted = st.form_submit_button("🔍 分析開始", type="primary")

if submitted:
    if not api_key: st.error("APIキーが必要です"); st.stop()
    if not q: st.warning("入力を確認してください"); st.stop()
    
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

# --- メイン処理 ---
if st.session_state['target_code']:
    code = st.session_state['target_code']
    model = get_model(api_key)
    now_str = get_current_time_jst().strftime("%Y-%m-%d %H:%M")
    
    with st.spinner(f"コード【{code}】を分析中..."):
        try:
            tk = yf.Ticker(f"{code}.T")
            hist = tk.history(period="2y")
            info = tk.info
            
            if hist.empty: st.error("データ取得失敗"); st.stop()
            
            hist, cross, kumo = calculate_technicals(hist)
            oneil, graham, rsi = calculate_scores(hist, info)
            latest = hist.iloc[-1]
            price = latest['Close']
            chg = ((price - hist.iloc[-2]['Close']) / hist.iloc[-2]['Close']) * 100
            name = info.get('longName', code)
            
            # 履歴保存
            st.session_state['history'][code] = {
                'name': name, 'timestamp': now_str, 'price': price, 'oneil': oneil, 'graham': graham
            }
            save_history(st.session_state['history'])
            
            st.header(f"{name} ({code})")
            
            # タブ機能の実装
            tab1, tab2, tab3 = st.tabs(["📝 分析レポート", "📈 詳細チャート", "📊 業績・財務"])
            
            # --- Tab 1: メインレポート ---
            with tab1:
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("株価", f"{price:,.0f}円", f"{chg:+.2f}%")
                c2.metric("RSI", f"{rsi:.1f}")
                c3.metric("成長スコア", f"{oneil}点")
                c4.metric("割安スコア", f"{graham}点")
                
                # AI分析エリア
                st.subheader("🤖 AIアナリストの見解")
                try:
                    news = get_news(code, name)
                    prompt = f"""
                    あなたはプロの機関投資家。現在日時「{now_str}」。
                    銘柄: {name} ({code}), 株価: {price}円
                    ニュース: {news}
                    スコア: 成長{oneil}, 割安{graham}
                    指示: 最新決算（あれば）の評価、スコア背景、売買戦略を簡潔かつ具体的に。
                    """
                    if model:
                        try:
                            resp = model.generate_content(prompt)
                            st.markdown(resp.text)
                        except Exception as e:
                            st.warning("⚠️ AIは休憩中ですが、他のデータは正常です！")
                            st.error(f"API制限: {e}")
                    else: st.warning("AI接続不可")
                except Exception as e: st.error(f"News Error: {e}")

            # --- Tab 2: チャート ---
            with tab2:
                st.info(f"テクニカル判定: {cross} / {kumo}")
                d_hist = hist.tail(150)
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=d_hist.index, y=d_hist['SpanA'], line=dict(width=0), showlegend=False, hoverinfo='skip'))
                fig.add_trace(go.Scatter(x=d_hist.index, y=d_hist['SpanB'], line=dict(width=0), name='雲', fill='tonexty', fillcolor='rgba(0,200,200,0.2)'))
                fig.add_trace(go.Candlestick(x=d_hist.index, open=d_hist['Open'], high=d_hist['High'], low=d_hist['Low'], close=d_hist['Close'], name='株価'))
                fig.add_trace(go.Scatter(x=d_hist.index, y=d_hist['SMA25'], line=dict(color='orange'), name='25MA'))
                fig.add_trace(go.Scatter(x=d_hist.index, y=d_hist['SMA75'], line=dict(color='skyblue'), name='75MA'))
                fig.update_layout(height=500, xaxis_rangeslider_visible=False, template="plotly_dark")
                st.plotly_chart(fig, use_container_width=True)

            # --- Tab 3: 業績・財務 (New!) ---
            with tab3:
                st.subheader("💰 業績推移 (AI不要)")
                try:
                    # 財務データの取得
                    fin = tk.financials
                    if fin is not None and not fin.empty:
                        # データ整理 (転置して日付を列に)
                        fin = fin.T.sort_index()
                        # 最新3期分
                        fin_recent = fin.tail(4)
                        
                        # グラフ描画
                        fig_fin = go.Figure()
                        if 'Total Revenue' in fin.columns:
                            fig_fin.add_trace(go.Bar(x=fin_recent.index, y=fin_recent['Total Revenue'], name='売上高', marker_color='#4ecdc4'))
                        elif 'Total Revenue' not in fin.columns and 'Revenue' in fin.columns: # 表記揺れ対応
                             fig_fin.add_trace(go.Bar(x=fin_recent.index, y=fin_recent['Revenue'], name='売上高', marker_color='#4ecdc4'))

                        if 'Net Income' in fin.columns:
                            fig_fin.add_trace(go.Bar(x=fin_recent.index, y=fin_recent['Net Income'], name='純利益', marker_color='#ff6b6b'))
                        
                        fig_fin.update_layout(title="売上高と純利益の推移 (年次)", barmode='group', template="plotly_dark", height=400)
                        st.plotly_chart(fig_fin, use_container_width=True)
                        
                        # データテーブル表示
                        st.write("📊 **詳細データ (単位: 円)**")
                        st.dataframe(fin[['Total Revenue', 'Net Income']].style.format("{:,.0f}") if 'Total Revenue' in fin.columns else fin)
                    else:
                        st.info("詳細な財務データが取得できませんでした。")
                except Exception as e:
                    st.error(f"財務データエラー: {e}")

        except Exception as e:
            st.error(f"データ取得エラー: {e}")
