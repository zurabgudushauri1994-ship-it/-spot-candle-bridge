# Spot Candle Bridge for ChatGPT

A free, read-only Cloudflare Worker that exposes **real closed Bybit spot candles** (OHLCV) at 15m, 1h and 4h.

## How it works

1. `wrangler.toml` sets `placement.region = "aws:eu-central-1"` so Cloudflare executes the Worker near Frankfurt. Check the response header `cf-placement: remote-FRA`; without this placement a request from a US client may be rejected by Bybit.
2. The Worker fetches only Bybit's public spot endpoint; **no exchange login or API key**.
3. Every request returns only closed 15m, 1h and 4h candles. It never substitutes Binance or another exchange.
4. The endpoint is public JSON, so ChatGPT can inspect it by URL after deployment.

## Setup

1. Create a free Cloudflare account and open **Workers & Pages**.
2. Create a Worker from this GitHub repository and deploy it. Cloudflare will provide a `workers.dev` address.
3. Verify `https://YOUR-WORKER.workers.dev/?symbols=BTCUSDT,SOLUSDT`.
4. Give that URL to ChatGPT and ask it to analyse the returned closed 15m / 1h / 4h candles.

No exchange login, API key, payment method, or scheduled GitHub runner is required. The Worker reads live data when requested; this is better than a delayed 15-minute snapshot for a chart analysis.

## Safety

This project is READ-ONLY: no trading or account API, no secrets, no positions, no market orders. Only use `status: "ok"` for current data; check `source` before calling it Bybit, and never use the newest still-open candle. The response includes `generated_at_ms` and `fresh` flags for each timeframe.

## Technical caveat

Bybit may reject a request depending on the caller's country or network. In that case the endpoint returns `status: "unavailable"` and a reason; it does not silently return another exchange's data.
