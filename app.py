# --- 改良版：バッチスキャン + 新高値ブレイク専用（O'Neil簡易要素 + 高値掴み回避） ---
import time
import yfinance as yf
import pandas as pd
import numpy as np
import streamlit as st

MAX_PER_RUN = 100  # 実用上の推奨上限

def fetch_hist_batch(codes, period="6mo", interval="1d"):
    """
    codes: list of '6758' etc.
    returns: dict code -> dataframe
    使用: yf.download でまとめて取り、各ティッカー毎にDataFrameを返す
    """
    tickers = [f"{c}.T" for c in codes]
    # yf.download returns multi-column dataframe if multiple tickers
    raw = yf.download(tickers, period=period, interval=interval, group_by='ticker', threads=True, progress=False)
    data = {}
    # If only one ticker, raw columns are normal
    if len(tickers) == 1:
        df = raw.copy()
        data[codes[0]] = df
        return data
    for t in tickers:
        try:
            df = raw[t].dropna(how='all').copy()
            code = t.split('.')[0]
            data[code] = df
        except Exception:
            pass
    return data

def enhanced_breakout_score(df, info=None):
    """
    df: 日次データ（pandas DataFrame）
    info: yfinance.Ticker.info (optional) - EPS growthなどを参照
    戻り: (score, rsi, judge, reason_dict)
    """
    reason = {}
    score = 0
    if df is None or len(df) < 60:
        return 0, None, "データ不足", reason

    # テクニカル
    df = df.copy()
    df['SMA25'] = df['Close'].rolling(25).mean()
    df['SMA75'] = df['Close'].rolling(75).mean()
    df['High20'] = df['Close'].rolling(20).max()
    df['High50'] = df['Close'].rolling(50).max()
    vol20 = df['Volume'].rolling(20).mean().iloc[-1]
    latest = df.iloc[-1]
    prev5 = df['Close'].iloc[-6]  # 5日前の終値

    # RSI
    delta = df['Close'].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = -delta.clip(upper=0).rolling(14).mean()
    rs = gain / loss
    rsi = (100 - (100 / (1 + rs))).iloc[-1]

    # O'Neil簡易（EPS成長）
    eps_growth = None
    if info:
        eps_growth = info.get('earningsQuarterlyGrowth')  # 例: 0.35 -> 35%
        # 追加: institutional holders / avgVolume etc available via info

    # ----- 除外ルール（高値掴み回避） -----
    # 75日線割れ
    if latest['Close'] < df['SMA75'].iloc[-1]:
        return 0, round(float(rsi),1), "75日線下", reason
    # RSI過熱
    if rsi is not None and rsi > 85:
        return 0, round(float(rsi),1), "RSI過熱", reason
    # 5日で急騰(例: +25%超)
    if (latest['Close'] / prev5 - 1) > 0.25:
        return 0, round(float(rsi),1), "短期急騰", reason

    # ----- トレンド（最大50点） -----
    # 株価 > 25日
    if latest['Close'] > df['SMA25'].iloc[-1]:
        score += 20; reason['trend_close>25'] = True
    # 25>75
    if df['SMA25'].iloc[-1] > df['SMA75'].iloc[-1]:
        score += 20; reason['trend_25>75'] = True
    # 直近20日高値更新（新高値）
    if latest['Close'] >= df['High20'].iloc[-1]:
        score += 10; reason['new_high20'] = True

    # ----- 出来高（最大30点） -----
    if latest['Volume'] > vol20 * 1.0:
        score += 15; reason['vol_above_avg'] = True
    if latest['Volume'] > df['Volume'].iloc[-2] * 1.3:
        score += 15; reason['vol_vs_prev'] = True

    # ----- 押し目耐性（最大20点） -----
    high20 = df['High20'].iloc[-1]
    if high20 > 0 and (high20 - latest['Close']) / high20 <= 0.10:
        score += 10; reason['small_pullback'] = True
    if (latest['Close'] - df['SMA25'].iloc[-1]) / df['SMA25'].iloc[-1] <= 0.15:
        score += 10; reason['sma25_gap_ok'] = True

    # ----- O'Neil簡易（追加点） -----
    if eps_growth is not None:
        try:
            if eps_growth > 0.25:
                score += 8; reason['eps_growth_25%'] = True
            elif eps_growth > 0.10:
                score += 4; reason['eps_growth_10%'] = True
        except:
            pass

    # ----- フォロー・スルー確認（信頼度上げる） -----
    # ブレイク日を終値で超えているか、直近2営業日のうち1回はブレイク以上で終わっているか
    # (ここではブレイク値 = 20日高値)
    breakout_price = df['High20'].iloc[-1]
    # Check if previous day or today closed >= breakout_price (i.e., follow-through)
    cond_follow = False
    try:
        if df['Close'].iloc[-1] >= breakout_price:
            cond_follow = True
        elif len(df) >= 2 and df['Close'].iloc[-2] >= breakout_price:
            cond_follow = True
    except:
        pass
    if cond_follow:
        score += 5; reason['follow_through'] = True
    else:
        # フォロー無い場合は減点小
        score -= 5; reason['no_follow_through'] = True

    # clamp score
    score = int(max(min(score, 100), 0))
    judge = "🟢 即エントリー" if score >= 85 else "🟡 押し目検討" if score >= 70 else "🔴 見送り"

    return score, round(float(rsi),1), judge, reason

def scan_codes_multibatch(codes_text):
    codes = [c.strip() for c in codes_text.splitlines() if c.strip()]
    if len(codes) == 0:
        st.warning("銘柄を1つ以上入力してください")
        return []
    if len(codes) > MAX_PER_RUN:
        st.warning(f"多数({len(codes)})の銘柄が指定されました。処理を分割して最初の {MAX_PER_RUN} 件のみ実行します。")
        codes = codes[:MAX_PER_RUN]

    # 価格を一括取得（効率的）
    hist_map = fetch_hist_batch(codes, period="6mo")
    results = []
    progress = st.progress(0)
    for i, code in enumerate(codes):
        df = hist_map.get(code)
        if df is None or df.empty:
            progress.progress((i+1)/len(codes)); continue
        # infoは個別取得（重いので必要最小限）
        info = None
        try:
            tk = yf.Ticker(f"{code}.T")
            info = tk.info
            # ちょっと待つとブロックされにくい
            time.sleep(0.12)
        except Exception:
            info = {}
        score, rsi, judge, reason = enhanced_breakout_score(df, info)
        results.append({
            "コード": code,
            "銘柄名": info.get('longName', code),
            "スコア": score,
            "RSI": rsi,
            "判定": judge,
            "理由": reason,
            "株価": round(df['Close'].iloc[-1],1)
        })
        progress.progress((i+1)/len(codes))
    progress.empty()
    return sorted(results, key=lambda x: x['スコア'], reverse=True)
