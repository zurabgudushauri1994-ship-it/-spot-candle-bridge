/**
 * Cloudflare Worker: public, read-only Bybit spot candle bridge.
 * Deploy with `npx wrangler deploy`; no exchange credentials are used.
 */

const BYBIT_KLINE = "https://api.bybit.com/v5/market/kline";
const FRAMES = { "15m": ["15", 15], "1h": ["60", 60], "4h": ["240", 240] };
const DEFAULT_SYMBOLS = ["PUMPUSDT", "ALGOUSDT", "NEARUSDT", "ICPUSDT", "BTCUSDT", "SOLUSDT", "TIAUSDT"];
const MAX_SYMBOLS = 8;
const COUNT = 200;
const HISTORY_LIMIT = 1000;
const SCAN_UNIVERSE = 16;
const SCAN_MULTITIMEFRAME = 8;

function symbolsFrom(request) {
  const raw = new URL(request.url).searchParams.get("symbols");
  const symbols = (raw ? raw.split(",") : DEFAULT_SYMBOLS)
    .map((value) => value.trim().toUpperCase())
    .filter((value) => /^[A-Z0-9]{3,24}$/.test(value));
  return [...new Set(symbols)].slice(0, MAX_SYMBOLS);
}

function closedRows(rows, minutes, nowMs) {
  return rows
    .map((row) => [Number(row[0]), ...row.slice(1, 6).map(String)])
    .filter((row) => row[0] + minutes * 60_000 <= nowMs - 5_000)
    .sort((a, b) => a[0] - b[0])
    .slice(-COUNT);
}

async function oneFrame(symbol, label, nowMs) {
  const [interval, minutes] = FRAMES[label];
  const url = new URL(BYBIT_KLINE);
  url.search = new URLSearchParams({ category: "spot", symbol, interval, limit: String(COUNT + 2), end: String(Math.floor(nowMs / 10_000) * 10_000) });
  let response;
  for (let attempt = 0; attempt < 2; attempt++) {
    response = await fetch(url, { headers: { accept: "application/json", "user-agent": "SpotCandleBridge/2.0" }, cf: { cacheTtlByStatus: { "200-299": 10, "400-599": -1 }, cacheEverything: true } });
    if (response.ok || (response.status !== 403 && response.status < 500)) break;
    if (attempt === 0) {
      await response.body?.cancel();
      await new Promise((resolve) => setTimeout(resolve, 300));
      url.searchParams.set("end", String(nowMs - 1000));
    }
  }
  if (!response.ok) throw new Error(`Bybit HTTP ${response.status} (${symbol} ${label})`);
  const payload = await response.json();
  if (payload.retCode !== 0 || !Array.isArray(payload.result?.list)) throw new Error(`Bybit ${payload.retCode ?? "bad response"}`);
  const rows = closedRows(payload.result.list, minutes, nowMs);
  if (rows.length < 30) throw new Error("too few completed candles");
  return rows;
}

async function historicalFrame(symbol, interval, start, end, nowMs) {
  const minutes = { "15": 15, "60": 60, "240": 240 }[interval];
  if (!minutes) throw new Error("interval must be 15, 60 or 240");
  const url = new URL(BYBIT_KLINE);
  url.search = new URLSearchParams({ category: "spot", symbol, interval, limit: String(HISTORY_LIMIT), start: String(start), end: String(Math.min(end, nowMs)) });
  const response = await fetch(url, { headers: { accept: "application/json", "user-agent": "SpotCandleBridge/2.0" }, cf: { cacheTtlByStatus: { "200-299": 60, "400-599": -1 }, cacheEverything: true } });
  if (!response.ok) throw new Error(`Bybit HTTP ${response.status}`);
  const payload = await response.json();
  if (payload.retCode !== 0 || !Array.isArray(payload.result?.list)) throw new Error(`Bybit ${payload.retCode ?? "bad response"}`);
  return closedRows(payload.result.list, minutes, nowMs);
}

async function tickers() {
  const url = "https://api.bybit.com/v5/market/tickers?category=spot";
  const response = await fetch(url, { headers: { accept: "application/json", "user-agent": "SpotCandleBridge/2.0" }, cf: { cacheTtlByStatus: { "200-299": 20, "400-599": -1 }, cacheEverything: true } });
  if (!response.ok) throw new Error(`Bybit tickers HTTP ${response.status}`);
  const payload = await response.json();
  if (payload.retCode !== 0 || !Array.isArray(payload.result?.list)) throw new Error("invalid ticker response");
  return payload.result.list;
}

