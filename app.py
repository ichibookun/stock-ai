import streamlit as st
import yfinance as yf
import pandas as pd
import time
import re

# ==============================
# 設定・定数定義
# ==============================
st.set_page_config(page_title="新高値ブレイク分析（CSV出力機能付）", layout="wide")

# 判定基準の閾値
SCORE_IMMEDIATE_BUY = 90   # 即買いの最低スコア
VOL_RATIO_IMMEDIATE = 2.0  # 即買いの出来高倍率
SCORE_WATCH = 80           # 監視・押し目の最低スコア
DIP_MIN = 0.03             # 押し目の下落率下限 (3%)
DIP_MAX = 0.07             # 押し目の下落率上限 (7%)
OVERHEAT_THRESHOLD = 0.05  # ブレイクラインからの乖離率上限 (5%ルール)

# ==============================
# ヘルパー関数: 安全な数値変換
# ==============================
def safe_float(value):
    """
    あらゆる型の値を安全にfloatに変換する。
    None, 文字列("%"や","含む), "-" などを0.0として処理し、エラーを防ぐ。
    """
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        # 不要な文字を除去 (%,カンマ,空白)
        clean_val = value.replace('%', '').replace(',', '').strip()
        # ハイフンのみや空文字は0とする
        if clean_val == '-' or clean_val == '':
            return 0.0
        try:
            return float(clean_val)
        except ValueError:
            return 0.0
    return 0.0

