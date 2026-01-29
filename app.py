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

# --- 履歴ファイルの管理 ---
HISTORY_FILE = 'stock_history.json'

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f:
                return json.load(f)
        except: return {}
    return {}

def save_history(history_data):
    try:
        with open(HISTORY_FILE, 'w') as f:
            json.dump(history_data, f)
    except: pass

# --- セッション初期化 ---
if 'history' not in st.session_state:
    st.session_state['history'] = load_history()
if 'target_code' not in st.session_state:
    st.session_state['target_code'] = None

# --- サイドバー ---
st.sidebar.title("🦅 Deep Dive Pro")
if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
    st.sidebar.success("🔑 API認証済み")
else:
    api_key = st.sidebar.text_input("Gemini APIキー", type="password")

st.sidebar.markdown("---")
st.sidebar.info("Ver 7.1: Chart Fixed")

# --- 履歴表示 ---
st.sidebar.subheader("🕒 最近のチェック")
history = st.session_state['history']
if history:
    sorted_codes = sorted(history.keys(), key=lambda x: history[x]['timestamp'], reverse=True)
    for c in sorted_codes[:5]:
        data = history[c]
        if st.sidebar.button(f"{data['name']} ({c})", key=f"hist_{c}"):
            st.session_state['target_code'] = c
            st.rerun()
    
    if st.sidebar.button("履歴をクリア"):
        if os.path.exists(HISTORY_FILE):
            os.remove(HISTORY_FILE)
        st.session_state['history'] = {}
        st.rerun()

# --- 関数群 ---

