import streamlit as st
import yfinance as yf
import pandas as pd
import time

# ==============================
# 設定
# ==============================
st.set_page_config(page_title="新高値ブレイク分析（完全版）", layout="wide")

# ==============================
# 日本語銘柄名マッピング (主要銘柄を強制変換)
# ==============================
JP_NAME_MAP = {
    "7203": "トヨタ自動車", "6758": "ソニーグループ", "9984": "ソフトバンクG",
    "8035": "東京エレクトロン", "6501": "日立製作所", "6702": "富士通",
    "6861": "キーエンス", "6098": "リクルートHD", "4063": "信越化学",
    "6902": "デンソー", "7974": "任天堂", "9432": "NTT",
    "9433": "KDDI", "9434": "ソフトバンク", "8306": "三菱UFJ",
    "8316": "三井住友FG", "8411": "みずほFG", "2914": "JT",
    "8058": "三菱商事", "8001": "伊藤忠", "8002": "丸紅",
    "8031": "三井物産", "4502": "武田薬品", "4503": "アステラス",
    "5401": "日本製鉄", "6146": "ディスコ", "6920": "レーザーテック",
    "6857": "アドバンテスト", "7729": "東京精密", "6723": "ルネサス",
    "6526": "ソシオネクスト", "7011": "三菱重工", "7012": "川崎重工",
    "6367": "ダイキン", "6594": "ニデック", "6981": "村田製作所"
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
        # 過去2年分
        hist = tk.history(period="2y", actions=False)
        if hist is None or hist.empty or len(hist) < 60:
            return None

        # --- テクニカルデータ計算 ---
        close = float(hist["Close"].iloc[-1])
        volume = int(hist["Volume"].iloc[-1])
        
        # 52週高値 (直近250営業日)
        window = min(252, len(hist))
        # 「当日を含まない」過去の最高値（ブレイク判定用）
        prev_high52 = hist["High"].iloc[-(window + 1):-1].max()

        # 移動平均
        ma25 = float(hist["Close"].rolling(25).mean().iloc[-1])
        avg_volume = float(hist["Volume"].rolling(20).mean().iloc[-1])

        # --- ブレイク＆押し目判定 ---
        broke_today = close > prev_high52  # 今日ブレイクしたか
        
        # 直近(過去5日)でブレイクしたか
        recent_window = min(5, len(hist)-1)
        recent_closes = hist["Close"].iloc[-(recent_window+1):-1]
        broke_recent = False
        pullback_pct = 0.0
        
        if recent_window > 0:
            broke_indices = recent_closes[recent_closes > prev_high52].index
            if len(broke_indices) > 0:
                broke_recent = True
                last_idx = broke_indices[-1]
                # ブレイク後の最高値を探す
                start = hist.index.get_loc(last_idx)
                max_val = hist["Close"].iloc[start:-1].max()
                if max_val > 0:
                    # 最高値からの下落率 (押し目率)
                    pullback_pct = (max_val - close) / max_val

        # --- モメンタム (3ヶ月) ---
        period_3m = min(63, len(hist)-1)
        momentum_3m = 0.0
        if period_3m >= 1:
            price_3m_ago = hist["Close"].iloc[-(period_3m+1)]
            momentum_3m = (close - price_3m_ago) / price_3m_ago

        # --- 企業情報 & 日本語名処理 ---
        try:
            info = tk.info or {}
            # 業績データ（CANSLIM用）
            earnings_q_growth = info.get("earningsQuarterlyGrowth")
            trailing_eps = info.get("trailingEps")
            forward_eps = info.get("forwardEps")
            
            # 名前決定ロジック
            if code in JP_NAME_MAP:
                name = JP_NAME_MAP[code] # 辞書にあるならそれを使う
            else:
                # 辞書になければAPIの短い名前を使う（英語の可能性あり）
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

# --- CANSLIM スコア計算 ---
def calc_canslim(stock):
    c = a = n = s = l = 0
    
    # C: 四半期利益成長
    eg = stock.get("earnings_q_growth")
    if eg and eg >= 0.20: c = 20
    
    # A: 年間成長期待
    te = stock.get("trailing_eps"); fe = stock.get("forward_eps")
    if te and fe and te != 0:
        if (fe - te) / abs(te) >= 0.15: a = 20

    # N: 新高値更新
    if stock["broke_today"]: n = 20
    
    # S: 需給 (出来高)
    vr = stock["volume"] / stock["avg_volume"] if stock["avg_volume"] > 0 else 0
    if vr >= 1.5: s = 20
    elif vr >= 1.0: s = 10
    
    # L: 主導株 (モメンタム)
    if stock.get("momentum_3m") >= 0.15: l = 20
    
    return c+a+n+s+l, {"C":c, "A":a, "N":n, "S":s, "L":l}

# --- 判定ロジック (復活) ---
def judge_action(stock, score):
    vr = stock["volume"] / stock["avg_volume"] if stock["avg_volume"] > 0 else 0
    
    # 🟢 即買い: スコア高く、当日ブレイクで出来高も伴う
    if score >= 60 and stock["broke_today"] and vr >= 1.2:
        return "🟢 即買い"
    
    # 🟡 押し目待ち: 最近ブレイクしており、現在3〜7%の調整中
    if stock["broke_recent"]:
        pb = stock["pullback_pct"]
        if 0.02 <= pb <= 0.08: # 2%~8%程度の押し
            return "🟡 押し目待ち"
            
    return "⚪ 監視中"

# --- 理由作成 (復活) ---
def make_reason(stock, action):
    reasons = []
    
    if stock["broke_today"]:
        reasons.append("本日52週高値更新")
    if stock["broke_recent"]:
        reasons.append("直近で高値更新済み")
    
    pb = stock["pullback_pct"]
    if 0.02 <= pb <= 0.08:
        reasons.append(f"現在-{pb*100:.1f}%の押し目(好機)")
    
    vr = stock["volume"] / stock["avg_volume"] if stock["avg_volume"] > 0 else 0
    if vr >= 1.5:
        reasons.append(f"出来高急増({vr:.1f}倍)")
        
    if not reasons:
        return "特になし"
        
    return " / ".join(reasons)

# ==============================
# メイン画面 (UI)
# ==============================
st.title("📈 新高値ブレイク分析ツール (完全復活版)")
st.caption("Ver 19.0: CANSLIM・押し目・日本語名 対応")

input_text = st.text_area("銘柄コード (改行区切り)", value="7203\n6758\n9984\n8035\n6702\n6501", height=150)

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
                score, details = calc_canslim(data)
                action = judge_action(data, score)
                reason = make_reason(data, action)
                
                # 株探リンク
                url = f"https://kabutan.jp/stock/?code={data['symbol']}"
                link = f'<a href="{url}" target="_blank" style="text-decoration:none;font-weight:bold;color:#1E90FF;">株探</a>'
                
                # 色分け判定
                judge_display = action
                if "即買い" in action:
                    judge_display = f'<span style="color:green;font-weight:bold;">{action}</span>'
                elif "押し目" in action:
                    judge_display = f'<span style="color:#DAA520;font-weight:bold;">{action}</span>'
                
                rows.append({
                    "Check": link,
                    "Code": data['symbol'],
                    "Name": data['name'],
                    "Price": f"{data['close']:,.0f}",
                    "Judge": judge_display,
                    "Reason": reason,
                    "Score": score,
                    "Vol Ratio": f"{data['volume']/data['avg_volume']:.1f}x" if data['avg_volume']>0 else "-"
                })
        
        bar.empty()
        
        if rows:
            df = pd.DataFrame(rows)
            # 優先順位: 判定(即買い>押し目>監視) -> スコア
            sort_map = {"🟢 即買い": 2, "🟡 押し目待ち": 1, "⚪ 監視中": 0}
            # sort用に一時的な列を作る（HTMLタグを除く）
            df["_sort"] = df["Judge"].apply(lambda x: sort_map.get(x.replace('<span style="color:green;font-weight:bold;">','').replace('<span style="color:#DAA520;font-weight:bold;">','').replace('</span>',''), 0))
            
            df = df.sort_values(by=["_sort", "Score"], ascending=[False, False]).drop(columns=["_sort"])
            
            st.success(f"{len(df)} 銘柄の分析が完了しました")
            
            # HTMLとしてテーブルを表示
            st.write(df.to_html(escape=False, index=False), unsafe_allow_html=True)
        else:
            st.error("データが取得できませんでした")
