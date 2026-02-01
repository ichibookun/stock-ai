import streamlit as st
import yfinance as yf
import pandas as pd
import time

# ==============================
# 設定
# ==============================
st.set_page_config(page_title="新高値ブレイク分析（日本語強化・点数表示版）", layout="wide")

# ==============================
# 日本語銘柄名辞書 (スクショ銘柄を重点追加 + 主要銘柄)
# ==============================
JP_NAME_MAP = {
    # --- スクリーンショット等の個別修正強化枠 ---
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
    "4452": "花王", "4503": "アステラス", "4506": "住友ファーマ",
    "4507": "塩野義製薬", "4523": "エーザイ", "4543": "テルモ",
    "4568": "第一三共", "4578": "大塚HD", "4661": "OLC", "4689": "LINEヤフー",
    "4704": "トレンド", "4751": "サイバー", "4755": "楽天G", "4901": "富士フイルム",
    "4902": "コニカミノルタ", "4911": "資生堂", "5019": "出光興産",
    "5101": "横浜ゴム", "5108": "ブリヂストン", "5201": "AGC", "5214": "日電硝",
    "5233": "太平洋セメ", "5301": "東海カボン", "5332": "TOTO", "5333": "日本ガイシ",
    "5401": "日本製鉄", "5406": "神戸製鋼", "5411": "JFE", "5631": "日本製鋼所",
    "5706": "三井金属", "5714": "DOWA",
    "5801": "古河電工", "5802": "住友電工", "5803": "フジクラ", "5831": "しずおかFG",
    "6098": "リクルート", "6103": "オークマ", "6113": "アマダ", "6146": "ディスコ",
    "6178": "日本郵政", "6273": "SMC", "6301": "コマツ", "6302": "住友重",
    "6305": "日立建機", "6326": "クボタ", "6361": "荏原", "6367": "ダイキン",
    "6471": "日本精工", "6472": "NTN", "6473": "ジェイテクト", "6479": "ミネベア",
    "6501": "日立", "6503": "三菱電機", "6504": "富士電機", "6506": "安川電機",
    "6526": "ソシオネクスト", "6532": "ベイカレント", "6645": "オムロン", "6674": "GSユアサ",
    "6701": "NEC", "6702": "富士通", "6723": "ルネサス", "6724": "エプソン",
    "6752": "パナソニック", "6753": "シャープ", "6758": "ソニーG", "6762": "TDK",
    "6770": "アルプスアル", "6841": "横河電機", "6857": "アドバンテスト", "6861": "キーエンス",
    "6902": "デンソー", "6920": "レーザーテク", "6954": "ファナック",
    "6963": "ローム", "6971": "京セラ", "6976": "太陽誘電", "6981": "村田製",
    "6988": "日東電工", "7004": "カナデビア", "7011": "三菱重工", "7012": "川崎重工",
    "7013": "IHI", "7186": "コンコルディア", "7201": "日産自", "7202": "いすゞ",
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
    "9503": "関西電", "9531": "東ガス", "9532": "大ガス", "9602": "東宝",
    "9735": "セコム", "9766": "コナミG", "9843": "ニトリHD", "9983": "ファストリ",
    "9984": "ソフトバンクG"
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

        # B. 直近ブレイク & 押し目判定 (期間10日)
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
                # ブレイク日以降の最高値 (昨日・当日含む)
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
            
            # 【重要】辞書完全優先
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
# スコア計算 (Total / CANSLIM)
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
    # C. トレンド (20点) - MA25 > MA75
    if stock["ma25"] > stock["ma75"]: score += 20
    # D. モメンタム (10点)
    if stock["momentum_3m"] >= 0.15: score += 10
    return score

def calc_canslim_score(stock):
    score = 0
    # C (20点)
    eg = stock.get("earnings_q_growth")
    if eg and eg >= 0.20: score += 20
    # A (20点)
    te = stock.get("trailing_eps"); fe = stock.get("forward_eps")
    if te and fe and te != 0:
        if (fe - te) / abs(te) >= 0.15: score += 20
    # N (20点)
    if stock["broke_today"] or stock["broke_recent"]: score += 20
    # S (20点)
    vr = stock["volume"] / stock["avg_volume"] if stock["avg_volume"] > 0 else 0
    if vr >= 1.5: score += 20
    # L (20点)
    if stock["momentum_3m"] >= 0.15: score += 20
    return score

# ==============================
# 判定ロジック (押し目条件の緩和と見える化)
# ==============================
def judge_action(stock, total_score):
    vr = stock["volume"] / stock["avg_volume"] if stock["avg_volume"] > 0 else 0
    
    # 1. 急騰警告
    if stock["broke_today"] and stock["breakout_divergence"] > 0.05:
        return "📈 急騰 (過熱)"

    # 2. 即買い
    if stock["broke_today"] and total_score >= 90 and vr >= 2.0:
        return "🟢 即買い"

    # 3. 押し目待ち
    # 条件: 直近ブレイクあり & 下落率2~8% & 25日線の上 & スコア50以上
    if stock["broke_recent"]:
        pb = stock["pullback_pct"]
        if 0.02 <= pb <= 0.08 and stock["close"] > stock["ma25"] and total_score >= 50:
            return "🟡 押し目待ち"
            
    # その他
    if stock["broke_today"]:
        return "⚪ ブレイク(弱)"
        
    return "⚪ 監視中"

def make_reason(stock):
    reasons = []
    
    # ブレイク状況
    if stock["broke_today"]:
        div = stock["breakout_divergence"] * 100
        if div > 5: reasons.append(f"高値更新(+{div:.1f}%過熱)")
        else: reasons.append("本日高値更新")
    elif stock["broke_recent"]:
        reasons.append("直近高値更新")
    
    # 押し目状況のデバッグ表示
    if stock["broke_recent"]:
        pb = stock["pullback_pct"]
        pb_display = pb * 100
        
        if 0.02 <= pb <= 0.08:
            if stock["close"] > stock["ma25"]:
                reasons.append(f"押し目(-{pb_display:.1f}%)")
            else:
                reasons.append(f"押し目(-{pb_display:.1f}%だが25日線割れ)")
        elif pb < 0.02:
            reasons.append(f"調整不足(-{pb_display:.1f}%)")
        else:
            reasons.append(f"調整深すぎ(-{pb_display:.1f}%)")
    
    # 出来高
    vr = stock["volume"] / stock["avg_volume"] if stock["avg_volume"] > 0 else 0
    if vr >= 2.0: reasons.append(f"出来高{vr:.1f}倍(強)")
    elif vr >= 1.5: reasons.append(f"出来高{vr:.1f}倍")
    
    return " / ".join(reasons) if reasons else "-"

# ==============================
# UI
# ==============================
st.title("📈 新高値ブレイク分析 (Ver 27.0)")
st.caption("オニール流厳格基準 / CANSLIM点数化 / 日本語完全版")

st.markdown("""
- **🟢 即買い**: スコア90以上、出来高2倍、本日高値更新(+5%以内)
- **🟡 押し目**: 直近高値更新後、2%~8%の調整中 (25日線の上)
- **📈 急騰**: 高値更新だが+5%以上乖離 (高値掴み注意)
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
                action = judge_action(data, t_score)
                reason = make_reason(data)
                
                # チャート直リンク
                url = f"https://kabutan.jp/stock/chart?code={data['symbol']}"
                link = f'<a href="{url}" target="_blank" style="text-decoration:none;font-weight:bold;color:#1E90FF;">チャート</a>'
                
                judge_html = action
                if "即買い" in action: judge_html = f'<span style="color:green;font-weight:bold;">{action}</span>'
                elif "押し目" in action: judge_html = f'<span style="color:#DAA520;font-weight:bold;">{action}</span>'
                elif "急騰" in action: judge_html = f'<span style="color:red;font-weight:bold;">{action}</span>'

                rows.append({
                    "Check": link,
                    "Code": data['symbol'],
                    "Name": data['name'],
                    "Price": f"{data['close']:,.0f}",
                    "Judge": judge_html,
                    "Total Score": t_score,
                    "CANSLIM": c_score, # 数値化
                    "Reason": reason,
                    "Vol Ratio": f"{data['volume']/data['avg_volume']:.1f}x" if data['avg_volume']>0 else "-"
                })
        
        bar.empty()
        
        if rows:
            df = pd.DataFrame(rows).sort_values("Total Score", ascending=False)
            st.success(f"{len(df)} 銘柄の分析完了")
            st.write(df.to_html(escape=False, index=False), unsafe_allow_html=True)
        else:
            st.error("データなし")