async function orderbook(symbol) {
  const url = new URL("https://api.bybit.com/v5/market/orderbook");
  url.search = new URLSearchParams({ category: "spot", symbol, limit: "50" });
  const response = await fetch(url, { headers: { accept: "application/json", "user-agent": "SpotCandleBridge/2.0" }, cf: { cacheTtlByStatus: { "200-299": 5, "400-599": -1 }, cacheEverything: true } });
  if (!response.ok) throw new Error(`Bybit orderbook HTTP ${response.status}`);
  const payload = await response.json();
  if (payload.retCode !== 0) throw new Error("invalid orderbook response");
  const bids = payload.result?.b ?? [], asks = payload.result?.a ?? [];
  const sum = (side) => side.reduce((total, row) => total + Number(row[0]) * Number(row[1]), 0);
  return { bid_depth_usdt: sum(bids), ask_depth_usdt: sum(asks) };
}

async function oneSymbol(symbol, nowMs) {
  try {
    const entries = await Promise.all(Object.keys(FRAMES).map(async (frame) => [frame, await oneFrame(symbol, frame, nowMs)]));
    const frames = Object.fromEntries(entries);
    const closed_utc_ms = Object.fromEntries(Object.entries(FRAMES).map(([frame, [, minutes]]) => [frame, frames[frame].at(-1)[0] + minutes * 60_000]));
    return { status: "ok", source: "bybit_spot", closed_utc_ms, fresh: Object.fromEntries(Object.entries(closed_utc_ms).map(([frame, end]) => [frame, nowMs - end <= FRAMES[frame][1] * 120_000])), frames };
  } catch (error) {
    return { status: "unavailable", source: null, reason: String(error.message || error), frames: {} };
  }
}


/**
 * Dedicated Bybit USDT perpetual reader. Never substitutes spot candles.
 * Read-only and no API credentials. /perp returns closed OHLCV bars.
 */
async function perpetualSnapshot(nowMs) {
  const symbol = "PUMPFUNUSDT";
  const frames = { "1m": ["1", 1, 120], "15m": ["15", 15, 180], "1h": ["60", 60, 120], "4h": ["240", 240, 90] };
  const entries = await Promise.all(Object.entries(frames).map(async ([name, [interval, minutes, count]]) => {
    const url = new URL(BYBIT_KLINE);
    url.search = new URLSearchParams({category: "linear", symbol, interval, limit: String(count + 3)});
    const resp = await fetch(url, {
      headers: {accept: "application/json", "user-agent": "PUMP-Perp-Reader/1.0"},
      cf: {cacheTtlByStatus: {"200-299": 10, "400-599": -1}, cacheEverything: true}
    });
    if (!resp.ok) throw new Error("Bybit perpetual HTTP " + resp.status + " (" + name + ")");
    const payload = await resp.json();
    if (payload.retCode !== 0 || payload.result?.symbol !== symbol || payload.result?.category !== "linear" || !Array.isArray(payload.result?.list))
      throw new Error("Bybit perpetual wrong symbol/category or invalid response (" + name + ")");
    const values = closedRows(payload.result.list, minutes, nowMs).slice(-count);
    if (values.length < 20) throw new Error("Insufficient closed candles (" + name + ")");
    const step = minutes * 60000;
    for (let i = 1; i < values.length; i++) {
      if (values[i][0] - values[i-1][0] !== step) throw new Error("Missing perpetual candles (" + name + ")");
    }
    for (const row of values) {
      const [, a, h, l, c, v] = row.map(Number);
      if (!(l > 0 && l <= Math.min(a,c) && h >= Math.max(a,c) && v >= 0)) throw new Error("Invalid perpetual OHLCV");
    }
    if (nowMs - (values.at(-1)[0] + step) > (2 * step + 120000))
      throw new Error("Stale perpetual bars (" + name + ")");
    return [name, values];
  }));
  const timeframes = Object.fromEntries(entries);
  return {
    status: "ok", source: "bybit_v5_linear_perpetual", market_type: "linear_perpetual",
    category: "linear", symbol, generated_at_ms: nowMs,
    generated_at_utc: new Date(nowMs).toISOString(),
    columns: ["open_time_ms","open","high","low","close","base_volume"],
    last_closed_utc: Object.fromEntries(Object.entries(frames).map(([name, [, mins]]) =>
      [name, new Date(timeframes[name].at(-1)[0] + mins * 60000).toISOString()])),
    timeframes, note: "Only closed trade-price bars. Mark-price SL triggers and intrabar event order are not implied."
  };
}


