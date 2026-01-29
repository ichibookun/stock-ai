import streamlit as st
import google.generativeai as genai
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from duckduckgo_search import DDGS
import time
import re
import datetime

# --- ページ設定 ---
st.set_page_config(page_title="Deep Dive Investing AI Pro", layout="wide")

# --- セッション初期化 ---
if 'candidates' not in st.session_state:
    st.session_state['candidates'] = None
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
st.sidebar.info("Ver 5.0: Tech & Earnings")

# --- 分析関数群 ---

def calculate_technicals(hist):
    # 移動平均
    hist['SMA5'] = hist['Close'].rolling(window=5).mean()
    hist['SMA25'] = hist['Close'].rolling(window=25).mean()
    hist['SMA75'] = hist['Close'].rolling(window=75).mean()
    
    # クロス判定
    latest = hist.iloc[-1]
    prev = hist.iloc[-2]
    
    cross_status = "なし"
    if prev['SMA5'] < prev['SMA25'] and latest['SMA5'] > latest['SMA25']:
        cross_status = "ゴールデンクロス (短期)"
    elif prev['SMA25'] < prev['SMA75'] and latest['SMA25'] > latest['SMA75']:
        cross_status = "ゴールデンクロス (長期)"
    elif prev['SMA5'] > prev['SMA25'] and latest['SMA5'] < latest['SMA25']:
        cross_status = "デッドクロス (短期)"
    elif prev['SMA25'] > prev['SMA75'] and latest['SMA25'] < latest['SMA75']:
        cross_status = "デッドクロス (長期)"

    # 一目均衡表 (簡易計算)
    high9 = hist['High'].rolling(window=9).max()
    low9 = hist['Low'].rolling(window=9).min()
    tenkan = (high9 + low9) / 2

    high26 = hist['High'].rolling(window=26).max()
    low26 = hist['Low'].rolling(window=26).min()
    kijun = (high26 + low26) / 2

    span_a = ((tenkan + kijun) / 2).shift(26)
    span_b = ((hist['High'].rolling(52).max() + hist['Low'].rolling(52).min()) / 2).shift(26)
    
    # 雲の状態
    kumo_status = "雲の中"
    current_price = latest['Close']
    current_span_a = span_a.iloc[-1]
    current_span_b = span_b.iloc[-1]
    
    if pd.isna(current_span_a) or pd.isna(current_span_b):
        kumo_status = "計算データ不足"
    elif current_price > max(current_span_a, current_span_b):
        kumo_status = "雲上抜け (強気)"
    elif current_price < min(current_span_a, current_span_b):
        kumo_status = "雲下抜け (弱気)"

    return hist, cross_status, kumo_status, tenkan.iloc[-1], kijun.iloc[-1]

def get_news_deep_dive(code, name):
    ddgs = DDGS()
    news_text = ""
    
    # 1. 決算・業績ニュース
    try:
        results = ddgs.text(f"{code} {name} 決算 コンセンサス 上方修正", region='jp-jp', timelimit='w', max_results=5)
        news_text += "【決算・業績ニュース】\n"
        for r in results:
            news_text += f"- {r['title']} ({r['body'][:50]}...)\n"
    except: pass
    
    # 2. 一般ニュース
    try:
        results = ddgs.text(f"{code} {name} 株価 材料", region='jp-jp', timelimit='w', max_results=3)
        news_text += "\n【市場の材料】\n"
        for r in results:
            news_text += f"- {r['title']}\n"
    except: pass
    
    return news_text if news_text else "特になし"

def get_model(api_key):
    try:
        genai.configure(api_key=api_key)
        return genai.GenerativeModel('gemini-1.5-flash')
    except: return None

# --- UI ---
st.title("🦅 Deep Dive Investing AI Pro")
query = st.text_input("銘柄コードまたは企業名", placeholder="例: 6702 または 富士通")

if st.button("🔍 プロ分析開始", type="primary"):
    if not api_key:
        st.error("APIキーを入れてください")
    elif not query:
        st.warning("銘柄を入力してください")
    else:
        # コード特定処理
        target_code = None
        if re.fullmatch(r'\d{4}', query.strip()):
            target_code = query.strip()
        else:
            with st.spinner("銘柄コード検索中..."):
                model = get_model(api_key)
                if model:
                    resp = model.generate_content(f"日本株「{query}」の銘柄コード(4桁)のみを返して。")
                    match = re.search(r'\d{4}', resp.text)
                    if match: target_code = match.group(0)
        
        if target_code:
            st.session_state['target_code'] = target_code
            st.rerun()
        else:
            st.error("銘柄が見つかりませんでした")

# --- 分析実行 ---
if st.session_state['target_code']:
    code = st.session_state['target_code']
    model = get_model(api_key)
    
    with st.spinner(f"コード【{code}】のテクニカル＆決算を徹底調査中..."):
        # データ取得
        ticker = yf.Ticker(f"{code}.T")
        hist = ticker.history(period="1y") # 1年分取得（雲の計算のため）
        info = ticker.info
        
        if hist.empty:
            st.error("データが取得できませんでした")
        else:
            # テクニカル計算
            hist, cross_stat, kumo_stat, tenkan, kijun = calculate_technicals(hist)
            
            # 直近データ
            latest = hist.iloc[-1]
            price = latest['Close']
            prev_close = hist.iloc[-2]['Close']
            change = price - prev_close
            change_pct = (change / prev_close) * 100
            
            # ニュース収集（決算重視）
            name = info.get('longName', code)
            news = get_news_deep_dive(code, name)
            
            # --- 表示セクション ---
            st.header(f"{name} ({code})")
            
            # メトリクス
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("株価", f"{price:,.0f}円", f"{change:+.0f}円 ({change_pct:+.2f}%)")
            c2.metric("MAクロス判定", cross_stat, delta_color="off")
            c3.metric("一目均衡表", kumo_stat, delta_color="off")
            c4.metric("PER / PBR", f"{info.get('trailingPE','-'):.1f}倍 / {info.get('priceToBook','-'):.2f}倍")

            # --- チャート (TradingView風 + MA) ---
            st.subheader("📈 テクニカルチャート")
            
            # 表示期間を直近6ヶ月に絞る
            display_hist = hist.tail(120) 
            
            fig = go.Figure()
            # ローソク足
            fig.add_trace(go.Candlestick(
                x=display_hist.index,
                open=display_hist['Open'], high=display_hist['High'],
                low=display_hist['Low'], close=display_hist['Close'],
                name="株価"
            ))
            # 移動平均線
            fig.add_trace(go.Scatter(x=display_hist.index, y=display_hist['SMA25'], line=dict(color='orange', width=1), name="25日線"))
            fig.add_trace(go.Scatter(x=display_hist.index, y=display_hist['SMA75'], line=dict(color='skyblue', width=1), name="75日線"))
            
            fig.update_layout(height=500, xaxis_rangeslider_visible=False, template="plotly_dark")
            st.plotly_chart(fig, use_container_width=True)

            # --- AIプロ分析レポート ---
            st.divider()
            st.subheader("📝 プロ・アナリストレポート")
            
            # 形状分析用の価格データ文字列作成
            price_seq
