# ==============================
# 新高値ブレイク分析ツール
# Streamlit 最終完成版
# ==============================

import streamlit as st

# ------------------------------
# 仮データ取得（後でAPIに差し替え）
# ------------------------------
def fetch_stock_data(symbol):
    return {
        "symbol": symbol,
        "name": f"銘柄{symbol}" if symbol.isdigit() else symbol,
        "close": 1020,
        "high52": 1050,
        "volume": 200000,
        "avg_volume": 100000,
        "ma25": 980,
        "ma75": 900,
        "eps_growth": 35,
        "sales_growth": 25,
        "roe": 18
    }

# ------------------------------
# 判定ロジック
# ------------------------------
def is_52week_high(stock):
    return stock["close"] >= stock["high52"] * 0.97

def volume_ratio(stock):
    return stock["volume"] / stock["avg_volume"]

def is_overextended(stock):
    return (stock["high52"] - stock["close"]) / stock["high52"] < 0.03

# ------------------------------
# スコア計算
# ------------------------------
def calc_score(stock):
    score = 0
    if is_52week_high(stock):
        score += 30
    if volume_ratio(stock) >= 1.5:
        score += 20
    if stock["ma25"] > stock["ma75"]:
        score += 10
    if stock["eps_growth"] >= 20:
        score += 20
    if stock["sales_growth"] >= 15:
        score += 20
    return score

# ------------------------------
# 行動判定
# ------------------------------
def judge_action(stock):
    vol = volume_ratio(stock)
    if vol >= 1.8 and is_overextended(stock):
        return "🟢 即買い"
    if 1.2 <= vol < 1.8:
        return "🟡 押し目待ち"
    return "⚪ 見送り"

# ------------------------------
# 理由文
# ------------------------------
def make_reason(stock, action):
    if action == "🟢 即買い":
        return "52週高値を出来高を伴って更新しており、初動ブレイクと判断されます。"
    if action == "🟡 押し目待ち":
        return "高値圏を維持しており、押し目形成後のエントリーが有効です。"
    return "条件が揃っておらず、見送りが妥当です。"

# ==============================
# UI
# ==============================

st.set_page_config(page_title="新高値ブレイク分析", layout="wide")

st.title("📈 新高値ブレイク分析ツール（勝率重視）")

st.write("株探などから **52週高値銘柄を改行区切りで貼り付けてください**")

input_text = st.text_area(
    "銘柄入力",
    height=200,
    placeholder="7203\n9984\nレーザーテック"
)

if st.button("分析する"):
    symbols = [s.strip() for s in input_text.split("\n") if s.strip()]

    if not symbols:
        st.warning("銘柄を入力してください")
    else:
        results = []

        for symbol in symbols:
            stock = fetch_stock_data(symbol)

            # 必須条件
            if not is_52week_high(stock):
                continue
            if stock["ma25"] <= stock["ma75"]:
                continue
            if not is_overextended(stock):
                continue

            score = calc_score(stock)
            if score < 85:
                continue

            action = judge_action(stock)

            results.append({
                "銘柄": stock["name"],
                "スコア": score,
                "判断": action,
                "理由": make_reason(stock, action)
            })

        if results:
            st.success(f"{len(results)} 銘柄が抽出されました")
            st.dataframe(results, use_container_width=True)
        else:
            st.info("条件を満たす銘柄はありませんでした")