/** Native Bybit PUMPFUNUSDT perpetual candles for any supported interval. */
const PERP_NATIVE_INTERVALS = new Set(["1","3","5","15","30","60","120","240","360","720","D","W","M"]);
function perpNativeEnd(start, interval) {
  if (interval === "M") {
    const d = new Date(start);
    return Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1);
  }
  if (interval === "W") return start + 7 * 86400000;
  if (interval === "D") return start + 86400000;
  return start + Number(interval) * 60000;
}
async function fetchPerpNative(interval, nowMs) {
  if (!PERP_NATIVE_INTERVALS.has(interval)) throw new Error("Unsupported Bybit candle interval");
  const symbol = "PUMPFUNUSDT";
  const url = new URL(BYBIT_KLINE);
  url.search = new URLSearchParams({category:"linear", symbol, interval, limit:"203"});
  const response = await fetch(url, {
    headers: {accept:"application/json", "user-agent":"PUMP-Native-OHLC/1.0"},
    cf: {cacheTtlByStatus: {"200-299": 8, "400-599": -1}, cacheEverything:true}
  });
  if (!response.ok) throw new Error("Bybit HTTP " + response.status);
  const data = await response.json();
  if (data.retCode !== 0 || data.result?.symbol !== symbol || data.result?.category !== "linear" || !Array.isArray(data.result?.list))
    throw new Error("Bybit perpetual source verification failed");
  const seen = new Map();
  for (const raw of data.result.list) {
    const row = [Number(raw[0]), ...raw.slice(1,6).map(Number)];
    const [stamp, open, high, low, close, volume] = row;
    if (![stamp,open,high,low,close,volume].every(Number.isFinite) || !(low>0 && low<=Math.min(open,close) && high>=Math.max(open,close) && volume>=0)) 
      throw new Error("Invalid native Bybit OHLCV row");
    if (perpNativeEnd(stamp,interval)>nowMs-3000) continue;
    seen.set(stamp,[stamp,...raw.slice(1,6).map(String)]);
  }
  const rows=[...seen.values()].sort((a,b)=>a[0]-b[0]).slice(-200);
  if (rows.length<20) throw new Error("Insufficient closed native Bybit candles");
  for (let i=1;i<rows.length;i++) {
    if (rows[i][0]!==perpNativeEnd(rows[i-1][0],interval)) throw new Error("Gap in native Bybit candles");
  }
  const closed=perpNativeEnd(rows.at(-1)[0],interval);
  const ms = interval==="M" ? 35*86400000 : interval==="W" ? 7*86400000 : interval==="D" ? 86400000 : Number(interval)*60000;
  if (nowMs-closed>2*ms+120000) throw new Error("Stale native Bybit candles");
  return {status:"ok",source:"bybit_v5_linear_perpetual",market_type:"linear_perpetual",symbol,category:"linear",interval,
    generated_at_ms:nowMs,generated_at_utc:new Date(nowMs).toISOString(),last_closed_utc:new Date(closed).toISOString(),
    columns:["open_time_ms","open","high","low","close","base_volume"],rows,
    note:"Only closed trade-price OHLCV. Market order trigger price types may differ."};
}

