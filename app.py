import streamlit as st
import google.generativeai as genai
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import datetime
import json
import os

# --- 設定 ---
st.set_page_config(page_title="Deep Dive Pro: Professional Edition", layout="wide")
JST = datetime.timezone(datetime.timedelta(hours=9))

# --- 安定版モデルの固定指定 ---
# 自動探索は廃止し、確実に動作するモデルを指名
TARGET_MODEL_NAME = "models/gemini-1.5-flash"

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

if 'history' not in st.session_state: st.session_state['history'] = load_history()
if 'target_code' not in st.session_state: st.session_state['target_code'] = None

# --- サイドバー ---
st.sidebar.title("🦅 Deep Dive Pro")
st.sidebar.caption("Professional Edition v16.0")

if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
    st.sidebar.success("Locked & Loaded")
else:
    api_key = st.sidebar.text_input("API Key", type="password")

# チャート設定
st.sidebar.markdown("---")
st.sidebar.subheader("Chart Settings")
show_ma = st.sidebar.checkbox("Moving Averages (25/75)", value=True)
show_bollinger = st.sidebar.checkbox("Bollinger Bands (±2σ)", value=True)
show_ichimoku = st.sidebar.checkbox("Ichimoku Cloud", value=True)

# 履歴
if st.session_state['history']:
    st.sidebar.markdown("---")
    st.sidebar.subheader("History")
    # 日付降順ソート
    sorted_hist = sorted(st.session_state['history'].items(), key=lambda x: x[1].get('timestamp',''), reverse=True)
    for code, data in sorted_hist[:5]:
        if st.sidebar.button(f"{data.get('name', code)} ({code})", key=f"hist_{code}"):
            st.session_state['target_code'] = code
            st.rerun()
    if st.sidebar.button("Clear History"):
        if os.path.exists(HISTORY_FILE): os.remove(HISTORY_FILE)
        st.session_state['history'] = {}
        st.rerun()

# --- 関数群 ---
def get_stock_data(code):
    """yfinanceからデータを取得し、エラーハンドリングを行う"""
    try:
        ticker = yf.Ticker(f"{code}.T")
        # 過去2年分のデータを取得
        hist = ticker.history(period="2y")
        if hist.empty:
            return None, None, "No Data"
        return ticker, hist, None
    except Exception as e:
        return None, None, str(e)

def calculate_indicators(hist):
    """テクニカル指標を計算する"""
    df = hist.copy()
    # MA
    df['SMA5'] = df['Close'].rolling(5).mean()
    df['SMA25'] = df['Close'].rolling(25).mean()
    df['SMA75'] = df['Close'].rolling(75).mean()
    
    # Bollinger
    df['SMA20'] = df['Close'].rolling(20).mean()
    df['STD20'] = df['Close'].rolling(20).std()
    df['Upper'] = df['SMA20'] + (df['STD20'] * 2)
    df['Lower'] = df['SMA20'] - (df['STD20'] * 2)
    
    # RSI (14)
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # Ichimoku
    high9 = df['High'].rolling(9).max()
    low9 = df['Low'].rolling(9).min()
    df['Tenkan'] = (high9 + low9) / 2
    
    high26 = df['High'].rolling(26).max()
    low26 = df['Low'].rolling(26).min()
    df['Kijun'] = (high26 + low26) / 2
    
    df['SpanA'] = ((df['Tenkan'] + df['Kijun']) / 2).shift(26)
    df['SpanB'] = ((df['High'].rolling(52).max() + df['Low'].rolling(52).min()) / 2).shift(26)
    
    return df

def get_ai_analysis(model, code, name, price, rsi, change_pct, fundamentals_text):
    """AIに分析を依頼する"""
    prompt = f"""
    あなたはプロの株式アナリストです。以下のデータに基づき、この銘柄の現状を客観的に評価してください。
    
    【対象】
    銘柄: {name} ({code})
    現在値: {price:,.0f}円 (前日比 {change_pct:+.2f}%)
    RSI(14日): {rsi:.1f}
    
    【財務・指標データ】
    {fundamentals_text}
    
    【指示】
    1. **財務健全性**: 提供された指標（ROE、PERなど）から、割安か割高か、経営効率はどうかを判定してください。
    2. **テクニカル**: RSIの値やトレンドから、現在の過熱感（買われすぎ/売られすぎ）を評価してください。
    3. **総合判断**: 短期・中期の投資スタンス（強気・中立・弱気）を結論づけてください。
    """
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI分析エラー: {e} (API制限の可能性がありますが、チャート判断を優先してください)"

# --- メイン画面 ---
st.title("🦅 Deep Dive Pro: Professional Edition")

with st.form("search_form"):
    col1, col2 = st.columns([3, 1])
    query = col1.text_input("銘柄コード (例: 6758)", placeholder="4桁の数字を入力")
    submit = col2.form_submit_button("ANALYZE", type="primary")

if submit:
    if not query:
        st.error("コードを入力してください")
    elif not re.fullmatch(r'\d{4}', query.strip()):
        st.error("4桁の半角数字のみ入力してください (例: 6758)")
    else:
        st.session_state['target_code'] = query.strip()
        st.rerun()

