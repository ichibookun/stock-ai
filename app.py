# app_strict_breakout.py
import streamlit as st
import traceback
import time
import io

# 遅延インポート（起動安定化）
try:
    import yfinance as yf
    import pandas as pd
    import numpy as np
    import requests
    from bs4 import BeautifulSoup
except Exception as e:
    st.set_page_config(page_title="Error", layout="wide")
    st.title("ライブラリ読み込みエラー")
    st.error(traceback.format_exc())
    st.stop()

# ---------- 設定 ----------
st.set_page_config(page_title="Strict Breakout Scanner", layout="wide")
st.title("🚀 Strict 新高値ブレイクスキャナー（高勝率志向）")
st.caption("株探でコピーした52週高値一覧を改行で貼り付けて実行。最大50銘柄/回推奨。")

MAX_PER_RUN = 50  # 実用上の上限（変更可）
DEFAULT_PERIOD = "6mo"

# ---------- ユーティリティ ----------
def df_to_csv_bytes(df):
    buf = io.BytesIO()
    df.to_csv(buf, index=True)
    buf.seek(0)
    return buf.getvalue()

def has_japanese(text):
    if not text: return False
    import re
    return bool(re.search(r'[\u3040-\u30ff\u4e00-\u9fff]', text))

# ---------- 企業名取得（優先順: yfinance -> kabutan -> yahoojp） ----------
def get_company_name_jp(code):
    """
    code: '6758' のような4桁文字列
    試行順:
      1) yfinance.info.longName が日本語なら返す
      2) kabutan ページの <title> 等から抽出
      3) Yahoo!ファイナンス日本のページタイトルから抽出
    失敗時は code を返す
    """
    # 1) yfinance
    try:
        tk = yf.Ticker(f"{code}.T")
        info = tk.info
        ln = info.get("longName") or info.get("shortName") or ""
        if ln and has_japanese(ln):
            return ln
    except Exception:
        pass

    headers = {"User-Agent": "Mozilla/5.0 (compatible)"}
    # 2) Kabutan
    try:
        url_k = f"https://kabutan.jp/stock/?code={code}"
        r = requests.get(url_k, timeout=6, headers=headers)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            # タイトルに「企業名（XXX）」の形で入っていることが多い
            title = soup.title.string if soup.title else ""
            if title and has_japanese(title):
                # 先頭の日本語部分を抽出
                import re
                m = re.search(r'^[\s]*([\u3000-\u30FF\u4E00-\u9FFF\w\-\(\)]+)', title)
                if m:
                    cand = m.group(1).strip()
                    if has_japanese(cand):
                        return cand
            # さらにページ上の見出し要素を探す
            h1 = soup.select_one(".company_name") or soup.select_one("h1") or soup.select_one(".stock_name")
            if h1:
                text = h1.get_text(strip=True)
                if has_japanese(text):
                    return text
    except Exception:
        pass

    # 3) Yahoo!ファイナンス日本
    try:
        url_y = f"https://stocks.finance.yahoo.co.jp/stocks/detail/?code={code}.T"
        r = requests.get(url_y, timeout=6, headers=headers)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            title = soup.title.string if soup.title else ""
            if title and has_japanese(title):
                # タイトルの日本語部分を抽出（例: トヨタ自動車(7203)）
                import re
                m = re.search(r'([\u3000-\u30FF\u4E00-\u9FFF\w\-\s]+)\(', title)
                if m:
                    cand = m.group(1).strip()
                    if has_japanese(cand):
                        return cand
            # ページ内の特定要素を探す
            el = soup.select_one(".symbol") or soup.select_one(".symbol h1") or soup.select_one(".title")
            if el:
                text = el.get_text(strip=True)
                if has_japanese(text):
                    return text
    except Exception:
        pass

    # fallback
    return code

