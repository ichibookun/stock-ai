import streamlit as st
import yfinance as yf
import pandas as pd
import time
from urllib.parse import quote_plus

# ==============================
# 設定 (必ず最初に書く)
# ==============================
st.set_page_config(page_title="新高値ブレイク分析（CANSLIM）", layout="wide")

# ==============================
# 新高値ブレイク分析ツール（押し目・Kabutanリンク・CANSLIM追加版）
# ==============================

# -----------------------------
# データ取得（yfinance） & キャッシュ
# -----------------------------
@st.cache_data(ttl=60 * 60)
def fetch_stock_data(symbol):
    """ symbol: '6758' など4桁コードを推奨。戻り値は dict または None """
    code = str(symbol).strip()
    ticker = f"{code}.T"
    try:
        tk = yf.Ticker(ticker)
        # 過去2年分のアクションなしデータを取得
        hist = tk.history(period="2y", actions=False)
        if hist is None or hist.empty or len(hist) < 60:
            return None

        # 基本値
        close = float(hist["Close"].iloc[-1])
        volume = int(hist["Volume"].iloc[-1])
        window = min(252, len(hist))
        high52_all = hist["High"].iloc[-window:].max()

        # 当日を除いた直前52週高値（重要）
        prev_high52 = hist["High"].iloc[-(window + 1):-1].max()

        ma25 = float(hist["Close"].rolling(25).mean().iloc[-1])
        ma75 = float(hist["Close"].rolling(75).mean().iloc[-1])
        avg_volume = float(hist["Volume"].rolling(20).mean().iloc[-1])

        # 直近ブレイク（過去5営業日以内に高値超えがあったか）
        recent_window = min(5, len(hist)-1)
        recent_closes = hist["Close"].iloc[-(recent_window+1):-1]  # 過去5日の終値（今日除く）
        
        # 直近で高値を超えた日があるか
        broke_indices = recent_closes[recent_closes > prev_high52].index if recent_window > 0 else []
        broke_recent = len(broke_indices) > 0
        
        break_days_ago = None
        max_close_since_break = None
        pullback_pct = 0.0
        
        if broke_recent:
            # 最後にブレイクした日
            last_break_idx = broke_indices[-1]
            # 何日前か
            break_days_ago = (hist.index[-1] - last_break_idx).days
            # ブレイク日以降の最高値（昨日の引けまで）
            start_pos = hist.index.get_loc(last_break_idx)
            max_close_since_break = hist["Close"].iloc[start_pos:-1].max()
            
            if max_close_since_break and max_close_since_break > 0:
                pullback_pct = (max_close_since_break - close) / max_close_since_break

        # 当日のブレイク判定
        broke_today = close > prev_high52

        # 短期モメンタム (3ヶ月 ~63営業日)
        period_3m = min(63, len(hist)-1)
        if period_3m >= 1:
            price_3m_ago = hist["Close"].iloc[-(period_3m+1)]
            momentum_3m = (close - price_3m_ago) / price_3m_ago
        else:
            momentum_3m = 0.0

        # info情報取得 (エラー回避付き)
        try:
            info = tk.info or {}
            earnings_q_growth = info.get("earningsQuarterlyGrowth")
            trailing_eps = info.get("trailingEps")
            forward_eps = info.get("forwardEps")
            name = info.get("longName") or info.get("shortName") or code
        except Exception:
            earnings_q_growth = None
            trailing_eps = None
            forward_eps = None
            name = code

        # API負荷軽減のための微小ウェイト
        time.sleep(0.05)

        return {
            "symbol": code,
            "name": name,
            "close": close,
            "volume": volume,
            "avg_volume": avg_volume,
            "high52": float(high52_all),
            "prev_high52": float(prev_high52),
            "ma25": ma25,
            "ma75": ma75,
            "broke_today": broke_today,
            "broke_recent": broke_recent,
            "break_days_ago": break_days_ago,
            "max_close_since_break": float(max_close_since_break) if max_close_since_break is not None else None,
            "pullback_pct": float(pullback_pct),
            "momentum_3m": float(momentum_3m),
            "earnings_q_growth": earnings_q_growth,
            "trailing_eps": trailing_eps,
            "forward_eps": forward_eps,
        }
    except Exception:
        return None

