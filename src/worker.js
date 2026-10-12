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

export default {
  async fetch(request) {
    if (request.method !== "GET") return new Response("Method not allowed", { status: 405 });
    const nowMs = Date.now();
    const page = new URL(request.url);
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