# ---------- 安全なヒストリ取得 ----------
def fetch_hist_batch_safe(codes, period=DEFAULT_PERIOD):
    tickers = [f"{c}.T" for c in codes]
    data = {}
    try:
        raw = yf.download(tickers, period=period, group_by='ticker', threads=True, progress=False)
    except Exception:
        raw = None
    if raw is None or len(codes) == 1:
        # 個別取得（確実）
        for c in codes:
            try:
                tk = yf.Ticker(f"{c}.T")
                df = tk.history(period=period)
                data[c] = df if not df.empty else None
                time.sleep(0.12)
            except Exception:
                data[c] = None
    else:
        for c in codes:
            key = f"{c}.T"
            try:
                df = raw[key].dropna(how='all').copy()
                data[c] = df if not df.empty else None
            except Exception:
                data[c] = None
    return data

# ---------- 厳格スコア（高勝率ルール） ----------
def strict_breakout_score(df, info=None):
    """
    厳格ルールでスコア化（0-100）
    - より厳格にして高得点を少数に絞る
    - 高値掴み回避の除外ルール多数
    """
    reason = []
    if df is None or len(df) < 70:
        return 0, None, "データ不足", "データ不足"

    d = df.copy()
    try:
        # 指標
        d['SMA25'] = d['Close'].rolling(25).mean()
        d['SMA75'] = d['Close'].rolling(75).mean()
        d['High20'] = d['Close'].rolling(20).max()
        d['High50'] = d['Close'].rolling(50).max()
        vol20 = d['Volume'].rolling(20).mean().iloc[-1]
        latest = d.iloc[-1]
        prev1 = d.iloc[-2]
        prev5 = d['Close'].iloc[-6]

        # RSI
        delta = d['Close'].diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = -delta.clip(upper=0).rolling(14).mean()
        rs = gain / loss
        rsi_now = float((100 - (100 / (1 + rs))).iloc[-1])

        # --- 除外条件（高値掴み回避: 強力） ---
        # 1) 75日線割れ
        if latest['Close'] < d['SMA75'].iloc[-1]:
            return 0, round(rsi_now,1), "除外", "75日線割れ"
        # 2) RSI過熱
        if rsi_now > 80:
            return 0, round(rsi_now,1), "除外", "RSI>80"
        # 3) 短期急騰（5日で+20%以上）
        if (latest['Close'] / prev5 - 1) > 0.20:
            return 0, round(rsi_now,1), "除外", "短期急騰>20%"
        # 4) 出来高低迷（ブレイクに裏付けがない）
        # (任意) we'll check later in scoring

        score = 0

        # ---- トレンド（40点） ----
        if latest['Close'] > d['SMA25'].iloc[-1]:
            score += 12; reason.append("Price>25")
        if d['SMA25'].iloc[-1] > d['SMA75'].iloc[-1]:
            score += 12; reason.append("25>75")
        # 20日新高（必須寄り）
        if latest['Close'] >= d['High20'].iloc[-1]:
            score += 16; reason.append("New20High")
        else:
            # 新高値でないなら厳格版は大幅に点を与えない
            score -= 10; reason.append("NoNew20High")

        # ---- 出来高（30点） ----
        # 厳格: 出来高はMA20の1.5倍以上を要求（強い裏付け）
        if vol20 and latest['Volume'] > vol20 * 1.5:
            score += 18; reason.append("Vol>1.5xMA20")
        elif vol20 and latest['Volume'] > vol20:
            score += 6; reason.append("Vol>MA20_weak")
        # 前日比での急増
        if latest['Volume'] > d['Volume'].iloc[-2] * 1.5:
            score += 12; reason.append("Vol>prev*1.5")
        elif latest['Volume'] > d['Volume'].iloc[-2] * 1.2:
            score += 4; reason.append("Vol>prev*1.2")

        # ---- 押し目耐性（20点） ----
        high20 = d['High20'].iloc[-1]
        if high20 > 0 and (high20 - latest['Close']) / high20 <= 0.07:
            score += 10; reason.append("Pullback<=7%")
        if (latest['Close'] - d['SMA25'].iloc[-1]) / d['SMA25'].iloc[-1] <= 0.10:
            score += 10; reason.append("Gap<=10%")

        # ---- フォロー・スルー（+10点） ----
        breakout_price = d['High20'].iloc[-1]
        cond_follow = False
        try:
            # today and/or yesterday close >= breakout
            if latest['Close'] >= breakout_price and prev1['Close'] >= breakout_price:
                cond_follow = True
                score += 10; reason.append("StrongFollow")
            elif latest['Close'] >= breakout_price or prev1['Close'] >= breakout_price:
                score += 5; reason.append("WeakFollow")
            else:
                # no follow -> penalize
                score -= 8; reason.append("NoFollow")
        except Exception:
            pass

        # ---- O'Neil 簡易加点（例: EPS成長） ----
        eps_growth = None
        if info:
            eps_growth = info.get('earningsQuarterlyGrowth')
            try:
                if eps_growth is not None:
                    if eps_growth > 0.5:
                        score += 6; reason.append("EPS>50%")
                    elif eps_growth > 0.2:
                        score += 3; reason.append("EPS>20%")
            except:
                pass

        # clamp
        score = int(max(min(score, 100), 0))
        judge = "🟢 即エントリー (厳格)" if score >= 90 else ("🟡 押し目検討" if score >= 78 else "🔴 見送り")
        return score, round(rsi_now,1), judge, ";".join(reason)

    except Exception as e:
        return 0, None, "エラー", str(e)

