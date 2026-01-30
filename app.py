// ==============================
// 新高値ブレイク判定ツール
// 最終・簡易完成版
// ==============================

const express = require("express");
const app = express();
app.use(express.json());

// ------------------------------
// 仮データ取得（ここをAPIに差し替える）
// ------------------------------
function fetchStockData(symbol) {
  // symbol: 銘柄コード or 名前（今はダミー）
  return {
    symbol,
    name: symbol.match(/^\d{4}$/) ? `銘柄${symbol}` : symbol,
    close: 1020,
    high52: 1050,
    volume: 200000,
    avgVolume: 100000,
    ma25: 980,
    ma75: 900,
    epsGrowth: 35,
    salesGrowth: 25,
    roe: 18
  };
}

// ------------------------------
// 判定ロジック
// ------------------------------
function is52WeekHigh(stock) {
  return stock.close >= stock.high52 * 0.97;
}

function volumeRatio(stock) {
  return stock.volume / stock.avgVolume;
}

function isOverExtended(stock) {
  return (stock.high52 - stock.close) / stock.high52 < 0.03;
}

// ------------------------------
// スコア計算（超厳しめ）
// ------------------------------
function calcScore(stock) {
  let score = 0;

  if (is52WeekHigh(stock)) score += 30;
  if (volumeRatio(stock) >= 1.5) score += 20;
  if (stock.ma25 > stock.ma75) score += 10;
  if (stock.epsGrowth >= 20) score += 20;
  if (stock.salesGrowth >= 15) score += 20;

  return score;
}

// ------------------------------
// 行動判定
// ------------------------------
function judgeAction(stock) {
  const vol = volumeRatio(stock);

  if (vol >= 1.8 && isOverExtended(stock)) return "🟢 即買い";
  if (vol < 1.8 && vol >= 1.2) return "🟡 押し目待ち";
  return "⚪ 見送り";
}

// ------------------------------
// 理由（日本語・端的）
// ------------------------------
function makeReason(stock, action) {
  if (action === "🟢 即買い") {
    return "52週高値を出来高を伴って更新しており、初動ブレイクと判断されます。";
  }
  if (action === "🟡 押し目待ち") {
    return "高値圏を維持していますが過熱感はなく、押し目形成後のエントリーが有効です。";
  }
  return "出来高やトレンド条件が不足しており、優位性が低いため見送りが妥当です。";
}

// ------------------------------
// メインAPI
// ------------------------------
app.post("/analyze", (req, res) => {
  try {
    const input = req.body.symbols || "";
    const symbols = input
      .split("\n")
      .map(s => s.trim())
      .filter(Boolean);

    if (symbols.length === 0) {
      return res.json({ results: [], message: "銘柄を入力してください。" });
    }

    const results = [];

    symbols.forEach(symbol => {
      const stock = fetchStockData(symbol);

      // 必須条件
      if (!is52WeekHigh(stock)) return;
      if (stock.ma25 <= stock.ma75) return;
      if (!isOverExtended(stock)) return;

      const score = calcScore(stock);
      if (score < 85) return;

      const action = judgeAction(stock);

      results.push({
        symbol: stock.symbol,
        name: stock.name,
        score,
        action,
        reason: makeReason(stock, action)
      });
    });

    res.json({
      count: results.length,
      results
    });

  } catch (e) {
    res.status(500).json({ error: "分析中にエラーが発生しました。" });
  }
});

// ------------------------------
// 起動
// ------------------------------
app.listen(3000, () => {
  console.log("新高値ブレイク分析サーバー起動中 : http://localhost:3000");
});
