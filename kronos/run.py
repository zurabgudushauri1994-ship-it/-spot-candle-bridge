"""Real Kronos inference on closed Bybit candles; read-only research reports."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import sys
import time
import subprocess
from datetime import datetime, timezone

import numpy as np
import pandas as pd

BRIDGE = "https://spot-candle-bridge.zurab-gudushauri1994.workers.dev/"
UPSTREAM_COMMIT = "67b630e67f6a18c9e9be918d9b4337c960db1e9a"
MODEL_ID = "NeoQuasar/Kronos-mini"
MODEL_REV = "f4e68697d9d5aed55cef5c96aabc3376bcad9f81"
TOKENIZER_ID = "NeoQuasar/Kronos-Tokenizer-2k"
TOKENIZER_REV = "26966d0035065a0cae0ebad7af8ece35bc1fb51c"
FRAMES = {"15m": 15, "1h": 60, "4h": 240}
FEATURES = ["open", "high", "low", "close", "volume"]


def validate_frame(rows, frame, generated_ms, checked_ms):
    """Reject unclosed, stale, gapped, malformed or nonfinite input before inference."""
    a = np.asarray(rows, dtype=float)
    step = FRAMES[frame] * 60000
    if a.ndim != 2 or a.shape[0] < 160 or a.shape[1] != 6:
        raise ValueError(f"{frame}: insufficient or malformed candles")
    if not np.isfinite(a).all():
        raise ValueError("nonfinite input")
    if not (np.diff(a[:, 0]) == step).all() or not (a[:, 0] % step == 0).all():
        raise ValueError("candles have gaps or are out of order")
    if (a[:, 0] + step > min(generated_ms, checked_ms) - 5000).any():
        raise ValueError("input includes an unclosed candle")
    if checked_ms - (a[-1, 0] + step) > step + 120000:
        raise ValueError("stale candle input")
    o, h, l, c, v = a[:, 1:].T
    if not ((l > 0) & (l <= np.minimum(o, c)) & (h >= np.maximum(o, c)) & (v >= 0)).all():
        raise ValueError("invalid OHLCV")
    df = pd.DataFrame(a[:, 1:], columns=FEATURES)
    stamps = pd.Series(pd.to_datetime(a[:, 0], unit="ms", utc=True).tz_localize(None))
    return df, stamps


def fetch_snapshot(symbols):
    url = BRIDGE + "?symbols=" + ",".join(symbols)
    for attempt in range(3):
        # This user-owned public Worker accepts standard curl API requests.
        # No browser impersonation or exchange authentication is involved.
        response = subprocess.run(["curl", "--silent", "--show-error", "--fail-with-body", "--max-time", "90", url], check=True, capture_output=True, text=True)
        payload = json.loads(response.stdout)
        checked_ms = int(time.time() * 1000)
        if payload.get("source") != "bybit_spot" or payload.get("market_type") != "spot_only":
            raise ValueError("wrong market source")
        if abs(checked_ms - payload["generated_at_ms"]) > 120000:
            raise ValueError("stale response")
        if all(payload["symbols"].get(s, {}).get("status") == "ok" for s in symbols):
            return payload
        if attempt < 2:
            time.sleep(2)
    raise RuntimeError("Bridge did not supply all requested symbols: " + str({s: payload["symbols"].get(s, {}).get("reason") for s in symbols}))


def technical(df):
    c = df.close
    ema20 = c.ewm(span=20, adjust=False).mean()
    ema50 = c.ewm(span=50, adjust=False).mean()
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean().iloc[-1]
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean().iloc[-1]
    rsi = 50.0 if gain == loss == 0 else (100.0 if loss == 0 else 100 - 100 / (1 + gain/loss))
    tr = pd.concat([df.high-df.low, (df.high-c.shift()).abs(), (df.low-c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/14, adjust=False).mean().iloc[-1]
    macd = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    hist = (macd - macd.ewm(span=9, adjust=False).mean()).iloc[-1]
    ref_volume = df.volume.iloc[-21:-1].mean()
    trend = "up" if c.iloc[-1] > ema20.iloc[-1] > ema50.iloc[-1] else "down" if c.iloc[-1] < ema20.iloc[-1] < ema50.iloc[-1] else "mixed"
    return {"last_close": float(c.iloc[-1]), "ema20": float(ema20.iloc[-1]), "ema50": float(ema50.iloc[-1]), "rsi14": float(rsi), "atr14": float(atr), "macd_histogram": float(hist), "volume_vs_previous20": float(df.volume.iloc[-1]/ref_volume) if ref_volume else None, "trend": trend, "breakout_previous20": bool(c.iloc[-1] > df.high.iloc[-21:-1].max())}


def load_predictor(upstream):
    import torch
    sys.path.insert(0, str(Path(upstream).resolve()))
    from model import Kronos, KronosTokenizer, KronosPredictor
    from huggingface_hub import snapshot_download
    torch.set_num_threads(2)
    torch.manual_seed(42)
    np.random.seed(42)
    random.seed(42)
    tokenizer = KronosTokenizer.from_pretrained(snapshot_download(TOKENIZER_ID, revision=TOKENIZER_REV))
    model = Kronos.from_pretrained(snapshot_download(MODEL_ID, revision=MODEL_REV))
    model.eval()
    tokenizer.eval()
    return KronosPredictor(model, tokenizer, device="cpu", max_context=256)


def predict(predictor, df, stamps, minutes, horizon, paths):
    future = pd.Series(pd.date_range(stamps.iloc[-1] + pd.Timedelta(minutes=minutes), periods=horizon, freq=f"{minutes}min"))
    # Separate sampled paths are kept; sample_count>1 would hide dispersion by averaging.
    predictions = predictor.predict_batch([df]*paths, [stamps]*paths, [future]*paths, pred_len=horizon, sample_count=1, T=1.0, top_p=0.9, verbose=False)
    values = np.stack([p[FEATURES].to_numpy(float) for p in predictions])
    if not np.isfinite(values).all():
        raise ValueError("nonfinite forecast")
    return future, values


def evaluate(predictor, df, stamps, minutes):
    errors, baseline, direction = [], [], []
    # Three nonoverlapping historical cutoffs, never using future candles in context.
    for remaining in (12, 8, 4):
        end = len(df) - remaining
        context = df.iloc[end-128:end].reset_index(drop=True)
        dates = stamps.iloc[end-128:end].reset_index(drop=True)
        _, paths = predict(predictor, context, dates, minutes, horizon=4, paths=3)
        prediction = np.median(paths[:, :, 3], axis=0)
        actual = df.close.iloc[end:end+4].to_numpy()
        anchor = context.close.iloc[-1]
        errors.extend(np.abs(prediction-actual) / anchor)
        baseline.extend(np.abs(anchor-actual) / anchor)
        direction.append(bool(np.sign(prediction[-1]-anchor) == np.sign(actual[-1]-anchor)))
    mae, flat = float(np.mean(errors)), float(np.mean(baseline))
    return {"cutoffs": 3, "predicted_candles_per_cutoff": 4, "kronos_close_mae_pct": mae*100, "flat_price_close_mae_pct": flat*100, "beats_flat_on_this_sample": bool(mae < flat), "direction_correct_cutoffs": sum(direction), "validation_status": "small_holdout_smoke_test_only", "profitable_after_costs": "not_tested"}


def forecast(predictor, df, stamps, minutes):
    future, paths = predict(predictor, df.iloc[-160:].reset_index(drop=True), stamps.iloc[-160:].reset_index(drop=True), minutes, horizon=4, paths=5)
    valid = ((paths[:, :, 2] > 0) & (paths[:, :, 2] <= np.minimum(paths[:, :, 0], paths[:, :, 3])) & (paths[:, :, 1] >= np.maximum(paths[:, :, 0], paths[:, :, 3])) & (paths[:, :, 4] >= 0)).all(axis=1)
    if not valid.all():
        # Do not repair impossible model outputs into fabricated candle predictions.
        return {"status": "rejected", "reason": "model_generated_invalid_ohlcv", "invalid_paths": int((~valid).sum())}
    close = paths[:, :, 3]
    anchor = float(df.close.iloc[-1])
    median = np.median(close, axis=0)
    return {"status": "ok", "future_open_times_utc": [t.isoformat()+"Z" for t in future], "median_ohlcv": np.median(paths, axis=0).tolist(), "close_min": close.min(axis=0).tolist(), "close_max": close.max(axis=0).tolist(), "sampled_close_paths": close.tolist(), "sampled_paths": 5, "dispersion_is_calibrated_confidence_interval": False, "terminal_median_return_pct": float((median[-1]/anchor-1)*100), "bias": "up" if median[-1] > anchor else "down" if median[-1] < anchor else "flat"}


def markdown(report):
    lines = ["# Bybit + Kronos – ChatGPT-raportti", "", f"Päivitetty (UTC): {report['generated_at_utc']}", "", "Kronos-mini on ajettu oikeilla Bybit Spot -kynttilöillä. Ennuste on tutkimustulos; mallin luotettavuutta tai tuottoa ei ole vahvistettu.", "", "| Pari | Aikaväli | Trend | RSI | Kronos-suunta | Ennustettu muutos | MAE / ennallaan-baseline |", "|---|---|---|---:|---|---:|---|" ]
    for symbol, frames in report["symbols"].items():
        for frame, entry in frames.items():
            t, f, e = entry["technical"], entry["forecast"], entry["evaluation"]
            bias = f.get("bias", "hylätty")
            change = f"{f['terminal_median_return_pct']:+.2f}%" if f["status"] == "ok" else "–"
            lines.append(f"| {symbol} | {frame} | {t['trend']} | {t['rsi14']:.1f} | {bias} | {change} | {e['kronos_close_mae_pct']:.3f}% / {e['flat_price_close_mae_pct']:.3f}% |")
    lines += ["", "Kukin ennuste kattaa seuraavat 4 kynttilää. Viiden simuloidun polun vaihteluväli ei ole kalibroitu todennäköisyys. Testi sisältää vain 3 historiallista ennustehetkeä per aikaväli; ei näyttöä kaupankäynnin kannattavuudesta.", "", "ChatGPT: lue myös latest.json; tarkista datan ikä. Älä käytä tätä BUY-signaalina, älä kutsu simuloitua osuutta onnistumistodennäköisyydeksi. Jos Kronos ja tekninen trendi ovat eri suuntaan, kerro ristiriita. Tarkista live-hinta ja tuoreet kynttilät ennen analyysiä."]
    return "\n".join(lines)+"\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", default=".kronos-upstream")
    parser.add_argument("--symbols", default="BTCUSDT,SOLUSDT,PUMPUSDT")
    parser.add_argument("--output", default="data/kronos")
    args = parser.parse_args()
    symbols = args.symbols.split(",")
    if not 1 <= len(symbols) <= 3 or any(not s.isalnum() or not s.endswith("USDT") for s in symbols):
        raise ValueError("provide 1–3 USDT symbols")
    started = time.time()
    snapshot = fetch_snapshot(symbols)
    series = {}
    for s in symbols:
        value = snapshot["symbols"][s]
        if value.get("source") != "bybit_spot":
            raise ValueError("wrong symbol source")
        series[s] = {f: validate_frame(value["frames"][f], f, snapshot["generated_at_ms"], int(time.time()*1000)) for f in FRAMES}
    predictor = load_predictor(args.upstream)
    report = {"schema_version": "1.0", "status": "ok", "generated_at_utc": datetime.now(timezone.utc).isoformat(), "input_generated_at_utc": snapshot["generated_at_utc"], "input_sha256": hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest(), "source": "bybit_spot", "model": {"id": MODEL_ID, "revision": MODEL_REV, "tokenizer": TOKENIZER_ID, "tokenizer_revision": TOKENIZER_REV, "code_commit": UPSTREAM_COMMIT, "device": "cpu", "seed": 42, "amount_feature": "estimated_from_ohlc_mean_times_base_volume"}, "forecast_columns": FEATURES, "symbols": {}, "automatic_trading": False}
    for s in symbols:
        report["symbols"][s] = {}
        for f, minutes in FRAMES.items():
            print(f"Kronos: {s} {f}", flush=True)
            df, stamps = series[s][f]
            report["symbols"][s][f] = {"input_candles": len(df), "last_closed_at_utc": (stamps.iloc[-1]+pd.Timedelta(minutes=minutes)).isoformat()+"Z", "technical": technical(df), "forecast": forecast(predictor, df, stamps, minutes), "evaluation": evaluate(predictor, df, stamps, minutes)}
    report["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    report["runtime_seconds"] = round(time.time()-started, 2)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    def write(name, content):
        temp = output / (name+".tmp")
        temp.write_text(content, encoding="utf-8")
        temp.replace(output / name)
    write("input.json", json.dumps(snapshot, indent=2, allow_nan=False)+"\n")
    write("latest.json", json.dumps(report, indent=2, allow_nan=False)+"\n")
    write("latest.md", markdown(report))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(markdown(report))
    print(f"Saved actual Kronos report in {report['runtime_seconds']} seconds", flush=True)


if __name__ == "__main__":
    main()
