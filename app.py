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
mode = st.sidebar.selectbox("モード選択", ["🔍 個別詳細分析", "💎 お宝発掘 (スクリーニング)"])

if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
    st.sidebar.success("🔑 API認証済み")
else:
    api_key = st.sidebar.text_input("Gemini APIキー", type="password")

st.sidebar.markdown("---")
st.sidebar.info("Ver 11.0: Market Hunter")

# チャート設定 (個別分析用)
if mode == "🔍 個別詳細分析":
    st.sidebar.subheader("🎨 チャート設定")
    show_bollinger = st.sidebar.checkbox("ボリンジャーバンド", value=True)
    show_ichimoku = st.sidebar.checkbox("一目均衡表", value=True)

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
    if hist.empty: return 0, 0, 50
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
    
    # Bollinger
    hist['std20'] = hist['Close'].rolling(20).std()
    hist['SMA20'] = hist['Close'].rolling(20).mean()
    hist['Upper'] = hist['SMA20'] + (hist['std20'] * 2)
    hist['Lower'] = hist['SMA20'] - (hist['std20'] * 2)

    # Ichimoku
    h9 = hist['High'].rolling(9).max(); l9 = hist['Low'].rolling(9).min()
    tenkan = (h9 + l9) / 2
    h26 = hist['High'].rolling(26).max(); l26 = hist['Low'].rolling(26).min()
    kijun = (h26 + l26) / 2
    hist['SpanA'] = ((tenkan + kijun) / 2).shift(26)
    hist['SpanB'] = ((hist['High'].rolling(52).max() + hist['Low'].rolling(52).min()) / 2).shift(26)
    
    curr = hist.iloc[-1]
    prev = hist.iloc[-2]
    cross = "なし"
    if pd.notna(prev['SMA5']) and pd.notna(prev['SMA25']):
        if prev['SMA5'] < prev['SMA25'] and curr['SMA5'] > curr['SMA25']: cross = "Gクロス(短)"
        elif prev['SMA25'] < prev['SMA75'] and curr['SMA25'] > curr['SMA75']: cross = "Gクロス(長)"
        elif prev['SMA5'] > prev['SMA25'] and curr['SMA5'] < curr['SMA25']: cross = "Dクロス(短)"
        elif prev['SMA25'] > prev['SMA75'] and curr['SMA25'] < curr['SMA75']: cross = "Dクロス(長)"
    
    kumo = "雲中"
    sa, sb = hist['SpanA'].iloc[-1], hist['SpanB'].iloc[-1]
    cp = curr['Close']
    if pd.notna(sa) and pd.notna(sb):
        if cp > max(sa, sb): kumo = "雲上抜け"
        elif cp < min(sa, sb): kumo = "雲下抜け"
        
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

# --- メイン UI ---
st.title("🦅 Deep Dive Investing AI Pro (Ver 11.0)")

# ==========================================
# モード1: 💎 お宝発掘 (スクリーニング)
# ==========================================
if mode == "💎 お宝発掘 (スクリーニング)":
    st.header("💎 お宝銘柄ハンター")
    st.markdown("複数の銘柄を一括分析し、**スコア80点以上**の有望株を発掘します。")
    
    # プリセットボタン
    col_p1, col_p2, col_p3 = st.columns(3)
    preset_codes = ""
    if col_p1.button("🇯🇵 日経平均・人気10選"):
        preset_codes = "7203, 6758, 9984, 8035, 6861, 6098, 4063, 6902, 7974, 9432"
    if col_p2.button("💰 高配当・バリュー10選"):
        preset_codes = "8306, 8316, 2914, 8058, 8001, 8002, 9433, 9434, 4503, 5401"
    if col_p3.button("🚀 半導体・ハイテク10選"):
        preset_codes = "8035, 6146, 6920, 6723, 6857, 7729, 6963, 6526, 6702, 6752"

    with st.form("screener_form"):
        input_codes = st.text_area("銘柄コードを入力 (カンマ区切り)", value=preset_codes, placeholder="例: 6758, 7203, 9984")
        scan_btn = st.form_submit_button("🛡️ 一括スキャン開始", type="primary")
    
    if scan_btn and input_codes:
        codes = [c.strip() for c in input_codes.replace("、", ",").split(",") if c.strip()]
        results = []
        progress = st.progress(0)
        
        for i, c in enumerate(codes):
            try:
                # 4桁コードのみ処理
                if re.match(r'\d{4}', c):
                    tk = yf.Ticker(f"{c}.T")
                    hist = tk.history(period="1y")
                    if not hist.empty:
                        info = tk.info
                        o_score, g_score, rsi = calculate_scores(hist, info)
                        hist, cross, kumo = calculate_technicals(hist)
                        
                        name = info.get('longName', c)
                        price = hist['Close'].iloc[-1]
                        
                        # 判定
                        judge = ""
                        if o_score >= 80: judge += "🏆成長株 "
                        if g_score >= 80: judge += "💎割安株 "
                        
                        results.append({
                            "コード": c,
                            "銘柄名": name,
                            "株価": f"{price:,.0f}円",
                            "成長(オニール)": o_score,
                            "割安(グレアム)": g_score,
                            "RSI": round(rsi, 1),
                            "MA判定": cross,
                            "一目": kumo,
                            "有望度": judge
                        })
                time.sleep(0.5) # 負荷軽減
                progress.progress((i + 1) / len(codes))
            except: pass
            
        progress.empty()
        
        if results:
            df = pd.DataFrame(results)
            # スコア順にソート
            df = df.sort_values(by=["成長(オニール)", "割安(グレアム)"], ascending=False)
            
            # ハイライト表示 (80点以上)
            def highlight_high_score(s):
                is_high = s >= 80
                return ['background-color: #334433' if v else '' for v in is_high]

            st.success(f"{len(results)}銘柄の分析が完了しました！")
            st.dataframe(
                df.style.apply(highlight_high_score, subset=["成長(オニール)", "割安(グレアム)"]),
                use_container_width=True,
                height=400
            )
            st.info("※成長スコアまたは割安スコアが **80点以上** のセルは緑色で強調されます。")
        else:
            st.error("データが取得できませんでした。コードを確認してください。")


