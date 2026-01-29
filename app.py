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
st.sidebar.info("Ver 7.2: Robust Mode")

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
        models = [m for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        target_model = "models/gemini-1.5-flash"
        if not any(m.name == target_model for m in models):
             target_model = next((m.name for m in models if 'flash' in m.name), "models/gemini-pro")
        return genai.GenerativeModel(target_model)
    except Exception as e:
        return None

def safe_get(info, keys, default=None):
    for k in keys:
        val = info.get(k)
        if val is not None: return val
    return default

def calculate_scores(hist, info):
    latest = hist.iloc[-1]
    price = latest['Close']
    
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
        return "直近24時間以内の重要ニュースは見当たりませんでした。"
    return news_text

# --- UI ---
st.title("🦅 Deep Dive Investing AI Pro (Ver 7.2)")
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
            else:
                # API制限時でも動くようにダミー検索を試みる等は省略
                st.error("現在API制限中のため、銘柄名検索ができません。コード（数字）で直接入力してください。")
    
    if target_code:
        st.session_state['target_code'] = target_code
        st.rerun()
    else:
        st.error("銘柄が見つかりませんでした")

# --- 分析実行 ---
if st.session_state['target_code']:
    code = st.session_state['target_code']
    model = get_model(api_key)
    
    # 【変更点】全体をtryで囲わず、各パートごとに安全に実行する
    
    # 1. データ取得と計算（ここはAPI制限関係なし）
    with st.spinner(f"コード【{code}】のデータを分析中..."):
        try:
            ticker = yf.Ticker(f"{code}.T")
            hist = ticker.history(period="2y")
            info = ticker.info
            
            if hist.empty:
                st.error("データ取得エラー：正しいコードか確認してください。")
                st.stop()
                
            hist, cross_stat, kumo_stat = calculate_technicals(hist)
            oneil, graham, rsi = calculate_scores(hist, info)
            
            latest = hist.iloc[-1]
            price = latest['Close']
            change_pct = ((price - hist.iloc[-2]['Close']) / hist.iloc[-2]['Close']) * 100
            name = info.get('longName', code)
            
            # 履歴保存
            current_data = {
                'name': name, 'timestamp': datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                'price': price, 'oneil': oneil, 'graham': graham
            }
            st.session_state['history'][code] = current_data
            save_history(st.session_state['history'])
            
            # --- 表示 ---
            st.header(f"{name} ({code})")
            
            # 変化表示
            prev_data = st.session_state['history'].get(code, {})
            # (省略: 簡易表示)
            
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("現在値", f"{price:,.0f}円", f"{change_pct:+.2f}%")
            c2.metric("RSI", f"{rsi:.1f}")
            c3.metric("成長株スコア", f"{oneil}点")
            c4.metric("割安株スコア", f"{graham}点")
            
            t1, t2 = st.columns(2)
            t1.info(f"MA判定: **{cross_stat}**")
            t2.info(f"一目判定: **{kumo_stat}**")

            # --- チャート表示 ---
            st.subheader("📈 チャート")
            display_hist = hist.tail(100)
            fig = go.Figure()
            # 雲
            fig.add_trace(go.Scatter(x=display_hist.index, y=display_hist['SpanA'], line=dict(width=0), showlegend=False, hoverinfo='skip'))
            fig.add_trace(go.Scatter(x=display_hist.index, y=display_hist['SpanB'], line=dict(width=0), name='雲', fill='tonexty', fillcolor='rgba(0, 200, 200, 0.2)'))
            # 株価
            fig.add_trace(go.Candlestick(x=display_hist.index, open=display_hist['Open'], high=display_hist['High'], low=display_hist['Low'], close=display_hist['Close'], name="株価"))
            # MA (移動平均線)
            fig.add_trace(go.Scatter(x=display_hist.index, y=display_hist['SMA25'], line=dict(color='orange', width=1.5), name="25日線"))
            fig.add_trace(go.Scatter(x=display_hist.index, y=display_hist['SMA75'], line=dict(color='skyblue', width=1.5), name="75日線"))
            
            fig.update_layout(height=450, xaxis_rangeslider_visible=False, template="plotly_dark", margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)

        except Exception as e:
            st.error(f"データ表示エラー: {e}")
            st.stop()

    # 2. ニュースとAIレポート（ここだけAPI制限の影響を受ける）
    st.divider()
    st.subheader("📝 決算 & AI分析")
    
    try:
        news = get_news_deep_dive(code, name)
        
        prompt = f"""
        あなたは機関投資家です。現在日時「{datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}」。
        本日発表された「決算短信」や「業績修正」があれば、その数値を元に徹底的に分析してください。
        銘柄: {name} ({code})
        株価: {price}円
        ニュース: {news}
        スコア: 成長{oneil}点, 割安{graham}点
        指示: 決算速報、スコア分析、売買戦略を記述。
        """
        
        if model:
            try:
                resp = model.generate_content(prompt)
                st.markdown(resp.text)
            except Exception as e:
                # ここでエラーになってもチャートは消えない！
                st.warning("⚠️ **AIは現在「休憩中（API制限）」ですが、上のチャートとスコアは最新です！**")
                st.error(f"Google AIエラー: {e}")
                st.write("※数分待ってから再読み込みすると、レポートも表示されます。")
        else:
             st.warning("AIモデルに接続できませんでした。APIキーを確認してください。")

    except Exception as e:
        st.error(f"ニュース取得エラー: {e}")
