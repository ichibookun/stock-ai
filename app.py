# app.py
import streamlit as st
import google.generativeai as genai
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from duckduckgo_search import DDGS
import requests
from bs4 import BeautifulSoup
import time
import re
import datetime
import json
import os
import io

# =========================
# 設定
# =========================
st.set_page_config(page_title="Deep Dive Investing AI Pro", layout="wide")
JST = datetime.timezone(datetime.timedelta(hours=9))
def get_current_time_jst(): return datetime.datetime.now(JST)

HISTORY_FILE = "stock_history.json"
MAX_HISTORY = 5

# =========================
# 履歴管理
# =========================
def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_history(data):
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except:
        pass

# セッション初期化
if 'history' not in st.session_state: st.session_state['history'] = load_history()
if 'target_code' not in st.session_state: st.session_state['target_code'] = None
if 'screener_codes' not in st.session_state: st.session_state['screener_codes'] = "6758, 7203, 9984"
if 'selected_model_name' not in st.session_state: st.session_state['selected_model_name'] = None

# =========================
# サイドバー UI
# =========================
st.sidebar.title("🦅 Deep Dive Pro")
mode = st.sidebar.radio("モード選択", ["🏠 市場ダッシュボード", "💎 お宝発掘 (一括採点)", "🔍 個別詳細分析"], index=2)

# APIキー
if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
    st.sidebar.success("🔑 API認証済み")
else:
    api_key = st.sidebar.text_input("Gemini APIキー", type="password")

st.sidebar.markdown("---")
st.sidebar.info("Ver 15.2: 全機能復活 + 決算精度強化")

# =========================
# ユーティリティ関数
# =========================
def safe_get(info, keys, default=None):
    for k in keys:
        if info.get(k) is not None:
            return info.get(k)
    return default