def get_model(api_key):
    try:
        genai.configure(api_key=api_key)
        # 利用可能なモデルを検索
        models = [m for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        
        # 優先順位: 1.5-flash -> 1.5-pro -> pro -> その他
        target_model = "models/gemini-1.5-flash"
        if not any(m.name == target_model for m in models):
             target_model = next((m.name for m in models if 'flash' in m.name), "models/gemini-pro")
        
        return genai.GenerativeModel(target_model)
    except Exception as e:
        st.sidebar.error(f"モデル接続エラー: {e}")
        return None

def safe_get(info, keys, default=None):
    for k in keys:
        val = info.get(k)
        if val is not None: return val
    return default

def calculate_scores(hist, info):
    latest = hist.iloc[-1]
    price = latest['Close']
    
    # --- 1. オニール式 ---
    oneil_score = 0
    high_52 = safe_get(info, ['fiftyTwoWeekHigh'])
    if high_52:
        dist_high = (high_52 - price) / high_52 * 100
        if dist_high < 10: oneil_score += 40
        elif dist_high < 20: oneil_score += 20
    else: oneil_score += 20
    
    vol_mean = hist['Volume'].rolling(20).mean().iloc[-1]
    current_vol = latest['Volume']
    if current_vol > vol_mean * 1.0: oneil_score += 30 
    
    sma25 = hist['Close'].rolling(25).mean().iloc[-1]
    if price > sma25: oneil_score += 30
    
    # --- 2. グレアム式 ---
    graham_score = 0
    eps = safe_get(info, ['forwardEps', 'trailingEps'])
    if eps and eps > 0:
        per = price / eps
        if 0 < per < 15: graham_score += 30
        elif 0 < per < 25: graham_score += 15
    else: graham_score += 15
    
    bps = safe_get(info, ['bookValue'])
    if bps and bps > 0:
        pbr = price / bps
        if 0 < pbr < 1.0: graham_score += 20
        elif 0 < pbr < 1.5: graham_score += 10
    else: graham_score += 10
    
    div_rate = safe_get(info, ['dividendRate', 'dividendYield'])
    if div_rate:
        yield_pct = div_rate * 100 if div_rate < 1 else (div_rate / price * 100)
        if yield_pct > 3.5: graham_score += 30
        elif yield_pct > 2.5: graham_score += 15
    
    delta = hist['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean().iloc[-1]
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean().iloc[-1]
    rsi = 100 - (100 / (1 + gain / loss)) if loss != 0 else 50
    if rsi < 30: graham_score += 20
    elif rsi < 40: graham_score += 10

    return oneil_score, graham_score, rsi

def calculate_technicals(hist):
    hist['SMA5'] = hist['Close'].rolling(window=5).mean()
    hist['SMA25'] = hist['Close'].rolling(window=25).mean()
    hist['SMA75'] = hist['Close'].rolling(window=75).mean()
    
    latest = hist.iloc[-1]
    prev = hist.iloc[-2]
    
    cross_status = "特になし"
    if pd.notna(prev['SMA5']) and pd.notna(prev['SMA25']):
        if prev['SMA5'] < prev['SMA25'] and latest['SMA5'] > latest['SMA25']: cross_status = "ゴールデンクロス (短期)"
        elif prev['SMA25'] < prev['SMA75'] and latest['SMA25'] > latest['SMA75']: cross_status = "ゴールデンクロス (長期)"
        elif prev['SMA5'] > prev['SMA25'] and latest['SMA5'] < latest['SMA25']: cross_status = "デッドクロス (短期)"
        elif prev['SMA25'] > prev['SMA75'] and latest['SMA25'] < latest['SMA75']: cross_status = "デッドクロス (長期)"

    high9 = hist['High'].rolling(window=9).max()
    low9 = hist['Low'].rolling(window=9).min()
    hist['Tenkan'] = (high9 + low9) / 2
    high26 = hist['High'].rolling(window=26).max()
    low26 = hist['Low'].rolling(window=26).min()
    hist['Kijun'] = (high26 + low26) / 2
    hist['SpanA'] = ((hist['Tenkan'] + hist['Kijun']) / 2).shift(26)
    hist['SpanB'] = ((hist['High'].rolling(52).max() + hist['Low'].rolling(52).min()) / 2).shift(26)
    
    kumo_status = "雲の中"
    current = latest['Close']
    sa, sb = hist['SpanA'].iloc[-1], hist['SpanB'].iloc[-1]
    if pd.notna(sa) and pd.notna(sb):
        if current > max(sa, sb): kumo_status = "雲上抜け (強気)"
        elif current < min(sa, sb): kumo_status = "雲下抜け (弱気)"

    return hist, cross_status, kumo_status

def get_news_deep_dive(code, name):
    ddgs = DDGS()
    news_text = ""
    # 決算・適時開示を狙うクエリ
    queries = [
        f"{code} {name} 決算短信 発表 2026",
        f"{code} {name} 業績予想修正 速報"
    ]
    for q in queries:
        try:
            results = ddgs.text(q, region='jp-jp', timelimit='d', max_results=3)
            if results:
                for r in results:
                    if r['title'] not in news_text:
                        news_text += f"- {r['title']} ({r['body'][:60]}...)\n"
        except: pass
        if len(news_text) > 300: break

    if not news_text:
        return "直近24時間以内の重要ニュースは見当たりませんでした（15:30前の可能性あり）。"
    return news_text

# --- UI ---
st.title("🦅 Deep Dive Investing AI Pro (Ver 7.1)")
query = st.text_input("銘柄コードまたは企業名", placeholder="例: 6702")

if st.button("🔍 プロ分析開始", type="primary"):
    if not api_key: st.error("APIキーを入れてください"); st.stop()
    if not query: st.warning("銘柄を入力してください"); st.stop()
    
    target_code = None
    if re.fullmatch(r'\d{4}', query.strip()):
        target_code = query.strip()
    else:
        with st.spinner("銘柄特定中..."):
            model = get_model(api_key)
            if model:
                try:
                    resp = model.generate_content(f"日本株「{query}」のコード(4桁)のみ出力。")
                    match = re.search(r'\d{4}', resp.text)
                    if match: target_code = match.group(0)
                except: pass
    
    if target_code:
        st.session_state['target_code'] = target_code
        st.rerun()
    else:
        st.error("銘柄が見つかりませんでした")

# --- 分析実行 ---
if st.session_state['target_code']:
    code = st.session_state['target_code']
    model = get_model(api_key)
    
    with st.spinner(f"コード【{code}】の最新情報（15:30以降対応）を取得中..."):
        try:
            ticker = yf.Ticker(f"{code}.T")
            hist = ticker.history(period="2y")
            info = ticker.info
            
            if hist.empty:
                st.error("データ取得エラー")
            else:
                hist, cross_stat, kumo_stat = calculate_technicals(hist)
                oneil, graham, rsi = calculate_scores(hist, info)
                
                latest = hist.iloc[-1]
                price = latest['Close']
                change_pct = ((price - hist.iloc[-2]['Close']) / hist.iloc[-2]['Close']) * 100
                name = info.get('longName', code)
                news = get_news_deep_dive(code, name)
                
                # 履歴保存
                prev_data = st.session_state['history'].get(code, None)
                current_data = {
                    'name': name,
                    'timestamp': datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                    'price': price,
                    'oneil': oneil,
                    'graham': graham
                }
                st.session_state['history'][code] = current_data
                save_history(st.session_state['history'])

                st.header(f"{name} ({code})")
                
                # 変化表示
                if prev_data:
                    st.info(f"🔄 **前回 ({prev_data['timestamp']}) からの変化:**")
                    p_diff = price - prev_data['price']
                    o_diff = oneil - prev_data['oneil']
                    g_diff = graham - prev_data['graham']
                    c_h1, c_h2, c_h3 = st.columns(3)
                    c_h1.metric("株価変化", f"{p_diff:+.0f}円", delta_color="normal")
                    c_h2.metric("成長スコア変化", f"{o_diff:+d}点")
                    c_h3.metric("割安スコア変化", f"{g_diff:+d}点")
                else:
                    st.success("✨ 初めて分析する銘柄です。履歴に保存しました。")

                st.divider()

                c1, c2, c3, c4 = st.columns(4)
                c1.metric("現在値", f"{price:,.0f}円", f"{change_pct:+.2f}%")
                c2.metric("RSI", f"{rsi:.1f}")
                c3.metric("成長株スコア", f"{oneil}点")
                c4.metric("割安株スコア", f"{graham}点")
                
                t1, t2 = st.columns(2)
                t1.info(f"MA判定: **{cross_stat}**")
                t2.info(f"一目判定: **{kumo_stat}**")

                # --- チャート (修正: MAを復活) ---
                st.subheader("📈 チャート")
                display_hist = hist.tail(100)
                fig = go.Figure()
                
                # 雲
                fig.add_trace(go.Scatter(x=display_hist.index, y=display_hist['SpanA'], line=dict(width=0), showlegend=False, hoverinfo='skip'))
                fig.add_trace(go.Scatter(x=display_hist.index, y=display_hist['SpanB'], line=dict(width=0), name='雲', fill='tonexty', fillcolor='rgba(0, 200, 200, 0.2)'))
                
                # ローソク足
                fig.add_trace(go.Candlestick(x=display_hist.index, open=display_hist['Open'], high=display_hist['High'], low=display_hist['Low'], close=display_hist['Close'], name="株価"))
                
                # 移動平均線 (復活!)
                fig.add_trace(go.Scatter(x=display_hist.index, y=display_hist['SMA25'], line=dict(color='orange', width=1.5), name="25日線"))
                fig.add_trace(go.Scatter(x=display_hist.index, y=display_hist['SMA75'], line=dict(color='skyblue', width=1.5), name="75日線"))
                
                fig.update_layout(height=450, xaxis_rangeslider_visible=False, template="plotly_dark", margin=dict(l=10, r=10, t=10, b=10))
                st.plotly_chart(fig, use_container_width=True)

                # AIレポート
                st.subheader("📝 決算 & AI分析")
                prompt = f"""
                あなたは機関投資家です。現在日時「{datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}」。
                本日発表された「決算短信」や「業績修正」があれば、その数値を元に徹底的に分析してください。
                
                銘柄: {name} ({code})
                株価: {price}円
                ニュース: {news}
                スコア: 成長{oneil}点, 割安{graham}点
                
                指示:
                1. **決算速報 (最重要)**:
                   ニュース欄を確認し、本日付の決算発表があれば内容（増益・減益など）を詳述。
                2. **スコア分析**:
                   {oneil}点、{graham}点というスコアの背景。
                3. **売買戦略**:
                   短期・中期の具体的なエントリー・損切りポイント。
                """
                
                if model:
                    try:
                        resp = model.generate_content(prompt)
                        st.markdown(resp.text)
                    except Exception as e:
                        # エラー内容を詳細に表示する
                        st.error(f"AI生成エラー: {e}")
                        st.error("※APIキーが無効、またはGoogle側の制限の可能性があります。")

        except Exception as e:
            st.error(f"全体エラー: {e}")
