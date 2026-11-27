(function(){
"use strict";
// Public producer facts: JeffxLabs/zrouteredemption data/resources.json (client table).
const CURVES={"food":[0,700,1300,1900,2500,3100,3700,4300,4900,5500,6100,6800,7700,8600,9700,11000,12600,14500,17000,19700,23400,27600,32600,38000,44100,52000,61300,71900,84500,99400,116900],"metal":[0,700,1300,1900,2500,3100,3700,4300,4900,5500,6100,6800,7700,8600,9700,11000,12600,14500,17000,19700,23400,27600,32600,38000,44100,52000,61300,71900,84500,99400,116900],"oil":[0,700,1300,1900,2500,3100,3700,4300,4900,5500,6100,6800,7700,8600,9700,10900,12500,14400,16900,19600,23300,27600,32500,37800,43900,51800,61100,71700,84200,99000,116500]};
const HOURS=[4,8,12,16,24];
const RESOURCES=["food","metal","oil"];
const MODES=["levels","base","effective"];
const number=(value,min=0,max=1e9)=>{
  if((typeof value!=="string"&&typeof value!=="number")||String(value).trim()==="")return null;
  const n=Number(value);return Number.isFinite(n)&&n>=min&&n<=max?n:null;
};
const optional=(value)=>value==null||String(value).trim()==="";
function producerRate(resource,input){
  if(!RESOURCES.includes(resource)||optional(input))return null;
  if(String(input).trim()==="0")return 0;
  const list=String(input).split(",").map(v=>v.trim());
  if(list.length>30||list.some(v=>!/^([1-9]|[12][0-9]|30)$/.test(v)))return null;
  return list.reduce((total,level)=>total+CURVES[resource][Number(level)],0);
}
function productionRates(resource,mode,values){
  if(mode==="effective")return {normal:number(values.effective),boosted:number(values.boosted)};
  const base=mode==="levels"?producerRate(resource,values.levels):number(values.base);
  const bonus=optional(values.bonus)?0:number(values.bonus,-100,10000);
  const extra=optional(values.extra)?null:number(values.extra,-100,10000);
  if(base===null||bonus===null)return {normal:null,boosted:null};
  const normal=base*(100+bonus)/100;
  const boosted=extra===null||bonus+extra < -100?null:base*(100+bonus+extra)/100;
  return {normal,boosted};
}
const product=(rate,hours)=>rate===null?null:rate*hours;
const rankOf=(value)=>Number.isInteger(Number(value))&&Number(value)>=1&&Number(value)<=5?Number(value):1;
function queueSavings(kind,rank,a,b){
  const maxPerQueue=(kind==="build"?2:4)*rankOf(rank);
  const byQueue=[a,b].map(t=>Math.min(number(t)??0,maxPerQueue));
  const total=byQueue[0]+byQueue[1];return {maxPerQueue,byQueue,total};
}
function limited(base,rank,room){
  const max=base*rankOf(rank);
  const actual=number(room);return {max,result:actual===null?null:Math.min(max,Math.floor(actual))};
}
function stamina(before){
  return before===null?null:{bonus:before/2,total:before*1.5};
}
function init(doc){
  const byId=(id)=>doc.getElementById(id);
  const root=byId("payout-controls");
  if(!root)return;
  const fmt=new Intl.NumberFormat("en",{maximumFractionDigits:2});
  const f=(n)=>n===null?"Not entered":fmt.format(n);
  const value=(id)=>byId(id).value;
  const node=(tag,string,cls)=>{
    const el=doc.createElement(tag); el.textContent=string;
    if(cls)el.className=cls;
    return el;
  };
  function updateProduction(){
    const mode=MODES.includes(value("production-mode"))?value("production-mode"):"levels";
    for(const el of root.querySelectorAll("[data-production]"))el.hidden=!el.dataset.production.split(" ").includes(mode);
    const message={levels:"Enter comma-separated levels 1 to 30, or 0 if you own no producers of that type. Then add the total bonus for that resource.",base:"Enter the combined unbuffed hourly rate. Bonuses use addition: +200% normal with +50 extra points gives +250%.",effective:"Enter the already-adjusted hourly rate. Enter a separate effective buffed rate to compare. No percentage is applied in this mode."};
    const records=Object.fromEntries(RESOURCES.map(r=>{
      const vals=Object.fromEntries(["levels","base","bonus","extra","effective","boosted"].map(k=>[k,value(r+"-"+k)]));
      return [r,productionRates(r,mode,vals)];
    }));
    const invalid=RESOURCES.some(r=>mode==="levels"&&!optional(value(r+"-levels"))&&records[r].normal===null);
    byId("production-note").textContent=message[mode]+(invalid?" Check entries with no result: levels must be whole numbers in the supported range, and bonuses must be valid.":"");
    const grid=byId("production-output");
    const cards=HOURS.map((h,index)=>{
      const card=node("article","","calc-rank");
      card.append(node("h4","Rank "+(index+1)+" · "+h+"h"));
      const list=node("ul","");
      for(const r of RESOURCES){
        const row=node("li","");
        const {normal,boosted}=records[r];
        row.append(node("strong",r[0].toUpperCase()+r.slice(1)+" "+f(product(normal,h))));
        if(boosted!==null){
          const diff=normal===null?null:product(boosted-normal,h);
          row.append(node("span","Buffed "+f(product(boosted,h))+(diff===null?"":" ("+(diff>=0?"+":"")+f(diff)+")")));
        }
        list.append(row);
      }
      card.append(list);return card;
    });
    grid.replaceChildren(...cards);
    grid.zrProductionRates=records;
    if(doc.defaultView?.CustomEvent)doc.dispatchEvent(new doc.defaultView.CustomEvent("zroute:production-rates",{detail:records}));
  }
  function updateOther(){
    const q=queueSavings(value("queue-skill"),value("queue-rank"),value("queue-a"),value("queue-b"));
    byId("queue-output").textContent="Up to "+f(q.maxPerQueue)+"h per queue. Your timers: "+f(q.total)+"h total ("+q.byQueue.map(x=>f(x)+"h").join(" + ")+").";
    const s=stamina(number(value("free-stamina")));
    byId("stamina-output").textContent=s?f(s.total)+" stamina total (+"+f(s.bonus)+") before any in-game rounding.":"Enter the unmodified free claim.";
    for(const [amount,rank,capacity,target,unit] of [[50,"reserve-rank","reserve-space","reserve-output","troops gained"],[1000,"heal-rank","untreated","heal-output","troops healed"]]){
      const cap=limited(amount,value(rank),value(capacity));
      byId(target).textContent=cap.result===null?"Up to "+f(cap.max)+" "+unit+".":f(cap.result)+" "+unit+" per activation (rank limit: "+f(cap.max)+").";
    }
  }
  const refresh=()=>{updateProduction();updateOther()};
  root.addEventListener("input",refresh);
  root.addEventListener("change",refresh);
  refresh();root.hidden=false;
}
if(typeof module==="object"&&module.exports)module.exports={HOURS,producerRate,productionRates,product,queueSavings,limited,stamina,init};
else init(document);
})();
