# ==============================
# 新高値ブレイク判定ツール
# Python 簡易完成版
# ==============================

from flask import Flask, request, jsonify

app = Flask(__name__)

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
# スコア計算（厳しめ）
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
# 理由（日本語・端的）
# ------------------------------
def make_reason(stock, action):
    if action == "🟢 即買い":
        return "52週高値を出来高を伴って更新しており、初動のブレイクと判断されます。"
    if action == "🟡 押し目待ち":
        return "高値圏を維持していますが過熱感はなく、押し目形成待ちが有効です。"
    return "条件が揃っておらず、優位性が低いため見送りが妥当です。"

# ------------------------------
# メインAPI
# ------------------------------
@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        data = request.get_json()
        input_text = data.get("symbols", "")

        symbols = [s.strip() for s in input_text.split("\n") if s.strip()]

        if not symbols:
            return jsonify({"results": [], "message": "銘柄を入力してください。"})

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
                "symbol": stock["symbol"],
                "name": stock["name"],
                "score": score,
                "action": action,
                "reason": make_reason(stock, action)
            })

        return jsonify({
            "count": len(results),
            "results": results
        })

    except Exception as e:
        return jsonify({"error": "分析中にエラーが発生しました。"}), 500

# ------------------------------
# 起動
# ------------------------------
if __name__ == "__main__":
    app.run(debug=True)
