(function(){
"use strict";
const KEY="z-route-season-1-briefing-v1";
const ROUTE=["city","strongholds","staging","window","coverage"];
const EXTRA=["declarer","rally","garrison","support","protection","decision"];
const CHECKS=["adjacent","window","ready"];
const text=value=>typeof value==="string"?value.trim().replace(/[\r\n]+/g," ").slice(0,160):"";
const activeRoute=decision=>decision==="fallback"?"fallback":"primary";
const signature=(route,extra)=>JSON.stringify([activeRoute(extra.decision),...ROUTE.map(k=>text(route[k])),text(extra.protection),text(extra.declarer),text(extra.rally),text(extra.garrison)]);
function makeBrief(primary,fallback,extra,confirm){
  const usingFallback=activeRoute(extra.decision)==="fallback";
  const route=usingFallback?fallback:primary;
  const checks=[
    [route.city,"selected city and coordinates"],
    [route.strongholds,"connected stronghold route"],
    [route.staging,"staging marker and resistance requirement"],
    [route.window,"declaration date and State Time"],
    [extra.protection,"protection status or expiry"],
    [extra.declarer,"declarer and backup"],
    [extra.rally,"rally assignments"],
    [extra.garrison,"garrison coverage"],
  ];
  const missing=checks.filter(([v])=>!text(v)).map(([,name])=>name);
  if(!confirm.adjacent)missing.push("owned adjacent stronghold check");
  if(!confirm.window)missing.push("live window and protection check");
  if(!confirm.ready)missing.push("march and coverage check");
  const ready=missing.length===0;
  const call=extra.decision==="hold"?"HOLD":
    extra.decision==="go"&&ready?"GO":
    usingFallback&&ready?"USE FALLBACK":"DRAFT - NOT A GO CALL";
  const planned=usingFallback?"Fallback":"Primary";
  const list=[["Target",route.city],["Connected strongholds",route.strongholds],["Staging / Resistance",route.staging],
    ["Declaration (State Time)",route.window],["Protection",extra.protection],["March coverage",route.coverage],
    ["Declarer",extra.declarer],["Rally leads",extra.rally],["Garrison",extra.garrison],["Support",extra.support]];
  const lines=["Season 1 battle briefing | "+call,planned+" route",...list.flatMap(([k,v])=>text(v)?[k+": "+text(v)]:[])];
  if(text(fallback.city)&&!usingFallback){
    lines.push("Fallback: "+text(fallback.city)+(text(fallback.staging)?" | "+text(fallback.staging):"")+(text(fallback.window)?" | "+text(fallback.window):""));
  }
  if(call==="HOLD"||call.startsWith("DRAFT"))lines.push("Wait for the officer call before relocating.");
  if(!ready)lines.push("Still to verify: "+missing.join(", ")+".");
  return {body:lines.join("\n"),missing,ready,call};
}
function restore(raw){
  try{const v=JSON.parse(raw);return v&&typeof v==="object"&&!Array.isArray(v)?v:{}}catch{return {}}
}
function init(doc,win){
  const byId=id=>doc.getElementById(id);
  const root=byId("brief-controls");
  if(!root)return;
  const routes=byId("route-form"),status=byId("brief-status"),destination=byId("brief-text");
  const storageWarn="Browser storage is unavailable; the briefing fields won't survive reload.";
  const source=prefix=>Object.fromEntries(ROUTE.map(k=>[k,byId(prefix+"-"+k).value]));
  const fields=()=>Object.fromEntries(EXTRA.map(k=>[k,byId("brief-"+k).value]));
  const flags=()=>Object.fromEntries(CHECKS.map(k=>[k,byId("brief-"+k).checked]));
  const currentSignature=()=>{const e=fields();return signature(source(activeRoute(e.decision)),e)};
  const clearFlags=()=>{for(const k of CHECKS)byId("brief-"+k).checked=false};
  let storage,saved={};
  try{storage=win.localStorage;saved=restore(storage.getItem(KEY))}catch{status.textContent=storageWarn}
  for(const k of EXTRA){
    const v=text(saved.extra?.[k]);
    byId("brief-"+k).value=k==="decision"&&!["draft","go","hold","fallback"].includes(v)?"draft":v;
  }
  let fingerprint=currentSignature();
  if(saved.fingerprint===fingerprint){
    for(const k of CHECKS)byId("brief-"+k).checked=saved.flags?.[k]===true;
  }
  function save(){
    try{storage.setItem(KEY,JSON.stringify({extra:fields(),flags:flags(),fingerprint}));}
    catch{status.textContent=storageWarn}
  }
  function display(){
    const next=makeBrief(source("primary"),source("fallback"),fields(),flags());
    const warn=next.missing.length?"Still to verify: "+next.missing.join(", ")+".":"All checklist fields filled. Follow the live in-game rules.";
    if(byId("brief-warning").textContent!==warn)byId("brief-warning").textContent=warn;
    destination.value=next.body;
  }
  function update(){
    const next=currentSignature();
    if(next!==fingerprint){clearFlags();fingerprint=next;}
    status.textContent="";
    display();save();
  }
  root.addEventListener("input",e=>{if(e.target!==destination)update()});
  root.addEventListener("change",e=>{if(e.target!==destination)update()});
  routes.addEventListener("input",e=>{if(e.target.hasAttribute("data-route"))update()});
  byId("brief-copy").addEventListener("click",async()=>{
    try{await win.navigator.clipboard.writeText(destination.value);status.textContent="Briefing copied. Nothing was sent.";}
    catch{destination.focus();destination.select();status.textContent="Briefing selected. Copy it manually.";}
  });
  byId("brief-clear").addEventListener("click",()=>{
    for(const k of EXTRA)byId("brief-"+k).value=k==="decision"?"draft":"";
    clearFlags();fingerprint=currentSignature();display();
    try{storage.removeItem(KEY);status.textContent="Briefing fields cleared. Your route worksheet is unchanged.";}
    catch{status.textContent="Briefing fields cleared for this session.";}
  });
  display();root.hidden=false;
}
if(typeof module==="object"&&module.exports)module.exports={makeBrief,signature,restore,init};
else init(document,window);
})();
