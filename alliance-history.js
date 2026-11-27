/* Offline alliance-history model for published Z-Route observations. */
(function(root,factory){
 const api=factory();
 if(typeof module==='object'&&module.exports)module.exports=api;
 else root.ZRouteAllianceHistory=api;
})(globalThis,function(){
'use strict';
const DAY=86400000, UTC=(v)=>typeof v==='string'&&/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(v)&&/(?:Z|[+-]\d{2}:\d{2})$/i.test(v)?Date.parse(v):NaN;
const clean=v=>typeof v==='string'?v.trim():'';
const tagKey=v=>{const t=clean(v).toLowerCase();return /^(?:none|unknown|no (?:guild|alliance)|unaffiliated|n\/a|-)$/i.test(t)?'':t};
const required=['server','player_id','coordinate_source','alliance_tag','player_history_json','roster_snapshot_at_utc'];
function parseCSV(source){
 const input=String(source).replace(/^\uFEFF/,'');
 const rows=[];let row=[],field='',quoted=false,header=null;
 const flush=()=>{
  row.push(field.replace(/\r$/,''));
  if(!header)header=row.map(x=>x.trim().toLowerCase());
  else if(row.some(x=>x.length)){
   if(row.length!==header.length)throw Error('Inconsistent published roster CSV');
   rows.push(Object.fromEntries(header.map((k,i)=>[k,row[i]])));
  }
  row=[];field='';
 };
 for(let i=0;i<input.length;i++){
  const c=input[i];
  if(quoted){if(c==='"'&&input[i+1]==='"'){field+='"';i++}else if(c==='"')quoted=false;else field+=c}
  else if(c==='"'&&!field)quoted=true;
  else if(c===','){row.push(field);field=''}
  else if(c==='\n')flush();
  else field+=c;
 }
 if(quoted)throw Error('Unfinished quoted field in roster CSV');
 if(field||row.length)flush();
 if(!header||new Set(header).size!==header.length||!required.every(k=>header.includes(k)))throw Error('Published roster does not contain alliance history columns');
 return rows;
}
function tagHistory(rows,server){
 const players=new Map(),latestRows=new Map(),tags=new Map(),routes=[];
 let archived=0,earliest=Infinity,latest=-Infinity,snapshot=-Infinity,malformed=0,conflicts=0;
 function observe(key,label,at){
  if(!key)return;
  let t=tags.get(key);
  if(!t){t={key,label,first:at,last:at,current:0};tags.set(key,t);}
  if(Number.isFinite(at)){if(!Number.isFinite(t.first)||at<t.first)t.first=at;if(!Number.isFinite(t.last)||at>=t.last){t.last=at;t.label=label;}}
  return t;
 }
 for(const row of rows){
  if(clean(row.server)!==String(server)||clean(row.coordinate_source)!=='passive_network_world_xy')continue;
  const id=clean(row.player_id);
  if(!id)continue;
  if(!players.has(id))players.set(id,new Map());
  const idHistory=players.get(id);
  const stamp=UTC(row.roster_snapshot_at_utc),rawTag=clean(row.alliance_tag),tag=tagKey(rawTag);
  const prev=latestRows.get(id);
  if(!prev||(Number.isFinite(stamp)&&(!Number.isFinite(prev.stamp)||stamp>prev.stamp))){
   latestRows.set(id,{stamp,tag,label:rawTag,ambiguous:false});
  }else if((stamp===prev.stamp||(!Number.isFinite(stamp)&&!Number.isFinite(prev.stamp)))&&prev.tag!==tag){prev.ambiguous=true;}
  if(Number.isFinite(stamp))snapshot=Math.max(stamp,snapshot);
  let data;
  try{data=JSON.parse(row.player_history_json||'[]');}catch{malformed++;continue;}
  if(!Array.isArray(data)){malformed++;continue;}
  for(const e of data){
   const at=UTC(e?.observed_at);
   if(!Number.isFinite(at))continue;
   // If an observation lacks a known membership field, retain it as a gap,
   // never as evidence of an exit/zero. Blank tags do not imply a destination.
   const label=clean(e?.alliance_tag),key=tagKey(label),old=idHistory.get(at);
   const explicit=Array.isArray(e?.fields)&&e.fields.includes('alliance_tag');
   if(!old)idHistory.set(at,{at,key,label,explicit,ambiguous:false});
   else if(old.key!==key){old.ambiguous=true;}
   else{old.explicit=old.explicit||explicit;}
  }
 }
 if(rows.length&&!players.size)throw Error('Published player rows did not match the selected server');
 for(const [id,byTime] of players){
  let previous=null;
  for(const e of [...byTime.values()].sort((a,b)=>a.at-b.at)){
   if(e.ambiguous){conflicts++;previous=null;continue;}
   archived++;earliest=Math.min(earliest,e.at);latest=Math.max(latest,e.at);
   observe(e.key,e.label,e.at);
   if(previous?.key&&e.key&&previous.key!==e.key&&e.explicit){
    routes.push({playerId:id,from:previous.key,to:e.key,after:previous.at,at:e.at});
   }
   previous=e;
  }
 }
 for(const row of latestRows.values()){
  if(!row.ambiguous&&row.tag&&row.stamp===snapshot){
   // File time is approximate and not a player observation. Do not add it
   // to the archive or use it as a first/last membership timestamp.
   const t=observe(row.tag,row.label,NaN);t.current++;
  }
 }
 const baselineEnd=Number.isFinite(earliest)?(Math.floor(earliest/DAY)+1)*DAY:NaN;
 return {tags,players:players.size,earliest,latest,snapshot,baselineEnd,archived,malformed,conflicts,routes};
}
function movement(model,{days=0,alliance=''}={}){
 const end=Number.isFinite(model.latest)?(Math.floor(model.latest/DAY)+1)*DAY:Infinity;
 const after=days>0?end-days*DAY:-Infinity;
 const selected=tagKey(alliance);
 const matches=model.routes.filter(r=>r.at>=after&&r.at<end&&(!selected||r.from===selected||r.to===selected));
 const pairs=new Map(),origins=new Map(),destinations=new Map(),people=new Set();
 for(const r of matches){
  const routeKey=JSON.stringify([r.from,r.to]);
  if(!pairs.has(routeKey))pairs.set(routeKey,{from:r.from,to:r.to,ids:new Set(),first:r.at,last:r.at});
  const pair=pairs.get(routeKey);pair.ids.add(r.playerId);people.add(r.playerId);
  pair.first=Math.min(pair.first,r.at);pair.last=Math.max(pair.last,r.at);
 }
 function counts(list,key){let n=0;for(const row of list){n+=row.count;key.set(row.tag,(key.get(row.tag)||0)+row.count);}return n;}
 const sorted=[...pairs.values()].map(({ids,...p})=>({...p,count:ids.size})).sort((a,b)=>b.count-a.count||b.last-a.last||a.from.localeCompare(b.from)||a.to.localeCompare(b.to));
 const inbound=selected?sorted.filter(r=>r.to===selected):sorted;
 const outbound=selected?sorted.filter(r=>r.from===selected):sorted;
 const total=counts(inbound.map(r=>({tag:r.from,count:r.count})),origins);
 const totalDest=counts(outbound.map(r=>({tag:r.to,count:r.count})),destinations);
 const share=(m,n,k=1)=>n?[...m.values()].sort((a,b)=>b-a).slice(0,k).reduce((a,b)=>a+b,0)/n:null;
 // A tag can be reused or changed; this compares only directions in
 // observed tagged transitions, not alliances' true population or intent.
 const topIn=share(origins,total),topOut=share(destinations,totalDest);
 const in3=share(origins,total,3),out3=share(destinations,totalDest,3);
 const enough=!selected&&total>=10&&Math.max(origins.size,destinations.size)>=4;
 const diff=(out3??0)-(in3??0);
 const pattern=!enough?'Insufficient evidence for a server-wide pattern':diff>=.15?'Observed movement concentrated into fewer tags':diff<=-.15?'Observed movement spread across more tags':'No clear directional difference in observed records';
 return {after,end,routes:sorted,moves:sorted.reduce((n,p)=>n+p.count,0),people:people.size,origins,destinations,inbound:total,outbound:totalDest,topIn,topOut,in3,out3,pattern};
}
function summarizeTags(m,{days=0,alliance=''}={}){
 const filter=tagKey(alliance),end=Number.isFinite(m.latest)?(Math.floor(m.latest/DAY)+1)*DAY:Infinity,from=days>0?end-days*DAY:-Infinity;
 return [...m.tags.values()].filter(t=>!filter||t.key===filter).map(t=>({...t,
  introduction:!Number.isFinite(t.first)?'Archive timestamp unavailable':t.first<m.baselineEnd?'Seen in archive baseline':t.first>=from?'First observed in selected period':'First observed before selected period',
  status:t.current>0?'Members observed':'Unknown (not observed in published snapshot)'
 })).sort((a,b)=>b.current-a.current||(Number.isFinite(b.first)?b.first:-Infinity)-(Number.isFinite(a.first)?a.first:-Infinity)||a.label.localeCompare(b.label));
}
/* Optional archival roster feed. An explicit count from a complete, verified
 * roster is required. Even complete feeds omitting an alliance are unknown:
 * omission might mean filters, identity churn or upstream export restrictions. */
function verifiedHistory(raw,server){
 const result={events:[],latest:[],usable:0};
 if(raw?.schema_version!==1||!Array.isArray(raw.snapshots))return result;
 const times=new Map(),byID=new Map();
 for(const s of raw.snapshots){
  const at=UTC(s?.observed_at);
  if(String(s?.server)!==String(server)||!Number.isFinite(at)||s?.complete!==true||!Array.isArray(s.alliances)||!clean(s.coverage_reference))continue;
  if(!times.has(at))times.set(at,new Map());
  const scan=times.get(at);
  for(const r of s.alliances){
   const id=clean(r?.id),tag=clean(r?.tag),n=r?.member_count;
   if(!id||!tagKey(tag)||!Number.isSafeInteger(n)||n<0)continue;
   const prev=scan.get(id);
   if(!prev)scan.set(id,{id,tag,n,at,conflict:false});
   else if(prev.tag!==tag||prev.n!==n)prev.conflict=true;
  }
 }
 const ordered=[...times].sort((a,b)=>a[0]-b[0]);let first=true,lastTime=-Infinity;
 for(const [at,scan] of ordered){
  if(![...scan.values()].some(r=>!r.conflict))continue;
  result.usable++;lastTime=at;
  for(const r of scan.values()){
   if(r.conflict)continue;
   const prior=byID.get(r.id),types=[];
   if(prior){
    if(tagKey(prior.tag)!==tagKey(r.tag))types.push({type:'Tag changed',prior});
    if(prior.n>0&&r.n===0)types.push({type:'Zero members verified',prior});
    if(prior.n===0&&r.n>0)types.push({type:'Members observed again',prior});
   }else if(r.n>0)types.push({type:first?'Active at verified baseline':'First observed active by roster',prior:null});
   for(const e of types)result.events.push({...e,...r});
   byID.set(r.id,r);
  }
  first=false;
 }
 result.latest=[...byID.values()].map(r=>({...r,current:r.at===lastTime?r.n:null}));
 result.events.sort((a,b)=>b.at-a.at||a.tag.localeCompare(b.tag));
 return result;
}
return {parseCSV,tagHistory,movement,summarizeTags,verifiedHistory,tagKey,DAY};
});
