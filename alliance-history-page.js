/* Vanilla DOM view for the static dashboard. */
(function(){
'use strict';
const A=ZRouteAllianceHistory,$=id=>document.getElementById(id);
const fmt=n=>n.toLocaleString(),pct=n=>n===null?'Unknown':Math.round(n*100)+'%';
const date=n=>Number.isFinite(n)?new Date(n).toISOString().slice(0,16).replace('T',' '):'Unknown';
const controls={server:$('allianceServer'),tag:$('allianceTag'),period:$('alliancePeriod'),retry:$('allianceRetry')};
const ids=['Tags','Routes','Verified'];
let limits,entries=[],state=null,request=null,seq=0,failed=null,queryFilters=true;
function resetLimits(){limits=Object.fromEntries(ids.map(k=>[k,60]));}
function fail(message,retry){$('allianceStatus').textContent=message;controls.retry.hidden=false;failed=retry;}
function table(name,data,cols,empty){
 const container=$('alliance'+name),fragment=document.createDocumentFragment();
 for(const row of data.slice(0,limits[name])){
  const tr=document.createElement('tr');
  row.forEach((value,i)=>{
   const td=document.createElement(i===0?'th':'td');
   if(i===0)td.setAttribute('scope','row');
   td.textContent=value;tr.append(td);
  });
  fragment.append(tr);
 }
 if(!data.length){const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=cols;td.className='muted';td.textContent=empty;tr.append(td);fragment.append(tr);}
 container.replaceChildren(fragment);
 const more=$('allianceMore'+name);
 more.hidden=data.length<=limits[name];
 if(!more.hidden)more.textContent='Show more ('+fmt(data.length-limits[name])+' remaining)';
}
function measures(labels){
 const f=document.createDocumentFragment();
 for(const [title,v] of labels){const d=document.createElement('div'),label=document.createElement('small'),value=document.createElement('strong');d.className='tile';label.textContent=title;value.textContent=v;d.append(label,value);f.append(d);}
 $('allianceMeasures').replaceChildren(f);
}
function render(){
 if(!state)return;
 const {model:m,verified:v,verifiedExpected,verifiedUnavailable}=state;
 const opts={days:Number(controls.period.value),alliance:controls.tag.value};
 const match=opts.alliance,tags=A.summarizeTags(m,opts),flows=A.movement(m,opts);
 const label=key=>m.tags.get(key)?.label??key;
 $('alliancePattern').textContent=match
  ?(flows.moves?'Recorded moves involving '+label(match)+'. Concentrated exits may suggest players regrouping; a diverse set of destinations may suggest dispersal.':'No tagged moves involving '+label(match)+' were observed for this period. That does not prove there were none.')
  :flows.pattern+'. This compares the top three origin tags with the top three destination tags.';
 measures(match
  ?[['Inbound player-route pairs',fmt(flows.inbound)],['Largest origin share',pct(flows.topIn)],['Outbound player-route pairs',fmt(flows.outbound)],['Largest destination share',pct(flows.topOut)]]
  :[['Player-route pairs',fmt(flows.moves)],['Distinct players',fmt(flows.people)],['Top 3 origins’ share',pct(flows.in3)],['Top 3 destinations’ share',pct(flows.out3)]]);
 table('Routes',flows.routes.map(r=>[label(r.from),label(r.to),fmt(r.count),date(r.first),date(r.last)]),5,'No known tag-to-tag routes in this period.');
 table('Tags',tags.map(t=>[t.label,date(t.first),date(t.last),t.introduction,t.current>0?fmt(t.current)+' observed members':t.status]),5,'No alliance tags available for this selection.');
 const visible=v.events.filter(e=>e.at>=flows.after&&(!match||A.tagKey(e.tag)===match||A.tagKey(e.prior?.tag)===match));
 $('allianceVerifiedNote').textContent=v.usable
  ?fmt(v.usable)+' verified roster timestamps. A zero is shown only when a complete, trusted roster explicitly reported zero for a stable alliance ID. Events are observations, not precise creation, closure or reactivation times.'
  :verifiedUnavailable?'The configured verified roster feed could not be loaded. Zero-member, reactivation and rename statuses remain unknown.'
  :verifiedExpected?'No usable verified roster records were published for this server. Zero-member, reactivation and rename statuses remain unknown.'
  :'This server’s published map history has tags and player observations, but no verified complete alliance rosters with stable alliance IDs. Zero-member alliances, reactivations and tag changes cannot be confirmed from this data.';
 $('allianceVerifiedTable').hidden=!v.usable;
 table('Verified',v.usable?visible.map(e=>[e.tag,e.type+(e.type==='Tag changed'?' (from '+e.prior.tag+')':''),date(e.prior?.at),date(e.at),fmt(e.n)]):[],5,'No verified roster events for this selection.');
 const notes=[];
 if(m.archived)notes.push(fmt(m.archived)+' dated player observations, '+date(m.earliest)+' to '+date(m.latest)+' UTC');
 else notes.push('No dated player history was published');
 if(Number.isFinite(m.snapshot))notes.push('roster file time ~'+date(m.snapshot)+' UTC');
 if(m.malformed||m.conflicts)notes.push('skipped '+fmt(m.malformed)+' unreadable histories and '+fmt(m.conflicts)+' conflicting observations');
 $('allianceStatus').textContent='Server '+controls.server.value+' · '+notes.join(' · ');
 $('alliancePanels').hidden=false;
}
function currentURL(){
 const params=new URLSearchParams(location.search),s=params.get('server'),a=params.get('alliance'),p=params.get('days');
 return {s,a,p};
}
function setURL(){
 const params=new URL(location.href);
 params.searchParams.set('server',controls.server.value);
 if(controls.tag.value)params.searchParams.set('alliance',controls.tag.value);else params.searchParams.delete('alliance');
 if(controls.period.value!=='0')params.searchParams.set('days',controls.period.value);else params.searchParams.delete('days');
 history.replaceState(null,'',params);
}
async function get(path,signal,kind){
 const res=await fetch(path,{signal,cache:'no-cache'});
 if(!res.ok)throw Error('HTTP '+res.status);
 return kind==='json'?res.json():res.text();
}
async function load(){
 const n=++seq;
 request?.abort();
 request=new AbortController();
 const signal=request.signal;
 const entry=entries.find(e=>e.id===controls.server.value);
 if(!entry)return;
 const preset=queryFilters?currentURL().a:'';
 const verifiedExpected=entry.alliance_history==='data/alliance_history/'+entry.id+'.json';
 $('alliancePanels').hidden=true;state=null;controls.retry.hidden=true;
 controls.tag.replaceChildren(new Option('All alliances',''));controls.tag.disabled=true;
 $('allianceStatus').textContent='Loading alliance observations for server '+entry.id+'…';
 try{
  const [csv,verification]=await Promise.all([
   get('./'+entry.data,signal,'text'),verifiedExpected
    ?get('./'+entry.alliance_history,signal,'json').then(data=>({data,failed:false}),()=>({data:null,failed:true}))
    :Promise.resolve({data:null,failed:false})
  ]);
  if(n!==seq)return;
  const model=A.tagHistory(A.parseCSV(csv),entry.id),verified=A.verifiedHistory(verification.data,entry.id);
  if(!model.players)throw Error('No published player rows available');
  const tags=[...model.tags.values()].map(({key,label})=>({key,label})),known=new Set(tags.map(t=>t.key));
  for(const t of [...verified.latest,...verified.events]){
   const key=A.tagKey(t.tag);
   if(!known.has(key)){known.add(key);tags.push({key,label:t.tag});}
  }
  for(const t of tags.sort((a,b)=>a.label.localeCompare(b.label)))controls.tag.append(new Option(t.label,t.key));
  if(preset&&known.has(A.tagKey(preset)))controls.tag.value=A.tagKey(preset);
  controls.tag.disabled=false;
  state={model,verified,verifiedExpected,verifiedUnavailable:verification.failed};
  queryFilters=false;resetLimits();setURL();render();
 }catch(error){
  if(n!==seq||signal.aborted)return;
  fail('Alliance data unavailable for server '+entry.id+'. A missing export does not imply zero members or no movement.',load);
 }
}
async function init(){
 controls.retry.hidden=true;
 try{
  const manifest=await get('./data/servers.json',undefined,'json');
  if(!Array.isArray(manifest?.servers))throw Error('Server directory unavailable');
  entries=manifest.servers.filter(e=>/^\d+$/.test(String(e?.id))&&e.data==='data/servers/'+String(e.id)+'/world-players.csv').map(e=>({...e,id:String(e.id)}));
  if(!entries.length)throw Error('No server rosters');
  controls.server.replaceChildren(...entries.map(e=>new Option(e.label||'Server '+e.id,e.id)));
  const {s,p}=currentURL();
  controls.server.value=entries.some(e=>e.id===s)?s:entries.some(e=>e.id===String(manifest.default_server))?String(manifest.default_server):entries[0].id;
  if(['0','7','14','30'].includes(p))controls.period.value=p;
  controls.server.disabled=false;
  await load();
 }catch(error){fail('The server directory is unavailable. No history was loaded.',init);}
}
controls.server.addEventListener('change',()=>{queryFilters=false;load();});
for(const c of [controls.tag,controls.period])c.addEventListener('change',()=>{resetLimits();setURL();render();});
controls.retry.addEventListener('click',()=>failed?.());
for(const k of ids)$('allianceMore'+k).addEventListener('click',()=>{limits[k]+=60;render();});
init();
})();
