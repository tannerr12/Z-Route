/* Read-only guild performance ranking. Missing list entry != missing dataset. */
(function(root,factory){const api=factory();if(typeof module==="object"&&module.exports)module.exports=api;else root.ZRouteChoppingBlock=api;})(typeof globalThis!=="undefined"?globalThis:this,function(){
"use strict";
const key=s=>String(s??"").trim().normalize("NFC").toLowerCase();
const count=v=>{if(v==null||String(v).trim()==="")return null;const n=Number(v);return Number.isSafeInteger(n)&&n>=0?n:null;};
const GAME_OFFSET_MS=2*60*60*1000;
function gameDay(t){
 if(typeof t==="string"&&/^\d{4}-\d{2}-\d{2}$/.test(t))return t;
 if(typeof t==="string"&&/^\d{4}\.\d{2}\.\d{2}(?: |$)/.test(t))return t.slice(0,10).replace(/\./g,"-");
 const value=t instanceof Date?t.getTime():typeof t==="number"?t:Date.parse(String(t||""));
 return Number.isFinite(value)?new Date(value-GAME_OFFSET_MS).toISOString().slice(0,10):"";
}
const date=gameDay;
const validDay=s=>/^\d{4}-\d{2}-\d{2}$/.test(s);
const maxTime=rows=>rows.reduce((a,r)=>String(r.captured_at||"")>a?String(r.captured_at):a,"");
const days=["MON","TUE","WED","THU","FRI","SAT"];
function csv(s){const rows=[];let r=[],v="",q=false;s=s.replace(/^\uFEFF/,"");for(let i=0;i<s.length;i++){const c=s[i];if(q){if(c==='"'&&s[i+1]==='"'){v+='"';i++;}else if(c==='"')q=false;else v+=c;}else if(c==='"')q=true;else if(c===","){r.push(v);v="";}else if(c==="\n"||c==="\r"){if(c==="\r"&&s[i+1]==="\n")i++;r.push(v);if(r.some(x=>x!==""))rows.push(r);r=[];v="";}else v+=c;}if(q)throw Error("Incomplete CSV record");if(r.length||v){r.push(v);rows.push(r);}const h=rows.shift()||[];return rows.map(r=>Object.fromEntries(h.map((x,i)=>[x.trim(),r[i]??""])));}
function arr(v){try{const a=JSON.parse(v||"[]");return Array.isArray(a)?a:[];}catch{return [];}}
function roster(rows){
 const ids=new Map();
 for(const r of rows){if(String(r.server)!=="125"||r.coordinate_source!=="passive_network_world_xy"||!r.player_id||!r.username)continue;const id=String(r.player_id);const p={id,name:r.username.trim(),guild:(r.alliance_tag||r.alliance_name||"").trim(),power:count(r.power),kills:count(r.kills),history:arr(r.player_history_json),killsAt:r.kills_observed_at_utc||"",observed:r.roster_snapshot_at_utc||"",aliases:[r.username,...arr(r.known_aliases_json).filter(x=>typeof x==="string")]};if(!ids.has(id)||p.observed>=ids.get(id).observed)ids.set(id,p);}
 const names=new Map();for(const p of ids.values())for(const a of new Set(p.aliases.map(key).filter(Boolean))){if(!names.has(a))names.set(a,new Set());names.get(a).add(p.id);}
 return {members:[...ids.values()].filter(p=>key(p.guild)==="d3ad"),ids,names};
}
function resolve(name,model){const ids=model.names.get(key(name));return ids?.size===1?[...ids][0]:null;}
function newest(rows){const valid=rows.filter(r=>key(r.username)&&count(r.points)!==null);const stamp=maxTime(valid);return {rows:stamp?valid.filter(r=>r.captured_at===stamp):valid,stamp};}
function scores(rows,model){
 const {rows:latest,stamp}=newest(rows);
 const map=new Map(),ambiguous=new Set(),unmatched=new Set(),duplicates=new Set();
 // Finalized donation rows carry stable IDs. Use names only when no ID is
 // supplied; shared historical aliases must not override a known account.
 const identity=r=>r.player_id?String(r.player_id):resolve(r.username,model);
 function protectAliases(r){if(!r.player_id)for(const candidate of model.names.get(key(r.username))||[])ambiguous.add(candidate);}
 const unknowns=rows.filter(r=>String(r.source||"").startsWith("UNKNOWN_"));
 for(const r of unknowns){const id=identity(r);if(id)ambiguous.add(id);else protectAliases(r);}
 for(const r of latest){
  const id=identity(r);
  if(!id){unmatched.add(r.username);protectAliases(r);continue;}
  if(!map.has(id))map.set(id,count(r.points));
  else{duplicates.add(id);map.set(id,Math.max(map.get(id),count(r.points)));}
 }
 return {map,stamp,available:latest.length>0||unknowns.length>0,ambiguous,unmatched,duplicates,size:latest.length};
}
function weekly(week,vs,don,model){const v=vs.filter(r=>r.week_start===week),d=don.filter(r=>r.week_start===week);const total=scores(v.filter(r=>["WEEKLY","WEEK","TOTAL"].includes(String(r.day).toUpperCase())),model);const daily=days.map(day=>[day,scores(v.filter(r=>String(r.day).toUpperCase()===day),model)]).filter(([,x])=>x.available);const donation=scores(d,model);return {week,total,daily,donation,vsAvailable:total.available||daily.length>0};}
function nextWeek(w){const t=Date.parse(w+"T00:00:00Z");return new Date(t+7*86400000).toISOString().slice(0,10);}
function frenzySnapshots(store){
 if(store?.schema_version!==1||!Array.isArray(store.snapshots))return [];
 return store.snapshots.filter(s=>s&&typeof s.snapshot_id==="string"&&Number.isFinite(Date.parse(s.captured_at_utc))&&Array.isArray(s.players)&&s.players.length>0&&s.player_count===s.players.length).sort((a,b)=>Date.parse(b.captured_at_utc)-Date.parse(a.captured_at_utc));
}
function frenzyBoard(snapshot,model){
 const map=new Map(),otherGuild=new Map(),ambiguous=new Set();
 if(!snapshot||!Array.isArray(snapshot.players)||!snapshot.players.length||snapshot.player_count!==snapshot.players.length)return {available:false,map,otherGuild,ambiguous,size:0,stamp:"",guildSize:0};
 const rows=snapshot.players.filter(p=>String(p.server)==="125"&&p.id&&count(p.points)!==null);
 const guildRows=rows.filter(p=>key(p.guild)==="d3ad");
 if(!guildRows.length)return {available:false,map,otherGuild,ambiguous,size:rows.length,stamp:snapshot.captured_at_utc,guildSize:0};
 const seen=new Set();
 for(const p of rows){const id=String(p.id);if(seen.has(id)){ambiguous.add(id);continue;}seen.add(id);
  if(key(p.guild)==="d3ad")map.set(id,count(p.points));else otherGuild.set(id,p.guild||"Unaffiliated");
 }
 return {available:true,map,otherGuild,ambiguous,size:snapshot.players.length,stamp:snapshot.captured_at_utc,guildSize:guildRows.length};
}
function extract(week,model,vs,don,attacks,events,changes,snapshot=null){
 const board=frenzyBoard(snapshot,model),w=weekly(week,vs,don,model),end=nextWeek(week),war=new Map(),frenzy=new Map(),joins=new Map(),seenWar=new Set(),seenEvent=new Set();const inWeek=d=>d>=week&&d<end;
 for(const x of attacks||[]){const t=date(x.game_event_time_utc||x.timestamp);if(!inWeek(t)||key(x.attacker_guild)!=="d3ad"||String(x.attacker_server)!=="125"||key(x.attack_direction)!=="outgoing")continue;const id=resolve(x.attacker,model);if(!id||!x.event_id||seenWar.has(x.event_id))continue;seenWar.add(x.event_id);war.set(id,(war.get(id)||0)+1);}
 for(const x of events||[]){if(x.category!=="player"||!inWeek(x.event_day_utc||date(x.timestamp_utc))||key(x.player_guild)!=="d3ad"||String(x.player_server)!=="125"||count(x.points)===null||!x.event_key||seenEvent.has(x.event_key))continue;seenEvent.add(x.event_key);const id=String(x.player_id);frenzy.set(id,(frenzy.get(id)||0)+Number(x.points));}
 for(const x of changes||[]){if(x.player_id_source==="conflicting_identity"||!["join","joined"].includes(key(x.event))||key(x.guild)&&key(x.guild)!=="d3ad")continue;const id=String(x.player_id||resolve(x.player,model)||"");const t=date(x.game_event_time_utc||x.timestamp);if(id&&validDay(t)&&(!joins.has(id)||t>joins.get(id)))joins.set(id,t);}
 const rows=model.members.map(p=>{const id=p.id;
 let vp=null,dp=null;const vm=w.total.available?w.total:null;
 if(vm){if(!vm.ambiguous.has(id))vp=vm.map.get(id)??0;}
 else if(w.daily.length&&!w.daily.some(([,s])=>s.ambiguous.has(id)))vp=w.daily.reduce((s,[,x])=>s+(x.map.get(id)??0),0);
 if(w.donation.available&&!w.donation.ambiguous.has(id))dp=w.donation.map.get(id)??0;
 const missed=w.daily.filter(([,s])=>!s.map.has(id)&&!s.ambiguous.has(id)).map(([day])=>day);
 const flagged=(vm?.ambiguous.has(id)||vm?.duplicates.has(id)||w.donation.ambiguous.has(id)||w.donation.duplicates.has(id)||w.daily.some(([,s])=>s.ambiguous.has(id)||s.duplicates.has(id)))??false;
 const joined=joins.get(id)||"",newJoin=joined>=week;
 const afterFrenzy=!!joined&&!!board.stamp&&joined>=date(board.stamp);
 let frenzyStatus="unavailable",fp=null;
 if(board.available){if(board.ambiguous.has(id))frenzyStatus="ambiguous";else if(board.map.has(id)){fp=board.map.get(id);frenzyStatus=fp===0?"zero":"listed";}else if(afterFrenzy)frenzyStatus="joined_after_or_on_capture";else if(board.otherGuild.has(id))frenzyStatus="other_guild";else{fp=0;frenzyStatus="missing";}}
 return {...p,vs:vp,donations:dp,war:war.get(id)??null,frenzy:fp,frenzyEvents:frenzy.get(id)??null,frenzyStatus,frenzyOtherGuild:board.otherGuild.get(id)||"",frenzyRed:frenzyStatus==="missing"||frenzyStatus==="zero",missed,vsListed:vm?vm.map.has(id):w.daily.some(([,s])=>s.map.has(id)),donListed:w.donation.map.has(id),joined,newJoin,flagged:flagged||frenzyStatus==="ambiguous"};
 });
 return {rows,w,board,warCount:seenWar.size,frenzyCount:seenEvent.size};
}

function addDays(d,n){return new Date(Date.parse(d+"T00:00:00Z")+n*86400000).toISOString().slice(0,10);}
function bounds(length,now=Date.now()){
 if(![3,7,14].includes(Number(length)))throw Error("Choose 3, 7 or 14 days");
 const today=gameDay(now),start=addDays(today,1-Number(length)),end=addDays(today,1);
 return {start,end,today,length:Number(length),now:Number(now),
         startUtcMs:Date.parse(start+"T00:00:00Z")+GAME_OFFSET_MS,
         endUtcMs:Date.parse(end+"T00:00:00Z")+GAME_OFFSET_MS};
}
function dayRange(b){return Array.from({length:b.length},(_,i)=>addDays(b.start,i));}
function vsDay(r){const i=days.indexOf(String(r.day).toUpperCase());return i>=0&&validDay(r.week_start)?addDays(r.week_start,i):"";}
function dailySets(rows,dateFn,range,model){
 const grouped=new Map();
 for(const r of rows){const d=dateFn(r);if(d>=range.start&&d<range.end){if(!grouped.has(d))grouped.set(d,[]);grouped.get(d).push(r);}}
 return [...grouped].sort(([a],[b])=>a.localeCompare(b)).map(([d,list])=>[d,scores(list,model)]).filter(([,x])=>x.available);
}
function dailyTotal(list,id){
 if(!list.length||list.some(([,x])=>x.ambiguous.has(id)))return null;
 return list.reduce((sum,[,x])=>sum+(x.map.get(id)??0),0);
}
// Recorded absolute kill measurements only. The previous observation may
// precede the range boundary; label this a scan-observed estimate, not exact.
function killRange(p,b){
 const start=b.startUtcMs??(Date.parse(b.start+"T00:00:00Z")+GAME_OFFSET_MS),end=Math.min(b.now,b.endUtcMs??(Date.parse(b.end+"T00:00:00Z")+GAME_OFFSET_MS));
 const points=new Map();
 let conflict=false;
 function add(at,value){const t=Date.parse(at),n=count(value);if(!Number.isFinite(t)||t>end||n===null)return;if(points.has(t)&&points.get(t)!==n)conflict=true;points.set(t,n);}
 for(const h of p.history||[])add(h.observed_at,h.kills);
 add(p.killsAt,p.kills);
 const sorted=[...points].sort((a,b)=>a[0]-b[0]),first=sorted.filter(x=>x[0]<=start).at(-1),last=sorted.at(-1);
 const at=x=>x?new Date(x[0]).toISOString():"";
 if(conflict||!first||!last||last[0]<start||first[0]===last[0]||last[1]<first[1]||start-first[0]>3*86400000||end-last[0]>3*86400000||sorted.some((x,i)=>i>0&&x[0]>=start&&x[1]<sorted[i-1][1]))return {value:null,from:at(first),to:at(last)};
 return {value:last[1]-first[1],from:at(first),to:at(last)};
}
function extractRange(b,model,vs,donDaily,attacks,events,changes,snapshots,derivedDaily=[]){
 const inRange=d=>d>=b.start&&d<b.end;
 // A completed-day delta replaces that day's raw partial Today snapshot.
 // An explicit UNKNOWN row protects its player from an inferred zero.
 const finalized=new Set(derivedDaily.filter(x=>x.game_date>=b.start&&x.game_date<b.end).map(x=>x.game_date));
 const preferred=donDaily.filter(x=>!finalized.has(x.game_date)).concat(derivedDaily);
 const v=dailySets(vs,vsDay,b,model),d=dailySets(preferred,r=>r.game_date,b,model);
 const snapshot=(snapshots||[]).find(s=>inRange(date(s.captured_at_utc))&&Date.parse(s.captured_at_utc)<=b.now);
 const board=frenzyBoard(snapshot,model);
 const joins=new Map(),war=new Map(),seen=new Set();
 for(const x of changes||[]){if(x.player_id_source==="conflicting_identity"||!["join","joined"].includes(key(x.event))||key(x.guild)&&key(x.guild)!=="d3ad")continue;
  const id=String(x.player_id||resolve(x.player,model)||""),t=date(x.game_event_time_utc||x.timestamp);
  if(id&&validDay(t)&&t<=b.today&&(!joins.has(id)||t>joins.get(id)))joins.set(id,t);}
 for(const x of attacks||[]){if(!inRange(date(x.game_event_time_utc||x.timestamp))||key(x.attacker_guild)!=="d3ad"||String(x.attacker_server)!=="125"||key(x.attack_direction)!=="outgoing"||!x.event_id||seen.has(x.event_id))continue;
  const id=resolve(x.attacker,model);if(!id)continue;seen.add(x.event_id);war.set(id,(war.get(id)||0)+1);}
 const expected=dayRange(b),vsExpected=expected.filter(t=>new Date(t+"T00:00:00Z").getUTCDay()!==0);
 const rows=model.members.map(p=>{
  const id=p.id,joined=joins.get(id)||"",newJoin=joined>=b.start,kr=killRange(p,b);
  let fp=null,frenzyStatus="unavailable";
  if(board.available){
   if(board.ambiguous.has(id))frenzyStatus="ambiguous";
   else if(board.map.has(id)){fp=board.map.get(id);frenzyStatus=fp===0?"zero":"listed";}
   else if(joined&&joined>=date(board.stamp))frenzyStatus="joined_after_or_on_capture";
   else if(board.otherGuild.has(id))frenzyStatus="other_guild";
   else{fp=0;frenzyStatus="missing";}
  }
  const flagged=[...v,...d].some(([,x])=>x.ambiguous.has(id)||x.duplicates.has(id))||frenzyStatus==="ambiguous";
  return {...p,kills:kr.value,killsFrom:kr.from,killsTo:kr.to,vs:dailyTotal(v,id),donations:dailyTotal(d,id),vsListed:v.some(([,x])=>x.map.has(id)),donListed:d.some(([,x])=>x.map.has(id)),missed:v.filter(([,x])=>!x.map.has(id)&&!x.ambiguous.has(id)).map(([day])=>day),frenzy:fp,frenzyStatus,frenzyOtherGuild:board.otherGuild.get(id)||"",frenzyRed:frenzyStatus==="missing"||frenzyStatus==="zero",war:war.get(id)??null,joined,newJoin,flagged};
 });
 return {rows,v,d,board,snapshot,warCount:seen.size,vsExpected,donExpected:expected,finalizedDays:[...finalized].sort()};
}

// Relative peer standing. Zero is always zero. Positive ties receive the mean
// of their occupied positions; unknown never becomes a zero.
function standing(rows,field){const list=rows.filter(r=>Number.isFinite(r[field])).sort((a,b)=>a[field]-b[field]);const map=new Map();let i=0;while(i<list.length){let j=i+1;while(j<list.length&&list[j][field]===list[i][field])j++;const score=list[i][field]===0?0:100*((i+1+j)/2)/list.length;for(let k=i;k<j;k++)map.set(list[k].id,score);i=j;}return map;}
function rank(rows,weights){
 const fields=["vs","donations","frenzy","kills","power","activity"],enabled=fields.filter(f=>weights[f]>0&&rows.some(r=>Number.isFinite(r[f])));const total=enabled.reduce((s,f)=>s+weights[f],0),maps=Object.fromEntries(enabled.map(f=>[f,standing(rows,f)]));
 const scored=rows.map(r=>{const scores=Object.fromEntries(fields.map(f=>[f,maps[f]?.get(r.id)??null]));const known=enabled.filter(f=>scores[f]!==null);const denom=known.reduce((s,f)=>s+weights[f],0);
 const score=denom?known.reduce((s,f)=>s+scores[f]*weights[f],0)/denom:null;
 const provisional=["vs","donations"].some(f=>weights[f]>0&&!enabled.includes(f))||known.length!==enabled.length||r.flagged||r.newJoin;
 return {...r,scores,score,provisional,zeroes:(r.vs===0?1:0)+(r.donations===0?1:0)+(r.frenzy===0?1:0)};});
 const ranked=scored.filter(r=>!r.provisional&&r.score!==null).sort((a,b)=>a.score-b.score||b.zeroes-a.zeroes||a.name.localeCompare(b.name));
 ranked.forEach((r,i)=>r.rank=i&&Math.abs(r.score-ranked[i-1].score)<1e-9?ranked[i-1].rank:i+1);
 const others=scored.filter(r=>r.provisional||r.score===null).sort((a,b)=>(a.score??Infinity)-(b.score??Infinity)||a.name.localeCompare(b.name));
 return {rows:[...ranked,...others],enabled,total};
}
return {csv,key,count,roster,resolve,weekly,extract,rank,nextWeek,frenzySnapshots,frenzyBoard,bounds,extractRange,killRange,gameDay};
});