# -----------------------------
# 判定ヘルパー
# -----------------------------
def is_true_52week_break(stock):
    """今日の終値が直前52週高値を上回っている（真のブレイク）"""
    try:
        return stock["close"] > stock["prev_high52"]
    except:
        return False

def volume_ratio(stock):
    try:
        if stock["avg_volume"] and stock["avg_volume"] > 0:
            return stock["volume"] / stock["avg_volume"]
    except:
        pass
    return 0.0

# -----------------------------
# CANSLIM（簡易）スコア計算
# -----------------------------
def calc_canslim(stock):
    c = a = n = s = l = 0

    # C: 四半期利益成長率 (earningsQuarterlyGrowth)
    eg = stock.get("earnings_q_growth")
    if eg is not None:
        if eg >= 0.5: c = 30
        elif eg >= 0.25: c = 20
        elif eg >= 0.15: c = 10

    # A: 年間EPS成長率 (予測EPSと実績EPSの差分で簡易判定)
    te = stock.get("trailing_eps")
    fe = stock.get("forward_eps")
    if te and fe:
        try:
            growth = (fe - te) / abs(te) if te != 0 else None
            if growth is not None:
                if growth >= 0.5: a = 25
                elif growth >= 0.2: a = 15
                elif growth >= 0.1: a = 8
        except:
            pass

    # N: 新高値 (52週高値更新)
    if is_true_52week_break(stock):
        n = 20

    # S: 需給 (出来高急増)
    vr = volume_ratio(stock)
    if vr >= 2.0: s = 15
    elif vr >= 1.5: s = 10

    # L: 主導株 (3ヶ月モメンタム)
    m3 = stock.get("momentum_3m", 0.0)
    if m3 >= 0.30: l = 20
    elif m3 >= 0.15: l = 10
    elif m3 >= 0.08: l = 5

    total = c + a + n + s + l
    breakdown = {"C": c, "A": a, "N": n, "S": s, "L": l}
    return total, breakdown

# -----------------------------
# メインスコア
# -----------------------------
def calc_score(stock):
    score = 0

    if is_true_52week_break(stock):
        score += 40

    vr = volume_ratio(stock)
    if vr >= 2.0: score += 30
    elif vr >= 1.5: score += 20

    if stock.get("ma25") and stock.get("ma75") and stock["ma25"] > stock["ma75"]:
        score += 20

    # 短期モメンタム加点
    if stock.get("momentum_3m") and stock["momentum_3m"] >= 0.15:
        score += 10

    return score

# -----------------------------
# 押し目判定
# -----------------------------
def is_pullback_candidate(stock):
    try:
        # 直近5日以内にブレイクしているか
        if not (stock.get("broke_recent") or stock.get("broke_today")):
            return False

        # 今日ブレイク中なら押し目ではない
        if stock.get("broke_today"):
            return False

        # 最高値からの下落率を計算
        max_close = stock.get("max_close_since_break")
        if not max_close or max_close <= 0:
            return False

        pull = stock.get("pullback_pct", 0.0)
        # 3%〜7%の押し目かつ、25日線の上にあること
        if 0.03 <= pull <= 0.07 and stock.get("ma25") and stock["close"] > stock["ma25"]:
            return True
    except:
        pass
    return False

# -----------------------------
# 行動判定
# -----------------------------
def judge_action(stock, score):
    vr = volume_ratio(stock)

    # 即買い: 高スコア + 出来高2倍以上 + 当日ブレイク
    if score >= 90 and vr >= 2.0 and stock.get("broke_today"):
        return "🟢 即買い"

    # 押し目待ち: 条件合致 + 高スコア
    if is_pullback_candidate(stock) and score >= 85:
        return "🟡 押し目待ち"

    # 当日ブレイクだがスコアが少し足りない場合も監視
    if stock.get("broke_today") and score >= 85:
        return "🟡 押し目待ち"

    return "⚪ 見送り"

