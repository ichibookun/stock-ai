# app_safe.py
import streamlit as st
import traceback
import time
import io

# ライブラリの遅延インポート（起動時の障害を局所化）
try:
    import yfinance as yf
    import pandas as pd
    import numpy as np
except Exception as e:
    st.set_page_config(page_title="Error", layout="wide")
    st.title("ライブラリ読み込みエラー")
    st.error(traceback.format_exc())
    st.stop()

st.set_page_config(page_title="Safe Breakout Scanner", layout="wide")
st.title("🚀 Safe 新高値ブレイクスキャナー（壊れにくい版）")
st.caption("改行区切りで株探の52週高値銘柄を貼り付け → 最大50銘柄/回推奨")

# 設定
MAX_PER_RUN = 50

# ユーティリティ
def df_to_csv_bytes(df):
    buf = io.BytesIO()
    df.to_csv(buf, index=True)
    buf.seek(0)
    return buf.getvalue()

# データ取得（まとめて取る簡易版）
def fetch_hist_batch_safe(codes, period="6mo"):
    """
    単純で安全な yf.download を使用（失敗しやすいので try/except）
    """
    tickers = [f"{c}.T" for c in codes]
    try:
        raw = yf.download(tickers, period=period, group_by='ticker', threads=True, progress=False)
    except Exception:
        # fallback: 個別取得（遅いが確実）
        raw = None
    data = {}
    if raw is None or len(codes) == 1:
        # 個別取得で確実に回す
        for c in codes:
            try:
                tk = yf.Ticker(f"{c}.T")
                df = tk.history(period=period)
                if not df.empty:
                    data[c] = df
                time.sleep(0.15)
            except Exception:
                data[c] = None
    else:
        # group_by= 'ticker' の場合、raw は dict-like
        for c in codes:
            key = f"{c}.T"
            try:
                df = raw[key].dropna(how='all').copy()
                data[c] = df
            except Exception:
                data[c] = None
    return data

# スコア（シンプルで安定版）
def enhanced_breakout_score_minimal(df):
    """
    簡潔・安定な判定（元のロジックの縮小版）
    returns: score, rsi, judge, reason_str
    """
    if df is None or len(df) < 60:
        return 0, None, "データ不足", "データ件数不足"
    d = df.copy()
    try:
        d['SMA25'] = d['Close'].rolling(25).mean()
        d['SMA75'] = d['Close'].rolling(75).mean()
        d['High20'] = d['Close'].rolling(20).max()
        vol20 = d['Volume'].rolling(20).mean().iloc[-1]
        latest = d.iloc[-1]
        prev5 = d['Close'].iloc[-6]

        # RSI
        delta = d['Close'].diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = -delta.clip(upper=0).rolling(14).mean()
        rs = gain / loss
        rsi_now = (100 - (100 / (1 + rs))).iloc[-1]

        # 除外
        if latest['Close'] < d['SMA75'].iloc[-1]:
            return 0, round(float(rsi_now),1), "除外", "75日線下"
        if rsi_now > 85:
            return 0, round(float(rsi_now),1), "除外", "RSI過熱"
        if (latest['Close'] / prev5 - 1) > 0.25:
            return 0, round(float(rsi_now),1), "除外", "短期急騰"

        score = 0
        reasons = []

        # トレンド
        if latest['Close'] > d['SMA25'].iloc[-1]:
            score += 20; reasons.append("Close>25")
        if d['SMA25'].iloc[-1] > d['SMA75'].iloc[-1]:
            score += 20; reasons.append("25>75")
        if latest['Close'] >= d['High20'].iloc[-1]:
            score += 10; reasons.append("new20High")

        # 出来高
        if latest['Volume'] > vol20:
            score += 15; reasons.append("Vol>MA20")
        if latest['Volume'] > d['Volume'].iloc[-2] * 1.3:
            score += 15; reasons.append("Vol>prev*1.3")

        # 押し目耐性
        high20 = d['High20'].iloc[-1]
        if high20>0 and (high20 - latest['Close']) / high20 <= 0.10:
            score += 10; reasons.append("pullback<=10%")
        if (latest['Close'] - d['SMA25'].iloc[-1]) / d['SMA25'].iloc[-1] <= 0.15:
            score += 10; reasons.append("SMA25 gap<=15%")

        # フォロー・スルー（軽め）
        breakout_price = d['High20'].iloc[-1]
        cond_follow = False
        try:
            if d['Close'].iloc[-1] >= breakout_price or d['Close'].iloc[-2] >= breakout_price:
                cond_follow = True
        except:
            pass
        if cond_follow:
            score += 5; reasons.append("follow_through")
        else:
            score -= 5; reasons.append("no_follow")

        score = int(max(min(score, 100), 0))
        judge = "🟢 即エントリー" if score >= 85 else "🟡 押し目検討" if score >= 70 else "🔴 見送り"
        return score, round(float(rsi_now),1), judge, ";".join(reasons)
    except Exception as e:
        return 0, None, "エラー", str(e)

# UI: 入力
st.markdown("### 入力: 株探でコピーした52週高値銘柄を改行で貼り付け")
codes_text = st.text_area("銘柄コード（改行区切り）", height=180, placeholder="例:\n6920\n8035\n6857")
run = st.button("🔍 スキャン（最大50）")

# 早期表示：UIが出たかはここで確認可能
st.markdown("---")
st.write("注: 大量処理はYahoo側で失敗する場合があります。推奨は20〜50件/回。")

if run:
    try:
        codes = [c.strip() for c in codes_text.splitlines() if c.strip()]
        if not codes:
            st.warning("銘柄を入力してください")
        else:
            if len(codes) > MAX_PER_RUN:
                st.warning(f"指定数が多い ({len(codes)})。最初の{MAX_PER_RUN}件で処理します。")
                codes = codes[:MAX_PER_RUN]

            with st.spinner("価格データを取得中..."):
                hist_map = fetch_hist_batch_safe(codes, period="6mo")

            results = []
            progress = st.progress(0)
            for i, code in enumerate(codes):
                df = hist_map.get(code)
                score, rsi, judge, reason = enhanced_breakout_score_minimal(df)
                # 銘柄名は個別取得（任意）
                name = ""
                try:
                    name = yf.Ticker(f"{code}.T").info.get("longName", "")
                except:
                    name = ""
                results.append({"コード": code, "銘柄名": name, "スコア": score, "RSI": rsi, "判定": judge, "理由": reason})
                progress.progress((i+1)/len(codes))
            progress.empty()
            df_res = pd.DataFrame(results).sort_values("スコア", ascending=False)
            st.dataframe(df_res, use_container_width=True)
            # CSVダウンロード
            csv_bytes = df_to_csv_bytes(df_res)
            st.download_button("CSVダウンロード", data=csv_bytes, file_name="breakout_scan.csv", mime="text/csv")
    except Exception:
        st.error("処理中に例外が発生しました。詳細は下記。")
        st.text(traceback.format_exc())
