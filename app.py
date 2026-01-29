import streamlit as st
import google.generativeai as genai
import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt
import japanize_matplotlib
import matplotlib as mpl
from duckduckgo_search import DDGS
import time
import re

# --- ページ設定 ---
st.set_page_config(page_title="Deep Dive Investing AI", layout="wide")
mpl.rcParams['font.family'] = 'IPAexGothic'

# --- サイドバー：設定 ---
st.sidebar.title("🛠 設定パネル")

# APIキーの自動読み込み設定
if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
    st.sidebar.success("APIキー認証済み")
else:
    api_key = st.sidebar.text_input("Gemini APIキー", type="password")
st.sidebar.markdown("---")
st.sidebar.markdown("Created by Deep Dive Investing Project")

st.title("🦅 Deep Dive Investing AI")
st.markdown("### プロ機関投資家レベルの分析を、ワンクリックで。")

# --- 関数群 ---
def get_model(api_key):
    try:
        genai.configure(api_key=api_key)
        all_models = list(genai.list_models())
        available_names = [m.name for m in all_models if 'generateContent' in m.supported_generation_methods]
        target_name = next((m for m in available_names if '1.5-flash' in m), available_names[0] if available_names else None)
        return genai.GenerativeModel(target_name) if target_name else None
    except:
        return None

def get_stock_news(keyword, limit=3):
    news_list = []
    try:
        results = DDGS().text(f"{keyword} 株価 日本 ニュース", region='jp-jp', timelimit='w', max_results=5)
        count = 0
        if results:
            for r in results:
                title = r.get('title', '')
                if re.search(r'[ぁ-んァ-ン]', title):
                    news_list.append(f"- {title[:35]}...")
                    count += 1
                    if count >= limit: break
    except:
        pass
    return "\n".join(news_list) if news_list else "(直近ニュースなし)"

