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
st.sidebar.info("Ver 5.3: Real-time Earnings")

# --- 関数群 ---

def get_model(api_key):
    try:
        genai.configure(api_key=api_key)
        models = [m for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        model_name = "models/gemini-1.5-flash"
        if not any(m.name == model_name for m in models):
             model_name = next((m.name for m in models if 'flash' in m.name), "models/gemini-pro")
        return genai.GenerativeModel(model_name)
    except:
        return None

def calculate_technicals(hist):
    hist['SMA5'] = hist['Close'].rolling(window=5).mean()
    hist['SMA25'] = hist['Close'].rolling(window=25).mean()
    hist['SMA75'] = hist['Close'].rolling(window=75).mean()
    
    latest = hist.iloc[-1]
    prev = hist.iloc[-2]
    
    cross_status = "特になし"
    cross_detail = "移動平均線のクロスは確認できません"
    
    if pd.notna(prev['SMA5']) and pd.notna(prev['SMA25']):
        if prev['SMA5'] < prev['SMA25'] and latest['SMA5'] > latest['SMA25']:
            cross_status = "ゴールデンクロス"
            cross_detail = "短期線(5日)が中期線(25日)を上抜け (買いサイン)"
        elif prev['SMA25'] < prev['SMA75'] and latest['SMA25'] > latest['SMA75']:
            cross_status = "ゴールデンクロス"
            cross_detail = "中期線(25日)が長期線(75日)を上抜け (強い買いサイン)"
        elif prev['SMA5'] > prev['SMA25'] and latest['SMA5'] < latest['SMA25']:
            cross_status = "デッドクロス"
            cross_detail = "短期線(5日)が中期線(25日)を下抜け (売りサイン)"
        elif prev['SMA25'] > prev['SMA75'] and latest['SMA25'] < latest['SMA75']:
            cross_status = "デッドクロス"
            cross_detail = "中期線(25日)が長期線(75日)を下抜け (強い売りサイン)"

    high9 = hist['High'].rolling(window=9).max()
    low9 = hist['Low'].rolling(window=9).min()
    hist['Tenkan'] = (high9 + low9) / 2
    high26 = hist['High'].rolling(window=26).max()
    low26 = hist['Low'].rolling(window=26).min()
    hist['Kijun'] = (high26 + low26) / 2
    hist['SpanA'] = ((hist['Tenkan'] + hist['Kijun']) / 2).shift(26)
    hist['SpanB'] = ((hist['High'].rolling(52).max() + hist['Low'].rolling(52).min()) / 2).shift(26)
    
    kumo_status = "雲の中"
    kumo_detail = "株価は雲の中にあります"
    current_price = latest['Close']
    span_a = hist['SpanA'].iloc[-1]
    span_b = hist['SpanB'].iloc[-1]
    
    if pd.notna(span_a) and pd.notna(span_b):
        if current_price > max(span_a, span_b):
            kumo_status = "雲上抜け"
            kumo_detail = "株価が雲を上に抜けました (強気入り)"
        elif current_price < min(span_a, span_b):
            kumo_status = "雲下抜け"
            kumo_detail = "株価が雲を下に抜けました (弱気入り)"

    return hist, cross_status, cross_detail, kumo_status, kumo_detail

def get_news_deep_dive(code, name):
    ddgs = DDGS()
    news_text = ""
    
    # 【戦略1】超速報：24時間以内の「決算短信・発表」を狙う
    try:
        # timelimit='d' (1日以内) で指定
        results = ddgs.text(f"{code} {name} 決算短信 発表 結果", region='jp-jp', timelimit='d', max_results=5)
        if results:
            news_text += "【🚨 HOT: 24時間以内の最新情報】\n"
            for r in results:
                news_text += f"- {r['title']} ({r['body'][:60]}...)\n"
    except: pass
    
    # 【戦略2】もし24時間以内がなければ、数日以内のニュースを探す
    if not news_text:
        try:
            results = ddgs.text(f"{code} {name} 決算 ニュース", region='jp-jp', timelimit='w', max_results=5)
            if results:
                news_text += "【直近1週間のニュース】\n"
                for r in results:
                    news_text += f"- {r['title']} ({r['body'][:50]}...)\n"
        except: pass

    # 【戦略3】材料検索
    if len(news_text) < 200: # 情報が少なければ追加検索
        try:
            results = ddgs.text(f"{code} {name} 株価材料 上方修正", region='jp-jp', timelimit='w', max_results=3)
            news_text += "\n【その他の材料】\n"
            for r in results:
                news_text += f"- {r['title']}\n"
        except: pass
    
    return news_text if news_text else "最新のニュースが見つかりませんでした。"

# --- UI ---
st.title("🦅 Deep Dive Investing AI Pro")
query = st.text_input("銘柄コードまたは企業名", placeholder="例: 7203 または トヨタ")

if st.button("🔍 プロ分析開始", type="primary"):
    if not api_key:
        st.error("APIキーを入れてください")
    elif not query:
        st.warning("銘柄を入力してください")
    else:
        target_code = None
        if re.fullmatch(r'\d{4}', query.strip()):
            target_code = query.strip()
        else:
            with st.spinner("銘柄コード検索中..."):
                model = get_model(api_key)
                if model:
                    try:
                        resp = model.generate_content(f"日本株「{query}」の銘柄コード(4桁)のみを返して。")
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
    
    with st.spinner(f"コード【{code}】の最新決算＆テクニカルを徹底調査中..."):
        try:
            ticker = yf.Ticker(f"{code}.T")
            hist = ticker.history(period="2y")
            info = ticker.info
            
            if hist.empty:
                st.error("データ取得エラー")
            else:
                hist, cross_stat, cross_dtl, kumo_stat, kumo_dtl = calculate_technicals(hist)
                latest = hist.iloc[-1]
                price = latest['Close']
                change_pct = ((price - hist.iloc[-2]['Close']) / hist.iloc[-2]['Close']) * 100
                
                name = info.get('longName', code)
                # ニュース取得ロジック強化版を呼び出し
                news = get_news_deep_dive(code, name)
                
                st.header(f"{name} ({code})")
                
                c1, c2, c3 = st.columns(3)
                c1.metric("株価", f"{price:,.0f}円", f"{change_pct:+.2f}%")
                val_per = info.get('trailingPE')
                val_pbr = info.get('priceToBook')
                c2.metric("PER", f"{val_per:.1f}倍" if val_per else "-")
                c3.metric("PBR", f"{val_pbr:.2f}倍" if val_pbr else "-")
                
                st.markdown("##### 🩺 テクニカル判定")
                t1, t2 = st.columns(2)
                if "ゴールデン" in cross_stat: t1.success(f"**{cross_stat}**\n\n{cross_dtl}")
                elif "デッド" in cross_stat: t1.error(f"**{cross_stat}**\n\n{cross_dtl}")
                else: t1.info(f"**{cross_stat}**\n\n{cross_dtl}")

                if "上抜け" in kumo_stat: t2.success(f"**{kumo_stat}**\n\n{kumo_dtl}")
                elif "下抜け" in kumo_stat: t2.error(f"**{kumo_stat}**\n\n{kumo_dtl}")
                else: t2.info(f"**{kumo_stat}**\n\n{kumo_dtl}")

                st.subheader("📈 一目均衡表 & テクニカルチャート")
                display_hist = hist.tail(150)
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=display_hist.index, y=display_hist['SpanA'], line=dict(width=0), showlegend=False, hoverinfo='skip'))
                fig.add_trace(go.Scatter(x=display_hist.index, y=display_hist['SpanB'], line=dict(width=0), name='雲', fill='tonexty', fillcolor='rgba(0, 200, 200, 0.2)'))
                fig.add_trace(go.Candlestick(x=display_hist.index, open=display_hist['Open'], high=display_hist['High'], low=display_hist['Low'], close=display_hist['Close'], name="株価"))
                fig.add_trace(go.Scatter(x=display_hist.index, y=display_hist['SMA25'], line=dict(color='orange', width=1.5), name="25日線"))
                fig.add_trace(go.Scatter(x=display_hist.index, y=display_hist['SMA75'], line=dict(color='skyblue', width=1.5), name="75日線"))
                fig.update_layout(height=550, xaxis_rangeslider_visible=False, template="plotly_dark")
                st.plotly_chart(fig, use_container_width=True)

                st.divider()
                st.subheader("📝 プロ・アナリストレポート")
                
                price_seq = display_hist['Close'].tail(30).tolist()
                today = datetime.datetime.now().strftime("%Y年%m月%d日 %H:%M")

                prompt = f"""
                あなたは機関投資家のシニアアナリストです。
                現在日時は「{today}」です。**今日発表された最新ニュース**があれば、それを最重要視してください。
                
                【銘柄】{name} ({code})
                【現在値】{price:,.0f}円
                
                【収集したニュース（上にあるほど最新）】
                {news}

                【指示】
                以下の構成で分析してください。
                1. **最新決算・速報分析 (最重要)**:
                   ニュース欄に「決算」や「速報」があれば、その内容（増益・減益・修正など）を詳しく解説し、ポジティブかネガティブか断定してください。
                   もし今日発表のニュースが無ければ、「直近の大きな材料は見当たりません」と正直に書いてください。
                
                2. **テクニカル分析**:
                   {cross_stat}、{kumo_stat}という現状を踏まえ、いまエントリーすべきタイミングか解説。
                
                3. **売買シナリオ**:
                   短期的な上値目処、下値目処（損切りライン）を提示。
                """
                
                if model:
                    try:
                        resp = model.generate_content(prompt)
                        st.markdown(resp.text)
                    except Exception as e:
                        st.error(f"AIレポートエラー: {e}")

        except Exception as e:
            st.error(f"エラー: {e}")