# ==============================
# 日本語銘柄名辞書 (完全版・変更なし)
# ==============================
JP_NAME_MAP = {
    # --- 個別修正・強化枠 ---
    "6742": "京三製作所", "7112": "キューブ", "5187": "クリエートメディック",
    "5741": "UACJ", "5713": "住友金属鉱山", "6366": "千代田化工建設",
    "6481": "THK", "6617": "東光高岳", "6197": "ソラスト", "6059": "ウチヤマHD",
    "4972": "綜研化学", "6794": "フォスター電機", "4659": "エイジス",
    "6268": "ナブテスコ", "5711": "三菱マテリアル", "4634": "artience",
    "4519": "中外製薬", "5204": "石塚硝子", "5252": "日本ナレッジ",
    "6952": "カシオ計算機", "6858": "小野測器", "7022": "サノヤスHD",
    "6998": "日本タングステン", "5984": "兼房", "5834": "SBIリーシング",
    "6787": "メイコー", "6349": "小森コーポレーション", "5021": "コスモエネルギー",
    "4410": "ハリマ化成", "4502": "武田薬品", "5020": "ENEOS",
    
    # --- ユーザー提供リスト (主要銘柄群) ---
    "1332": "ニッスイ", "1605": "INPEX", "1721": "コムシスHD", "1801": "大成建設",
    "1802": "大林組", "1803": "清水建設", "1808": "長谷工", "1812": "鹿島",
    "1925": "大和ハウス", "1928": "積水ハウス", "1963": "日揮HD", "2002": "日清製粉G",
    "2269": "明治HD", "2282": "日本ハム", "2413": "エムスリー", "2432": "DeNA",
    "2501": "サッポロHD", "2502": "アサヒGHD", "2503": "キリンHD", "2768": "双日",
    "2801": "キッコーマン", "2802": "味の素", "2871": "ニチレイ", "2914": "JT",
    "3086": "Jフロント", "3092": "ZOZO", "3099": "三越伊勢丹", "3289": "東急不HD",
    "3382": "セブン&アイ", "3401": "帝人", "3402": "東レ", "3405": "クラレ",
    "3407": "旭化成", "3436": "SUMCO", "3659": "ネクソン", "3697": "SHIFT",
    "3861": "王子HD", "4004": "レゾナック", "4005": "住友化学", "4021": "日産化学",
    "4042": "東ソー", "4043": "トクヤマ", "4061": "デンカ", "4062": "イビデン",
    "4063": "信越化学", "4151": "協和キリン", "4183": "三井化学", "4188": "三菱ケミカル",
    "4208": "UBE", "4307": "NRI", "4324": "電通G", "4385": "メルカリ",
    "4452": "花王", "4502": "武田薬品", "4503": "アステラス", "4506": "住友ファーマ",
    "4507": "塩野義製薬", "4519": "中外製薬", "4523": "エーザイ", "4543": "テルモ",
    "4568": "第一三共", "4578": "大塚HD", "4661": "OLC", "4689": "LINEヤフー",
    "4704": "トレンド", "4751": "サイバー", "4755": "楽天G", "4901": "富士フイルム",
    "4902": "コニカミノルタ", "4911": "資生堂", "5019": "出光興産", "5020": "ENEOS",
    "5101": "横浜ゴム", "5108": "ブリヂストン", "5201": "AGC", "5214": "日電硝",
    "5233": "太平洋セメ", "5301": "東海カボン", "5332": "TOTO", "5333": "日本ガイシ",
    "5401": "日本製鉄", "5406": "神戸製鋼", "5411": "JFE", "5631": "日本製鋼所",
    "5706": "三井金属", "5711": "三菱マテリアル", "5713": "住友鉱", "5714": "DOWA",
    "5801": "古河電工", "5802": "住友電工", "5803": "フジクラ", "5831": "しずおかFG",
    "6098": "リクルート", "6103": "オークマ", "6113": "アマダ", "6146": "ディスコ",
    "6178": "日本郵政", "6273": "SMC", "6301": "コマツ", "6302": "住友重",
    "6305": "日立建機", "6326": "クボタ", "6337": "テセック", "6349": "小森コーポ",
    "6361": "荏原", "6367": "ダイキン", "6370": "栗田工業", "6471": "日本精工",
    "6472": "NTN", "6473": "ジェイテクト", "6479": "ミネベア", "6490": "日本ピラー",
    "6501": "日立", "6503": "三菱電機", "6504": "富士電機", "6506": "安川電機",
    "6526": "ソシオネクスト", "6532": "ベイカレント", "6645": "オムロン", "6674": "GSユアサ",
    "6701": "NEC", "6702": "富士通", "6723": "ルネサス", "6724": "エプソン",
    "6752": "パナソニック", "6753": "シャープ", "6758": "ソニーG", "6762": "TDK",
    "6770": "アルプスアル", "6787": "メイコー", "6841": "横河電機", "6857": "アドバンテスト",
    "6858": "小野測器", "6861": "キーエンス", "6902": "デンソー", "6920": "レーザーテク",
    "6952": "カシオ", "6954": "ファナック", "6963": "ローム", "6971": "京セラ",
    "6976": "太陽誘電", "6981": "村田製", "6988": "日東電工", "6998": "日本タングス",
    "7004": "カナデビア", "7011": "三菱重工", "7012": "川崎重工", "7013": "IHI",
    "7022": "サノヤスHD", "7186": "コンコルディア", "7201": "日産自", "7202": "いすゞ",
    "7203": "トヨタ", "7205": "日野自", "7211": "三菱自", "7261": "マツダ",
    "7267": "ホンダ", "7269": "スズキ", "7270": "SUBARU", "7272": "ヤマハ発",
    "7453": "良品計画", "7731": "ニコン", "7733": "オリンパス", "7735": "SCREEN",
    "7741": "HOYA", "7751": "キヤノン", "7752": "リコー", "7832": "バンナムHD",
    "7911": "TOPPAN", "7912": "大日印", "7951": "ヤマハ", "7974": "任天堂",
    "8001": "伊藤忠", "8002": "丸紅", "8015": "豊田通商", "8031": "三井物産",
    "8035": "東エレク", "8053": "住友商事", "8058": "三菱商事", "8233": "高島屋",
    "8252": "丸井G", "8253": "クレセゾン", "8267": "イオン", "8304": "あおぞら",
    "8306": "三菱UFJ", "8308": "りそなHD", "8309": "三井住友トラ", "8316": "三井住友FG",
    "8331": "千葉銀", "8354": "ふくおかFG", "8411": "みずほ", "8591": "オリックス",
    "8601": "大和証G", "8604": "野村HD", "8630": "SOMPO", "8697": "JPX",
    "8725": "MS&AD", "8750": "第一生命", "8766": "東京海上", "8795": "T&D",
    "8801": "三井不", "8802": "三菱地所", "8804": "東京建物", "8830": "住友不",
    "9001": "東武", "9005": "東急", "9007": "小田急", "9008": "京王",
    "9009": "京成", "9020": "JR東日本", "9021": "JR西日本", "9022": "JR東海",
    "9064": "ヤマトHD", "9101": "郵船", "9104": "商船三井", "9107": "川崎汽",
    "9147": "NXHD", "9201": "JAL", "9202": "ANA", "9432": "NTT",
    "9433": "KDDI", "9434": "ソフトバンク", "9501": "東電HD", "9502": "中部電",
    "9503": "関西電", "9504": "中国電", "9505": "北陸電", "9506": "東北電",
    "9507": "四国電", "9508": "九州電", "9509": "北海道電", "9511": "沖縄電",
    "9513": "電源開発", "9514": "エフオン", "9517": "イーレックス", "9519": "レノバ",
    "9531": "東ガス", "9532": "大ガス", "9602": "東宝", "9735": "セコム",
    "9766": "コナミG", "9843": "ニトリHD", "9983": "ファストリ", "9984": "ソフトバンクG",
    "9997": "ベルーナ"
}