# =========================
# スコアリング（O'Neil と Graham）
# =========================
def calculate_scores(hist, info):
    if hist.empty:
        return 0, 0, 50
    latest = hist.iloc[-1]
    price = latest['Close']
    # O'Neil-like
    oneil = 0
    high52 = safe_get(info, ['fiftyTwoWeekHigh'])
    if high52:
        dist = (high52 - price) / high52 * 100
        if dist < 10: oneil += 40
        elif dist < 20: oneil += 20
    else:
        oneil += 20
    vol_mean = hist['Volume'].rolling(20).mean().iloc[-1] if len(hist)>=20 else hist['Volume'].mean()
    if latest['Volume'] > vol_mean: oneil += 30
    sma25 = hist['Close'].rolling(25).mean().iloc[-1] if len(hist)>=25 else hist['Close'].mean()
    if price > sma25: oneil += 30

    # Graham-like
    graham = 0
    eps = safe_get(info, ['forwardEps', 'trailingEps'])
    if eps and eps > 0:
        per = price / eps if eps != 0 else 9999
        if 0 < per < 15: graham += 30
        elif 0 < per < 25: graham += 15
    else:
        graham += 15
    bps = safe_get(info, ['bookValue'])
    if bps and bps > 0:
        pbr = price / bps
        if 0 < pbr < 1.0: graham += 20
        elif 0 < pbr < 1.5: graham += 10
    else:
        graham += 10
    div = safe_get(info, ['dividendRate', 'dividendYield'])
    if div:
        try:
            yld = div * 100 if div < 1 else (div / price * 100)
            if yld > 3.5: graham += 30
            elif yld > 2.5: graham += 15
        except:
            pass

    # RSI approximate
    delta = hist['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean().iloc[-1] if len(hist)>=14 else (delta.where(delta > 0, 0).mean())
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean().iloc[-1] if len(hist)>=14 else (-delta.where(delta < 0, 0).mean())
    try:
        rsi = 100 - (100 / (1 + gain / loss)) if loss != 0 else 50
    except:
        rsi = 50
    if rsi < 30: graham += 20
    elif rsi < 40: graham += 10

    return int(oneil), int(graham), round(float(rsi),1)

# =========================
# テクニカル算出
# =========================
def calculate_technicals(hist):
    h = hist.copy()
    h['SMA5'] = h['Close'].rolling(5).mean()
    h['SMA25'] = h['Close'].rolling(25).mean()
    h['SMA75'] = h['Close'].rolling(75).mean()
    h['std20'] = h['Close'].rolling(20).std()
    h['SMA20'] = h['Close'].rolling(20).mean()
    h['Upper'] = h['SMA20'] + (h['std20'] * 2)
    h['Lower'] = h['SMA20'] - (h['std20'] * 2)
    # Ichimoku
    h9 = h['High'].rolling(9).max(); l9 = h['Low'].rolling(9).min()
    tenkan = (h9 + l9) / 2
    h26 = h['High'].rolling(26).max(); l26 = h['Low'].rolling(26).min()
    kijun = (h26 + l26) / 2
    h['SpanA'] = ((tenkan + kijun) / 2).shift(26)
    h['SpanB'] = ((h['High'].rolling(52).max() + h['Low'].rolling(52).min()) / 2).shift(26)

    # クロス判定
    cross = "なし"
    try:
        curr = h.iloc[-1]; prev = h.iloc[-2]
        if pd.notna(prev['SMA5']) and pd.notna(prev['SMA25']):
            if prev['SMA5'] < prev['SMA25'] and curr['SMA5'] > curr['SMA25']:
                cross = "Gクロス(短)"
            elif prev['SMA25'] < prev['SMA75'] and curr['SMA25'] > curr['SMA75']:
                cross = "Gクロス(長)"
            elif prev['SMA5'] > prev['SMA25'] and curr['SMA5'] < curr['SMA25']:
                cross = "Dクロス(短)"
            elif prev['SMA25'] > prev['SMA75'] and curr['SMA25'] < curr['SMA75']:
                cross = "Dクロス(長)"
    except:
        pass

    # 雲判定
    kumo = "雲中"
    try:
        sa, sb = h['SpanA'].iloc[-1], h['SpanB'].iloc[-1]
        cp = h['Close'].iloc[-1]
        if pd.notna(sa) and pd.notna(sb):
            if cp > max(sa, sb): kumo = "雲上抜け"
            elif cp < min(sa, sb): kumo = "雲下抜け"
    except:
        pass

    return h, cross, kumo

# =========================
# TDnet 速報取得（公式） — 最優先で取得する
# =========================
def get_tdnet_ir(code, days=3):
    """
    TDnetの速報一覧ページをスクレイピングして、該当コードの直近IRを取得する。
    戻り: list of dict {date, title, url}
    """
    results = []
    base = "https://release.tdnet.info/inbs/I_list_001_"
    today = get_current_time_jst()
    headers = {"User-Agent":"Mozilla/5.0"}

    for page in range(1, 5):  # 直近数ページをチェック
        url = f"{base}{page}.html"
        try:
            r = requests.get(url, timeout=8, headers=headers)
            r.encoding = "utf-8"
            soup = BeautifulSoup(r.text, "html.parser")
            rows = soup.select("table tr")
            for row in rows:
                cols = row.find_all("td")
                if len(cols) < 4: 
                    continue
                date_str = cols[0].text.strip()
                # 企業コードは4列目または3列目に来る場合がある
                try:
                    company_col = cols[2].text.strip()
                except:
                    company_col = ""
                # コードが含まれるかチェック（数列4桁を含む）
                found_code = re.search(r'\d{4}', company_col)
                if not found_code:
                    # タイトルやリンクにコードがあるか確認
                    title_text = cols[3].text.strip() if len(cols)>3 else ""
                    if str(code) not in title_text and (not found_code):
                        continue
                # 列データ取得
                date = None
                try:
                    date = datetime.datetime.strptime(date_str, "%Y/%m/%d").replace(tzinfo=JST)
                except:
                    # skip malformed
                    continue
                # 日付範囲
                if (today - date).days > days:
                    continue
                title_cell = cols[3]
                a = title_cell.find("a")
                title = title_cell.text.strip()
                href = a["href"] if a and a.get("href") else ""
                # 絶対URL化
                if href and not href.startswith("http"):
                    href = "https://release.tdnet.info" + href
                results.append({"date": date_str, "title": title, "url": href})
        except Exception:
            pass
        time.sleep(0.2)
    # 一意化
    uniq = []
    seen = set()
    for r in results:
        key = (r['date'], r['title'])
        if key not in seen:
            seen.add(key)
            uniq.append(r)
    return uniq

# =========================
# 決算PDF等：補助的にDuckDuckGoでPDFを探す
# =========================
def find_pdfs_by_search(code, name):
    ddgs = DDGS()
    items = []
    queries = [f"site:tdnet-pdf.kabutan.jp {code} 決算", f"{code} 決算PDF", f"{name} 決算 PDF"]
    for q in queries:
        try:
            res = ddgs.text(q, region="jp-jp", max_results=6)
            for r in res:
                title = r.get("title","")
                href = r.get("href","")
                items.append({"title": title, "url": href})
        except:
            pass
        time.sleep(0.2)
    return items

# =========================
# 統合ニュース取得（TDnet優先 → Kabutan/DDG 補完）
# =========================
def get_latest_ir(code, name):
    blocks = []
    # TDnet
    td = get_tdnet_ir(code, days=3)
    if td:
        for r in td:
            blocks.append(f"【TDnet公式IR】\n日付: {r['date']}\nタイトル: {r['title']}\nURL: {r['url']}")
    # PDF検索
    pdfs = find_pdfs_by_search(code, name)
    for p in pdfs:
        blocks.append(f"【PDF候補】\nタイトル: {p.get('title')}\nURL: {p.get('url')}")
    # 補足：Kabutan / Nikkei via DDG（TDnet無ければ）
    if not blocks:
        ddgs = DDGS()
        try:
            q = f"site:kabutan.jp {code} 決算"
            res = ddgs.text(q, region="jp-jp", max_results=10)
            for r in res:
                blocks.append(f"【参考】\nタイトル: {r.get('title')}\nURL: {r.get('href')}\n{r.get('body','')[:500]}")
        except:
            pass
    if not blocks:
        return "直近の公式IR・決算速報は確認できませんでした。", []
    return "\n\n".join(blocks[:12]), blocks

# =========================
# モデル自動選択（堅牢）
# =========================
def get_model_and_name(api_key):
    try:
        genai.configure(api_key=api_key)
    except Exception as e:
        return None, f"API設定エラー: {e}"
    # 既に選択済みなら再利用
    cached = st.session_state.get('selected_model_name')
    if cached:
        try:
            return genai.GenerativeModel(cached), cached
        except:
            st.session_state['selected_model_name'] = None
    try:
        models = genai.list_models()
    except Exception as e:
        return None, f"モデル一覧取得エラー: {e}"
    candidate = []
    for m in models:
        name = getattr(m, "name", None)
        methods = getattr(m, "supported_generation_methods", []) or []
        if name and "generateContent" in methods:
            candidate.append(name)
    if not candidate:
        return None, "generateContent 対応モデルが見つかりません。"
    # 優先順
    for pref in ["1.5-flash", "1.5-pro", "1.0"]:
        for c in candidate:
            if pref in c:
                try:
                    st.session_state['selected_model_name'] = c
                    return genai.GenerativeModel(c), c
                except:
                    continue
    # 最初の候補
    try:
        st.session_state['selected_model_name'] = candidate[0]
        return genai.GenerativeModel(candidate[0]), candidate[0]
    except Exception as e:
        return None, f"モデル作成エラー: {e}"

# =========================
# CSVダウンロードヘルパー
# =========================
def df_to_csv_bytes(df):
    buf = io.BytesIO()
    df.to_csv(buf, index=True)
    buf.seek(0)
    return buf.getvalue()

# =========================
# UI: 市場ダッシュボード
# =========================
st.title("🦅 Deep Dive Investing AI Pro")

if mode == "🏠 市場ダッシュボード":
    st.header("📈 Market Dashboard")
    c1, c2, c3 = st.columns(3)
    with st.spinner("Loading..."):
        try:
            nk = yf.Ticker("^N225").history(period="2d")
            if not nk.empty: c1.metric("日経平均", f"{nk['Close'].iloc[-1]:,.0f}", f"{nk['Close'].iloc[-1]-nk['Close'].iloc[-2]:+.0f}")
            uj = yf.Ticker("JPY=X").history(period="2d")
            if not uj.empty: c2.metric("ドル円", f"{uj['Close'].iloc[-1]:.2f}", f"{uj['Close'].iloc[-1]-uj['Close'].iloc[-2]:+.2f}")
            c3.info(get_current_time_jst().strftime('%Y/%m/%d %H:%M'))
        except Exception as e:
            st.error("Market Data Error: " + str(e))
    st.divider()
    st.subheader("🏆 監視銘柄ランキング")
    history = st.session_state.get('history', {})
    if history:
        r = sorted([{'c':c,'n':d['name'],'p':d['price'],'s':d.get('oneil',0)+d.get('graham',0)} for c,d in history.items()], key=lambda x:x['s'], reverse=True)
        for i in r[:3]:
            with st.container():
                ca, cb, cc = st.columns([2,3,1])
                ca.markdown(f"**{i['n']}** ({i['c']})")
                cb.metric("Score", f"{i['s']}", f"¥{i['p']:,.0f}")
                if cc.button("Go", key=f"g_{i['c']}"):
                    st.session_state['target_code'] = i['c']; st.experimental_rerun()
    else:
        st.info("履歴なし")

# =========================
# UI: お宝発掘（簡易）
# =========================
elif mode == "💎 お宝発掘 (一括採点)":
    st.header("💎 お宝銘柄ハンター")
    c1, c2, c3 = st.columns(3)
    if c1.button("🇯🇵 日経"): st.session_state['screener_codes'] = "7203, 6758, 9984, 8035, 6861"
    if c2.button("💰 高配当"): st.session_state['screener_codes'] = "8306, 8316, 2914, 8058"
    if c3.button("🚀 半導体"): st.session_state['screener_codes'] = "8035, 6146, 6920, 6723"
    with st.form("sc"):
        txt = st.text_area("コード (カンマ区切り)", key="screener_codes")
        btn = st.form_submit_button("🛡️ スキャン")
    if btn:
        cds = [x.strip() for x in txt.replace("、",",").split(",") if x.strip()]
        res = []; prog = st.progress(0); st_txt = st.empty()
        for i, c in enumerate(cds):
            st_txt.text(f"Scanning {c}...")
            try:
                if re.match(r'\d{4}$', c):
                    tk = yf.Ticker(f"{c}.T"); h = tk.history(period="1y")
                    if not h.empty:
                        oneil, graham, rsi = calculate_scores(h, tk.info)
                        res.append({"コード":c, "銘柄":tk.info.get('longName',c), "株価":f"{h['Close'].iloc[-1]:,.0f}", "成長":oneil, "割安":graham, "RSI":rsi})
                time.sleep(0.3); prog.progress((i+1)/len(cds))
            except Exception:
                pass
        st_txt.empty(); prog.empty()
        if res:
            df = pd.DataFrame(res).sort_values(by=["成長","割安"], ascending=False)
            st.dataframe(df, use_container_width=True)

# =========================
# UI: 個別詳細分析（すべて復活 + AI決算ハンター）
# =========================
elif mode == "🔍 個別詳細分析":
    # 検索フォーム (Enterで送れる)
    with st.form("find"):
        q = st.text_input("銘柄コード/社名", placeholder="例: 6758 または トヨタ", key="search_input")
        sub = st.form_submit_button("🔍 分析開始", type="primary")
    if sub:
        # コードか名前か判定
        tgt = None
        if re.fullmatch(r'\d{4}', q.strip()):
            tgt = q.strip()
        else:
            # 名前→コード変換：yfinance検索 or LLM補助（簡易）
            try:
                # yfinanceで検索（簡易）
                # ※ yfinance に社名→コードの確実なサーチはないため、LLMを使う選択肢も残す
                # ここでは LLM を呼ばず、単純に数字が含まれなければ入力は社名扱いで停止（ユーザーにコードを入力してもらう）
                st.info("社名を入力した場合は、4桁コードで再入力してください（自動検索は未実装）。")
            except:
                pass
        if tgt:
            st.session_state['target_code'] = tgt

    # 最近履歴表示（サイドバー）
    history = st.session_state.get('history', {})
    if history:
        st.sidebar.subheader("🕒 最近の履歴")
        sorted_codes = sorted(history.keys(), key=lambda x: history[x].get('timestamp',''), reverse=True)
        for c in sorted_codes[:MAX_HISTORY]:
            d = history[c]
            # 前回との差分（price）
            prev_price = d.get('prev_price')
            change = ""
            if prev_price:
                try:
                    change = f" ({int(d['price'])-int(prev_price):+,.0f})"
                except:
                    change = ""
            if st.sidebar.button(f"{d['name']} ({c}) {change}", key=f"side_{c}"):
                st.session_state['target_code'] = c
                st.experimental_rerun()
        if st.sidebar.button("履歴クリア"):
            if os.path.exists(HISTORY_FILE): os.remove(HISTORY_FILE)
            st.session_state['history'] = {}
            st.experimental_rerun()

    # 分析本体
    if st.session_state.get('target_code'):
        code = st.session_state['target_code']
        # モデル選択
        if not api_key:
            st.error("Gemini APIキーが必要です")
            st.stop()
        model_obj, model_name_or_msg = get_model_and_name(api_key)
        if not model_obj:
            st.error(f"モデル選択エラー: {model_name_or_msg}")
            st.stop()

        now = get_current_time_jst()
        now_str = now.strftime("%Y年%m月%d日 %H:%M")

        with st.spinner(f"分析中... {code}"):
            try:
                tk = yf.Ticker(f"{code}.T")
                hist = tk.history(period="2y")
                info = tk.info
                if hist.empty:
                    st.error("株価データが取得できません")
                    st.stop()

                # 技術指標・スコア
                hist_t, cross, kumo = calculate_technicals(hist)
                oneil, graham, rsi = calculate_scores(hist, info)
                price = hist['Close'].iloc[-1]

                # 履歴更新（最新5件）
                hist_store = st.session_state.get('history', {})
                prev_price = hist_store.get(code, {}).get('price')
                hist_store[code] = {
                    "name": info.get('longName', code),
                    "price": int(price),
                    "timestamp": now.isoformat(),
                    "oneil": oneil,
                    "graham": graham,
                    "rsi": rsi,
                    "prev_price": prev_price
                }
                # 保持数制限
                if len(hist_store) > MAX_HISTORY:
                    # 古いものを削除
                    keys_sorted = sorted(hist_store.keys(), key=lambda x: hist_store[x]['timestamp'])
                    for k in keys_sorted[:-MAX_HISTORY]:
                        hist_store.pop(k, None)
                st.session_state['history'] = hist_store
                save_history(hist_store)

                # 取得ニュース（TDnet優先）
                news_text, raw_news = get_latest_ir(code, info.get('longName', code))

                # ヘッダー情報
                st.header(f"{info.get('longName', code)} ({code})")
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("株価", f"{price:,.0f} 円", f"{(price-hist['Close'].iloc[-2])/hist['Close'].iloc[-2]*100:+.2f}%")
                c2.metric("RSI", f"{rsi}")
                c3.metric("成長スコア", f"{oneil}")
                c4.metric("割安スコア", f"{graham}")

                # Tabs: レポート/チャート/業績/ダウンロード
                t1, t2, t3, t4 = st.tabs(["📝 レポート & ニュース", "📈 チャート", "📊 業績（PL）", "⬇ CSVダウンロード"])

                # --- Tab1: レポート & ニュース ---
                with t1:
                    st.subheader("📰 決算・重要ニュース（TDnet優先）")
                    with st.expander("🔍 取得したニュース一覧 (クリックで確認)", expanded=False):
                        if raw_news:
                            for n in raw_news: st.text(n)
                        else:
                            st.warning("ニュースが見つかりませんでした")

                    # AI分析プロンプト（改良版）
                    prompt = f"""
あなたは日本株専門の機関投資家AIです。
推測・憶測・一般論は禁止します。

現在日時: {now_str}

対象銘柄:
- 名称: {info.get('longName')}
- コード: {code}

【取得したニュース（TDnet優先、最大12件）】
{news_text}

【最重要ルール】
・決算数値（売上・営業利益・経常利益・純利益・進捗率）が明示されていない場合は
  「数値は確認できません」と必ず明記すること
・古い情報しか無い場合は「直近決算の速報は見当たりません」と記載すること
・URLと日付がある情報はそのまま根拠として扱うこと
・勝手な評価・創作は禁止

【STEP1｜決算抽出（表）】
| 項目 | 内容 |
| 決算期 | |
| 売上高 | |
| 営業利益 | |
| 経常利益 | |
| 純利益 | |
| 進捗率 | |
| 修正 | |
| ガイダンス | |

【STEP2｜市場評価】
・強気 / 中立 / 弱気（1つを選ぶ）
・理由は最大3点（必ずニュース/数値を根拠として記載）

【STEP3｜売買判断】
・短期買い / 押し目待ち / 様子見 / 回避（1つを選ぶ）
・理由（テクニカル: {cross} 、一目: {kumo} を必ず考慮）

【出力形式】
### 📊 決算サマリー
（表）

### 📉 市場の評価
（箇条書き）

### 🧭 売買戦略
（結論）
"""
                    try:
                        resp = model_obj.generate_content(prompt)
                        output_text = getattr(resp, "text", None) or str(resp)
                        st.markdown(output_text)
                    except Exception as e:
                        st.error(f"AI呼び出しエラー: {e}")
                        try:
                            models = genai.list_models()
                            available = [getattr(m, "name", "<unknown>") for m in models][:20]
                            st.info("利用可能なモデル例: " + ", ".join(available))
                        except:
                            pass

                # --- Tab2: チャート ---
                with t2:
                    st.info(f"Technical: {cross} / {kumo}")
                    d = hist_t.tail(150)
                    fig = go.Figure()
                    # Ichimoku雲（塗りつぶし）
                    try:
                        fig.add_trace(go.Scatter(x=d.index, y=d['SpanB'], line=dict(width=0), name='雲B', showlegend=False))
                        fig.add_trace(go.Scatter(x=d.index, y=d['SpanA'], line=dict(width=0), name='雲A', fill='tonexty', fillcolor='rgba(0,200,200,0.15)', showlegend=False))
                    except:
                        pass
                    # Bollinger
                    try:
                        fig.add_trace(go.Scatter(x=d.index, y=d['Upper'], line=dict(width=1, dash='dot'), name='+2σ'))
                        fig.add_trace(go.Scatter(x=d.index, y=d['Lower'], line=dict(width=1, dash='dot'), name='-2σ'))
                    except:
                        pass
                    fig.add_trace(go.Candlestick(x=d.index, open=d['Open'], high=d['High'], low=d['Low'], close=d['Close'], name='株価'))
                    fig.add_trace(go.Scatter(x=d.index, y=d['SMA25'], line=dict(width=1), name='25MA'))
                    fig.add_trace(go.Scatter(x=d.index, y=d['SMA75'], line=dict(width=1), name='75MA'))
                    fig.update_layout(height=600, xaxis_rangeslider_visible=True, template="plotly_dark")
                    st.plotly_chart(fig, use_container_width=True)

                # --- Tab3: 業績（yfinanceのfinancialsを利用） ---
                with t3:
                    st.subheader("業績（過去・四半期）")
                    # yfinance の financials (年次) と quarterly_financials (四半期)
                    try:
                        fin = tk.financials  # 年次（DataFrame）
                        qfin = tk.quarterly_financials
                        if fin is not None and not fin.empty:
                            # transpose -> 年次の列を可視化
                            fin_disp = fin.fillna(0).T
                            st.dataframe(fin_disp, use_container_width=True)
                            # 売上・純利益の推移プロット（年次）
                            if 'Total Revenue' in fin.index or 'Revenue' in fin.index:
                                rev_key = 'Total Revenue' if 'Total Revenue' in fin.index else ('Revenue' if 'Revenue' in fin.index else None)
                            else:
                                rev_key = None
                            # 純利益キー候補
                            profit_key = None
                            for k in ['Net Income', 'Net Income Common Stockholders', 'Net Income Applicable To Common Shares']:
                                if k in fin.index:
                                    profit_key = k
                                    break
                            # プロット
                            plot_df = pd.DataFrame()
                            if rev_key:
                                plot_df['Revenue'] = fin.loc[rev_key].astype(float)
                            if profit_key:
                                plot_df['NetIncome'] = fin.loc[profit_key].astype(float)
                            if not plot_df.empty:
                                plot_df = plot_df.T  # 年を横軸に
                                st.line_chart(plot_df)
                        else:
                            st.info("財務情報が取得できません（yfinanceに依存）。")
                    except Exception as e:
                        st.error("業績取得エラー: " + str(e))

                # --- Tab4: CSVダウンロード ---
                with t4:
                    st.subheader("CSVダウンロード")
                    df = hist.copy()
                    if not df.empty:
                        csv_bytes = df_to_csv_bytes(df)
                        st.download_button("株価CSVをダウンロード", data=csv_bytes, file_name=f"{code}_history.csv", mime="text/csv")
                    else:
                        st.info("ダウンロードするデータがありません。")

            except Exception as e:
                st.error(f"エラー: {e}")
