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

# --- 日本時間の設定 ---
JST = datetime.timezone(datetime.timedelta(hours=9))

def get_current_time_jst():
    return datetime.datetime.now(JST)

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
st.sidebar.info("Ver 8.0: JST & Deep Search")

# --- 履歴表示 ---
st.sidebar.subheader("🕒 最近のチェック")
history = st.session_state['history']
if history:
    # 新しい順にソート
    sorted_codes = sorted(history.keys(), key=lambda x: history[x].get('timestamp', ''), reverse=True)
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
    except:
        return None

def safe_get(info, keys, default=None):
    for k in keys:
        val = info.get(k)
        if val is not None: return val
    return default

def calculate_scores(hist, info):
    latest = hist.iloc[-1]
    price = latest['Close']
    
    # オニール式
    oneil_score = 0
    high_52 = safe_get(info, ['fiftyTwoWeekHigh'])
    if high_52:
        dist_high = (high_52 - price) / high_52 * 100
        if dist_high < 10: oneil_score += 40
        elif dist_high < 20: oneil_score += 20
    else: oneil_score += 20
    
    vol_mean = hist['Volume'].rolling(20).mean().iloc[-1]
    if latest['Volume'] > vol_mean * 1.0: oneil_score += 30 
    
    sma25 = hist['Close'].rolling(25).mean().iloc[-1]
    if price > sma25: oneil_score += 30
    
    # グレアム式
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
    
    # 戦略1: 「24時間以内」の速報・決算短信 (カブタン・日経などを狙う)
    # 期間を 'd' (1日) に設定
    queries_hot = [
        f"{code} {name} 決算短信 発表",
        f"{code} {name} 決算 カブタン",
        f"{code} {name} 業績修正"
    ]
    
    for q in queries_hot:
        try:
            results = ddgs.text(q, region='jp-jp', timelimit='d', max_results=3)
            if results:
                for r in results:
                    if r['title'] not in news_text:
                        news_text += f"【速報】{r['title']} ({r['body'][:60]}...)\n"
        except: pass
        if len(news_text) > 200: break

    # 戦略2: もし速報がなければ、期間を「1週間(w)」に広げて再検索 (バックアップ)
    # これで「昨日の夕方」のニュースなどが漏れていた場合に拾う
    if not news_text:
        try:
            results = ddgs.text(f"{code} {name} 決算 ニュース", region='jp-jp', timelimit='w', max_results=5)
            if results:
                news_text += "【直近ニュース】\n"
                for r in results:
                    if r['title'] not in news_text:
                        news_text += f"- {r['title']} ({r['body'][:50]}...)\n"
        except: pass

    if not news_text:
        return "直近の決算・重要ニュースは検索できませんでした。"
    return news_text

# --- UI ---
st.title("🦅 Deep Dive Investing AI Pro (Ver 8.0)")
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
    
    # 日本時間を取得
    now_jst = get_current_time_jst()
    now_str = now_jst.strftime("%Y年%m月%d日 %H:%M (JST)")
    
    # 1. データ取得
    with st.spinner(f"コード【{code}】を分析中... (現在日時: {now_str})"):
        try:
            ticker = yf.Ticker(f"{code}.T")
            hist = ticker.history(period="2y")
            info = ticker.info
            
            if hist.empty:
                st.error("データ取得エラー。正しいコードか確認してください。")
                st.stop()
            
            hist, cross_stat, kumo_stat = calculate_technicals(hist)
            oneil, graham, rsi = calculate_scores(hist, info)
            
            latest = hist.iloc[-1]
            price = latest['Close']
            change_pct = ((price - hist.iloc[-2]['Close']) / hist.iloc[-2]['Close']) * 100
            name = info.get('longName', code)
            
            # 履歴保存
            current_data = {
                'name': name, 'timestamp': now_str,
                'price': price, 'oneil': oneil, 'graham': graham
            }
            st.session_state['history'][code] = current_data
            save_history(st.session_state['history'])
            
            # --- 表示 ---
            st.header(f"{name} ({code})")
            st.caption(f"分析日時: {now_str}")
            
            # 変化表示
            # (履歴比較ロジックは簡略化のため省略、保存はされています)

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("現在値", f"{price:,.0f}円", f"{change_pct:+.2f}%")
            c2.metric("RSI", f"{rsi:.1f}")
            c3.metric("成長株スコア", f"{oneil}点")
            c4.metric("割安株スコア", f"{graham}点")
            
            t1, t2 = st.columns(2)
            t1.info(f"MA判定: **{cross_stat}**")
            t2.info(f"一目判定: **{kumo_stat}**")

            # --- チャート ---
            st.subheader("📈 チャート")
            display_hist = hist.tail(100)
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=display_hist.index, y=display_hist['SpanA'], line=dict(width=0), showlegend=False, hoverinfo='skip'))
            fig.add_trace(go.Scatter(x=display_hist.index, y=display_hist['SpanB'], line=dict(width=0), name='雲', fill='tonexty', fillcolor='rgba(0, 200, 200, 0.2)'))
            fig.add_trace(go.Candlestick(x=display_hist.index, open=display_hist['Open'], high=display_hist['High'], low=display_hist['Low'], close=display_hist['Close'], name="株価"))
            fig.add_trace(go.Scatter(x=display_hist.index, y=display_hist['SMA25'], line=dict(color='orange', width=1.5), name="25日線"))
            fig.add_trace(go.Scatter(x=display_hist.index, y=display_hist['SMA75'], line=dict(color='skyblue', width=1.5), name="75日線"))
            fig.update_layout(height=450, xaxis_rangeslider_visible=False, template="plotly_dark", margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)

        except Exception as e:
            st.error(f"データエラー: {e}")
            st.stop()

    # 2. ニュースとAI (エラー分離)
    st.divider()
    st.subheader("📝 決算 & AI分析")
    
    try:
        news = get_news_deep_dive(code, name)
        
        prompt = f"""
        あなたは日本株運用のプロ機関投資家です。
        【重要】現在日時は「{now_str}」です。この日時を基準に分析してください。

        銘柄: {name} ({code})
        株価: {price}円
        ニュース: {news}
        スコア: 成長{oneil}点, 割安{graham}点
        
        指示:
        1. **決算分析 (最重要)**:
           ニュース欄を読み解き、直近(今日〜昨日)に発表された決算や修正があれば、その内容（増益率・修正理由など）を詳細に解説。
           ※もしニュースに「速報」がなくとも、過去数日の情報から最新の状況を推測してください。
        2. **スコア＆テクニカル**:
           {cross_stat}や{kumo_stat}を踏まえた売買判断。
        3. **戦略**:
           明日以降の具体的なアクション。
        """
        
        if model:
            try:
                resp = model.generate_content(prompt)
                st.markdown(resp.text)
            except Exception as e:
                st.warning("⚠️ AIが一時的に混雑しています (API制限)。")
                st.error(f"詳細: {e}")
        else:
             st.warning("AIモデル接続不可。")

    except Exception as e:
        st.error(f"ニュース取得エラー: {e}")
