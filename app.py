import streamlit as st
import yfinance as yf
import pandas as pd
import time

# ==============================
# 設定
# ==============================
st.set_page_config(page_title="新高値ブレイク分析（CANSLIM表示版）", layout="wide")

# ==============================
# 日本語銘柄名マッピング (大幅強化)
# ==============================
JP_NAME_MAP = {
    # スクリーンショットにあった銘柄
    "4502": "武田薬品", "6370": "栗田工業", "6952": "カシオ計算機",
    "4519": "中外製薬", "5020": "ENEOS", "5021": "コスモエネルギー",
    "5834": "SBIリーシング", "6337": "テセック", "6490": "日本ピラー",
    "6787": "メイコー", "7022": "サノヤスHD", "4410": "ハリマ化成",
    "4507": "塩野義製薬",
    # その他主要銘柄
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
# 関数定義
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

        # --- データ計算 ---
        close = float(hist["Close"].iloc[-1])
        volume = int(hist["Volume"].iloc[-1])
        
        # 52週高値 (直近250営業日)
        window = min(252, len(hist))
        prev_high52 = hist["High"].iloc[-(window + 1):-1].max()

        ma25 = float(hist["Close"].rolling(25).mean().iloc[-1])
        avg_volume = float(hist["Volume"].rolling(20).mean().iloc[-1])

        # ブレイク判定
        broke_today = close > prev_high52
        
        # 直近ブレイク判定 & 押し目計算
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
            
            # 日本語名処理 (辞書優先 -> yfinanceのshortName -> code)
            if code in JP_NAME_MAP:
                name = JP_NAME_MAP[code]
            else:
                name = info.get("shortName") or info.get("longName") or code
        except:
            earnings_q_growth = None
            trailing_eps = None
            forward_eps = None
            name = code

        time.sleep(0.05) # 負荷軽減

        return {
            "symbol": code, "name": name, "close": close,
            "volume": volume, "avg_volume": avg_volume,
            "prev_high52": float(prev_high52),
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

# --- CANSLIM スコア計算 (0-100点) ---
def calc_canslim(stock):
    score = 0
    # C: 四半期利益成長 (20点)
    eg = stock.get("earnings_q_growth")
    if eg and eg >= 0.20: score += 20
    elif eg and eg >= 0.10: score += 10
    
    # A: 年間成長期待 (20点)
    te = stock.get("trailing_eps"); fe = stock.get("forward_eps")
    if te and fe and te != 0:
        if (fe - te) / abs(te) >= 0.15: score += 20

    # N: 新高値 (20点)
    if stock["broke_today"] or stock["broke_recent"]: score += 20
    
    # S: 需給 (出来高) (20点)
    vr = stock["volume"] / stock["avg_volume"] if stock["avg_volume"] > 0 else 0
    if vr >= 1.5: score += 20
    elif vr >= 1.2: score += 10
    
    # L: 主導株 (モメンタム) (20点)
    if stock.get("momentum_3m") >= 0.15: score += 20
    elif stock.get("momentum_3m") >= 0.05: score += 10
    
    return score

# --- 判定ロジック ---
def judge_action(stock, canslim_score):
    vr = stock["volume"] / stock["avg_volume"] if stock["avg_volume"] > 0 else 0
    
    # 🟢 即買い: 当日ブレイク & 出来高増
    if stock["broke_today"] and vr >= 1.2:
        return "🟢 即買い"
    
    # 🟡 押し目待ち: 最近ブレイク & 2~8%の押し
    if stock["broke_recent"]:
        pb = stock["pullback_pct"]
        if 0.02 <= pb <= 0.08:
            return "🟡 押し目待ち"
            
    # その他
    if stock["broke_today"]: return "⚪ ブレイク(出来高不足)"
    return "⚪ 監視中"

# --- 理由作成 ---
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
# UI
# ==============================
st.title("📈 新高値ブレイク分析 (CANSLIM点数表示)")

# デフォルト銘柄コード (スクリーンショットの銘柄も含めました)
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
                canslim = calc_canslim(data)
                action = judge_action(data, canslim)
                reason = make_reason(data)
                
                # 株探リンク (変更なし)
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
                    "CANSLIM": canslim,  # ここに点数を追加
                    "Reason": reason,
                    "Vol Ratio": f"{data['volume']/data['avg_volume']:.1f}x" if data['avg_volume']>0 else "-"
                })
        
        bar.empty()
        
        if rows:
            df = pd.DataFrame(rows)
            # 優先順位: Judge(色付きタグ込みでソートは難しいので別ロジックでソート推奨だが簡易的に)
            # CANSLIM点数が高い順にソート
            df = df.sort_values("CANSLIM", ascending=False)
            
            st.success(f"{len(df)} 銘柄の分析完了")
            # HTML表示
            st.write(df.to_html(escape=False, index=False), unsafe_allow_html=True)
        else:
            st.error("データなし")
