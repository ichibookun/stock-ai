import streamlit as st
import yfinance as yf
import pandas as pd
import time

# ==============================
# 設定
# ==============================
st.set_page_config(page_title="新高値ブレイク分析（高値掴み防止版）", layout="wide")

# ==============================
# 日本語銘柄名マッピング (スクショの銘柄を追加)
# ==============================
JP_NAME_MAP = {
    # ユーザー指摘 & スクショ銘柄
    "4502": "武田薬品", "6370": "栗田工業", "6952": "カシオ計算機",
    "4519": "中外製薬", "5020": "ENEOS", "5021": "コスモエネルギー",
    "5834": "SBIリーシング", "6337": "テセック", "6490": "日本ピラー",
    "6787": "メイコー", "7022": "サノヤスHD", "4410": "ハリマ化成",
    "4507": "塩野義製薬", 
    "5204": "石塚硝子", "5252": "日本ナレッジ", "6858": "小野測器",
    "6998": "日本タングステン", "5984": "兼房", "6349": "小森コーポ",
    "5019": "出光興産", "8053": "住友商事", "2768": "双日",
    # 主要銘柄
    "7203": "トヨタ自動車", "6758": "ソニーG", "9984": "ソフトバンクG",
    "8035": "東京エレク", "6501": "日立製作所", "6702": "富士通",
    "6861": "キーエンス", "6098": "リクルート", "4063": "信越化学",
    "6902": "デンソー", "7974": "任天堂", "9432": "NTT",
    "9433": "KDDI", "9434": "ソフトバンク", "8306": "三菱UFJ",
    "8316": "三井住友FG", "8411": "みずほFG", "2914": "JT",
    "8058": "三菱商事", "8001": "伊藤忠", "8002": "丸紅",
    "5401": "日本製鉄", "6146": "ディスコ", "6920": "レーザーテック",
    "6857": "アドバンテスト", "7729": "東京精密", "6723": "ルネサス"
}

# ==============================
# データ取得
# ==============================
@st.cache_data(ttl=3600)
def fetch_stock_data(symbol):
    code = str(symbol).strip()
    ticker = f"{code}.T"
    try:
        tk = yf.Ticker(ticker)
        hist = tk.history(period="2y", actions=False)
        if hist is None or hist.empty or len(hist) < 60:
            return None

        # 値取得
        close = float(hist["Close"].iloc[-1])
        volume = int(hist["Volume"].iloc[-1])
        
        # 52週高値 (直前まで)
        window = min(252, len(hist))
        prev_high52 = hist["High"].iloc[-(window + 1):-1].max()

        ma25 = float(hist["Close"].rolling(25).mean().iloc[-1])
        avg_volume = float(hist["Volume"].rolling(20).mean().iloc[-1])

        # --- 判定ロジック ---
        broke_today = close > prev_high52
        
        # ブレイクからの乖離率 (5%ルール用)
        # (今日の終値 - ブレイクライン) / ブレイクライン
        breakout_divergence = (close - prev_high52) / prev_high52 if prev_high52 > 0 else 0

        # 直近ブレイク & 押し目
        recent_window = min(5, len(hist)-1)
        recent_closes = hist["Close"].iloc[-(recent_window+1):-1]
        broke_recent = False
        pullback_pct = 0.0
        
        if recent_window > 0:
            broke_indices = recent_closes[recent_closes > prev_high52].index
            if len(broke_indices) > 0:
                broke_recent = True
                last_idx = broke_indices[-1]
                start = hist.index.get_loc(last_idx)
                max_val = hist["Close"].iloc[start:-1].max()
                if max_val > 0:
                    pullback_pct = (max_val - close) / max_val

        # モメンタム
        period_3m = min(63, len(hist)-1)
        momentum_3m = 0.0
        if period_3m >= 1:
            price_3m_ago = hist["Close"].iloc[-(period_3m+1)]
            momentum_3m = (close - price_3m_ago) / price_3m_ago

        # 企業情報
        try:
            info = tk.info or {}
            earnings_q_growth = info.get("earningsQuarterlyGrowth")
            trailing_eps = info.get("trailingEps")
            forward_eps = info.get("forwardEps")
            if code in JP_NAME_MAP:
                name = JP_NAME_MAP[code]
            else:
                name = info.get("shortName") or info.get("longName") or code
        except:
            earnings_q_growth = None; trailing_eps = None; forward_eps = None; name = code

        time.sleep(0.05)

        return {
            "symbol": code, "name": name, "close": close,
            "volume": volume, "avg_volume": avg_volume,
            "prev_high52": float(prev_high52),
            "breakout_divergence": breakout_divergence,
            "ma25": ma25,
            "broke_today": broke_today,
            "broke_recent": broke_recent,
            "pullback_pct": float(pullback_pct),
            "momentum_3m": float(momentum_3m),
            "earnings_q_growth": earnings_q_growth,
            "trailing_eps": trailing_eps,
            "forward_eps": forward_eps,
        }
    except:
        return None

# ==============================
# スコア & 判定
# ==============================

def calc_total_score(stock):
    score = 0
    # A. 52週高値ブレイク (40点)
    if stock["broke_today"]: score += 40
    elif stock["broke_recent"]: score += 30
        
    # B. 出来高急増 (30点)
    vr = stock["volume"] / stock["avg_volume"] if stock["avg_volume"] > 0 else 0
    if vr >= 2.0: score += 30
    elif vr >= 1.5: score += 20
    elif vr >= 1.2: score += 10
    
    # C. トレンド (20点)
    if stock["close"] > stock["ma25"]: score += 20
        
    # D. モメンタム (10点)
    if stock["momentum_3m"] >= 0.15: score += 10
        
    return score

