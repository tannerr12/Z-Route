/* Server-wide scan freshness. Timestamp = source roster file mtime, not live player activity. */
(function(root){
'use strict';
const HOUR=3600000;
const DAY=24*HOUR;
function parseTime(value,now=Date.now()){
 if(typeof value!=='string'||!/\d{4}-\d{2}-\d{2}T/.test(value)||!/(Z|[+-]\d{2}:\d{2})$/i.test(value))return null;
 const t=Date.parse(value);
 if(!Number.isFinite(t)||t< Date.UTC(2020,0,1)||t>now+5*60000)return null;
 return t;
}
function ageLabel(age){
 if(age<60000)return 'just now';
 if(age<HOUR)return Math.floor(age/60000)+'m ago';
 if(age<DAY)return Math.floor(age/HOUR)+'h ago';
 return Math.floor(age/DAY)+'d ago';
}
function describe(value,now=Date.now()){
 const time=parseTime(value,now);
 if(time===null)return {known:false,status:'Unknown',age:'unknown',display:'Unknown',time:null};
 const age=Math.max(0,now-time);
 const status=age<DAY?'Recent':age<3*DAY?'Aging':'Stale';
 const display=new Date(time).toLocaleString(undefined,{
  year:'numeric',month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'
 });
 return {known:true,status,age:ageLabel(age),display,time};
}
function render(container,servers,selected,now=Date.now()){
 if(!container)return;
 container.replaceChildren();
 const list=Array.isArray(servers)?servers:[];
 for(const server of list){
  const stamp=describe(server.last_scan_at_utc,now);
  const item=document.createElement('div');
  item.className='scan-entry';
  if(String(server.id)===String(selected))item.classList.add('selected');
  item.dataset.freshness=stamp.status.toLowerCase();
  const name=document.createElement('strong');name.textContent='S'+server.id;
  const caption=document.createElement('span');
  caption.textContent=stamp.known
   ? 'Last scanned ~'+stamp.display+' · '+stamp.age+' · '+stamp.status
   : 'Last scanned: Unknown';
  const full=stamp.known?new Date(stamp.time).toISOString():'Unavailable';
  item.title='Approximate scan snapshot time: '+full+
   '. Derived from the original roster modification time, not from the website publish time or a per-player observation.';
  item.append(name,caption);
  container.append(item);
 }
}
function observedFromRows(rows){
 // Rows of a single-server published roster have the same snapshot time.
 const raw=Array.isArray(rows)&&rows.length?rows[0].roster_snapshot_at_utc:'';
 return parseTime(raw)!==null?raw:null;
}
function reconcile(server,observed){
 // The loaded CSV is the authoritative file for the selected server,
 // so avoid displaying a newer registry time for older CSV content.
 if(server&&parseTime(observed)!==null)server.last_scan_at_utc=observed;
}
const api={parseTime,ageLabel,describe,render,observedFromRows,reconcile};
if(typeof module==='object'&&module.exports)module.exports=api;
else root.ZRouteFreshness=api;
})(typeof window==='undefined'?globalThis:window);
