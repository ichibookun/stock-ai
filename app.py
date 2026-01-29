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

# --- セッション状態の初期化 ---
if 'candidates' not in st.session_state:
    st.session_state['candidates'] = None
if 'target_code' not in st.session_state:
    st.session_state['target_code'] = None

# --- サイドバー：設定 ---
st.sidebar.title("🛠 設定パネル")

# SecretsからAPIキーを読み込む (なければ入力欄を表示)
if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
    st.sidebar.success("🔑 APIキー認証済み")
else:
    api_key = st.sidebar.text_input("Gemini APIキー", type="password")
    st.sidebar.warning("APIキーが設定されていません")

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

def search_stock_candidates(model, query):
    prompt = f"""
    ユーザーは日本株の銘柄を探しています。検索ワード:「{query}」
    このワードに関連する可能性が高い日本株銘柄を最大3つ挙げてください。
    出力形式は必ず「コード 銘柄名」のリストのみにしてください。
    例:
    7203 トヨタ自動車
    7267 ホンダ
    """
    try:
        resp = model.generate_content(prompt)
        lines = resp.text.strip().split('\n')
        candidates = []
        for line in lines:
            # 4桁の数字を含む行を抽出
            match = re.search(r'(\d{4})\s*(.*)', line)
            if match:
                candidates.append(f"{match.group(1)} {match.group(2)}")
        return candidates[:3]
    except:
        return []

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
st.markdown("##### 銘柄コード、または企業名を入力してください")
input_query = st.text_input("検索", placeholder="例: 7203 または トヨタ", value="")

# 検索ボタン
if st.button("🔍 検索・分析開始", type="primary"):
    st.session_state['candidates'] = None # リセット
    st.session_state['target_code'] = None

    if not api_key:
        st.error("APIキーが設定されていません。")
    elif not input_query:
        st.warning("何か入力してください。")
    else:
        # 数字4桁ならそのままコードとして扱う
        if re.fullmatch(r'\d{4}', input_query.strip()):
            st.session_state['target_code'] = input_query.strip()
        else:
            # 名前ならAIで検索
            with st.spinner(f"AIが「{input_query}」の銘柄を探しています..."):
                model = get_model(api_key)
                if model:
                    candidates = search_stock_candidates(model, input_query)
                    if candidates:
                        st.session_state['candidates'] = candidates
                    else:
                        st.error("銘柄が見つかりませんでした。別の言葉で試してください。")

# 候補選択UI
selected_candidate_code = None
if st.session_state['candidates']:
    st.success("以下の候補が見つかりました。分析する銘柄を選んでください。")
    selection = st.radio("候補一覧", st.session_state['candidates'])
    
    if st.button("🚀 この銘柄で分析する"):
        code_part = selection.split()[0]
        st.session_state['target_code'] = code_part
        st.session_state['candidates'] = None # 選択したら候補を消す
        st.rerun() # 再読み込みして分析へ

# 分析実行
if st.session_state['target_code']:
    main_code = st.session_state['target_code']
    
    # 競合設定（ここはシンプル化）
    model = get_model(api_key)
    if not model:
        st.error("モデル接続エラー")
    else:
        with st.spinner(f'コード【{main_code}】を徹底分析中...'):
            # 競合自動選定
            tickers = [main_code]
            try:
                resp = model.generate_content(f"日本株コード「{main_code}」の強力なライバル2社のコード(4桁)のみ出力。")
                found = re.findall(r'\d{4}', resp.text)
                found = [c for c in found if c != main_code][:2]
                tickers += found
            except: pass
            
            data_list = []
            for t in tickers:
                d = get_full_data(t)
                if d: data_list.append(d)
                time.sleep(1)
            
            if not data_list:
                st.error(f"データ取得失敗: {main_code}")
            else:
                main_data = data_list[0]
                
                # --- 結果表示 ---
                st.subheader(f"📊 {main_data['Name']}")
                
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
                    st.subheader("🎯 投資判断")
                    fig2, ax2 = plt.subplots(figsize=(5, 5))
                    scores = [main_data['Oneil_Score'], main_data['Graham_Score']]
                    labels = ['成長性', '割安性']
                    colors = ['#ff6b6b', '#4ecdc4']
                    ax2.barh(labels, scores, color=colors)
                    ax2.set_xlim(0, 100)
                    ax2.grid(axis='x', linestyle='--')
                    st.pyplot(fig2)
                    
                    judge = "様子見"
                    if main_data['Oneil_Score'] >= 70: judge = "買い (成長)"
                    elif main_data['Graham_Score'] >= 70: judge = "買い (割安)"
                    st.markdown(f"### 判定: **{judge}**")
                    st.write(f"🛑 損切ライン: **{main_data['Stop_Loss']:.0f}円**")

                st.divider()
                st.subheader("📝 AIアナリスト・レポート")
                
                clean_name = main_data['Name'].split('(')[0]
                news_text = get_stock_news(clean_name)
                
                prompt = f"""
                あなたはプロの機関投資家です。{main_data['Name']}の詳細レポートを書いてください。
                【データ】
                価格:{main_data['Price']:.0f}円, PER:{main_data['PER']:.1f}, PBR:{main_data['PBR']:.2f}, 配当利回り:{main_data['Yield']:.2f}%
                スコア: 成長性{main_data['Oneil_Score']}点, 割安性{main_data['Graham_Score']}点
                ニュース: {news_text}
                
                【構成】
                1. **結論**: 買うべきか、待つべきか（ズバリ一言で）
                2. **良い点・懸念点**: ファンダメンタルズとテクニカルの両面から
                3. **シナリオ**: どうなったら買いか、どこで逃げるか
                """
                
                try:
                    resp = model.generate_content(prompt)
                    st.markdown(resp.text)
                except:
                    st.error("AIレポート生成エラー")