# ==============================
# データ取得関数
# ==============================
@st.cache_data(ttl=3600)
def fetch_stock_data(symbol):
    code = str(symbol).strip()
    
    # 【必須】日本株フィルタリング (数字4桁のみ許可)
    if not re.fullmatch(r'\d{4}', code):
        return None

    ticker = f"{code}.T"
    try:
        tk = yf.Ticker(ticker)
        # 過去2年分
        hist = tk.history(period="2y", actions=False)
        if hist is None or hist.empty or len(hist) < 60:
            return None

        # --- データ処理 ---
        close = float(hist["Close"].iloc[-1])
        volume = int(hist["Volume"].iloc[-1])
        
        # 52週高値 (直前まで)
        window = min(252, len(hist))
        prev_high52 = hist["High"].iloc[-(window + 1):-1].max()

        ma25 = float(hist["Close"].rolling(25).mean().iloc[-1])
        ma75 = float(hist["Close"].rolling(75).mean().iloc[-1])
        avg_volume = float(hist["Volume"].rolling(20).mean().iloc[-1])

        # A. 当日ブレイク判定
        broke_today = close > prev_high52
        breakout_divergence = (close - prev_high52) / prev_high52 if prev_high52 > 0 else 0

        # B. 直近ブレイク & 押し目判定
        recent_window = min(10, len(hist)-1)
        recent_closes = hist["Close"].iloc[-(recent_window+1):-1]
        
        broke_recent = False
        pullback_pct = 0.0
        
        if recent_window > 0:
            broke_indices = recent_closes[recent_closes > prev_high52].index
            if len(broke_indices) > 0:
                broke_recent = True
                last_idx = broke_indices[-1]
                start = hist.index.get_loc(last_idx)
                # ブレイク日以降の最高値を探索
                max_val = hist["Close"].iloc[start:].max()
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
            
            # 【絶対優先】辞書にあればそれを使う
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
# スコア計算
# ==============================

def calc_total_score(stock):
    score = 0
    # A. ブレイク (40点)
    if stock["broke_today"]: score += 40
    elif stock["broke_recent"]: score += 30
    
    # B. 出来高 (30点)
    vr = stock["volume"] / stock["avg_volume"] if stock["avg_volume"] > 0 else 0
    if vr >= 2.0: score += 30
    elif vr >= 1.5: score += 20
    
    # C. トレンド (20点)
    if stock["ma25"] > stock["ma75"]:
        score += 20
    
    # D. モメンタム (10点)
    if stock["momentum_3m"] >= 0.15:
        score += 10
        
    return score

def calc_canslim_score(stock):
    score = 0
    eg = safe_float(stock.get("earnings_q_growth"))
    if eg >= 0.20: score += 20
    
    te = safe_float(stock.get("trailing_eps"))
    fe = safe_float(stock.get("forward_eps"))
    if te != 0:
        if (fe - te) / abs(te) >= 0.15: score += 20
        
    if stock["broke_today"] or stock["broke_recent"]: score += 20
    
    vr = stock["volume"] / stock["avg_volume"] if stock["avg_volume"] > 0 else 0
    if vr >= 1.5: score += 20
    
    if stock["momentum_3m"] >= 0.15: score += 20
    return score

def get_canslim_details(stock):
    details = []
    
    # C: 四半期成長
    if safe_float(stock.get("earnings_q_growth")) >= 0.20:
        details.append("C")
        
    # A: 年間成長
    te = safe_float(stock.get("trailing_eps"))
    fe = safe_float(stock.get("forward_eps"))
    if te != 0:
        if (fe - te) / abs(te) >= 0.15:
            details.append("A")
            
    # N: 新高値
    if stock["broke_today"] or stock["broke_recent"]:
        details.append("N")
        
    # S: 出来高
    if (stock["volume"] / stock["avg_volume"]) >= 1.5:
        details.append("S")
        
    # L: モメンタム
    if stock["momentum_3m"] >= 0.15:
        details.append("L")
        
    return "-".join(details) if details else "-"

