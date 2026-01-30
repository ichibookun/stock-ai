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

# =========================
# ページ設定
# =========================
st.set_page_config(page_title="Deep Dive Investing AI Pro", layout="wide")

# =========================
# JST
# =========================
JST = datetime.timezone(datetime.timedelta(hours=9))
def get_current_time_jst():
    return datetime.datetime.now(JST)

# =========================
# 履歴管理
# =========================
HISTORY_FILE = "stock_history.json"

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_history(data):
    try:
        with open(HISTORY_FILE, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except:
        pass

# =========================
# 初期化
# =========================
if "history" not in st.session_state:
    st.session_state["history"] = load_history()
if "target_code" not in st.session_state:
    st.session_state["target_code"] = None
if "screener_codes" not in st.session_state:
    st.session_state["screener_codes"] = "6758,7203,9984"

# =========================
# サイドバー
# =========================
st.sidebar.title("🦅 Deep Dive Pro")

mode = st.sidebar.radio(
    "モード選択",
    ["🏠 市場ダッシュボード", "💎 お宝発掘 (一括採点)", "🔍 個別詳細分析"]
)

if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
    st.sidebar.success("🔑 API認証済み")
else:
    api_key = st.sidebar.text_input("Gemini APIキー", type="password")

st.sidebar.info("Ver 15.0 : 決算精度強化版")

# =========================
# AIモデル
# =========================
def get_model(key):
    genai.configure(api_key=key)
    return genai.GenerativeModel("models/gemini-1.5-pro")

# =========================
# ニュース取得（決算特化）
# =========================
def get_news(code, name):
    ddgs = DDGS()
    news = []

    queries = [
        f"site:kabutan.jp {code} 決算",
        f"site:kabutan.jp {code} 決算短信",
        f"site:nikkei.com {code} 決算",
        f"{code} {name} 決算 第3四半期"
    ]

    for q in queries:
        try:
            results = ddgs.text(q, region="jp-jp", max_results=5)
            for r in results:
                title = r.get("title", "")
                body = r.get("body", "")
                if title and body:
                    news.append(f"【{title}】\n{body}")
        except:
            pass
        time.sleep(0.3)

    if not news:
        return "直近の決算ニュースは確認できませんでした。"

    return "\n\n".join(news[:10])

# =========================
# メイン画面
# =========================
st.title("🦅 Deep Dive Investing AI Pro")

# =========================
# 個別詳細分析
# =========================
if mode == "🔍 個別詳細分析":

    with st.form("search"):
        q = st.text_input("銘柄コード（4桁）", placeholder="例：6758")
        submitted = st.form_submit_button("分析開始")

    if submitted:
        st.session_state["target_code"] = q.strip()

    if st.session_state["target_code"]:

        if not api_key:
            st.error("Gemini APIキーが必要です")
            st.stop()

        code = st.session_state["target_code"]
        model = get_model(api_key)

        now_str = get_current_time_jst().strftime("%Y年%m月%d日 %H:%M")

        with st.spinner("分析中..."):
            tk = yf.Ticker(f"{code}.T")
            hist = tk.history(period="2y")
            info = tk.info

            if hist.empty:
                st.error("株価データが取得できません")
                st.stop()

            price = hist["Close"].iloc[-1]
            news_text = get_news(code, info.get("longName", code))

            st.header(f"{info.get('longName', code)}（{code}）")
            st.metric("株価", f"{price:,.0f} 円")

            # =========================
            # 決算AIプロンプト（超重要）
            # =========================
            prompt = f"""
あなたは日本株専門の機関投資家AIです。
推測・憶測・一般論は禁止です。

現在日時: {now_str}

対象銘柄:
{info.get('longName')}（{code}）

【取得したニュース】
{news_text}

【最重要ルール】
・決算数値が書かれていない場合は
  「数値は確認できません」と明記
・古い情報しか無い場合は
  「直近決算の速報は見当たりません」と記載
・勝手な評価は禁止

【STEP1｜決算抽出（表）】
| 項目 | 内容 |
| 決算期 | |
| 売上高 | |
| 営業利益 | |
| 経常利益 | |
| 進捗率 | |
| 修正 | |
| ガイダンス | |

【STEP2｜市場評価】
・強気 / 中立 / 弱気
・理由は最大3点

【STEP3｜売買判断】
・短期買い / 押し目待ち / 様子見 / 回避
"""

            try:
                resp = model.generate_content(prompt)
                st.markdown(resp.text)
            except Exception as e:
                st.error(f"AIエラー: {e}")