# -----------------------------
# 理由文作成
# -----------------------------
def make_reason(stock, action, score, canslim_breakdown):
    if action == "🟢 即買い":
        return "52週高値を出来高急増で明確に更新。初動ブレイクと判断。"
    if action == "🟡 押し目待ち":
        return "高値更新済み。浅い押し（3〜7%）で反発期待。25日線付近で確認したい。"
    
    # 見送りの場合、CANSLIMの内訳をヒントに表示
    c_hint = ""
    if canslim_breakdown:
        c_parts = [f"{k}:{v}" for k,v in canslim_breakdown.items() if v > 0]
        if c_parts:
            c_hint = " CANSLIM要素(" + ",".join(c_parts) + ")"
    return "条件未達で見送り。" + c_hint

# ==============================
# UI構築
# ==============================
st.title("📈 新高値ブレイク分析ツール（CANSLIM版）")
st.markdown("""
以下のテキストボックスに、**52週高値更新銘柄**のコードを貼り付けてください。
（例: 7203, 6758 などを改行区切りで入力）
""")

# 入力エリア
input_text = st.text_area("銘柄コード入力", height=150, placeholder="7203\n6758\n9984")
max_process = st.number_input("一度に処理する最大数", min_value=5, max_value=200, value=50, step=5)

if st.button("🚀 分析開始", type="primary"):
    symbols = [s.strip() for s in input_text.split("\n") if s.strip()]
    
    if not symbols:
        st.warning("銘柄コードを入力してください")
    else:
        symbols = symbols[:int(max_process)]
        rows = []
        
        # プログレスバー
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for i, sym in enumerate(symbols):
            status_text.text(f"Analyzing {sym}...")
            stock = fetch_stock_data(sym)
            
            # 進捗更新
            progress_bar.progress((i + 1) / len(symbols))
            
            if stock is None:
                continue

            score = calc_score(stock)
            canslim_score, canslim_breakdown = calc_canslim(stock)
            action = judge_action(stock, score)
            reason = make_reason(stock, action, score, canslim_breakdown)

            # Kabutanリンク作成
            kabutan_url = f"https://kabutan.jp/stock/?code={stock['symbol']}"

            rows.append({
                "コード": stock["symbol"],
                "銘柄名": stock["name"],
                "スコア": score,
                "CANSLIM": canslim_score,
                "CANSLIM内訳": canslim_breakdown,
                "判断": action,
                "理由": reason,
                "出来高倍率": round(volume_ratio(stock), 2),
                "52週高値": stock.get("high52"),
                "当日終値": stock.get("close"),
                "押し目率(%)": round(stock.get("pullback_pct", 0.0) * 100, 2),
                "Kabutan": kabutan_url
            })

        status_text.empty()
        progress_bar.empty()

        if rows:
            df = pd.DataFrame(rows)
            # 判断(降順) > スコア(降順) > CANSLIM(降順) でソート
            df = df.sort_values(["判断", "スコア", "CANSLIM"], ascending=[False, False, False])
            
            st.success(f"✅ {len(df)} 銘柄の分析が完了しました！")

            # 表示用データフレームの作成（リンクのHTML化など）
            df_display = df.copy()
            
            # 内訳辞書を文字列化
            df_display["CANSLIM内訳"] = df_display["CANSLIM内訳"].apply(
                lambda d: ",".join([f"{k}:{v}" for k,v in d.items()]) if isinstance(d, dict) else ""
            )
            
            # KabutanリンクをHTML化
            df_display["Kabutan"] = df_display["Kabutan"].apply(
                lambda u: f'<a href="{u}" target="_blank" style="text-decoration:none; color:#4da6ff;">株探</a>'
            )
            
            # HTMLテーブルとして表示 (リンクを有効にするため)
            st.write(df_display.to_html(escape=False, index=False), unsafe_allow_html=True)

        else:
            st.warning("有効なデータが取得できませんでした。コードを確認してください。")