# ==========================================
# モード2: 🔍 個別詳細分析 (従来の画面)
# ==========================================
elif mode == "🔍 個別詳細分析":
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

    # 個別分析実行
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
                
                # 企業情報
                st.sidebar.subheader("🏢 企業情報")
                sector = safe_get(info, ['sector'], '不明')
                st.sidebar.write(f"**業種**: {sector}")
                website = safe_get(info, ['website'])
                if website: st.sidebar.link_button("🌐 公式サイトを見る", website)

                # 履歴保存
                st.session_state['history'][code] = {
                    'name': name, 'timestamp': now_str, 'price': price, 'oneil': oneil, 'graham': graham
                }
                save_history(st.session_state['history'])
                
                st.header(f"{name} ({code})")
                
                tab1, tab2, tab3 = st.tabs(["📝 分析レポート", "📈 詳細チャート", "📊 業績・財務"])
                
                with tab1:
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("株価", f"{price:,.0f}円", f"{chg:+.2f}%")
                    c2.metric("RSI", f"{rsi:.1f}")
                    c3.metric("成長スコア", f"{oneil}点")
                    c4.metric("割安スコア", f"{graham}点")
                    
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

                with tab2:
                    st.info(f"テクニカル判定: {cross} / {kumo}")
                    d_hist = hist.tail(150)
                    fig = go.Figure()
                    if show_ichimoku:
                        fig.add_trace(go.Scatter(x=d_hist.index, y=d_hist['SpanA'], line=dict(width=0), showlegend=False, hoverinfo='skip'))
                        fig.add_trace(go.Scatter(x=d_hist.index, y=d_hist['SpanB'], line=dict(width=0), name='雲', fill='tonexty', fillcolor='rgba(0,200,200,0.2)'))
                    if show_bollinger:
                        fig.add_trace(go.Scatter(x=d_hist.index, y=d_hist['Upper'], line=dict(width=1, color='gray', dash='dot'), name='+2σ'))
                        fig.add_trace(go.Scatter(x=d_hist.index, y=d_hist['Lower'], line=dict(width=1, color='gray', dash='dot'), name='-2σ', fill='tonexty', fillcolor='rgba(128,128,128,0.1)'))

                    fig.add_trace(go.Candlestick(x=d_hist.index, open=d_hist['Open'], high=d_hist['High'], low=d_hist['Low'], close=d_hist['Close'], name='株価'))
                    fig.add_trace(go.Scatter(x=d_hist.index, y=d_hist['SMA25'], line=dict(color='orange'), name='25MA'))
                    fig.add_trace(go.Scatter(x=d_hist.index, y=d_hist['SMA75'], line=dict(color='skyblue'), name='75MA'))
                    fig.update_layout(height=550, xaxis_rangeslider_visible=False, template="plotly_dark")
                    st.plotly_chart(fig, use_container_width=True)

                with tab3:
                    st.subheader("💰 業績データ")
                    try:
                        fin = tk.financials
                        if fin is not None and not fin.empty:
                            fin = fin.T.sort_index()
                            fin_recent = fin.tail(4)
                            fig_fin = go.Figure()
                            if 'Total Revenue' in fin.columns:
                                fig_fin.add_trace(go.Bar(x=fin_recent.index, y=fin_recent['Total Revenue'], name='売上高', marker_color='#4ecdc4'))
                            elif 'Revenue' in fin.columns:
                                 fig_fin.add_trace(go.Bar(x=fin_recent.index, y=fin_recent['Revenue'], name='売上高', marker_color='#4ecdc4'))
                            if 'Net Income' in fin.columns:
                                fig_fin.add_trace(go.Bar(x=fin_recent.index, y=fin_recent['Net Income'], name='純利益', marker_color='#ff6b6b'))
                            fig_fin.update_layout(title="売上高と純利益 (年次)", barmode='group', template="plotly_dark", height=400)
                            st.plotly_chart(fig_fin, use_container_width=True)
                            
                            csv = hist.to_csv().encode('utf-8')
                            st.download_button(label="📥 株価CSVダウンロード", data=csv, file_name=f"{code}_data.csv", mime='text/csv')
                        else:
                            st.info("財務データなし")
                    except Exception as e: st.error(f"Financial Error: {e}")

            except Exception as e: st.error(f"データ取得エラー: {e}")
