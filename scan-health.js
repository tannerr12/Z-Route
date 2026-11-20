/* Published-data diagnostics. Missing captures never imply zero activity. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.ZRouteScanHealth=api;})(globalThis,function(){
'use strict';
const DAY=86400000,OFFSET=7200000;
const gameDay=now=>new Date(Number(now)-OFFSET).toISOString().slice(0,10);
const add=(d,n)=>new Date(Date.parse(d+'T00:00:00Z')+n*DAY).toISOString().slice(0,10);
function timestamp(raw,now=Date.now()){
 if(typeof raw!=='string'||!/(Z|[+-]\d{2}:\d{2})$/i.test(raw))return null;
 const n=Date.parse(raw);return Number.isFinite(n)&&n>=Date.UTC(2020,0,1)&&n<=now+300000?n:null;
}
function latest(rows,field,now){return rows.reduce((last,r)=>{const n=timestamp(r[field],now);return n===null?last:last===null?n:Math.max(last,n);},null);}
function measured(v){return v!=null&&String(v).trim()!==''&&Number.isSafeInteger(Number(v))&&Number(v)>=0;}
function serverSummary(entry,rows,now=Date.now(),available=true){
 const players=new Map();
 for(const r of rows||[]){
  if(String(r.server)!==String(entry.id)||r.coordinate_source!=='passive_network_world_xy'||!r.player_id)continue;
  const prior=players.get(String(r.player_id));
  if(!prior||(timestamp(r.roster_snapshot_at_utc,now)??-Infinity)>=(timestamp(prior.roster_snapshot_at_utc,now)??-Infinity))players.set(String(r.player_id),r);
 }
 const valid=[...players.values()],captured=latest(valid,'roster_snapshot_at_utc',now);
 const age=captured===null?null:Math.max(0,now-captured);
 return {server:String(entry.id),available,count:valid.length,captured,
  status:!available?'Unavailable':captured===null?'Unknown':age<DAY?'Recent':age<3*DAY?'Aging':'Stale',
  power:valid.filter(r=>measured(r.power)).length,kills:valid.filter(r=>measured(r.kills)).length,
  history:valid.filter(r=>{try{const a=JSON.parse(r.player_history_json||'[]');return Array.isArray(a)&&a.length>0;}catch{return false;}}).length,
  guildMembers:valid.filter(r=>String(r.alliance_tag||'').trim().toLowerCase()==='d3ad').length};
}
function weekStart(d){const index=(new Date(d+'T00:00:00Z').getUTCDay()+6)%7;return add(d,-index);}
function vsDate(r){const n=['MON','TUE','WED','THU','FRI','SAT'].indexOf(String(r.day).toUpperCase()),start=Date.parse(r.week_start+'T00:00:00Z');return n>=0&&/^\d{4}-\d{2}-\d{2}$/.test(r.week_start)&&Number.isFinite(start)&&new Date(start).toISOString().slice(0,10)===r.week_start?add(r.week_start,n):'';}
function dailyCoverage(vs,raw,derived,opts={}){
 const now=opts.now??Date.now(),length=Number(opts.length??14);
 if(![7,14].includes(length))throw Error('Choose 7 or 14 days');
 const finish=add(gameDay(now),opts.excludeToday===false?0:-1);
 function summary(rows,isDerived=false){
  const valid=rows.filter(r=>r.username&&measured(r.points));
  const unknown=rows.filter(r=>String(r.source||'').startsWith('UNKNOWN_'));
  return {rows:rows.length,scored:valid.length,unknown:unknown.length,captured:latest(rows,'captured_at',now),
   state:!rows.length?'Missing':isDerived?(unknown.length?'Finalized / unknown rows':valid.length?'Finalized':'Unusable'):valid.length?'Raw snapshot':'Unusable'};
 }
 return Array.from({length},(_,i)=>{
  const date=add(finish,i-length+1),week=weekStart(date);
  const v=vs.filter(r=>vsDate(r)===date);
  const d=derived.filter(r=>r.game_date===date&&r.week_start===week);
  const r=raw.filter(r=>r.game_date===date&&r.week_start===week);
  const out={date,vs:summary(v),donations:summary(d.length?d:r,d.length>0)};
  if(new Date(date+'T00:00:00Z').getUTCDay()===0)out.vs.state='Not scheduled';
  else if(out.vs.scored)out.vs.state='Captured';
  return out;
 });
}
function activitySummary(rows,now=Date.now(),available=true){
 const ids=new Set();let unkeyed=0;
 for(const r of rows||[])if(r.event_id)ids.add(r.event_id);else unkeyed++;
 return {available,events:ids.size,unkeyed,captured:latest(rows||[],'scanned_at',now),latestEvent:latest(rows||[],'game_event_time_utc',now)};
}
function warnings(servers,days,feeds,activity={},now=Date.now()){
 const out=[];
 for(const s of servers)if(['Stale','Unknown','Unavailable'].includes(s.status))out.push('Server '+s.server+': '+s.status.toLowerCase()+' map capture.');
 const missingVS=days.filter(d=>d.vs.state==='Missing').length;
 const missingDon=days.filter(d=>d.donations.state==='Missing').length;
 const raw=days.filter(d=>d.donations.state==='Raw snapshot').length;
 const unknown=days.reduce((n,d)=>n+d.donations.unknown,0);
 if(missingVS)out.push(missingVS+' scheduled VS days have no captured list.');
 if(missingDon)out.push(missingDon+' donation days have no captured list.');
 if(raw)out.push(raw+' donation days use raw snapshots and may be partial.');
 if(unknown)out.push(unknown+' finalized donation rows have unknown differences.');
 for(const [name,feed] of Object.entries(feeds||{}))if(!feed.available)out.push(name+' feed could not be loaded.');
 for(const [name,a] of Object.entries(activity))if(a.available){
  if(a.captured===null)out.push(name+' log capture time is unknown.');
  else if(now-a.captured>=3*DAY)out.push(name+' log capture is over three days old.');
 }
 return out;
}
return {gameDay,add,timestamp,measured,serverSummary,dailyCoverage,activitySummary,warnings};
});
