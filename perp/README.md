# PUMP USDT perpetual – candle freshness

Source: Bybit V5 public `/market/kline`, `category=linear`, `symbol=PUMPFUNUSDT`.

This repository has a read-only 1m / 15m / 1h / 4h OHLCV snapshot updater in `.github/workflows/perp-ohlc.yml`. Its scheduled 15-minute GitHub Actions runs are **best effort**, not guaranteed to run on time; GitHub may delay or skip scheduled jobs. Workflow `workflow_dispatch` permits manual refresh from GitHub Actions.

Latest snapshot: `data/perp/latest.json` or `data/perp/latest.md`.

**Important:** The report's `generated_at_utc` is NOT proof of currently fresh candles. Before any new PUMP perpetual analysis, compare timestamps against actual current UTC and the latest completed 15-minute candle. Flag as stale if the newest closed 15m candle is older than 30 minutes, or if generated timestamp is older than 30 minutes. Never silently treat a historical snapshot as live data, nor use CMC spot quotations as Bybit perpetual OHLC. Check `status: ok`, `source`, `symbol`, and `category: linear`. Closing level is based on last-trade OHLC, not necessarily Bybit mark price used for triggered stops.

Live URL (once worker code is redeployed): `https://spot-candle-bridge.zurab-gudushauri1994.workers.dev/perp`. A GitHub commit to `src/worker.js` does **not** automatically redeploy the Cloudflare Worker without separate deployment.

A direct manual workflow run is preferable when schedules delay; confirm the new report's `generated_at_utc` after it completes.
