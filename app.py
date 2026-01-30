import streamlit as st
import google.generativeai as genai
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import datetime
import json
import os
import re  # 【必須】これがないと動かないため確実に記述

# --- 設定 ---
st.set_page_config(page_title="Deep Dive Pro: Professional Edition", layout="wide")
JST = datetime.timezone(datetime.timedelta(hours=9))

# --- AIモデル固定 (Google推奨の安定版) ---
# 自動選択はリスクがあるため、確実に動作するモデルを指名
TARGET_MODEL_NAME = "models/gemini-1.5-flash"

# --- 履歴管理機能 ---
HISTORY_FILE = 'stock_history.json'

def load_history():
    """履歴ファイルを読み込む"""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f: return json.load(f)
        except: return {}
    return {}

def save_history(data):
    """履歴ファイルに保存する"""
    try:
        with open(HISTORY_FILE, 'w') as f: json.dump(data, f)
    except: pass

# セッション状態の初期化
if 'history' not in st.session_state: st.session_state['history'] = load_history()
if 'target_code' not in st.session_state: st.session_state['target_code'] = None

# --- サイドバー (設定・履歴) ---
st.sidebar.title("🦅 Deep Dive Pro")
st.sidebar.caption("Professional Edition v16.3")

# APIキー管理
if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
    st.sidebar.success("API Key: Loaded")
else:
    api_key = st.sidebar.text_input("API Key", type="password")

st.sidebar.markdown("---")
st.sidebar.subheader("Chart Settings")
show_ma = st.sidebar.checkbox("Moving Averages (25/75)", value=True)
show_bollinger = st.sidebar.checkbox("Bollinger Bands (±2σ)", value=True)
show_ichimoku = st.sidebar.checkbox("Ichimoku Cloud", value=True)

# 履歴ボタンの表示
if st.session_state['history']:
    st.sidebar.markdown("---")
    st.sidebar.subheader("History")
    # 日付が新しい順にソート
    sorted_hist = sorted(
        st.session_state['history'].items(), 
        key=lambda x: x[1].get('timestamp', ''), 
        reverse=True
    )
    for code, data in sorted_hist[:5]:
        # keyをユニークにして重複エラーを防ぐ
        if st.sidebar.button(f"{data.get('name', code)} ({code})", key=f"hist_{code}"):
            st.session_state['target_code'] = code
            st.rerun()
    
    if st.sidebar.button("Clear History"):
        if os.path.exists(HISTORY_FILE): os.remove(HISTORY_FILE)
        st.session_state['history'] = {}
        st.rerun()

# --- データ取得・計算関数 ---

def get_stock_data(code):
    """yfinanceから株価データを取得"""
    try:
        ticker = yf.Ticker(f"{code}.T")
        hist = ticker.history(period="2y")
        
        if hist.empty:
            return None, None, "データが見つかりません。コードが正しいか確認してください。"
        
        # データが極端に少ない場合のエラー回避
        if len(hist) < 25: 
            return None, None, "データ不足: 上場直後などのため分析に必要なデータ数が足りません。"
            
        return ticker, hist, None
    except Exception as e:
        return None, None, f"通信エラー: {str(e)}"

def calculate_indicators(hist):
    """テクニカル指標を一括計算"""
    df = hist.copy()
    
    # 1. 移動平均線 (SMA)
    df['SMA5'] = df['Close'].rolling(5).mean()
    df['SMA25'] = df['Close'].rolling(25).mean()
    df['SMA75'] = df['Close'].rolling(75).mean()
    
    # 2. ボリンジャーバンド (20日, ±2σ)
    df['SMA20'] = df['Close'].rolling(20).mean()
    df['STD20'] = df['Close'].rolling(20).std()
    df['Upper'] = df['SMA20'] + (df['STD20'] * 2)
    df['Lower'] = df['SMA20'] - (df['STD20'] * 2)
    
    # 3. RSI (14日)
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    # ゼロ除算を防ぐための小さな値
    loss = loss.replace(0, 1e-10)
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # 4. 一目均衡表 (雲のみ実装)
    # 転換線 = (過去9日間の高値 + 安値) / 2
    high9 = df['High'].rolling(9).max()
    low9 = df['Low'].rolling(9).min()
    df['Tenkan'] = (high9 + low9) / 2
    
    # 基準線 = (過去26日間の高値 + 安値) / 2
    high26 = df['High'].rolling(26).max()
    low26 = df['Low'].rolling(26).min()
    df['Kijun'] = (high26 + low26) / 2
    
    # 先行スパンA, B (26日先にずらして表示するものだが、データフレーム上では現在位置に計算結果を保持)
    # プロット時にX軸をずらすか、ここでは「現在の雲の位置」として過去の値を持ってくる
    # 判定用: 「今日の株価」vs「今日ある雲」を見るため、26日前の計算値を今日に持ってくる
    df['SpanA'] = ((df['Tenkan'] + df['Kijun']) / 2).shift(26)
    df['SpanB'] = ((df['High'].rolling(52).max() + df['Low'].rolling(52).min()) / 2).shift(26)
    
    return df