def calc_canslim(stock):
    score = 0
    eg = stock.get("earnings_q_growth")
    if eg and eg >= 0.20: score += 30
    te = stock.get("trailing_eps"); fe = stock.get("forward_eps")
    if te and fe and te != 0:
        if (fe - te) / abs(te) >= 0.15: score += 30
    if stock["broke_today"] or stock["broke_recent"]: score += 20
    vr = stock["volume"] / stock["avg_volume"] if stock["avg_volume"] > 0 else 0
    if vr >= 1.5: score += 10
    if stock["momentum_3m"] >= 0.15: score += 10
    return score

# --- 判定ロジック (改良版) ---
def judge_action(stock, total_score):
    vr = stock["volume"] / stock["avg_volume"] if stock["avg_volume"] > 0 else 0
    
    # 1. 当日ブレイクの判定
    if stock["broke_today"]:
        # 【重要】ブレイクラインから5%以上離れていたら「過熱」とする
        if stock["breakout_divergence"] > 0.05:
            return "📈 急騰 (過熱)"
        
        # 正常なブレイク範囲内なら即買い
        if total_score >= 80 and vr >= 1.2:
            return "🟢 即買い"
        
        return "⚪ ブレイク(力不足)"

    # 2. 押し目待ちの判定
    if stock["broke_recent"]:
        pb = stock["pullback_pct"]
        # 2%〜10%の押し目ならチャンス
        if 0.02 <= pb <= 0.10 and total_score >= 60:
            return "🟡 押し目待ち"
            
    return "⚪ 監視中"

def make_reason(stock):
    reasons = []
    if stock["broke_today"]:
        div = stock["breakout_divergence"] * 100
        if div > 5:
            reasons.append(f"高値更新(+{div:.1f}%乖離中)")
        else:
            reasons.append("本日高値更新")
            
    if stock["broke_recent"]:
        reasons.append("直近更新")
    
    pb = stock["pullback_pct"]
    if 0.02 <= pb <= 0.10:
        reasons.append(f"押し目(-{pb*100:.1f}%)")
    
    vr = stock["volume"] / stock["avg_volume"] if stock["avg_volume"] > 0 else 0
    if vr >= 1.5:
        reasons.append(f"出来高増({vr:.1f}倍)")
        
    return " / ".join(reasons) if reasons else "-"

# ==============================
# UI
# ==============================
st.title("📈 新高値ブレイク分析 (Ver 22.0)")
st.info("💡 **即買い vs 押し目待ち の違い**\n\n"
        "**🟢 即買い**: 本日52週高値を更新し、かつ「過熱しすぎていない（乖離+5%以内）」銘柄。まさに飛び乗るタイミング。\n\n"
        "**📈 急騰 (過熱)**: 本日高値を更新したが、+5%以上急騰してしまった銘柄。今買うと「高値掴み」のリスク大。監視リストに入れて、下がるのを待ちましょう。\n\n"
        "**🟡 押し目待ち**: 数日前に高値を更新し、今は利益確定売りなどで少し下がっている(-2%〜-10%)状態。再上昇を狙う安全なエントリーポイント。")

# デフォルト銘柄
default_codes = """4502
6370
6952
4519
5020
5021
5834
6337
6490
6787
7022
4410
4507
5204
5252
6858
6998
5984
6349"""

input_text = st.text_area("銘柄コード (改行区切り)", value=default_codes, height=200)

if st.button("🚀 分析開始", type="primary"):
    symbols = [s.strip() for s in input_text.split("\n") if s.strip()]
    
    if not symbols:
        st.warning("コードを入力してください")
    else:
        rows = []
        bar = st.progress(0)
        
        for i, sym in enumerate(symbols):
            bar.progress((i + 1) / len(symbols))
            data = fetch_stock_data(sym)
            
            if data:
                t_score = calc_total_score(data)
                c_score = calc_canslim(data)
                action = judge_action(data, t_score)
                reason = make_reason(data)
                
                url = f"https://kabutan.jp/stock/?code={data['symbol']}"
                link = f'<a href="{url}" target="_blank" style="text-decoration:none;font-weight:bold;color:#1E90FF;">株探</a>'
                
                # 色分け
                judge_html = action
                if "即買い" in action:
                    judge_html = f'<span style="color:green;font-weight:bold;">{action}</span>'
                elif "押し目" in action:
                    judge_html = f'<span style="color:#DAA520;font-weight:bold;">{action}</span>'
                elif "急騰" in action:
                    judge_html = f'<span style="color:red;font-weight:bold;">{action}</span>'

                rows.append({
                    "Check": link,
                    "Code": data['symbol'],
                    "Name": data['name'],
                    "Price": f"{data['close']:,.0f}",
                    "Judge": judge_html,
                    "Total Score": t_score,
                    "CANSLIM": c_score,
                    "Reason": reason,
                    "Vol Ratio": f"{data['volume']/data['avg_volume']:.1f}x" if data['avg_volume']>0 else "-"
                })
        
        bar.empty()
        
        if rows:
            df = pd.DataFrame(rows)
            # ソート順: 総合スコアが高い順
            df = df.sort_values("Total Score", ascending=False)
            
            st.success(f"{len(df)} 銘柄の分析完了")
            st.write(df.to_html(escape=False, index=False), unsafe_allow_html=True)
        else:
            st.error("データなし")
