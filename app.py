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
st.sidebar.info("Ver 5.2: Cloud Chart & Fixes")

# --- 関数群 ---

def get_model(api_key):
    # 安全にモデルを探すロジック（エラー回避）
    try:
        genai.configure(api_key=api_key)
        # 利用可能なモデル一覧を取得
        models = [m for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        # 1.5-flash を優先して探す
        model_name = "models/gemini-1.5-flash"
        if not any(m.name == model_name for m in models):
             # 見つからなければ gemini-pro や最新版を探す
             model_name = next((m.name for m in models if 'flash' in m.name), "models/gemini-pro")
        return genai.GenerativeModel(model_name)
    except:
        return None

def calculate_technicals(hist):
    # 移動平均
    hist['SMA5'] = hist['Close'].rolling(window=5).mean()
    hist['SMA25'] = hist['Close'].rolling(window=25).mean()
    hist['SMA75'] = hist['Close'].rolling(window=75).mean()
    
    # クロス判定（文字切れ対策のため短縮名も用意）
    latest = hist.iloc[-1]
    prev = hist.iloc[-2]
    
    cross_status = "特になし"
    cross_detail = "移動平均線のクロスは確認できません"
    
    if pd.notna(prev['SMA5']) and pd.notna(prev['SMA25']):
        if prev['SMA5'] < prev['SMA25'] and latest['SMA5'] > latest['SMA25']:
            cross_status = "ゴールデンクロス"
            cross_detail = "短期線(5日)が中期線(25日)を上抜けました（買いサイン）"
        elif prev['SMA25'] < prev['SMA75'] and latest['SMA25'] > latest['SMA75']:
            cross_status = "ゴールデンクロス"
            cross_detail = "中期線(25日)が長期線(75日)を上抜けました（強い買いサイン）"
        elif prev['SMA5'] > prev['SMA25'] and latest['SMA5'] < latest['SMA25']:
            cross_status = "デッドクロス"
            cross_detail = "短期線(5日)が中期線(25日)を下抜けました（売りサイン）"
        elif prev['SMA25'] > prev['SMA75'] and latest['SMA25'] < latest['SMA75']:
            cross_status = "デッドクロス"
            cross_detail = "中期線(25日)が長期線(75日)を下抜けました（強い売りサイン）"

    # 一目均衡表
    high9 = hist['High'].rolling(window=9).max()
    low9 = hist['Low'].rolling(window=9).min()
    hist['Tenkan'] = (high9 + low9) / 2

    high26 = hist['High'].rolling(window=26).max()
    low26 = hist['Low'].rolling(window=26).min()
    hist['Kijun'] = (high26 + low26) / 2

    hist['SpanA'] = ((hist['Tenkan'] + hist['Kijun']) / 2).shift(26)
    hist['SpanB'] = ((hist['High'].rolling(52).max() + hist['Low'].rolling(52).min()) / 2).shift(26)
    
    # 雲の状態判定
    kumo_status = "雲の中"
    kumo_detail = "株価は雲（抵抗帯）の中にあります"
    
    current_price = latest['Close']
    span_a = hist['SpanA'].iloc[-1]
    span_b = hist['SpanB'].iloc[-1]
    
    if pd.isna(span_a) or pd.isna(span_b):
        kumo_status = "計算中"
        kumo_detail = "データ不足のため判定できません"
    elif current_price > max(span_a, span_b):
        kumo_status = "雲上抜け"
        kumo_detail = "株価が雲を上に抜けました（強気相場入り）"
    elif current_price < min(span_a, span_b):
        kumo_status = "雲下抜け"
        kumo_detail = "株価が雲を下に抜けました（弱気相場入り）"

    return hist, cross_status, cross_detail, kumo_status, kumo_detail

def get_news_deep_dive(code, name):
    ddgs = DDGS()
    news_text = ""
    try:
        results = ddgs.text(f"{code} {name} 決算 コンセンサス 上方修正", region='jp-jp', timelimit='w', max_results=5)
        if results:
            news_text += "【決算・業績ニュース】\n"
            for r in results:
                news_text += f"- {r['title']} ({r['body'][:50]}...)\n"
    except: pass
    
    if not news_text:
        try:
            results = ddgs.text(f"{code} {name} 株価 材料", region='jp-jp', timelimit='w', max_results=3)
            if results:
                news_text += "\n【市場の材料】\n"
                for r in results:
                    news_text += f"- {r['title']}\n"
        except: pass
    
    return news_text if news_text else "特になし"

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
    
    with st.spinner(f"コード【{code}】のテクニカル＆決算を徹底調査中..."):
        try:
            # データ取得
            ticker = yf.Ticker(f"{code}.T")
            hist = ticker.history(period="2y")
            info = ticker.info
            
            if hist.empty:
                st.error("株価データが取得できませんでした。")
            else:
                # テクニカル計算
                hist, cross_stat, cross_dtl, kumo_stat, kumo_dtl = calculate_technicals(hist)
                
                latest = hist.iloc[-1]
                price = latest['Close']
                change_pct = ((price - hist.iloc[-2]['Close']) / hist.iloc[-2]['Close']) * 100
                
                name = info.get('longName', code)
                news = get_news_deep_dive(code, name)
                
                st.header(f"{name} ({code})")
                
                # --- 指標パネル（レイアウト修正） ---
                # 文字切れしないようにMetricではなくMarkdownやBoxを使用
                
                # 1行目: 株価とPER/PBR
                c1, c2, c3 = st.columns(3)
                c1.metric("株価", f"{price:,.0f}円", f"{change_pct:+.2f}%")
                
                val_per = info.get('trailingPE')
                val_pbr = info.get('priceToBook')
                c2.metric("PER (株価収益率)", f"{val_per:.1f}倍" if val_per else "-")
                c3.metric("PBR (株価純資産倍率)", f"{val_pbr:.2f}倍" if val_pbr else "-")
                
                # 2行目: テクニカル判定（大きなボックスで表示）
                st.markdown("##### 🩺 テクニカル判定")
                t1, t2 = st.columns(2)
                
                # クロス判定の色分け
                if "ゴールデン" in cross_stat:
                    t1.success(f"**{cross_stat}**\n\n{cross_dtl}")
                elif "デッド" in cross_stat:
                    t1.error(f"**{cross_stat}**\n\n{cross_dtl}")
                else:
                    t1.info(f"**{cross_stat}**\n\n{cross_dtl}")

                # 雲判定の色分け
                if "上抜け" in kumo_stat:
                    t2.success(f"**{kumo_stat}**\n\n{kumo_dtl}")
                elif "下抜け" in kumo_stat:
                    t2.error(f"**{kumo_stat}**\n\n{kumo_dtl}")
                else:
                    t2.info(f"**{kumo_stat}**\n\n{kumo_dtl}")

                # --- チャート（雲の描画追加） ---
                st.subheader("📈 一目均衡表 & テクニカルチャート")
                display_hist = hist.tail(150) # 少し長めに表示
                
                fig = go.Figure()
                
                # 雲 (先行スパンAとBの間を塗る)
                # Plotlyのバグ回避のため、AとBを表示してから塗りつぶし設定を行う
                fig.add_trace(go.Scatter(
                    x=display_hist.index, y=display_hist['SpanA'],
                    line=dict(width=0), name='先行スパンA', showlegend=False, hoverinfo='skip'
                ))
                fig.add_trace(go.Scatter(
                    x=display_hist.index, y=display_hist['SpanB'],
                    line=dict(width=0), name='雲 (抵抗帯)',
                    fill='tonexty', # ひとつ前のトレース(SpanA)との間を塗る
                    fillcolor='rgba(0, 200, 200, 0.2)' # 薄い青緑
                ))

                # ローソク足
                fig.add_trace(go.Candlestick(
                    x=display_hist.index,
                    open=display_hist['Open'], high=display_hist['High'],
                    low=display_hist['Low'], close=display_hist['Close'],
                    name="株価"
                ))
                
                # 移動平均線
                fig.add_trace(go.Scatter(x=display_hist.index, y=display_hist['SMA25'], line=dict(color='orange', width=1.5), name="25日線"))
                fig.add_trace(go.Scatter(x=display_hist.index, y=display_hist['SMA75'], line=dict(color='skyblue', width=1.5), name="75日線"))
                
                fig.update_layout(height=550, xaxis_rangeslider_visible=False, template="plotly_dark")
                st.plotly_chart(fig, use_container_width=True)

                # --- AIプロ分析レポート ---
                st.divider()
                st.subheader("📝 プロ・アナリストレポート")
                
                price_seq = display_hist['Close'].tail(30).tolist()
                price_seq_str = ",".join([str(int(x)) for x in price_seq])
                today = datetime.date.today().strftime("%Y年%m月%d日")

                prompt = f"""
                あなたは機関投資家のシニアアナリストです。今日は「{today}」です。
                
                【銘柄】{name} ({code})
                【現在値】{price:,.0f}円 (PER: {val_per if val_per else '-'}, PBR: {val_pbr if val_pbr else '-'})
                
                【テクニカル判定】
                1. 移動平均線: {cross_stat} ({cross_dtl})
                2. 一目均衡表: {kumo_stat} ({kumo_dtl})
                3. 直近30日の価格推移: [{price_seq_str}]
                
                【最新ニュース・決算情報】
                {news}

                【指示】
                以下の構成で辛口に分析してください。ですます調。
                1. **決算・ファンダメンタルズ評価**:
                   PER/PBRの水準感と、ニュース内容（決算）が株価に織り込まれているかを評価。
                2. **テクニカル詳細分析**:
                   移動平均線のクロスや、一目均衡表の「雲」との位置関係（上にあるか下にあるか）に必ず言及し、トレンドを診断。
                   チャートパターン（ダブルトップ等）の兆候があれば指摘。
                3. **売買戦略**:
                   「雲の上限である〇〇円を割ったら損切り」「25日線で反発したら買い」など具体的なシナリオを提示。
                """
                
                if model:
                    try:
                        resp = model.generate_content(prompt)
                        st.markdown(resp.text)
                    except Exception as e:
                        st.error(f"AIレポート生成中にエラーが発生しました: {e}")
                else:
                    st.error("AIモデルの接続に失敗しました。APIキーを確認してください。")

        except Exception as e:
            st.error(f"システムエラー: {e}")
