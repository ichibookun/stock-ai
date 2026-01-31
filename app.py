import streamlit as st
import yfinance as yf
import pandas as pd
import time

# ==============================
# 設定
# ==============================
st.set_page_config(page_title="新高値ブレイク分析", layout="wide")

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

        # データ取得
        close = float(hist["Close"].iloc[-1])
        volume = int(hist["Volume"].iloc[-1])
        
        # 52週高値計算
        window = min(252, len(hist))
        # 直前までの52週高値（当日を含まない）
        prev_high52 = hist["High"].iloc[-(window + 1):-1].max()

        ma25 = float(hist["Close"].rolling(25).mean().iloc[-1])
        avg_volume = float(hist["Volume"].rolling(20).mean().iloc[-1])

        # ブレイク判定
        broke_today = close > prev_high52
        
        # 直近のブレイク判定
        recent_window = min(5, len(hist)-1)
        recent_closes = hist["Close"].iloc[-(recent_window+1):-1]
        broke_recent = False
        pullback_pct = 0.0
        
        if recent_window > 0:
            # 過去5日で高値を超えた日があるか
            broke_indices = recent_closes[recent_closes > prev_high52].index
            if len(broke_indices) > 0:
                broke_recent = True
                last_idx = broke_indices[-1]
                # ブレイク後の最高値からの押し目率
                start = hist.index.get_loc(last_idx)
                max_val = hist["Close"].iloc[start:-1].max()
                if max_val > 0:
                    pullback_pct = (max_val - close) / max_val

        # 企業名取得
        try:
            name = tk.info.get("longName", code)
        except:
            name = code

        time.sleep(0.1) # 負荷軽減

        return {
            "symbol": code, "name": name, "close": close,
            "volume": volume, "avg_volume": avg_volume,
            "broke_today": broke_today, "broke_recent": broke_recent,
            "pullback_pct": pullback_pct
        }
    except:
        return None

def judge_action(d):
    # 出来高倍率
    vr = d["volume"] / d["avg_volume"] if d["avg_volume"] > 0 else 0
    
    # 判定
    if d["broke_today"] and vr >= 1.5:
        return "🟢 即買い (ブレイク)", 100
    elif d["broke_recent"] and 0.03 <= d["pullback_pct"] <= 0.07:
        return "🟡 押し目待ち", 80
    else:
        return "⚪ 監視中", 50

# ==============================
# メイン画面
# ==============================
st.title("📈 新高値ブレイク分析ツール")
st.caption("Ver 1.0: 修正済み完動版")

input_text = st.text_area("銘柄コード (改行区切り)", value="7203\n6758\n9984\n8035\n6501", height=150)

if st.button("分析開始", type="primary"):
    symbols = [s.strip() for s in input_text.split("\n") if s.strip()]
    if not symbols:
        st.warning("コードを入力してください")
    else:
        rows = []
        bar = st.progress(0)
        
        for i, sym in enumerate(symbols):
            bar.progress((i + 1) / len(symbols))
            d = fetch_stock_data(sym)
            if d:
                judge, score = judge_action(d)
                
                # 株探リンク
                url = f"https://kabutan.jp/stock/?code={d['symbol']}"
                link = f'<a href="{url}" target="_blank" style="text-decoration:none;font-weight:bold;">株探</a>'
                
                rows.append({
                    "Check": link,
                    "Code": d['symbol'],
                    "Name": d['name'],
                    "Price": f"{d['close']:,.0f}",
                    "Judge": judge,
                    "Score": score
                })
        
        bar.empty()
        
        if rows:
            df = pd.DataFrame(rows).sort_values("Score", ascending=False)
            # HTMLとしてテーブルを表示（リンク有効化のため）
            st.write(df.to_html(escape=False, index=False), unsafe_allow_html=True)
            st.success("分析完了！")
        else:
            st.error("データが取得できませんでした")