# --- 分析実行部 ---
if st.session_state['target_code']:
    code = st.session_state['target_code']
    
    # 1. まずデータを取得 (AIより先に！)
    with st.spinner(f"Fetching Data for {code}..."):
        tk, hist, err = get_stock_data(code)
        
        if err:
            st.error(f"データ取得失敗: {err}")
            st.stop()
            
        # データ加工
        df = calculate_indicators(hist)
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        # 基本情報
        try:
            info = tk.info
            name = info.get('longName', f"Code {code}")
            sector = info.get('sector', 'Unknown')
        except:
            name = f"Code {code}"
            sector = "-"
            info = {}

        # 履歴保存
        st.session_state['history'][code] = {
            'name': name,
            'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
            'price': latest['Close']
        }
        save_history(st.session_state['history'])

        # --- UI構築 ---
        
        # ヘッダー情報
        st.header(f"{name} ({code})")
        st.caption(f"Sector: {sector} | Date: {latest.name.strftime('%Y-%m-%d')}")
        
        col_m1, col_m2, col_m3, col_m4 = st.columns(4)
        price = latest['Close']
        change = price - prev['Close']
        change_pct = (change / prev['Close']) * 100
        
        col_m1.metric("株価", f"{price:,.0f}円", f"{change:+.0f} ({change_pct:+.2f}%)")
        col_m2.metric("Volume", f"{latest['Volume']:,}")
        col_m3.metric("RSI (14)", f"{latest['RSI']:.1f}")
        
        # 財務指標 (取れる場合のみ表示)
        roe = info.get('returnOnEquity', None)
        per = info.get('forwardPE', info.get('trailingPE', None))
        pbr = info.get('priceToBook', None)
        
        fund_text = ""
        if roe: fund_text += f"- ROE: {roe*100:.1f}%\n"
        if per: fund_text += f"- PER: {per:.1f}倍\n"
        if pbr: fund_text += f"- PBR: {pbr:.1f}倍\n"
        
        col_m4.metric("PER / PBR", f"{per:.1f}x / {pbr:.2f}x" if per and pbr else "-")

        # --- チャート (最重要・エラーなし) ---
        st.subheader("📈 Technical Chart")
        
        # 表示期間 (直近150日)
        chart_data = df.tail(150)
        
        fig = go.Figure()
        
        # 一目均衡表
        if show_ichimoku:
            fig.add_trace(go.Scatter(x=chart_data.index, y=chart_data['SpanA'], line=dict(width=0), hoverinfo='skip', showlegend=False))
            fig.add_trace(go.Scatter(x=chart_data.index, y=chart_data['SpanB'], line=dict(width=0), fill='tonexty', fillcolor='rgba(0, 250, 250, 0.1)', name='Cloud'))
        
        # ボリンジャーバンド
        if show_bollinger:
            fig.add_trace(go.Scatter(x=chart_data.index, y=chart_data['Upper'], line=dict(width=1, color='gray', dash='dot'), name='+2σ'))
            fig.add_trace(go.Scatter(x=chart_data.index, y=chart_data['Lower'], line=dict(width=1, color='gray', dash='dot'), fill='tonexty', fillcolor='rgba(128,128,128,0.05)', name='-2σ'))

        # ローソク足
        fig.add_trace(go.Candlestick(
            x=chart_data.index,
            open=chart_data['Open'], high=chart_data['High'],
            low=chart_data['Low'], close=chart_data['Close'],
            name='Price'
        ))
        
        # 移動平均線
        if show_ma:
            fig.add_trace(go.Scatter(x=chart_data.index, y=chart_data['SMA25'], line=dict(color='orange', width=1.5), name='SMA 25'))
            fig.add_trace(go.Scatter(x=chart_data.index, y=chart_data['SMA75'], line=dict(color='skyblue', width=1.5), name='SMA 75'))

        fig.update_layout(
            height=550,
            xaxis_rangeslider_visible=False,
            template="plotly_dark",
            margin=dict(l=10, r=10, t=30, b=10)
        )
        st.plotly_chart(fig, use_container_width=True)

        # --- AI分析 (ここは失敗してもチャートは残る) ---
        st.divider()
        st.subheader("🤖 AI Strategist Report")
        
        if api_key:
            # モデル接続 (固定)
            try:
                genai.configure(api_key=api_key)
                model = genai.GenerativeModel(TARGET_MODEL_NAME)
                
                with st.spinner("AI is analyzing fundamentals & technicals..."):
                    # ニュース検索は廃止。事実データのみを渡す
                    analysis = get_ai_analysis(
                        model, code, name, price, latest['RSI'], change_pct,
                        fund_text if fund_text else "財務データ取得不可"
                    )
                    st.markdown(analysis)
                    st.caption(f"Analysis by {TARGET_MODEL_NAME}")
                    
            except Exception as e:
                st.error(f"AI Connection Error: {e}")
                st.info("※チャートと指標は正常です。AI分析のみスキップされました。")
        else:
            st.warning("APIキーを入力すると、詳細なAIレポートが表示されます。")