# ==============================
# シグナル判定ロジック
# ==============================
def judge_signal(stock, score):
    vr = stock["volume"] / stock["avg_volume"] if stock["avg_volume"] > 0 else 0
    
    # 共通足切り: トレンド弱 or 25日線割れ
    is_uptrend = (stock["ma25"] > stock["ma75"]) and (stock["close"] > stock["ma25"])
    if not is_uptrend:
        return "⚪ 対象外(トレンド弱)"

    # 1. 【即買い】
    if score >= SCORE_IMMEDIATE_BUY and vr >= VOL_RATIO_IMMEDIATE:
        if stock["broke_today"] and stock["breakout_divergence"] > OVERHEAT_THRESHOLD:
            return "📈 急騰(過熱注意)"
        return "🟢 即買い"

    # 2. 【押し目買い】
    pb = stock["pullback_pct"]
    if score >= SCORE_WATCH and DIP_MIN <= pb <= DIP_MAX:
        return "🟡 押し目買い"

    # 3. 【監視：押し目待ち】
    if score >= SCORE_WATCH:
        return "👀 監視(押し目待ち)"

    return "⚪ 監視中(スコア不足)"

def make_reason(stock):
    reasons = []
    if stock["broke_today"]:
        div = stock["breakout_divergence"] * 100
        reasons.append(f"高値更新(乖離+{div:.1f}%)")
    elif stock["broke_recent"]:
        pb = stock["pullback_pct"] * 100
        reasons.append(f"直近更新(現在-{pb:.1f}%)")
    
    vr = stock["volume"] / stock["avg_volume"] if stock["avg_volume"] > 0 else 0
    if vr >= 2.0: reasons.append(f"出来高{vr:.1f}倍")
    elif vr >= 1.5: reasons.append(f"出来高増")
    
    return " / ".join(reasons) if reasons else "-"

# ==============================
# UI
# ==============================
st.title("📈 新高値ブレイク分析 (Ver 29.0)")
st.caption("オニール流シグナル判定 / CSVダウンロード機能付き")

st.markdown("""
- **🟢 即買い**: スコア90点以上、出来高2倍以上、強力な上昇トレンド
- **🟡 押し目買い**: 上昇トレンド中、高値から3%~7%の健全な調整中
- **👀 監視(押し目待ち)**: ファンダ・トレンド良好だが、今は過熱中または出来高不足。調整を待つ。
""")

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
6349
6742
7112
5187
5741
5713
6366
6481
6617
6197
6059
4972
6794
4659
6268
5711
4634"""

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
                c_score = calc_canslim_score(data)
                canslim_det = get_canslim_details(data)
                signal = judge_signal(data, t_score)
                reason = make_reason(data)
                
                url = f"https://kabutan.jp/stock/chart?code={data['symbol']}"
                link = f'<a href="{url}" target="_blank" style="text-decoration:none;font-weight:bold;color:#1E90FF;">チャート</a>'
                
                sig_html = signal
                if "即買い" in signal: sig_html = f'<span style="color:green;font-weight:bold;">{signal}</span>'
                elif "押し目買い" in signal: sig_html = f'<span style="color:#DAA520;font-weight:bold;">{signal}</span>'
                elif "監視" in signal: sig_html = f'<span style="color:#1E90FF;font-weight:bold;">{signal}</span>'
                elif "急騰" in signal: sig_html = f'<span style="color:red;font-weight:bold;">{signal}</span>'

                rows.append({
                    "Link": link,
                    "Code": data['symbol'],
                    "Name": data['name'],
                    "Price": f"{data['close']:,.0f}",
                    "Signal": sig_html,
                    "Score": t_score,
                    "CANSLIM": c_score,
                    "Elements": canslim_det,
                    "Reason": reason,
                    "Vol Ratio": f"{data['volume']/data['avg_volume']:.1f}x" if data['avg_volume']>0 else "-"
                })
        
        bar.empty()
        
        if rows:
            df = pd.DataFrame(rows)
            df = df.sort_values("Score", ascending=False)
            st.success(f"{len(df)} 銘柄の分析完了")
            
            # --- CSVダウンロード機能 (追加) ---
            # 「即買い」シグナルを含む銘柄のみ抽出
            buy_df = df[df['Signal'].str.contains('即買い', na=False)].copy()
            
            if not buy_df.empty:
                # 必要な列を抽出・リネーム
                csv_data = buy_df[['Code', 'Name', 'Score', 'CANSLIM', 'Price']].rename(columns={
                    'Code': 'コード',
                    'Name': '銘柄名',
                    'Score': 'スコア',
                    'CANSLIM': 'CANSLIM',
                    'Price': '現在値'
                })
                
                # CSV変換 (utf-8)
                csv = csv_data.to_csv(index=False, encoding='utf-8')
                
                st.download_button(
                    label="📥 即買い銘柄をCSVでダウンロード",
                    data=csv,
                    file_name="immediate_buy_stocks.csv",
                    mime="text/csv"
                )
            # -----------------------------------

            st.write(df.to_html(escape=False, index=False), unsafe_allow_html=True)
        else:
            st.error("データなし")
