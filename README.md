# Spot Candle Bridge for ChatGPT

A read-only collection of **real closed spot candles** (OHLCV) at 15m, 1h and 4h.

## How it works

1. GitHub Actions runs on its schedule or manually.
2. Python fetches candles from Bybit's public REST `category=spot` endpoint; **no API key**.
3. The default workflow is **strictly Bybit spot only**. If Bybit is unavailable, it fails visibly and leaves no misleading snapshot. A developer may enable Binance's public spot API only for diagnostics with `ALLOW_BINANCE_FALLBACK=1`; such results are explicitly tagged `binance_spot_fallback_NOT_bybit` and must NOT be interpreted as actual Bybit candles.
4. It saves compact JSON at `data/latest.json` (source, timestamp, raw OHLCV, freshness status).
5. ChatGPT with connected GitHub may read `data/latest.json` using the GitHub connector, provided the repository is accessible to the connection.

## Setup

Create a GitHub repo, upload these files **including `.github/workflows/candles.yml`**, and allow GitHub Actions to run. The workflow must be on the *default branch*. No exchange login or API key is necessary. A public repo exposes only **public market data** and normally has no Actions minutes charges on standard GitHub-hosted runners. A private repo uses your monthly Actions minutes and may incur costs after plan quota; confirm billing and set a hard spending limit before enabling schedule. At 15m cadence there are about **2880 invocations per 30 days**; GitHub bills private job minutes rounded up to a whole minute. You can change cron to `7,37 * * * *` (every 30m) to use roughly 1440 runs per month.

Scheduled jobs may be delayed or dropped. This is **not a realtime trading alert service**. Your existing ChatGPT hourly automation does NOT automatically gain this GitHub data until its instructions are updated to fetch `data/latest.json` from the connected GitHub repo.

After initial Action run succeeds, tell ChatGPT `Lue GitHub-repon <owner>/<repo> data/latest.json ja analysoi sulkeutuneet 15m / 1h / 4h kynttilät`.

## Safety

This project is READ-ONLY: no trading or account API, no secrets, no positions, no market orders. Only use `status: "ok"` for current data; check `source` before calling it Bybit, and never use the newest still-open candle. The latest snapshot can be older than the latest trade. If the job fails, the previous JSON remains in place: always examine `generated_at_ms` and `fresh` flags.

## Technical caveat

If outbound API hosts reject GitHub runner IPs or both sources fail, the job fails instead of silently claiming valid market data. This package is locally unit-tested with synthetic responses; **live GitHub Actions and API connectivity remain unverified until a first workflow run succeeds**.
