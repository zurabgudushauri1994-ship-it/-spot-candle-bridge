/**
 * Cloudflare Worker: public, read-only Bybit spot candle bridge.
 * Deploy with `npx wrangler deploy`; no exchange credentials are used.
 */

const BYBIT_KLINE = "https://api.bybit.com/v5/market/kline";
const FRAMES = { "15m": ["15", 15], "1h": ["60", 60], "4h": ["240", 240] };
const DEFAULT_SYMBOLS = ["PUMPUSDT", "ALGOUSDT", "NEARUSDT", "ICPUSDT", "BTCUSDT", "SOLUSDT", "TIAUSDT"];
const MAX_SYMBOLS = 12;
const COUNT = 200;

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
  url.search = new URLSearchParams({ category: "spot", symbol, interval, limit: String(COUNT + 2) });
  const response = await fetch(url, { headers: { accept: "application/json", "user-agent": "SpotCandleBridge/2.0" }, cf: { cacheTtl: 10, cacheEverything: true } });
  if (!response.ok) throw new Error(`Bybit HTTP ${response.status}`);
  const payload = await response.json();
  if (payload.retCode !== 0 || !Array.isArray(payload.result?.list)) throw new Error(`Bybit ${payload.retCode ?? "bad response"}`);
  const rows = closedRows(payload.result.list, minutes, nowMs);
  if (rows.length < 30) throw new Error("too few completed candles");
  return rows;
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
    const symbols = symbolsFrom(request);
    if (!symbols.length) return Response.json({ error: "Provide a valid symbols query, e.g. ?symbols=BTCUSDT,SOLUSDT" }, { status: 400 });
    const results = await Promise.all(symbols.map(async (symbol) => [symbol, await oneSymbol(symbol, nowMs)]));
    return Response.json({ schema_version: "2.0", generated_at_utc: new Date(nowMs).toISOString(), generated_at_ms: nowMs, source: "bybit_spot", market_type: "spot_only", not_trading_advice: true, columns: ["open_time_ms", "open", "high", "low", "close", "base_volume"], symbols: Object.fromEntries(results) }, { headers: { "cache-control": "public, max-age=10", "access-control-allow-origin": "*" } });
  },
};
