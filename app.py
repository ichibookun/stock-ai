import streamlit as st
import yfinance as yf
import pandas as pd
import time

# ==============================
# 設定
# ==============================
st.set_page_config(page_title="新高値ブレイク分析（スコア順）", layout="wide")

# ==============================
# 日本語銘柄名マッピング (維持)
# ==============================
JP_NAME_MAP = {
    # ユーザー提供銘柄
    "4502": "武田薬品", "6370": "栗田工業", "6952": "カシオ計算機",
    "4519": "中外製薬", "5020": "ENEOS", "5021": "コスモエネルギー",
    "5834": "SBIリーシング", "6337": "テセック", "6490": "日本ピラー",
    "6787": "メイコー", "7022": "サノヤスHD", "4410": "ハリマ化成",
    "4507": "塩野義製薬",
    # その他主要
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
# データ取得関数
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

        # --- テクニカル指標 ---
        close = float(hist["Close"].iloc[-1])
        volume = int(hist["Volume"].iloc[-1])
        
        # 52週高値
        window = min(252, len(hist))
        prev_high52 = hist["High"].iloc[-(window + 1):-1].max()

        ma25 = float(hist["Close"].rolling(25).mean().iloc[-1])
        ma75 = float(hist["Close"].rolling(75).mean().iloc[-1])
        avg_volume = float(hist["Volume"].rolling(20).mean().iloc[-1])

        # ブレイク判定 (当日)
        broke_today = close > prev_high52
        
        # 直近ブレイク & 押し目計算 (過去5日)
        recent_window = min(5, len(hist)-1)
        recent_closes = hist["Close"].iloc[-(recent_window+1):-1]
        broke_recent = False
        pullback_pct = 0.0
        
        if recent_window > 0:
            # 過去5日以内に高値更新があったか
            broke_indices = recent_closes[recent_closes > prev_high52].index
            if len(broke_indices) > 0:
                broke_recent = True
                last_idx = broke_indices[-1]
                # ブレイク後の最高値を探索
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

        # --- 企業情報 ---
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
            "ma25": ma25, "ma75": ma75,
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
# スコア計算ロジック
# ==============================

# 1. 総合スコア (売買判断用: テクニカル重視)
def calc_total_score(stock):
    score = 0
    
    # A. 52週高値ブレイク (40点)
    if stock["broke_today"]:
        score += 40
    elif stock["broke_recent"]: # 直近でブレイク済みなら30点
        score += 30
        
    # B. 出来高急増 (30点)
    vr = stock["volume"] / stock["avg_volume"] if stock["avg_volume"] > 0 else 0
    if vr >= 2.0: score += 30
    elif vr >= 1.5: score += 20
    elif vr >= 1.2: score += 10
    
    # C. トレンド (20点)
    if stock["ma25"] > stock["ma75"]:
        score += 20
        
    # D. モメンタム (10点)
    if stock["momentum_3m"] >= 0.15:
        score += 10
        
    return score

# 2. CANSLIMスコア (ファンダメンタルズ参考用)
def calc_canslim(stock):
    score = 0
    # C: 四半期成長
    eg = stock.get("earnings_q_growth")
    if eg and eg >= 0.20: score += 30
    # A: 年間成長期待
    te = stock.get("trailing_eps"); fe = stock.get("forward_eps")
    if te and fe and te != 0:
        if (fe - te) / abs(te) >= 0.15: score += 30
    # N: 新高値
    if stock["broke_today"] or stock["broke_recent"]: score += 20
    # S: 出来高
    vr = stock["volume"] / stock["avg_volume"] if stock["avg_volume"] > 0 else 0
    if vr >= 1.5: score += 10
    # L: モメンタム
    if stock["momentum_3m"] >= 0.15: score += 10
    
    return score

# ==============================
# 判定ロジック (スコアに基づくランク付け)
# ==============================
def judge_action(stock, total_score):
    vr = stock["volume"] / stock["avg_volume"] if stock["avg_volume"] > 0 else 0
    
    # 🟢 即買い: 総合スコアが高く、当日ブレイク & 出来高伴う
    if total_score >= 80 and stock["broke_today"] and vr >= 1.2:
        return "🟢 即買い"
    
    # 🟡 押し目待ち: 総合スコアそこそこで、最近ブレイク & 浅い調整中
    # 条件: 直近ブレイク済み AND (現在2%〜8%の押し目 OR 当日ブレイクだが出来高不足)
    if stock["broke_recent"]:
        pb = stock["pullback_pct"]
        if 0.02 <= pb <= 0.08 and total_score >= 60:
            return "🟡 押し目待ち"
            
    # 当日ブレイクだが出来高が足りない場合も押し目候補とする
    if stock["broke_today"] and total_score >= 60:
        return "🟡 押し目待ち"
            
    return "⚪ 監視中"

# 理由作成
def make_reason(stock):
    reasons = []
    if stock["broke_today"]: reasons.append("本日高値更新")
    if stock["broke_recent"]: reasons.append("直近高値更新")
    
    pb = stock["pullback_pct"]
    if 0.02 <= pb <= 0.08: reasons.append(f"押し目-{pb*100:.1f}%")
    
    vr = stock["volume"] / stock["avg_volume"] if stock["avg_volume"] > 0 else 0
    if vr >= 1.5: reasons.append(f"出来高{vr:.1f}倍")
    
    return " / ".join(reasons) if reasons else "-"

# ==============================
# メイン画面
# ==============================
st.title("📈 新高値ブレイク分析 (Ver 21.0)")
st.caption("総合スコア順 / CANSLIM併記 / 日本語対応")

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
4507"""

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
                # 計算
                total_score = calc_total_score(data) # 総合スコア(復活)
                canslim = calc_canslim(data)         # CANSLIM
                action = judge_action(data, total_score) # 判定
                reason = make_reason(data)
                
                # 株探リンク
                url = f"https://kabutan.jp/stock/?code={data['symbol']}"
                link = f'<a href="{url}" target="_blank" style="text-decoration:none;font-weight:bold;color:#1E90FF;">株探</a>'
                
                # 判定の色付け
                judge_html = action
                if "即買い" in action:
                    judge_html = f'<span style="color:green;font-weight:bold;">{action}</span>'
                elif "押し目" in action:
                    judge_html = f'<span style="color:#DAA520;font-weight:bold;">{action}</span>'

                rows.append({
                    "Check": link,
                    "Code": data['symbol'],
                    "Name": data['name'],
                    "Price": f"{data['close']:,.0f}",
                    "Judge": judge_html,
                    "Total Score": total_score, # 総合スコア
                    "CANSLIM": canslim,         # 横に配置
                    "Reason": reason,
                    "Vol Ratio": f"{data['volume']/data['avg_volume']:.1f}x" if data['avg_volume']>0 else "-"
                })
        
        bar.empty()
        
        if rows:
            df = pd.DataFrame(rows)
            # 並び替え: 総合スコア(降順)
            df = df.sort_values("Total Score", ascending=False)
            
            st.success(f"{len(df)} 銘柄の分析完了")
            # HTML表示
            st.write(df.to_html(escape=False, index=False), unsafe_allow_html=True)
        else:
            st.error("データなし")
