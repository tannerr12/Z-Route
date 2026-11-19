/* Read-only guild performance ranking. Missing list entry != missing dataset. */
(function(root,factory){const api=factory();if(typeof module==="object"&&module.exports)module.exports=api;else root.ZRouteChoppingBlock=api;})(typeof globalThis!=="undefined"?globalThis:this,function(){
"use strict";
const key=s=>String(s??"").trim().normalize("NFC").toLowerCase();
const count=v=>{if(v==null||String(v).trim()==="")return null;const n=Number(v);return Number.isSafeInteger(n)&&n>=0?n:null;};
const date=s=>String(s||"").slice(0,10);
const validDay=s=>/^\d{4}-\d{2}-\d{2}$/.test(s);
const maxTime=rows=>rows.reduce((a,r)=>String(r.captured_at||"")>a?String(r.captured_at):a,"");
const days=["MON","TUE","WED","THU","FRI","SAT"];
function csv(s){const rows=[];let r=[],v="",q=false;s=s.replace(/^\uFEFF/,"");for(let i=0;i<s.length;i++){const c=s[i];if(q){if(c==='"'&&s[i+1]==='"'){v+='"';i++;}else if(c==='"')q=false;else v+=c;}else if(c==='"')q=true;else if(c===","){r.push(v);v="";}else if(c==="\n"||c==="\r"){if(c==="\r"&&s[i+1]==="\n")i++;r.push(v);if(r.some(x=>x!==""))rows.push(r);r=[];v="";}else v+=c;}if(q)throw Error("Incomplete CSV record");if(r.length||v){r.push(v);rows.push(r);}const h=rows.shift()||[];return rows.map(r=>Object.fromEntries(h.map((x,i)=>[x.trim(),r[i]??""])));}
function arr(v){try{const a=JSON.parse(v||"[]");return Array.isArray(a)?a:[];}catch{return [];}}
function roster(rows){
 const ids=new Map();
 for(const r of rows){if(String(r.server)!=="125"||r.coordinate_source!=="passive_network_world_xy"||!r.player_id||!r.username)continue;const id=String(r.player_id);const p={id,name:r.username.trim(),guild:(r.alliance_tag||r.alliance_name||"").trim(),power:count(r.power),kills:count(r.kills),killsAt:r.kills_observed_at_utc||"",observed:r.roster_snapshot_at_utc||"",aliases:[r.username,...arr(r.known_aliases_json).filter(x=>typeof x==="string")]};if(!ids.has(id)||p.observed>=ids.get(id).observed)ids.set(id,p);}
 const names=new Map();for(const p of ids.values())for(const a of new Set(p.aliases.map(key).filter(Boolean))){if(!names.has(a))names.set(a,new Set());names.get(a).add(p.id);}
 return {members:[...ids.values()].filter(p=>key(p.guild)==="d3ad"),ids,names};
}
function resolve(name,model){const ids=model.names.get(key(name));return ids?.size===1?[...ids][0]:null;}
function newest(rows){const valid=rows.filter(r=>key(r.username)&&count(r.points)!==null);const stamp=maxTime(valid);return {rows:stamp?valid.filter(r=>r.captured_at===stamp):valid,stamp};}
function scores(rows,model){const {rows:latest,stamp}=newest(rows);const map=new Map(),ambiguous=new Set(),unmatched=new Set(),duplicates=new Set();for(const r of latest){const id=resolve(r.username,model);if(!id){unmatched.add(r.username);for(const candidate of model.names.get(key(r.username))||[])ambiguous.add(candidate);continue;}if(!map.has(id))map.set(id,count(r.points));else{duplicates.add(id);map.set(id,Math.max(map.get(id),count(r.points)));}}return {map,stamp,available:latest.length>0,ambiguous,unmatched,duplicates,size:latest.length};}
function weekly(week,vs,don,model){const v=vs.filter(r=>r.week_start===week),d=don.filter(r=>r.week_start===week);const total=scores(v.filter(r=>["WEEKLY","WEEK","TOTAL"].includes(String(r.day).toUpperCase())),model);const daily=days.map(day=>[day,scores(v.filter(r=>String(r.day).toUpperCase()===day),model)]).filter(([,x])=>x.available);const donation=scores(d,model);return {week,total,daily,donation,vsAvailable:total.available||daily.length>0};}
function nextWeek(w){const t=Date.parse(w+"T00:00:00Z");return new Date(t+7*86400000).toISOString().slice(0,10);}
function extract(week,model,vs,don,attacks,events,changes){
 const w=weekly(week,vs,don,model),end=nextWeek(week),war=new Map(),frenzy=new Map(),joins=new Map(),seenWar=new Set(),seenEvent=new Set();const inWeek=d=>d>=week&&d<end;
 for(const x of attacks||[]){const t=date(x.game_event_time_utc||x.timestamp);if(!inWeek(t)||key(x.attacker_guild)!=="d3ad"||String(x.attacker_server)!=="125"||key(x.attack_direction)!=="outgoing")continue;const id=resolve(x.attacker,model);if(!id||!x.event_id||seenWar.has(x.event_id))continue;seenWar.add(x.event_id);war.set(id,(war.get(id)||0)+1);}
 for(const x of events||[]){if(x.category!=="player"||!inWeek(x.event_day_utc||date(x.timestamp_utc))||key(x.player_guild)!=="d3ad"||String(x.player_server)!=="125"||count(x.points)===null||!x.event_key||seenEvent.has(x.event_key))continue;seenEvent.add(x.event_key);const id=String(x.player_id);frenzy.set(id,(frenzy.get(id)||0)+Number(x.points));}
 for(const x of changes||[]){if(!["join","joined"].includes(key(x.event))||key(x.guild)&&key(x.guild)!=="d3ad")continue;const id=String(x.player_id||resolve(x.player,model)||"");const t=date(x.game_event_time_utc||x.timestamp);if(id&&validDay(t)&&(!joins.has(id)||t>joins.get(id)))joins.set(id,t);}
 const rows=model.members.map(p=>{const id=p.id;
 let vp=null,dp=null;const vm=w.total.available?w.total:null;
 if(vm){if(!vm.ambiguous.has(id))vp=vm.map.get(id)??0;}
 else if(w.daily.length&&!w.daily.some(([,s])=>s.ambiguous.has(id)))vp=w.daily.reduce((s,[,x])=>s+(x.map.get(id)??0),0);
 if(w.donation.available&&!w.donation.ambiguous.has(id))dp=w.donation.map.get(id)??0;
 const missed=w.daily.filter(([,s])=>!s.map.has(id)&&!s.ambiguous.has(id)).map(([day])=>day);
 const flagged=(vm?.ambiguous.has(id)||vm?.duplicates.has(id)||w.donation.ambiguous.has(id)||w.donation.duplicates.has(id)||w.daily.some(([,s])=>s.ambiguous.has(id)||s.duplicates.has(id)))??false;
 const joined=joins.get(id)||"",newJoin=joined>=week;
 return {...p,vs:vp,donations:dp,war:war.get(id)??null,frenzy:frenzy.get(id)??null,missed,vsListed:vm?vm.map.has(id):w.daily.some(([,s])=>s.map.has(id)),donListed:w.donation.map.has(id),joined,newJoin,flagged};
 });
 return {rows,w,warCount:seenWar.size,frenzyCount:seenEvent.size};
}
// Relative peer standing. Zero is always zero. Positive ties receive the mean
// of their occupied positions; unknown never becomes a zero.
function standing(rows,field){const list=rows.filter(r=>r[field]!==null).sort((a,b)=>a[field]-b[field]);const map=new Map();let i=0;while(i<list.length){let j=i+1;while(j<list.length&&list[j][field]===list[i][field])j++;const score=list[i][field]===0?0:100*((i+1+j)/2)/list.length;for(let k=i;k<j;k++)map.set(list[k].id,score);i=j;}return map;}
function rank(rows,weights){
 const fields=["vs","donations","kills"],enabled=fields.filter(f=>weights[f]>0&&rows.some(r=>r[f]!==null));const total=enabled.reduce((s,f)=>s+weights[f],0),maps=Object.fromEntries(enabled.map(f=>[f,standing(rows,f)]));
 const scored=rows.map(r=>{const scores=Object.fromEntries(fields.map(f=>[f,maps[f]?.get(r.id)??null]));const known=enabled.filter(f=>scores[f]!==null);const denom=known.reduce((s,f)=>s+weights[f],0);
 const score=denom?known.reduce((s,f)=>s+scores[f]*weights[f],0)/denom:null;
 const provisional=enabled.length!==fields.filter(f=>weights[f]>0).length||known.length!==enabled.length||r.flagged||r.newJoin;
 return {...r,scores,score,provisional,zeroes:(r.vs===0?1:0)+(r.donations===0?1:0)};});
 const ranked=scored.filter(r=>!r.provisional&&r.score!==null).sort((a,b)=>a.score-b.score||b.zeroes-a.zeroes||a.name.localeCompare(b.name));
 ranked.forEach((r,i)=>r.rank=i&&Math.abs(r.score-ranked[i-1].score)<1e-9?ranked[i-1].rank:i+1);
 const others=scored.filter(r=>r.provisional||r.score===null).sort((a,b)=>(a.score??Infinity)-(b.score??Infinity)||a.name.localeCompare(b.name));
 return {rows:[...ranked,...others],enabled,total};
}
return {csv,key,count,roster,resolve,weekly,extract,rank,nextWeek};
});