def get_ai_analysis(model, code, name, price, rsi, change_pct, fundamentals_text):
    """AIに分析プロンプトを投げる"""
    prompt = f"""
    あなたはプロの株式アナリストです。
    提供された「数値データ」と「チャート形状」のみに基づき、客観的な分析を行ってください。
    ※ニュース検索は行わないでください。事実データのみを重視します。
    
    【分析対象】
    ・銘柄: {name} ({code})
    ・現在値: {price:,.0f}円 (前日比 {change_pct:+.2f}%)
    ・テクニカル: RSI(14) = {rsi:.1f}
    
    【財務・指標データ】
    {fundamentals_text}
    
    【レポート作成指示】
    1. **財務健全性スコア**: 
       ROEやPERなどの指標から、企業の「稼ぐ力」と「株価の割安度」を評価してください。
    2. **テクニカル判断**: 
       RSIの値（{rsi:.1f}）や価格変動から、現在のトレンド（上昇・下落・保ち合い）と過熱感を判定してください。
    3. **投資スタンス**: 
       短期および中期の視点で、総合的な判断（強気・中立・弱気）を簡潔に結論づけてください。
    """
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"⚠️ AI分析エラー: {str(e)}\n(※API制限の可能性がありますが、上部のチャートと指標は正確です。そちらを参考にしてください。)"

# --- メイン画面レイアウト ---
st.title("🦅 Deep Dive Pro: Professional Edition")

# 検索フォーム
with st.form("search_form"):
    col1, col2 = st.columns([3, 1])
    query = col1.text_input("銘柄コード (例: 6758)", placeholder="4桁の数字を入力")
    submit = col2.form_submit_button("ANALYZE", type="primary")

# 検索実行時の処理
if submit:
    if not query:
        st.warning("コードを入力してください")
    # import re があるのでこのチェックは安全
    elif not re.fullmatch(r'\d{4}', query.strip()):
        st.error("4桁の半角数字のみ入力してください (例: 6702)")
    else:
        st.session_state['target_code'] = query.strip()
        st.rerun()

