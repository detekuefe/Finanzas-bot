// Prueba muchas combinaciones del Laboratorio en todos los activos (velas diarias, 6, 12, 18 y 24 meses)
// y guarda el ranking en data/ranking.json. Usa el mismo código del Laboratorio que está en index.html,
// así los resultados coinciden con los de la página.
// Uso: node scripts/ranking.js
const fs=require('fs');const path=require('path');const R=path.join(__dirname,'..')+'/';
const html=fs.readFileSync(R+'index.html','utf8');
const pick=n=>html.split('\n').find(l=>l.startsWith(n));
let src=[pick('const sma='),pick('const ema='),pick('function rsi(')].join('\n')+'\n'+html.slice(html.indexOf('// ---------- Laboratorio'),html.indexOf('let rerender=()=>{},curRoute=null;'));
src+='\n;globalThis.T={labRunAsset,labCond};';
globalThis.cacheT={};globalThis.esc=x=>x;globalThis.CUR='USD';globalThis.fxAt=()=>1;
eval(src);
const assets=Object.keys(JSON.parse(fs.readFileSync(R+'data/summary.json')).tickers).filter(t=>{const d=JSON.parse(fs.readFileSync(R+`data/${t}.json`));cacheT[t]=d;return d.daily.length>=200});
const C=(k,op,p,m)=>({k,op,p,m:m||'e'});
const S=[];const add=(name,group,entry,exit,extra={})=>S.push({name,group,cfg:Object.assign({tf:'d',cur:'USD',stop:'',tp:'',trail:'',cost:0.05,entry:{all:true,c:entry},exit:{all:false,c:exit}},extra)});
const ADX=(x=20)=>C('adx','up',{n:14,x});const SLOPE=C('slope','up',{ta:'SMA',a:50,n:10});const CHOP=(x=50)=>C('chop','dn',{n:14,x});
const filters=[['',[]],[' + ADX>20',[ADX(20)]],[' + ADX>25',[ADX(25)]],[' + SMA50 subiendo',[SLOPE]],[' + Choppiness<50',[CHOP(50)]]];
// Medias: cruce de dos
for(const [ta,a,tb,b] of [['EMA',5,'EMA',20],['EMA',9,'EMA',21],['EMA',10,'SMA',30],['SMA',20,'SMA',50],['SMA',50,'SMA',200]])
  for(const [fn,f] of filters) add(`${ta} ${a} sobre ${tb} ${b}${fn}`,'Cruce de medias',[C('ma2','up',{ta,a,tb,b}),...f],[C('ma2','dn',{ta,a,tb,b})]);
// Tres medias
for(const [a,b,c] of [[9,18,30],[5,10,20],[10,20,50],[20,50,100]])
  for(const [fn,f] of filters) add(`EMA ${a}/${b} sobre SMA ${c}${fn}`,'Tres medias',[C('ma3','up',{ta:'EMA',a,tb:'EMA',b,tc:'SMA',c}),...f],[C('ma3','dn',{ta:'EMA',a,tb:'EMA',b,tc:'SMA',c})]);
