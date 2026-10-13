(()=>{"use strict";
const Q=id=>document.getElementById(id);
if(!Q("war-canvas"))return;
const colors={bear:"#f36b7f",bull:"#44d79d",neutral:"#ecc870"};
const labels={bear:"LASKEE",bull:"NOUSEE",neutral:"EPÄVARMA"};
const TF=[["1","1 minuutti"],["15","15 minuuttia"],["60","1 tunti"],["240","4 tuntia"]];
let frames={},roles=[],soldiers=[],state="waiting",result="neutral",certainty=0,clock=0,round=0,playSpeed=1,rafPrev=0,loadedAt=0,analysisId=0;
const c=Q("war-canvas"),ctx=c.getContext("2d"),fmt=n=>n.toLocaleString("fi-FI",{maximumFractionDigits:6,minimumFractionDigits:6});
const timeString=ms=>new Date(ms).toLocaleString("fi-FI",{timeZone:"Europe/Helsinki",day:"numeric",month:"numeric",hour:"2-digit",minute:"2-digit"});
const clamp=(v,min,max)=>Math.max(min,Math.min(max,v));
function safeText(id,str){const e=Q(id);if(e)e.textContent=str;}
function candleEnd(ts,tf){return ts+Number(tf)*60000;}
function ema(values,n){const k=2/(n+1),out=[];let prev=values[0];for(const v of values){prev=out.length?prev+k*(v-prev):v;out.push(prev);}return out;}
function rsi(vals,n=14){if(vals.length<n+2)return null;let gain=0,loss=0;for(let i=1;i<=n;i++){let d=vals[i]-vals[i-1];gain+=Math.max(0,d);loss+=Math.max(0,-d)}gain/=n;loss/=n;let last=50;for(let i=n+1;i<vals.length;i++){let d=vals[i]-vals[i-1];gain=(gain*(n-1)+Math.max(d,0))/n;loss=(loss*(n-1)+Math.max(-d,0))/n;}last=loss===0?(gain>0?100:50):100-100/(1+gain/loss);return last;}
function stats(rows,tf){
 const o=rows.map(a=>a[1]),h=rows.map(a=>a[2]),l=rows.map(a=>a[3]),z=rows.map(a=>a[4]),v=rows.map(a=>a[5]),i=z.length-1;
 const e20=ema(z,20),e50=ema(z,50),e12=ema(z,12),e26=ema(z,26),m=e12.map((t,j)=>t-e26[j]),sig=ema(m,9);
 const n=14,trs=h.map((p,j)=>Math.max(p-l[j],Math.abs(p-(z[j-1]||z[j])),Math.abs(l[j]-(z[j-1]||z[j])))),atr=trs.slice(-n).reduce((a,b)=>a+b,0)/n;
 const avgvol=v.slice(-21,-1).reduce((a,b)=>a+b,0)/Math.min(20,v.length-1);
 const highest=Math.max(...h.slice(-21,-1)),lowest=Math.min(...l.slice(-21,-1));
 const up=z[i]>o[i],volRatio=avgvol>0?v[i]/avgvol:1;
 const vwap=z.slice(-60).reduce((a,b,j)=>a+b*v[v.length-Math.min(60,z.length)+j],0)/Math.max(1,v.slice(-60).reduce((a,b)=>a+b,0));
 const R=rsi(z),macd=(m[i]-sig[i]),ret6=z[i]/z[Math.max(0,i-6)]-1;
 return {tf,ts:rows[i][0],close:z[i],open:o[i],high:h[i],low:l[i],volume:v[i],ema20:e20[i],ema50:e50[i],rsi:R,macd,atr,ret6,vwap,highest,lowest,volRatio,up,bars:rows.length,
   emaTrend:clamp((z[i]-e20[i])/(atr*1.5||z[i]*.01),-1,1),
   rsiTrend:R===null?0:clamp((R-50)/22,-1,1),
   macdTrend:clamp(macd/(atr*.18||z[i]*.002),-1,1),
   moveTrend:clamp(ret6/(atr/z[i]*2.5||.01),-1,1),
   volTrend:volRatio>1.3?(up?1:-1)*Math.min(1,volRatio/2):0};
}
function bias(s){if(!s)return null;return .35*s.emaTrend+.23*s.rsiTrend+.18*s.macdTrend+.19*s.moveTrend+.05*s.volTrend;}
function role(name,group,tf,test,why){const s=frames[tf],n=test(s);
 roles.push({name,group,tf,side:n===null||Math.abs(n)<.11?"neutral":n>0?"bull":"bear",strength:n===null?0:Math.abs(n),reason:why(s,n),valid:n!==null});}
const absent=(name,group,reason)=>roles.push({name,group,tf:null,side:"neutral",strength:0,reason:"Tieto puuttuu: "+reason,valid:false});
function signs(s){if(!s)return null;return s.close>s.ema20?1:-1;}
const checks={
 candle:s=>s?(s.close>s.open?1:s.close<s.open?-1:0):null,
 ema20:s=>s?(s.close/s.ema20-1)/(s.atr/s.close||.01):null,
 ema50:s=>s?(s.close/s.ema50-1)/(2*s.atr/s.close||.01):null,
 trend:s=>s?clamp(s.ret6/(s.atr/s.close*2||.01),-1,1):null,
 rsi:s=>s?s.rsi===null?null:clamp((s.rsi-50)/22,-1,1):null,
 macd:s=>s?clamp(s.macd/(s.atr*.16||.00001),-1,1):null,
 vwap:s=>s?clamp((s.close/s.vwap-1)/(s.atr/s.close||.01),-1,1):null,
 cross:s=>s?clamp((s.ema20/s.ema50-1)/(s.atr/s.close||.01),-1,1):null,
 breakout:s=>s?(s.close>s.highest?1:s.close<s.lowest?-1:0):null,
 vol:s=>s?s.volRatio<1.3?0:(s.up?1:-1)*clamp(s.volRatio/2,0,1):null
};
const tfNames={"1":"1m","15":"15m","60":"1h","240":"4h"};
function buildRoles(){
 roles=[];
 const base=(name,group,tf,key)=>{
   role(name,group,tf,s=>{const v=checks[key](s);return v===null?null:clamp(v,-1,1);},(s,v)=>!s?"Bybitin "+tfNames[tf]+" kynttilöitä ei ole vahvistettu":
    key==="ema20"?tfNames[tf]+": hinta "+fmt(s.close)+" ja EMA20 "+fmt(s.ema20):
    key==="ema50"?tfNames[tf]+": hinta "+fmt(s.close)+" ja EMA50 "+fmt(s.ema50):
    key==="rsi"?tfNames[tf]+": RSI14 "+s.rsi.toFixed(1):
    key==="macd"?tfNames[tf]+": MACD-histogrammi "+s.macd.toExponential(2):
    key==="vwap"?tfNames[tf]+": hinta verrattuna 60 kynttilän volyymipainotettuun keskiarvoon":
    key==="cross"?tfNames[tf]+": EMA20 "+fmt(s.ema20)+" suhteessa EMA50:een "+fmt(s.ema50):
    key==="breakout"?tfNames[tf]+": 20 edeltävän kynttilän huippu "+fmt(s.highest)+", pohja "+fmt(s.lowest):
    key==="vol"?tfNames[tf]+": volyymi "+s.volRatio.toFixed(2)+"× edeltävään keskiarvoon":
    key==="trend"?tfNames[tf]+": kuuden kynttilän muutos "+(s.ret6*100).toFixed(2)+" %":
    tfNames[tf]+": kynttilän open "+fmt(s.open)+" ja close "+fmt(s.close));
 };
 // 10 trend, 10 momentum, 10 structure, 10 volume/psychology, 10 risk
 [["1m hintakynttilä","1","candle"],["1m EMA20","1","ema20"],["1m EMA50","1","ema50"],["1m lyhyt trendi","1","trend"],
 ["15m hintakynttilä","15","candle"],["15m EMA20","15","ema20"],["15m EMA50","15","ema50"],
 ["1h EMA20","60","ema20"],["1h kuuden tunnin trendi","60","trend"],["4h EMA20","240","ema20"]].forEach(([n,t,k])=>base(n,"Hinta ja trendi",t,k));
 [["1m RSI","1","rsi"],["15m RSI","15","rsi"],["1h RSI","60","rsi"],["4h RSI","240","rsi"],
 ["1m MACD","1","macd"],["15m MACD","15","macd"],["1h MACD","60","macd"],["4h MACD","240","macd"],
 ["1m momentum","1","trend"],["15m momentum","15","trend"]].forEach(([n,t,k])=>base(n,"Momentum",t,k));
 [["1m breakout","1","breakout"],["15m breakout","15","breakout"],["1h breakout","60","breakout"],["4h breakout","240","breakout"],
 ["1m VWAP","1","vwap"],["15m VWAP","15","vwap"],["1h VWAP","60","vwap"],["4h VWAP","240","vwap"],
 ["1m EMA-risteymä","1","cross"],["15m EMA-risteymä","15","cross"]].forEach(([n,t,k])=>base(n,"Hintarakenne",t,k));
 [["1m volyymi","1","vol"],["15m volyymi","15","vol"],["1h volyymi","60","vol"],["4h volyymi","240","vol"]].forEach(([n,t,k])=>base(n,"Volyymi ja psykologia",t,k));
 role("FOMO-asiantuntija","Volyymi ja psykologia","1",s=>s?s.volRatio>1.6&&s.up?Math.min(1,s.volRatio/3):0:null,(s,n)=>!s?"Tuoretta dataa ei ole":"Hintaan ja volyymiin perustuva FOMO-proxy ("+s.volRatio.toFixed(2)+"×). Ei todennettua some-FOMOa");
 role("FUD-asiantuntija","Volyymi ja psykologia","1",s=>s?s.volRatio>1.6&&!s.up?-Math.min(1,s.volRatio/3):0:null,(s,n)=>!s?"Tuoretta dataa ei ole":"Laskun ja volyymin yhdistelmä. Ei todennettua some-FUDia");
 role("Mean reversion","Volyymi ja psykologia","15",s=>s&&s.rsi!==null?(s.rsi<28?.38:s.rsi>72?-.38:0):null,(s,n)=>!s?"15m-dataa puuttuu":"Äärimmäinen RSI voi merkitä palautuksen riskiä; nykyinen RSI "+s.rsi.toFixed(1));
 absent("Short squeeze","Volyymi ja psykologia","position likvidaatiot ja shorttikeskittymä");
 absent("Valasseuranta","Volyymi ja psykologia","valaslompakoiden tai suurkauppojen reaaliaikainen seuranta");
 absent("Somehype","Volyymi ja psykologia","varmennettu sosiaalinen sentimenttidata");
 for(const [n,reason] of [
 ["Order book","osto-/myyntilaidan tilannekuva"],["CVD","aggressiivinen osto-/myyntivirta"],
 ["Open interest","perpetual-sopimuksen open interest"],["Funding","nykyinen funding rate"],
 ["Likvidaatiot","reaaliaikainen likvidaatiokartta"],["Spread","osto- ja myyntihinnan erotus"],
 ["Valaskaupat","yksittäiset vahvistetut suuret kaupat"]])absent(n,"Riskit ja laatu",reason);
 role("ATR-riskipäällikkö","Riskit ja laatu","15",s=>s?0:null,s=>!s?"ATR puuttuu":"ATR14 "+fmt(s.atr)+"; volatiliteetti ei yksin kerro suuntaa");
 role("Moniaikavälien linja","Riskit ja laatu","60",s=>{const a=bias(frames["15"]),b=bias(frames["60"]),d=bias(frames["240"]);return a===null||b===null||d===null?null:Math.sign(a)===Math.sign(b)&&Math.sign(b)===Math.sign(d)?clamp((a+b+d)/3,-1,1):0},s=>"15m, 1h ja 4h suunnat arvioidaan yhdessä; ristiriidassa rooli jää neutraaliksi");
 absent("Skeptinen pääanalyytikko","Riskit ja laatu","Tulevaa 1–3 h osumistarkkuutta ei ole todistettu riippumattomalla testillä");
 if(roles.length!==50)throw Error("Asiantuntijamäärä poikkeaa: "+roles.length);
}
function compute(){
 buildRoles();
 const counts={bear:0,bull:0,neutral:0};
 roles.forEach(x=>{counts[x.side]++;});
 const weights={"1":.18,"15":.32,"60":.3,"240":.2};
 let sum=0,den=0;
 for(const tf of Object.keys(weights)){const s=frames[tf];if(s){sum+=bias(s)*weights[tf];den+=weights[tf]}}
 certainty=den?sum/den:0;
 result=den<.70||Math.abs(certainty)<.18?"neutral":certainty>0?"bull":"bear";
 return {counts,den,certainty};
}
function renderRoles(){
 const dest=Q("war-roles");dest.replaceChildren();
 const cts={bear:0,bull:0,neutral:0};
 roles.forEach((r,i)=>{
  cts[r.side]++;
  const e=document.createElement("div");e.className="war-role";
  const dot=document.createElement("span");dot.className="war-role-dot";dot.style.background=colors[r.side];
  const info=document.createElement("div"),head=document.createElement("strong"),sub=document.createElement("small");
  head.textContent=(i+1)+". "+r.name+" — "+labels[r.side];head.style.color=colors[r.side];sub.textContent=r.reason;
  info.append(head,sub);e.append(dot,info);dest.append(e);
 });
 safeText("war-counts","LASKEE "+cts.bear+"  ·  NOUSEE "+cts.bull+"  ·  EPÄVARMA "+cts.neutral+"  (50 roolia / 100 sotilasta)");
 safeText("war-signal","Suunta: "+labels[result]);
 Q("war-signal").style.color=colors[result];
 const s=Object.entries(frames).map(([tf,s])=>tfNames[tf]+": close "+fmt(s.close)+", RSI "+(s.rsi===null?"?":s.rsi.toFixed(1))+", EMA20 "+fmt(s.ema20)+", MACD "+s.macd.toExponential(1));
 safeText("war-indicators",s.join("  |  "));
 safeText("war-conf", "Painotettu signaali "+(certainty*100).toFixed(1)+"/100; ei voittotodennäköisyys");
}
async function fetchCandles(){
 const id=++analysisId;state="loading";Q("war-analyze").disabled=true;
 safeText("war-status","Haetaan Bybitin sulkeutuneet 1m / 15m / 1h / 4h kynttilät…");
 const answers=await Promise.allSettled(TF.map(async([tf])=>{
  const ctrl=new AbortController(),timeout=setTimeout(()=>ctrl.abort(),13500);
  try{
   const r=await fetch("/api/candles?interval="+tf+"&t="+Date.now(),{cache:"no-store",signal:ctrl.signal});
   if(!r.ok)throw Error("HTTP "+r.status);
   const data=await r.json();
   if(data.status!=="ok"||data.symbol!=="PUMPFUNUSDT"||data.category!=="linear"||data.market_type!=="linear_perpetual"||data.source!=="bybit_v5_linear_perpetual"||data.interval!==tf||!Array.isArray(data.rows))throw Error("Lähde tai aikaväli väärin");
   const rows=data.rows.map(r=>r.map(Number));
   if(rows.length<60)throw Error("Liian vähän kynttilöitä");
   if(rows.some(r=>r.length<6||r.some(v=>!Number.isFinite(v))||!(r[3]>0&&r[3]<=Math.min(r[1],r[4])&&r[2]>=Math.max(r[1],r[4]))))throw Error("OHLC virheellinen");
   const newest=rows.at(-1)[0]+Number(tf)*60000;
   const delay=Date.now()-newest;
   if(delay< -120000||delay>Number(tf)*60000+120000)throw Error("Vanhentunut: sulku "+timeString(newest));
   if(rows.some((r,i)=>i&&r[0]-rows[i-1][0]!==Number(tf)*60000))throw Error("Kynttilöiden aikajaksossa aukko");
   return [tf,stats(rows,tf)];
  }finally{clearTimeout(timeout)}
 }));
 if(id!==analysisId)return;
 frames={};
 const errs=[];
 answers.forEach((x,i)=>{if(x.status==="fulfilled")frames[x.value[0]]=x.value[1];else errs.push(tfNames[TF[i][0]]+": "+String(x.reason?.message||x.reason))});
 const valid=Object.keys(frames).length;
 if(valid===0){state="offline";safeText("war-status","Analyysi keskeytetty. Tuoreita Bybit-kynttilöitä ei saatu. "+errs.join(" | "));Q("war-analyze").disabled=false;Q("war-play").disabled=true;return;}
 const a=compute();renderRoles();setupSoldiers();
 loadedAt=Date.now();Q("war-play").disabled=valid<3;
 state="ready";
 safeText("war-status",valid===4?"Kaikki 4 aikaväliä tuoreita · Viimeisin 1m sulku "+timeString(frames["1"].ts+60000):
 "Osittainen data "+valid+"/4 · "+errs.join(" | ")+" · Ei vahvaa treidisignaalia");
 if(valid<3){result="neutral";safeText("war-signal","Suunta: EPÄVARMA · Puutteellinen data")}
 Q("war-analyze").disabled=false;
 paint();
}
function speeches(){
 const pos=roles.filter(r=>r.side==="bull").sort((a,b)=>b.strength-a.strength)[0];
 const neg=roles.filter(r=>r.side==="bear").sort((a,b)=>b.strength-a.strength)[0];
 const unk=roles.find(r=>r.name==="Skeptinen pääanalyytikko");
 return [neg,pos,neg,pos,unk].filter(Boolean).map((r,i)=>({name:r.name,quote:r.reason,side:r.side}));
}
let debate=[];
function announce(){
 debate=speeches();
 const selected=debate[Math.min(debate.length-1,Math.floor(clock/5))];
 if(selected){
  safeText("war-speaker",selected.name+" ("+labels[selected.side]+")");
  safeText("war-speech",selected.quote);
  Q("war-speaker").style.color=colors[selected.side];
 }
}
function setupSoldiers(){
 soldiers=[];const W=c.clientWidth||620,H=c.clientHeight||360;
 let per={bear:0,bull:0,neutral:0};
 roles.forEach((r,i)=>{
  for(let j=0;j<2;j++){
   const k=per[r.side]++,a=r.side==="bear"?.05:r.side==="bull"?.72:.40,b=r.side==="bear"?.28:r.side==="bull"?.95:.60;
   const cols=r.side==="neutral"?7:7,row=Math.floor(k/cols),col=k%cols,stepY=Math.max(12,(H*.62)/Math.max(7,Math.ceil(2*roles.filter(x=>x.side===r.side).length/cols)));
   const x=W*(a+(col+.5)*(b-a)/cols),y=H*.31+row*stepY;
   soldiers.push({id:soldiers.length,role:r,team:r.side,x,y,originX:x,originY:y,life:1,phase:i*1.71+j*.43,retreat:0});
  }
 });
 clock=0;round=0;state="ready";safeText("war-step","Armeijat valmiina · 100 sotilasta");
 const cnt={bear:0,bull:0,neutral:0};soldiers.forEach(s=>cnt[s.team]++);
 for(const side of Object.keys(cnt))safeText("army-"+side, String(cnt[side]));
 announce();paint();
}
function renderArena(){
 const d=Math.min(window.devicePixelRatio||1,2),W=Math.max(290,c.clientWidth),H=Math.max(280,c.clientHeight);
 if(c.width!==Math.round(W*d)||c.height!==Math.round(H*d)){c.width=Math.round(W*d);c.height=Math.round(H*d);}
 ctx.setTransform(d,0,0,d,0,0);
 const g=ctx.createLinearGradient(0,0,W,H);g.addColorStop(0,"#253c34");g.addColorStop(1,"#101d27");ctx.fillStyle=g;ctx.fillRect(0,0,W,H);
 ctx.strokeStyle="#7b9b7a17";ctx.lineWidth=1;
 for(let x=0;x<W;x+=24){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,H);ctx.stroke()}
 for(let y=0;y<H;y+=24){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(W,y);ctx.stroke()}
 for(const s of ["bear","neutral","bull"]){
  let x=s==="bear"?0:s==="neutral"?W*.35:W*.7;
  ctx.fillStyle=s==="bear"?"#e25c6814":s==="bull"?"#4fe9a914":"#e9c96a0e";
  ctx.fillRect(x,0,W*(s==="neutral"?.3:.32),H);
 }
 const r=Math.max(3.1,Math.min(6.2,W/115));
 const active=state==="battle",elapsed=active?Math.min(1,clock/27):state==="done"?1:0;
 for(const s of soldiers){
  const dx=s.team==="bear"?1:s.team==="bull"?-1:0;
  const nudge=dx*W*.22*Math.min(1,elapsed*1.7);
  const spread=Math.sin(clock*2+s.phase)*2*elapsed;
  const decay=state==="done"&&s.team!==result?0.13:1;
  const x=s.originX+nudge+(Math.sin(s.phase)*W*.025*elapsed);
  const y=s.originY+spread;
  ctx.save();ctx.translate(x,y);ctx.globalAlpha=decay;
  ctx.fillStyle="#091a1ba0";ctx.beginPath();ctx.ellipse(1,r*.93,r*1.15,r*.45,0,0,Math.PI*2);ctx.fill();
  ctx.strokeStyle="#b7ced6";ctx.lineWidth=1.4;ctx.beginPath();ctx.moveTo(0,-r*.1);ctx.lineTo(dx*r*2.3,-r*.6);ctx.stroke();
  ctx.fillStyle=colors[s.team];ctx.beginPath();ctx.ellipse(0,0,r*.80,r*1.04,0,0,Math.PI*2);ctx.fill();
  ctx.strokeStyle="#ecf9fa88";ctx.lineWidth=.7;ctx.stroke();
  ctx.fillStyle="#d6e7e7";ctx.beginPath();ctx.arc(0,-r*.12,r*.63,0,2*Math.PI);ctx.fill();
  ctx.fillStyle=colors[s.team];ctx.fillRect(-r*.6,-r*.3,r*1.1,r*.42);
  ctx.fillStyle="#334d5f";ctx.beginPath();ctx.ellipse(-dx*r*.7,r*.42,r*.56,r*.67,0,0,Math.PI*2);ctx.fill();
  ctx.restore();
 }
 if(active){
  const k=clock*3.8;
  for(let i=0;i<Math.min(30,Math.floor(clock*2));i++){
   const x=W*(.43+.15*Math.sin(i*9.7+k*.19)),y=H*(.28+.59*Math.abs(Math.sin(i*2.31+k*.32)));
   ctx.fillStyle=i%3?"#ffdb9090":"#cee9d590";ctx.beginPath();ctx.arc(x,y,1.5+(i%3),0,2*Math.PI);ctx.fill();
  }
 }
 ctx.fillStyle="#e7f2e1";ctx.font="bold 12px system-ui";ctx.textAlign="center";ctx.fillText("50 PERUSTELUA  ·  100 SOTILASTA",W/2,22);
 ctx.font="bold 10px system-ui";ctx.fillStyle=colors.bear;ctx.fillText("LASKEE",W*.14,43);ctx.fillStyle=colors.neutral;ctx.fillText("EPÄVARMA",W*.5,43);ctx.fillStyle=colors.bull;ctx.fillText("NOUSEE",W*.85,43);
 if(state==="done"){ctx.fillStyle=colors[result];ctx.font="bold 27px system-ui";ctx.fillText("TUOMIO: "+labels[result],W/2,H-29);}
}
function paint(){renderArena();}
function animate(ts){
 if(!rafPrev)rafPrev=ts;const dt=Math.min(.05,(ts-rafPrev)/1000);rafPrev=ts;
 if(state==="battle"){
  clock+=dt*playSpeed;
  if(Math.floor(clock/5)!==round){round=Math.floor(clock/5);announce();}
  safeText("war-step","Väittelykierros "+Math.min(6,Math.floor(clock/5)+1)+"/6 · "+Math.round(clock)+"/30 s");
  if(clock>=30){state="done";safeText("war-speaker","Lopullinen yhteenveto");safeText("war-speech","Markkinasuunnan valitsi sulkeutuneisiin kynttilöihin perustuva pisteytys. Taisteluefektit eivät muuta suuntaa.");safeText("war-step","Taistelu päättyi · "+labels[result]);}
 }
 renderArena();requestAnimationFrame(animate);
}
Q("war-analyze").addEventListener("click",fetchCandles);
Q("war-play").addEventListener("click",()=>{if(!roles.length)return;setupSoldiers();state="battle";playSpeed=1;speechReset();});
function speechReset(){round=-1;announce();}
Q("war-speed").addEventListener("click",()=>{playSpeed=playSpeed===1?2:playSpeed===2?4:1;safeText("war-speed","Nopeus "+playSpeed+"×");});
Q("war-toggle-roles").addEventListener("click",()=>{const p=Q("war-roles");p.hidden=!p.hidden;safeText("war-toggle-roles",p.hidden?"Näytä 50 asiantuntijaa":"Piilota asiantuntijat");});
c.addEventListener("click",e=>{
 const box=c.getBoundingClientRect(),xx=e.clientX-box.left,yy=e.clientY-box.top;
 let best=null,dist=Infinity;
 for(const s of soldiers){let dx=s.team==="bear"?1:s.team==="bull"?-1:0,x=s.originX+dx*c.clientWidth*.22*Math.min(1,(state==="battle"?clock/27:state==="done"?1:0)*1.7)+(Math.sin(s.phase)*c.clientWidth*.025*(state==="battle"?Math.min(1,clock/27):state==="done"?1:0)),y=s.originY+(state==="battle"?Math.sin(clock*2+s.phase)*2:0);const d=Math.hypot(x-xx,y-yy);if(d<dist){dist=d;best=s;}}
 if(best&&dist<20){safeText("war-speaker",best.role.name+" — "+labels[best.team]);safeText("war-speech",best.role.reason);}
});
window.addEventListener("resize",()=>{if(state!=="battle"&&state!=="done"&&roles.length)setupSoldiers();paint();});
Q("war-play").disabled=true;
requestAnimationFrame(animate);
fetchCandles();
})();