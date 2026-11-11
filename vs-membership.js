/* Browser/Node historical D3AD membership annotation for VS analytics.
 * Name-only correlation: an activity name is NOT a stable account-ID link.
 * Never alter or reattribute scores based only on these labels.
 */
(function(root,factory){
  'use strict';
  const api=factory();
  if(typeof module==='object'&&module.exports) module.exports=api;
  if(root)root.ZRouteMembership=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  function parse(rows){
    const map=new Map();
    for(const row of Array.isArray(rows)?rows:[]){
      if(row.source!=='union_oplog_network')continue;
      const name=String(row.player||'').trim();
      const event=String(row.event||'').trim().toLowerCase();
      if(!name||!['joined','left','removed'].includes(event))continue;
      const stamp=Date.parse(row.game_event_time_utc||'');
      if(!Number.isFinite(stamp)||!/[zZ]|[+-]\d\d:\d\d$/.test(row.game_event_time_utc||''))continue;
      const key=name.toLocaleLowerCase();
      if(!map.has(key))map.set(key,[]);
      const records=map.get(key);
      if(!records.some(r=>r.at===stamp&&r.event===event)){
        records.push({at:stamp,event});
      }
    }
    for(const records of map.values())records.sort((a,b)=>a.at-b.at);
    return map;
  }
  function status(history,name,week){
    const first=Date.parse(String(week)+'T00:00:00Z');
    if(!Number.isFinite(first))return {label:'Unknown',kind:'unknown'};
    const end=first+7*86400000;
    const records=history instanceof Map ?history.get(String(name||'').trim().toLocaleLowerCase())||[]:[];
    const inside=records.filter(r=>r.at>=first&&r.at<end);
    if(inside.length)return {label:'Changed during week',kind:'changed'};
    const prior=records.filter(r=>r.at<first).at(-1);
    if(!prior)return {label:'No verified history',kind:'unknown'};
    return prior.event==='joined'
      ?{label:'Member (name match)',kind:'member'}
      :{label:'Former (name match)',kind:'former'};
  }
  return {parse,status};
});
