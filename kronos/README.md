# Kronos + Bybit + ChatGPT

GitHub Actions runs the actual open-source Kronos-mini neural network on CPU, using the Frankfurt Cloudflare candle bridge. It writes:

- `data/kronos/latest.md`: compact report readable by the connected GitHub app in ChatGPT.
- `data/kronos/latest.json`: model provenance, forecasts, technical indicators and evaluation.
- `data/kronos/input.json`: exact Bybit candle snapshot used for the run.

The workflow is scheduled every 15 minutes (GitHub scheduling can be delayed), and can also be run manually from **Actions → Bybit Kronos Research → Run workflow** on an iPhone. An initial run starts when the implementation is pushed. It uses standard CPU runners in this public repository. No GPU, trading keys or paid service is used.

## ChatGPT usage

In ChatGPT with the GitHub connection enabled, ask:

> Lue repositoriosta zurabgudushauri1994-ship-it/-spot-candle-bridge tiedostot data/kronos/latest.md ja data/kronos/latest.json. Tarkista raportin ja kynttilöiden ikä. Vertaa Kronos-ennustetta 4h → 1h → 15m tekniseen trendiin. Kerro ristiriidat ja baseline-testin tulos. Älä esitä mallin viiden polun vaihtelua onnistumistodennäköisyytenä.

Model weights are not installed inside ChatGPT. ChatGPT reads results produced by the real model running in GitHub Actions. A connection does not make every new chat automatically read the repository.

## Model and method

- Original code: https://github.com/shiyu-coder/Kronos pinned to `67b630e67f6a18c9e9be918d9b4337c960db1e9a` (MIT).
- Model: `NeoQuasar/Kronos-mini`, revision `f4e68697d9d5aed55cef5c96aabc3376bcad9f81` (MIT).
- Matching tokenizer: `NeoQuasar/Kronos-Tokenizer-2k`, revision `26966d0035065a0cae0ebad7af8ece35bc1fb51c` (MIT).
- Three symbols; 15m, 1h, 4h; 160 input candles; next 4 candles; five independently sampled paths.
- `amount` is estimated internally by the original predictor as mean OHLC × base volume; this is explicitly labelled, not claimed to be exchange turnover.
- CPU with fixed seed. Model and tokenizer run in evaluation mode.
- EMA20/50, RSI14 and ATR14 (exponential initialization), MACD histogram, prior 20-bar volume ratio and close breakout.
- Three historical cutoffs per frame, 128 context candles and four held-out candles; no future input in normalization/context. Compare normalized close MAE against unchanged-price baseline. This is a smoke evaluation, not an adequate backtest or demonstration of profitable trading. No fees, slippage or execution is simulated.

## Data and forecast gates

Closed, finite, continuous and fresh Bybit Spot data is required. Missing data aborts publication; the previous report remains and its timestamp must be checked. Invalid model-generated OHLCV paths are rejected without artificial repair. Min/max of five sampled paths is model dispersion, not calibrated confidence.

This module produces research forecasts, not orders or automated BUY recommendations.