add('EMA 9/18 sobre SMA 30, confirmada 3 barras','Tres medias',[C('ma3','up',{},'c3')],[C('ma3','dn',{})]);
add('EMA 9/18 sobre SMA 30 con margen 1%','Tres medias',[C('ma3','up',{}),C('pmm','up',{ta:'SMA',a:30,x:1})],[C('ma3','dn',{})]);
// Precio vs media
for(const a of [20,50,100,200]) for(const [fn,f] of filters.slice(0,3)) add(`Precio sobre SMA ${a}${fn}`,'Precio vs media',[C('pma','up',{ta:'SMA',a}),...f],[C('pma','dn',{ta:'SMA',a})]);
for(const a of [20,50]) add(`Precio sobre SMA ${a} por más de 0,5 ATR`,'Precio vs media',[C('pmatr','up',{ta:'SMA',a,x:0.5,n:14})],[C('pma','dn',{ta:'SMA',a})]);
// Ichimoku
for(const [fn,f] of filters){add(`Ichimoku completo (app)${fn}`,'Ichimoku',[C('cloud','up'),C('tk','up'),C('chikou','up'),...f],[C('cloud','dn'),C('tk','dn')]);}
add('Ichimoku: precio sobre la nube','Ichimoku',[C('cloud','up')],[C('cloud','dn')]);
add('Ichimoku: Tenkan sobre Kijun','Ichimoku',[C('tk','up')],[C('tk','dn')]);
add('Ichimoku: Tenkan sobre Kijun y sobre la nube','Ichimoku',[C('tk','up'),C('cloud','up')],[C('tk','dn')]);
// MACD
for(const [fn,f] of filters.slice(0,4)) add(`MACD sobre su señal${fn}`,'MACD',[C('macd','sup'),...f],[C('macd','sdn')]);
add('MACD sobre cero','MACD',[C('macd','zup')],[C('macd','zdn')]);
add('MACD sobre su señal y sobre cero','MACD',[C('macd','sup'),C('macd','zup')],[C('macd','sdn')]);
// Rupturas
for(const [a,b] of [[10,5],[20,10],[55,20]]) for(const [fn,f] of filters.slice(0,2)) add(`Ruptura de ${a} barras, salida mínimo de ${b}${fn}`,'Rupturas',[C('donch','hi',{n:a}),...f],[C('donch','lo',{n:b})]);
// RSI / Bollinger / momentum
add('RSI 14 rebote sobre 30, venta en 70','Osciladores',[C('rsi','up',{n:14,x:30},'x')],[C('rsi','up',{n:14,x:70})]);
add('RSI 14 sobre 50 (impulso), venta bajo 45','Osciladores',[C('rsi','up',{n:14,x:50})],[C('rsi','dn',{n:14,x:45})]);
add('Bollinger: compra bajo banda inferior, venta en la media','Osciladores',[C('boll','lo')],[C('boll','mup')]);
add('Bollinger: compra bajo banda inferior con SMA 200 subiendo','Osciladores',[C('boll','lo'),C('slope','up',{ta:'SMA',a:200,n:20})],[C('boll','mup')]);
for(const n of [20,60]) add(`Rentabilidad de ${n} barras positiva`,'Impulso',[C('roc','up',{n,x:0})],[C('roc','dn',{n,x:0})]);
// Stops sobre algunas
for(const tr of [10,15,20]){add(`EMA 9/18 sobre SMA 30 + stop móvil ${tr}%`,'Con stop móvil',[C('ma3','up',{})],[C('ma3','dn',{})],{trail:tr});add(`Precio sobre SMA 50 + stop móvil ${tr}%`,'Con stop móvil',[C('pma','up',{ta:'SMA',a:50})],[C('pma','dn',{ta:'SMA',a:50})],{trail:tr});add(`Ichimoku completo + stop móvil ${tr}%`,'Con stop móvil',[C('cloud','up'),C('tk','up'),C('chikou','up')],[C('cloud','dn'),C('tk','dn')],{trail:tr})}
const W=['6m','12m','18m','24m'];
const gm=a=>a.length?Math.exp(a.reduce((s,x)=>s+Math.log((1+x.ret)/(1+x.bh)),0)/a.length)-1:null;
const med=v=>{v=[...v].sort((x,y)=>x-y);return v.length?(v.length%2?v[v.length>>1]:(v[v.length/2-1]+v[v.length/2])/2):null};
const r4=x=>x==null?null:Math.round(x*1e4)/1e4;
const out=[];
for(const s of S){s.cfg.entry.c=s.cfg.entry.c.map(T.labCond);s.cfg.exit.c=s.cfg.exit.c.map(T.labCond);
  const per={};for(const w of W)per[w]=[];
  for(const t of assets){const r=T.labRunAsset(t,{...s.cfg,assets:[t]});if(!r)continue;for(const w of W){const x=r.res[w];if(x)per[w].push({t,ret:x.ret,bh:x.bh,dd:x.dd,bhdd:x.bhdd,tr:x.trades,expo:x.expo})}}
  const stat=a=>({rel:r4(gm(a)),beat:a.filter(x=>x.ret>x.bh).length,n:a.length,risk:a.filter(x=>x.ret/Math.max(.01,-x.dd)>x.bh/Math.max(.01,-x.bhdd)).length,
    ret:r4(med(a.map(x=>x.ret))),bh:r4(med(a.map(x=>x.bh))),dd:r4(med(a.map(x=>x.dd))),bhdd:r4(med(a.map(x=>x.bhdd))),tr:r4(a.reduce((s,x)=>s+x.tr,0)/a.length),expo:r4(a.reduce((s,x)=>s+x.expo,0)/a.length)});
  const w={};for(const k of W)w[k]=stat(per[k]);w.all=stat(W.flatMap(k=>per[k]));
  const assetsRel={};for(const t of assets){const xs=W.map(k=>per[k].find(x=>x.t===t)).filter(Boolean);if(xs.length)assetsRel[t]=r4(gm(xs))}
  out.push({name:s.name,group:s.group,cfg:s.cfg,w,assets:assetsRel});}
fs.writeFileSync(R+'data/ranking.json',JSON.stringify({generated:new Date().toISOString(),to:cacheT.QQQ.daily[cacheT.QQQ.daily.length-1][0],assets,list:out}));
console.log(`Ranking: ${S.length} combinaciones en ${assets.length} activos`);
