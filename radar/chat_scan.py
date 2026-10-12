#!/usr/bin/env python3
"""Read-only Bybit spot scan; publishes a chat-readable report."""
import concurrent.futures, datetime, json, math, pathlib, time, urllib.request, urllib.parse

ROOT="https://api.bybit.com/v5/market/"
HOSTS=["https://api.bybit.com/v5/market/","https://api.bytick.com/v5/market/","https://api.bybit.nl/v5/market/"]
OUT=pathlib.Path("data/chat-radar")
def get(endpoint, params):
    errors=[]
    for host in HOSTS:
        try:
            url=host+endpoint+"?"+urllib.parse.urlencode(params)
            req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 ChatSpotRadar/1.1","Accept":"application/json"})
            with urllib.request.urlopen(req,timeout=12) as response:
                body=json.load(response)
            if body.get("retCode")!=0: raise ValueError(str(body.get("retMsg")))
            return body["result"]
        except Exception as e:
            errors.append(f"{host}: {e}")
    raise RuntimeError("All Bybit endpoints failed: "+"; ".join(errors))
def ema(vals,n):
    v=vals[0]; a=2/(n+1)
    for x in vals[1:]: v=a*x+(1-a)*v
    return v
def evaluate(symbol,turnover):
    now=int(time.time()*1000)
    def candles(interval,period):
        rows=get("kline",{"category":"spot","symbol":symbol,"interval":interval,"limit":120})["list"]
        data=sorted((int(r[0]),*[float(v) for v in r[1:6]]) for r in rows if int(r[0])+period*60000<=now-5000)
        if len(data)<55: raise ValueError("insufficient closed candles")
        if now-(data[-1][0]+period*60000)>period*120000: raise ValueError("stale candles")
        return data
    a=candles("15",15)
    c=[r[4] for r in a]; hi=[r[2] for r in a]; lo=[r[3] for r in a]; vol=[r[5] for r in a]
    e20=ema(c,20); e50=ema(c,50)
    delta=[c[i]-c[i-1] for i in range(1,len(c))]
    up=sum(max(x,0) for x in delta[-14:])/14; dn=sum(max(-x,0) for x in delta[-14:])/14
    rsi=100 if dn==0 else 100-100/(1+up/dn)
    tr=[max(hi[i]-lo[i],abs(hi[i]-c[i-1]),abs(lo[i]-c[i-1])) for i in range(1,len(c))]
    atr=sum(tr[-14:])/14
    rv=vol[-1]/(sum(vol[-21:-1])/20) if sum(vol[-21:-1]) else 0
    resistance=max(hi[-21:-1]); support=min(lo[-21:-1])
    breakout=c[-1]>resistance and c[-2]<=max(hi[-22:-2])
    score=(25 if breakout else 0)+(15 if e20>e50 and c[-1]>e20 else 0)+(15 if 48<=rsi<=70 else 0)+(15 if rv>=1.5 else 8 if rv>=1.15 else 0)+(10 if c[-1]>c[-4] else 0)
    trend={}
    for frame,period in (("60",60),("240",240)):
        b=candles(frame,period); prices=[r[4] for r in b]
        trend[{"60":"1h","240":"4h"}[frame]]="up" if prices[-1]>ema(prices,20) else "down"
    score+=10*(trend["1h"]=="up")+10*(trend["4h"]=="up")
    entry=c[-1]; stop=min(support,entry-1.5*atr)
    risk=entry-stop; tp=entry+2*risk
    state="ENTRY_CANDIDATE" if score>=75 and breakout and trend["1h"]=="up" and trend["4h"]=="up" and rv>=1.2 else "WATCH" if score>=55 else "AVOID"
    return {"symbol":symbol,"score":score,"state":state,"closed_15m_utc":datetime.datetime.fromtimestamp((a[-1][0]+900000)/1000,datetime.timezone.utc).isoformat(),"price_at_close":entry,"entry_reference":entry if state!="AVOID" else None,"stop_reference":stop if state!="AVOID" else None,"tp_reference":tp if state!="AVOID" else None,"rsi":round(rsi,1),"relative_volume":round(rv,2),"breakout":breakout,"trend":trend,"turnover24h_usdt":turnover}
def main():
    OUT.mkdir(parents=True,exist_ok=True)
    stamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
    report={"generated_at_utc":stamp,"source":"bybit_spot","status":"unavailable","scanned":0,"requested":100,"candidates":[],"errors":[],"disclaimer":"Read-only signals, not orders; validate current price, spread and execution."}
    try:
        tickers=get("tickers",{"category":"spot"})["list"]
        pairs=sorted([(t["symbol"],float(t.get("turnover24h") or 0)) for t in tickers if t["symbol"].endswith("USDT") and float(t.get("turnover24h") or 0)>=1000000 and not any(x in t["symbol"] for x in ("3LUSDT","3SUSDT","5LUSDT","5SUSDT"))],key=lambda x:-x[1])[:100]
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            futures={pool.submit(evaluate,*p):p[0] for p in pairs}
            for f in concurrent.futures.as_completed(futures):
                try: report["candidates"].append(f.result())
                except Exception as e: report["errors"].append({"symbol":futures[f],"reason":str(e)[:130]})
        report["candidates"].sort(key=lambda x:x["score"],reverse=True)
        report["scanned"]=len(report["candidates"])
        report["status"]="ok" if report["scanned"]>=80 else "partial" if report["scanned"] else "unavailable"
    except Exception as e: report["errors"].append({"reason":str(e)[:200]})
    (OUT/"latest.json").write_text(json.dumps(report,indent=2,ensure_ascii=False))
    lines=["# Bybit Spot Radar 100",f"Updated UTC: {stamp}",f"Status: {report['status']} | analyzed: {report['scanned']}/100","", "| Pair | Score | State | Entry ref | Stop ref | TP ref | RSI | RVOL |","|---|---:|---|---:|---:|---:|---:|---:|"]
    for x in report["candidates"][:20]:
        fmt=lambda v: "-" if v is None else f"{v:.8g}"
        lines.append(f"| {x['symbol']} | {x['score']} | {x['state']} | {fmt(x['entry_reference'])} | {fmt(x['stop_reference'])} | {fmt(x['tp_reference'])} | {x['rsi']} | {x['relative_volume']} |")
    lines+=["","Do not treat historical close references as executable live quotes. Confirm spread, freshness, and risk.","",f"Errors: {len(report['errors'])}"]
    (OUT/"latest.md").write_text("\n".join(lines)+"\n")
    print(f"Scanned {report['scanned']} pairs; status={report['status']}")
if __name__=="__main__": main()
