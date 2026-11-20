/* Pure performance review model. All dates are game UTC calendar dates. */
(function(root,factory){const api=factory();if(typeof module==="object"&&module.exports)module.exports=api;else root.ZRouteReview=api;})(globalThis,function(){
"use strict";
const DAYS=["MON","TUE","WED","THU","FRI","SAT"],key=s=>String(s??"").trim().normalize("NFC").toLowerCase(),day=t=>String(t||"").slice(0,10).replace(/\./g,"-"),add=(d,n)=>new Date(Date.parse(d+"T00:00:00Z")+86400000*n).toISOString().slice(0,10);
const valid=v=>v!=null&&String(v).trim()!==""&&Number.isSafeInteger(Number(v))&&Number(v)>=0;
function arr(v){try{const a=JSON.parse(v||"[]");return Array.isArray(a)?a:[];}catch{return [];}}
function build(input,opts){
 const {week,today,excludeToday,excludeJoined,excludeLeft,donGoal,vsGoal,guild}=opts;
 const end=add(week,7),cutoff=excludeToday?today:add(today,1),stop=end<cutoff?end:cutoff;
 const activeDate=Array.from({length:7},(_,i)=>add(week,i)).filter(d=>d<stop),activeDays=DAYS.filter((_,i)=>activeDate.includes(add(week,i)));
 const isD3=key(guild)==="d3ad",rosterById=new Map(),names=new Map();
 for(const r of isD3?input.roster||[]:[]){
  if(String(r.server)!=="125"||r.coordinate_source!=="passive_network_world_xy"||!r.player_id||!r.username)continue;
  const id=String(r.player_id),p={id,name:r.username.trim(),guild:r.alliance_tag||r.alliance_name||"",at:r.roster_snapshot_at_utc||"",aliases:[r.username,...arr(r.known_aliases_json).filter(x=>typeof x==="string")]};
  if(!rosterById.has(id)||p.at>=rosterById.get(id).at)rosterById.set(id,p);
 }
 for(const p of rosterById.values())for(const a of new Set(p.aliases.map(key).filter(Boolean))){if(!names.has(a))names.set(a,new Set());names.get(a).add(p.id);}
 function identity(name,id){if(id)return "id:"+String(id);const ids=names.get(key(name));return ids?.size===1?"id:"+[...ids][0]:"name:"+key(name);}
 const map=new Map(),events=new Map(),ambiguousIds=new Set();
 function row(name,id){const ident=identity(name,id),p=ident.startsWith("id:")?rosterById.get(ident.slice(3)):null;
  if(!map.has(ident))map.set(ident,{id:ident,name:p?.name||String(name).trim(),aliases:p?.aliases||[name],don:null,vs:new Map(),meta:null,missing:[],below:[],missingEntry:[],identityAmbiguous:!id&&(names.get(key(name))?.size||0)>1,current:!!p&&key(p.guild)==="d3ad"});
  return map.get(ident);
 }
 const seenEvents=new Set();
 for(const e of isD3?input.changes||[]:[]){const t=day(e.game_event_time_utc||e.timestamp),kind=key(e.event);
  if(!/^\d{4}-\d{2}-\d{2}$/.test(t)||t>today||!e.player||!["joined","join","left","removed","kicked","leave"].includes(kind)||(key(e.guild)&&key(e.guild)!=="d3ad"))continue;
  if(e.event_id&&seenEvents.has(e.event_id))continue;if(e.event_id)seenEvents.add(e.event_id);
  const id=identity(e.player,e.player_id);if(!events.has(id))events.set(id,[]);
  events.get(id).push({date:t,at:e.game_event_time_utc||e.timestamp,kind:["joined","join"].includes(kind)?"join":"left",name:e.player,id:e.player_id});
 }
 for(const es of events.values())es.sort((a,b)=>a.at.localeCompare(b.at));
 // Current roster supplies players absent from both score lists. For older
 // weeks exclude known post-week joins unless other evidence places them in the week.
 for(const p of rosterById.values())if(key(p.guild)==="d3ad"){
  const es=events.get("id:"+p.id)||[],prior=es.filter(e=>e.date<end).at(-1),next=es.find(e=>e.date>=end);
  if(end<=today&&((prior?.kind==="left"&&!es.some(e=>e.kind==="join"&&e.date>=week&&e.date<end))||(next?.kind==="join"&&!prior)))continue;
  row(p.name,p.id);
 }
 // D3AD alliance-oplog departures and joins in the selected week are roster
 // evidence even if those players never appeared on a score list.
 for(const es of events.values())for(const e of es)if(e.date>=week&&e.date<end)row(e.name,e.id);
 function latest(list){const rows=list.filter(r=>r.username&&valid(r.points));const stamp=rows.map(r=>r.captured_at||"").sort().at(-1)||"";return stamp?rows.filter(r=>r.captured_at===stamp):rows;}
 function scoreMap(list){const out=new Map();for(const r of latest(list)){if(!r.player_id&&names.get(key(r.username))?.size>1)for(const id of names.get(key(r.username)))ambiguousIds.add("id:"+id);const m=row(r.username,r.player_id);out.set(m.id,Math.max(out.get(m.id)??0,Number(r.points)));}return out;}
 const dailyVS=new Map();
 for(const d of activeDays){const list=latest((input.vs||[]).filter(r=>r.week_start===week&&r.day===d));if(list.length)dailyVS.set(d,scoreMap(list));}
 const dailyDon=new Map(),unknownDaily=new Set(),finalizedDays=[];
 for(const d of activeDate){
  const derived=(input.derivedDon||[]).filter(r=>r.week_start===week&&r.game_date===d);
  const usingDerived=derived.length>0;
  const selected=usingDerived?derived:(input.dailyDon||[]).filter(r=>r.week_start===week&&r.game_date===d);
  if(usingDerived)for(const r of derived)if(String(r.source||"").startsWith("UNKNOWN_")){
   unknownDaily.add(identity(r.username,r.player_id));row(r.username,r.player_id);
  }
  const list=latest(selected);
  if(list.length){dailyDon.set(d,scoreMap(list));if(usingDerived)finalizedDays.push(d);}
 }
 // If excluding today in the current week, a weekly cumulative snapshot
 // may contain today's points. Use daily records exclusively in that case.
 const fullWeek=end<=today,weeklyAllowed=activeDate.length>0&&(fullWeek||!excludeToday);
 // Most recently captured pre-day cumulative value is authoritative for
 // days strictly before that game date; it excludes the ongoing game day.
 const usableBaselines=isD3?(input.baselines||[]).filter(r=>
  r.week_start===week&&r.game_date<=today&&r.game_date>week&&
  valid(r.pre_day_total)&&r.player_id&&r.captured_at):[];
 const baselineDays=[...new Set(usableBaselines.map(r=>r.game_date))].sort();
 const baselineDay=excludeToday||fullWeek?baselineDays.at(-1)||"":""; 
 const baselineRecords=baselineDay?usableBaselines.filter(r=>r.game_date===baselineDay):[];
 const baselineMap=new Map(baselineRecords.map(r=>["id:"+r.player_id,Number(r.pre_day_total)]));
 const baselineCount=baselineDay?Math.max(0,Math.min(7,Math.round((Date.parse(baselineDay+"T00:00:00Z")-Date.parse(week+"T00:00:00Z"))/86400000))):0;
 const weeklyRows=weeklyAllowed?latest((input.don||[]).filter(r=>r.week_start===week&&(!r.captured_at||day(r.captured_at)<=today))):[];
 const weeklyDon=weeklyRows.length?scoreMap(weeklyRows):null;
 const donationDays=baselineRecords.length?baselineCount:weeklyDon?(fullWeek?7:Math.max(0,activeDate.filter(d=>d<=day(weeklyRows[0].captured_at||today)).length)):dailyDon.size;
 const effectiveDonGoal=Math.ceil(donGoal*donationDays/7);
 // Membership metadata is optional and not the basis for zero fill.
 for(const m of input.members||[])if(m.username){const ident=identity(m.username,m.player_id);if(map.has(ident))map.get(ident).meta={...m};}
 const excluded={joined:0,left:0,total:0};
 const rows=[];
 for(const m of map.values()){
  if(ambiguousIds.has(m.id))m.identityAmbiguous=true;
  const es=events.get(m.id)||[],joined=es.filter(e=>e.kind==="join").at(-1),weekEvents=es.filter(e=>e.date>=week&&e.date<end&&e.date<=today);
  const joinedWeek=weekEvents.some(e=>e.kind==="join"),leftWeek=weekEvents.some(e=>e.kind==="left");
  if(joined&&joined.date<=today)m.meta={...(m.meta||{}),joined_at:joined.date};
  m.joinedWeek=joinedWeek;m.leftWeek=leftWeek;
  if(excludeJoined&&joinedWeek||excludeLeft&&leftWeek){if(excludeJoined&&joinedWeek)excluded.joined++;if(excludeLeft&&leftWeek)excluded.left++;excluded.total++;continue;}
  for(const d of activeDays){const list=dailyVS.get(d);if(!list){m.missing.push(d);continue;}if(list.has(m.id)){m.vs.set(d,list.get(m.id));continue;}if(m.identityAmbiguous){m.missing.push(d);continue;}m.vs.set(d,0);m.missingEntry.push(d);}
  if(baselineRecords.length){
   m.don=m.identityAmbiguous?null:baselineMap.get(m.id)??0;
   m.donAbsent=!baselineMap.has(m.id)&&m.don===0;
  }else if(weeklyDon){m.don=weeklyDon.has(m.id)?weeklyDon.get(m.id):m.identityAmbiguous?null:0;m.donAbsent=!weeklyDon.has(m.id)&&m.don===0;}
  else if(dailyDon.size){const lists=[...dailyDon.values()],has=lists.some(x=>x.has(m.id));m.don=m.identityAmbiguous||unknownDaily.has(m.id)?null:lists.reduce((sum,x)=>sum+(x.get(m.id)??0),0);m.donAbsent=!has&&m.don===0;}
  m.lowDon=!m.identityAmbiguous&&m.don!==null&&m.don<effectiveDonGoal;
  m.below=m.identityAmbiguous?[]:activeDays.filter(d=>m.vs.has(d)&&m.vs.get(d)<vsGoal);
  m.vsIssues=m.below.length>0;m.review=m.lowDon||m.vsIssues;
  rows.push(m);
 }
 return {rows,activeDays,activeDate,vsDays:[...dailyVS.keys()],donationDays,effectiveDonGoal,donationSource:baselineRecords.length?"pre-day verified ("+baselineDay+")":weeklyDon?"weekly":dailyDon.size?"daily":"unavailable",finalizedDays,excluded,rosterCount:[...rosterById.values()].filter(p=>key(p.guild)==="d3ad").length};
}
function visible(rows,filter,search){const q=key(search);return rows.filter(m=>(!q||[m.name,...(m.aliases||[])].some(s=>key(s).includes(q)))&&(filter==="all"||filter==="review"&&m.review||filter==="don"&&m.lowDon||filter==="vs"&&m.vsIssues||filter==="missing"&&(m.don===null||m.donAbsent||m.missing.length||m.missingEntry.length)));}
function bad(rows,filter){return rows.filter(m=>filter==="don"?m.lowDon:filter==="vs"?m.vsIssues:m.review);}
return {build,visible,bad};
});