export default {
  async fetch(request) {
    if (request.method !== "GET") return new Response("Method not allowed", { status: 405 });
    const nowMs = Date.now();
    const page = new URL(request.url);
    if (page.pathname === "/perp-candles") {
      const interval=page.searchParams.get("interval") || "1";
      if (!PERP_NATIVE_INTERVALS.has(interval))
        return Response.json({status:"invalid",reason:"Allowed: 1,3,5,15,30,60,120,240,360,720,D,W,M"}, {status:400,headers:{"access-control-allow-origin":"*"}});
      try {
        const report=await fetchPerpNative(interval,nowMs);
        return Response.json(report,{headers:{"cache-control":"public, max-age=8","access-control-allow-origin":"*"}});
      } catch(error) {
        return Response.json({status:"unavailable",source:null,reason:String(error.message || error)}, {status:502,headers:{"access-control-allow-origin":"*"}});
      }
    }
    if (page.pathname === "/perp") {
      try {
        const report = await perpetualSnapshot(nowMs);
        return Response.json(report, { headers: { "cache-control": "public, max-age=10", "access-control-allow-origin": "*" } });
      } catch (error) {
        return Response.json({ status: "unavailable", source: null, category: "linear", reason: String(error.message || error) }, { status: 502 });
      }
    }
    if (page.pathname === "/history") {
      const symbol = page.searchParams.get("symbol")?.trim().toUpperCase();
      const interval = page.searchParams.get("interval");
      const start = Number(page.searchParams.get("start"));
      const end = Number(page.searchParams.get("end"));
      if (!symbol || !/^[A-Z0-9]{3,24}$/.test(symbol) || !Number.isFinite(start) || !Number.isFinite(end) || start >= end) return Response.json({ error: "valid symbol, interval, start and end required" }, { status: 400 });
      try {
        const rows = await historicalFrame(symbol, interval, start, end, nowMs);
        return Response.json({ schema_version: "2.1", source: "bybit_spot", market_type: "spot_only", symbol, interval, generated_at_ms: nowMs, rows }, { headers: { "cache-control": "public, max-age=60", "access-control-allow-origin": "*" } });
      } catch (error) { return Response.json({ status: "unavailable", source: null, reason: String(error.message || error) }, { status: 502 }); }
    }
    if (page.pathname === "/scan") {
      try {
        const universe = (await tickers()).filter((x) => x.symbol.endsWith("USDT") && Number(x.turnover24h) >= 1_000_000 && Number(x.lastPrice) > 0).sort((a, b) => Number(b.turnover24h) - Number(a.turnover24h)).slice(0, SCAN_UNIVERSE);
        const candles15m = await Promise.all(universe.map(async (ticker) => [ticker.symbol, await oneFrame(ticker.symbol, "15m", nowMs)]));
        const leaders = universe.slice(0, SCAN_MULTITIMEFRAME);
        const extra = await Promise.all(leaders.map(async (ticker) => [ticker.symbol, { "1h": await oneFrame(ticker.symbol, "1h", nowMs), "4h": await oneFrame(ticker.symbol, "4h", nowMs), liquidity: await orderbook(ticker.symbol) }]));
        const additional = Object.fromEntries(extra);
        const symbols = Object.fromEntries(universe.map((ticker) => {
          const details = additional[ticker.symbol] || {};
          const bid = Number(ticker.bid1Price), ask = Number(ticker.ask1Price);
          return [ticker.symbol, { status: "ok", source: "bybit_spot", ticker: { last_price: Number(ticker.lastPrice), turnover24h: Number(ticker.turnover24h), volume24h: Number(ticker.volume24h), price24h_pct: Number(ticker.price24hPcnt) * 100, spread_bps: bid > 0 && ask >= bid ? (ask - bid) / ((ask + bid) / 2) * 10_000 : null }, liquidity: details.liquidity || null, frames: { "15m": Object.fromEntries(candles15m)[ticker.symbol], ...(details["1h"] ? { "1h": details["1h"], "4h": details["4h"] } : {}) } }];
        }));
        return Response.json({ schema_version: "2.1", generated_at_ms: nowMs, generated_at_utc: new Date(nowMs).toISOString(), source: "bybit_spot", market_type: "spot_only", scan_universe_size: universe.length, symbols }, { headers: { "cache-control": "public, max-age=10", "access-control-allow-origin": "*" } });
      } catch (error) { return Response.json({ status: "unavailable", source: null, reason: String(error.message || error) }, { status: 502 }); }
    }
    const symbols = symbolsFrom(request);
    if (!symbols.length) return Response.json({ error: "Provide a valid symbols query, e.g. ?symbols=BTCUSDT,SOLUSDT" }, { status: 400 });
    const results = [];
    for (let i = 0; i < symbols.length; i += 2) {
      results.push(...await Promise.all(symbols.slice(i, i + 2).map(async (symbol) => [symbol, await oneSymbol(symbol, nowMs)])));
    }
    return Response.json({ schema_version: "2.0", generated_at_utc: new Date(nowMs).toISOString(), generated_at_ms: nowMs, source: "bybit_spot", market_type: "spot_only", not_trading_advice: true, columns: ["open_time_ms", "open", "high", "low", "close", "base_volume"], symbols: Object.fromEntries(results) }, { headers: { "cache-control": "public, max-age=10", "access-control-allow-origin": "*" } });
  },
};