def get_full_data(ticker, manual_name=None):
    code = f"{ticker}.T"
    try:
        stock = yf.Ticker(code)
        hist = stock.history(period="6mo")
        info = stock.info
        if hist.empty: return None

        display_name = f"{manual_name} ({ticker})" if manual_name else f"{info.get('longName', ticker)} ({ticker})"
        
        price = hist['Close'].iloc[-1]
        
        # 指標
        ma25 = hist['Close'].rolling(25).mean().iloc[-1]
        delta = hist['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean().iloc[-1]
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean().iloc[-1]
        rsi = 100 - (100 / (1 + gain / loss)) if loss != 0 else 50
        
        eps = info.get('forwardEps', info.get('trailingEps', 0))
        bps = info.get('bookValue', 0)
        per = price / eps if eps and eps > 0 else 0
        pbr = price / bps if bps and bps > 0 else 0
        div_rate = info.get('dividendRate')
        div_yield = (div_rate / price * 100) if div_rate else (info.get('dividendYield', 0) * 100)
        target_analyst = info.get('targetMeanPrice', 0)

        # スコア
        oneil_score = 0
        high_52 = info.get('fiftyTwoWeekHigh', price)
        dist_high = ((high_52 - price) / high_52 * 100) if high_52 else 0
        if dist_high < 15: oneil_score += 40
        elif dist_high < 25: oneil_score += 20
        vol_mean = hist['Volume'].rolling(20).mean().iloc[-1]
        if hist['Volume'].iloc[-1] > vol_mean * 1.2: oneil_score += 30
        if price > ma25: oneil_score += 30
        
        graham_score = 0
        if 0 < per < 15: graham_score += 30
        elif per < 20: graham_score += 15
        if 0 < pbr < 1.5: graham_score += 20
        if div_yield > 3.5: graham_score += 30
        elif div_yield > 2.5: graham_score += 15
        if rsi < 30: graham_score += 20
        elif rsi < 45: graham_score += 10
        
        return {
            "Code": ticker, "Name": display_name, "Price": price,
            "PER": per, "PBR": pbr, "Yield": div_yield, "RSI": rsi,
            "Target_Analyst": target_analyst, "Hist": hist['Close'],
            "Oneil_Score": oneil_score, "Graham_Score": graham_score,
            "Stop_Loss": price * 0.93, "Profit_Target": price * 1.20
        }
    except:
        return None

# --- メインUI ---
col1, col2 = st.columns(2)
with col1:
    main_code = st.text_input("銘柄コード (例: 6758)", "6758")
with col2:
    main_name_input = st.text_input("銘柄名 (任意: ソニー)", "")

rival_input = st.text_input("ライバル銘柄 (空欄でAI自動選定)", "")

if st.button("🚀 分析開始", type="primary"):
    if not api_key:
        st.error("左のサイドバーからAPIキーを入力してください！")
    else:
        model = get_model(api_key)
        if not model:
            st.error("APIキーが間違っているか、モデルに接続できません。")
        else:
            with st.spinner('AIが市場データをスキャン中...'):
                tickers = [main_code]
                if rival_input:
                    tickers += [t.strip() for t in rival_input.split(',')]
                else:
                    try:
                        resp = model.generate_content(f"日本株銘柄「{main_code}」の競合2社のコード(4桁)のみ出力。例: 8035, 6857")
                        found = re.findall(r'\d{4}', resp.text)
                        found = [c for c in found if c != main_code][:2]
                        tickers += found
                        if found: st.info(f"🤖 AIが選定したライバル: {', '.join(found)}")
                    except: pass
                
                data_list = []
                main_d = get_full_data(main_code, main_name_input)
                if main_d: data_list.append(main_d)
                for t in tickers[1:]:
                    d = get_full_data(t)
                    if d: data_list.append(d)
                    time.sleep(1)
                
                if not data_list:
                    st.error("データの取得に失敗しました。コードを確認してください。")
                else:
                    main_data = data_list[0]
                    
                    # --- ダッシュボード ---
                    m_col1, m_col2, m_col3, m_col4 = st.columns(4)
                    m_col1.metric("現在値", f"{main_data['Price']:.0f}円")
                    m_col2.metric("RSI", f"{main_data['RSI']:.1f}")
                    m_col3.metric("順張りスコア", f"{main_data['Oneil_Score']}点")
                    m_col4.metric("逆張りスコア", f"{main_data['Graham_Score']}点")
                    
                    c_col1, c_col2 = st.columns([2, 1])
                    with c_col1:
                        st.subheader("📈 パフォーマンス比較")
                        fig, ax = plt.subplots(figsize=(10, 5))
                        for d in data_list:
                            norm = (d['Hist'] / d['Hist'].iloc[0] - 1) * 100
                            ax.plot(norm.index, norm, label=d['Name'])
                        ax.legend()
                        ax.grid(True, alpha=0.3)
                        st.pyplot(fig)
                    
                    with c_col2:
                        st.subheader("📊 AIスコア詳細")
                        fig2, ax2 = plt.subplots(figsize=(5, 5))
                        scores = [main_data['Oneil_Score'], main_data['Graham_Score']]
                        labels = ['成長性', '割安性']
                        colors = ['#ff6b6b', '#4ecdc4']
                        bars = ax2.barh(labels, scores, color=colors)
                        ax2.set_xlim(0, 100)
                        ax2.grid(axis='x', linestyle='--')
                        st.pyplot(fig2)
                        
                        judge = "様子見"
                        if main_data['Oneil_Score'] >= 70: judge = "買い (成長)"
                        elif main_data['Graham_Score'] >= 70: judge = "買い (割安)"
                        st.info(f"判定: **{judge}**")
                        st.write(f"損切: {main_data['Stop_Loss']:.0f}円")

                    st.divider()
                    st.subheader("📝 AIストラテジスト・レポート")
                    
                    clean_name = main_data['Name'].split('(')[0]
                    news_text = get_stock_news(clean_name)
                    
                    prompt = f"""
                    あなたはプロの投資家です。{main_data['Name']}のレポートを作成してください。
                    【スコア】成長性:{main_data['Oneil_Score']}点, 割安性:{main_data['Graham_Score']}点
                    【価格】現在:{main_data['Price']:.0f}円, 損切:{main_data['Stop_Loss']:.0f}円
                    【ニュース】{news_text}
                    マークダウン形式で、結論、スコア分析、戦略を簡潔に。
                    """
                    
                    try:
                        resp = model.generate_content(prompt)
                        st.markdown(resp.text)
                    except:
                        st.error("AIレポート生成エラー")