# --- 詳細分析ロジック ---
if st.session_state['target_code']:
    code = st.session_state['target_code']
    
    # データの取得・計算 (AIより先に実行して画面を表示させる)
    with st.spinner(f"Analyzing {code}..."):
        tk, hist, err = get_stock_data(code)
        
        if err:
            st.error(err)
            st.stop()
            
        # テクニカル計算
        df = calculate_indicators(hist)
        latest = df.iloc[-1]
        
        # 前日比の計算
        if len(df) >= 2:
            prev = df.iloc[-2]
            change = latest['Close'] - prev['Close']
            change_pct = (change / prev['Close']) * 100
        else:
            change = 0; change_pct = 0
            
        # 企業情報の取得 (失敗しても止まらないようにする)
        try:
            info = tk.info
            name = info.get('longName', f"Code {code}")
            sector = info.get('sector', 'Unknown')
        except:
            name = f"Code {code}"; sector = "-"; info = {}

        # 履歴の保存
        st.session_state['history'][code] = {
            'name': name,
            'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
            'price': latest['Close']
        }
        save_history(st.session_state['history'])

        # --- 結果表示 ---
        st.header(f"{name} ({code})")
        st.caption(f"Sector: {sector} | Last Update: {latest.name.strftime('%Y-%m-%d')}")
        
        # メトリクス表示
        col_m1, col_m2, col_m3, col_m4 = st.columns(4)
        col_m1.metric("Price", f"{latest['Close']:,.0f}", f"{change:+.0f} ({change_pct:+.2f}%)")
        col_m2.metric("Volume", f"{latest['Volume']:,}")
        
        rsi_val = latest['RSI']
        col_m3.metric("RSI (14)", f"{rsi_val:.1f}" if pd.notna(rsi_val) else "-")
        
        # 財務データの整形
        roe = info.get('returnOnEquity', None)
        per = info.get('forwardPE', info.get('trailingPE', None))
        pbr = info.get('priceToBook', None)
        
        fund_text = ""
        if roe: fund_text += f"- ROE: {roe*100:.1f}%\n"
        if per: fund_text += f"- PER: {per:.1f}倍\n"
        if pbr: fund_text += f"- PBR: {pbr:.1f}倍\n"
        
        col_m4.metric("PER / PBR", f"{per:.1f}x / {pbr:.2f}x" if (per and pbr) else "-")

        # --- チャート描画 (Plotly) ---
        st.subheader("📈 Technical Chart")
        
        # 直近150日分を表示
        chart_data = df.tail(150)
        
        fig = go.Figure()
        
        # 1. 一目均衡表の雲
        if show_ichimoku:
            fig.add_trace(go.Scatter(x=chart_data.index, y=chart_data['SpanA'], line=dict(width=0), showlegend=False, hoverinfo='skip'))
            fig.add_trace(go.Scatter(x=chart_data.index, y=chart_data['SpanB'], line=dict(width=0), fill='tonexty', fillcolor='rgba(0, 200, 200, 0.1)', name='Cloud'))
        
        # 2. ボリンジャーバンド
        if show_bollinger:
            fig.add_trace(go.Scatter(x=chart_data.index, y=chart_data['Upper'], line=dict(width=1, color='gray', dash='dot'), name='+2σ'))
            fig.add_trace(go.Scatter(x=chart_data.index, y=chart_data['Lower'], line=dict(width=1, color='gray', dash='dot'), fill='tonexty', fillcolor='rgba(128,128,128,0.05)', name='-2σ'))

        # 3. ローソク足
        fig.add_trace(go.Candlestick(
            x=chart_data.index,
            open=chart_data['Open'], high=chart_data['High'],
            low=chart_data['Low'], close=chart_data['Close'],
            name='Price'
        ))
        
        # 4. 移動平均線
        if show_ma:
            fig.add_trace(go.Scatter(x=chart_data.index, y=chart_data['SMA25'], line=dict(color='orange', width=1.5), name='SMA 25'))
            fig.add_trace(go.Scatter(x=chart_data.index, y=chart_data['SMA75'], line=dict(color='skyblue', width=1.5), name='SMA 75'))

        # レイアウト調整
        fig.update_layout(
            height=550,
            xaxis_rangeslider_visible=False,
            template="plotly_dark",
            margin=dict(l=10, r=10, t=30, b=10),
            legend=dict(orientation="h", y=1.02, x=0.5, xanchor="center")
        )
        st.plotly_chart(fig, use_container_width=True)

        # --- AIレポート (APIキーがある場合のみ実行) ---
        st.divider()
        st.subheader("🤖 AI Analyst Report")
        
        if api_key:
            # モデル接続
            try:
                genai.configure(api_key=api_key)
                model = genai.GenerativeModel(TARGET_MODEL_NAME)
                
                with st.spinner("AI is thinking..."):
                    # 安全な数値を渡す (NaN対策)
                    safe_rsi = rsi_val if pd.notna(rsi_val) else 50.0
                    
                    analysis = get_ai_analysis(
                        model, code, name, latest['Close'], safe_rsi, change_pct,
                        fund_text if fund_text else "（詳細な財務データなし）"
                    )
                    st.markdown(analysis)
                    
            except Exception as e:
                st.error(f"AI Connection Error: {str(e)}")
        else:
            st.info("💡 APIキーを入力すると、詳細なAI分析が表示されます。")
