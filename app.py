import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np

st.set_page_config(page_title="Entry Score Scanner", layout="wide")
st.title("📊 勝率重視・エントリー判定スキャナー")

# ======================
# スコア計算ロジック
# ======================
def calculate_entry_score(df):
    score = 0
    latest = df.iloc[-1]

    # 移動平均
    df["SMA25"] = df["Close"].rolling(25).mean()
    df["SMA75"] = df["Close"].rolling(75).mean()

    # RSI
    delta = df["Close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = -delta.clip(upper=0).rolling(14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    rsi_latest = rsi.iloc[-1]

    # 出来高
    vol_mean = df["Volume"].rolling(20).mean().iloc[-1]

    # ======================
    # トレンド（40点）
    # ======================
    if latest["Close"] > df["SMA25"].iloc[-1]:
        score += 15
    if df["SMA25"].iloc[-1] > df["SMA75"].iloc[-1]:
        score += 15
    if latest["Close"] >= df["Close"].rolling(20).max().iloc[-1]:
        score += 10

    # ======================
    # モメンタム（30点）
    # ======================
    if 50 <= rsi_latest <= 70:
        score += 15
    if latest["Volume"] > vol_mean:
        score += 15

    # ======================
    # リスク調整（-10〜0点）
    # ======================
    if rsi_latest >= 80:
        score -= 10
    if latest["Close"] < df["SMA75"].iloc[-1]:
        score -= 10

    return max(score, 0), round(rsi_latest, 1)

# ======================
# UI
# ======================
codes = st.text_area(
    "📌 銘柄コード（カンマ区切り）",
    "6758,7203,9984"
)

run = st.button("🔍 スキャン開始")

if run:
    code_list = [c.strip() for c in codes.replace("、", ",").split(",") if c.strip()]
    results = []

    progress = st.progress(0.0)

    for i, code in enumerate(code_list):
        try:
            ticker = yf.Ticker(f"{code}.T")
            df = ticker.history(period="6mo")

            if len(df) < 80:
                continue

            score, rsi = calculate_entry_score(df)

            results.append({
                "コード": code,
                "銘柄名": ticker.info.get("longName", code),
                "スコア": score,
                "RSI": rsi,
                "株価": round(df["Close"].iloc[-1], 1),
                "判定": "🟢 エントリーOK" if score >= 80 else "🟡 監視" if score >= 65 else "🔴 見送り"
            })

        except:
            pass

        progress.progress((i + 1) / len(code_list))

    progress.empty()

    if results:
        df_result = pd.DataFrame(results).sort_values("スコア", ascending=False)
        st.subheader("🏆 エントリー候補ランキング")
        st.dataframe(df_result, use_container_width=True)
    else:
        st.warning("該当銘柄がありませんでした")