# ---------- スキャン処理（UI連携） ----------
st.markdown("---")
st.markdown("### 入力（改行区切り）")
codes_text = st.text_area("銘柄コード（改行区切り）", height=220, placeholder="例:\n6920\n8035\n6857")

col1, col2 = st.columns([1,1])
with col1:
    min_score = st.slider("最小スコア（これ以上のみ表示）", min_value=70, max_value=95, value=90, step=1,
                          help="高くすると候補が少なく、より勝率重視になります（推奨: 85〜95）")
with col2:
    use_jp_name = st.checkbox("日本語の正式社名を取得する（試行）", value=True)

run = st.button("🔍 厳格スキャン実行")

st.info("注意: 大量のティッカーを一度に処理すると遅延や取得失敗が起きます。推奨50銘柄/回。")

if run:
    try:
        codes = [c.strip() for c in codes_text.splitlines() if c.strip()]
        if not codes:
            st.warning("銘柄コードを1つ以上入力してください（改行区切り）")
        else:
            if len(codes) > MAX_PER_RUN:
                st.warning(f"指定数が多い({len(codes)})。最初の{MAX_PER_RUN}件で処理します。")
                codes = codes[:MAX_PER_RUN]

            with st.spinner("価格データを一括取得中..."):
                hist_map = fetch_hist_batch_safe(codes, period=DEFAULT_PERIOD)

            # 上位候補だけ info を取りに行く（効率化）
            results = []
            progress = st.progress(0)
            for i, code in enumerate(codes):
                df = hist_map.get(code)
                # 先に info を None にしておき、必要なら後でとる
                info = None
                try:
                    # 軽量取得（失敗しても続行）
                    tk = yf.Ticker(f"{code}.T")
                    info = tk.info
                    time.sleep(0.08)
                except:
                    info = {}
                score, rsi, judge, reason = strict_breakout_score(df, info)
                results.append({
                    "コード": code,
                    "銘柄名": (get_company_name_jp(code) if use_jp_name else (info.get("longName") or code)),
                    "スコア": score,
                    "RSI": rsi,
                    "判定": judge,
                    "理由": reason,
                    "株価": round(df['Close'].iloc[-1],1) if df is not None and not df.empty else None
                })
                progress.progress((i+1)/len(codes))
            progress.empty()

            df_res = pd.DataFrame(results).sort_values("スコア", ascending=False)
            # 絞り込み
            df_filtered = df_res[df_res["スコア"] >= int(min_score)]
            if df_filtered.empty:
                st.warning("指定の基準を満たす銘柄は見つかりませんでした。基準を下げるか、銘柄母集団を変更してください。")
            else:
                st.subheader("🏆 厳格スコア上位（絞り込み済）")
                st.dataframe(df_filtered, use_container_width=True)
                st.download_button("CSVダウンロード", data=df_to_csv_bytes(df_filtered), file_name="strict_breakout_results.csv", mime="text/csv")
    except Exception:
        st.error("処理中に例外が発生しました。詳細：")
        st.text(traceback.format_exc())
