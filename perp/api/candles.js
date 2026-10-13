// Read-only PUMP perpetual proxy for the Vercel Hobby plan.
// Always serves CLOSED real OHLCV, refuses stale/wrong-market data.
const SYMBOL="PUMPFUNUSDT";
const W="https://spot-candle-bridge.zurab-gudushauri1994.workers.dev";
const ALLOWED=new Set(["1","3","5","15","30","60","120","240","360","720","D","W","M"]);
const lengthMs=tf=>tf==="M"?31*86400000:tf==="W"?7*86400000:tf==="D"?86400000:Number(tf)*60000;
function closeTime(ts,tf){if(tf==="M"){const d=new Date(ts);return Date.UTC(d.getUTCFullYear(),d.getUTCMonth()+1,1);}return ts+lengthMs(tf);}
function validate(rows,interval){
 if(!Array.isArray(rows))throw Error("No data");
 const a=[],now=Date.now();
 for(const original of rows){
  const r=original.slice(0,6).map(Number);
  const [ts,o,h,l,c,v]=r;
  if(r.length<6||r.some(n=>!Number.isFinite(n))||!(l>0&&l<=Math.min(o,c)&&h>=Math.max(o,c)&&v>=0))throw Error("Bad OHLC");
  if(closeTime(ts,interval)<=now-2500)a.push(r);
 }
 a.sort((a,b)=>a[0]-b[0]);
 const unique=a.filter((row,i)=>i===0||row[0]!==a[i-1][0]);
 if(unique.length<4)throw Error("Not enough closed candles");
 for(let i=1;i<unique.length;i++)if(unique[i][0]!==closeTime(unique[i-1][0],interval))throw Error("Noncontiguous bars");
 const age=now-closeTime(unique.at(-1)[0],interval);
 if(age>lengthMs(interval)+120000)throw Error("Stale bars: "+Math.round(age/1000)+" seconds");
 return unique.slice(-200);
}
function verified(d){
 if(d.status!=="ok"||d.category!=="linear"||d.symbol!==SYMBOL||
 d.market_type!=="linear_perpetual"||!["bybit_v5_linear_perpetual","bybit_v5_linear_perpetual_via_cloudflare_worker"].includes(d.source))throw Error("Wrong market or source");
}
async function fetchJSON(url,ms=3600){
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),ms);
 try{
  const response=await fetch(url,{signal:controller.signal,headers:{accept:"application/json"},cache:"no-store"});
  if(!response.ok)throw Error("HTTP "+response.status);
  return await response.json();
 }finally{clearTimeout(timer)}
}
function combine(d,interval){
 const specs={"1":["1m",1],"3":["1m",1],"5":["1m",1],"15":["15m",15],"30":["15m",15],
 "60":["1h",60],"120":["1h",60],"240":["4h",240],"360":["1h",60],"720":["4h",240],"D":["4h",240]};
 const spec=specs[interval];if(!spec)throw Error("Fallback not supported for this interval");
 const [key,base]=spec,raw=d.timeframes?.[key];if(!Array.isArray(raw))throw Error("Missing source candles");
 const size=lengthMs(interval),blocks=new Map(),unit=base*60000;
 for(const row of raw){
  const r=row.map(Number),start=Math.floor(r[0]/size)*size;
  if(!blocks.has(start))blocks.set(start,[]);
  blocks.get(start).push(r);
 }
 const arr=[];
 for(const [start,a] of blocks){
  a.sort((a,b)=>a[0]-b[0]);
  if(a.length!==size/unit||a[0][0]!==start||a.at(-1)[0]+unit!==start+size)continue;
  if(a.some((x,i)=>i&&x[0]-a[i-1][0]!==unit))continue;
  arr.push([start,a[0][1],Math.max(...a.map(x=>x[2])),Math.min(...a.map(x=>x[3])),a.at(-1)[4],a.reduce((s,x)=>s+x[5],0)]);
 }
 return arr;
}
async function get(tf){
 const now=Date.now();
 // Direct Cloudflare V5 native API when deployed
 try{
  const d=await fetchJSON(W+"/perp-candles?interval="+encodeURIComponent(tf),2700);
  verified(d);if(d.interval!==tf||Math.abs(Date.now()-Number(d.generated_at_ms))>180000)throw Error("Native endpoint stale");
  return {rows:validate(d.rows,tf),source:"cloudflare-native"};
 }catch(_){}
 // Direct Bybit from Frankfurt edge (or alternative official host).
 for(const host of ["https://api.bybit.com","https://api.bytick.com"]){
  try{
   const q=new URLSearchParams({category:"linear",symbol:SYMBOL,interval:tf,limit:"200"});
   const d=await fetchJSON(host+"/v5/market/kline?"+q.toString(),2700);
   if(d.retCode!==0||d.result?.symbol!==SYMBOL||d.result?.category!=="linear")throw Error("Wrong market");
   return {rows:validate(d.result.list,tf),source:"bybit-v5-direct"};
  }catch(_){}
 }
 // Existing Frankfurt worker that GitHub uses: assemble native closed OHLC.
 try{
  const d=await fetchJSON(W+"/perp",3200);
  verified(d);
  if(Math.abs(Date.now()-Number(d.generated_at_ms))>180000)throw Error("Worker stale");
  return {rows:validate(combine(d,tf),tf),source:"cloudflare-legacy-validated"};
 }catch(_){}
 throw Error("No fresh verified Bybit Perpetual candles available");
}
module.exports=async function handler(req,res){
 if(req.method!=="GET"){res.setHeader("Allow","GET");return res.status(405).json({status:"error",reason:"Only GET allowed"});}
 const tf=String(req.query.interval||"1");
 if(!ALLOWED.has(tf))return res.status(400).json({status:"error",reason:"Unsupported timeframe"});
 res.setHeader("Cache-Control","public, s-maxage=5, stale-while-revalidate=5");
 res.setHeader("X-Content-Type-Options","nosniff");
 try{
  const result=await get(tf);
  const at=Date.now();
  return res.status(200).json({status:"ok",symbol:SYMBOL,category:"linear",market_type:"linear_perpetual",
   source:"bybit_v5_linear_perpetual",upstream:result.source,interval:tf,generated_at_ms:at,
   generated_at_utc:new Date(at).toISOString(),last_closed_utc:new Date(closeTime(result.rows.at(-1)[0],tf)).toISOString(),
   columns:["open_time_ms","open","high","low","close","base_volume"],rows:result.rows});
 }catch(e){return res.status(503).json({status:"unavailable",symbol:SYMBOL,interval:tf,reason:String(e.message||e)})}
};