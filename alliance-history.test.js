'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const A=require('./alliance-history');
const day=d=>'2026-11-'+String(d).padStart(2,'0')+'T12:00:00Z';
const event=(d,t,fields=['alliance_tag'])=>({observed_at:day(d),alliance_tag:t,fields});
const row=(p,tag,hist,stamp=day(27),server='125')=>({server,player_id:p,coordinate_source:'passive_network_world_xy',alliance_tag:tag,roster_snapshot_at_utc:stamp,player_history_json:JSON.stringify(hist)});
const snap=(d,alliances,fields={})=>({server:'125',observed_at:day(d),complete:true,coverage_reference:'test-proof-'+d,alliances,...fields});
const member=(id,tag,n)=>({id,tag,member_count:n});
const roster=snapshots=>({schema_version:1,snapshots});

test('reads BOM, CRLF, quoted JSON with commas and escaped quotes; rejects malformed roster data',()=>{
 const p='server,player_id,coordinate_source,alliance_tag,player_history_json,roster_snapshot_at_utc';
 const rr=A.parseCSV('\uFEFF'+p+'\r\n125,1,passive_network_world_xy,"X,X","[{""alliance_tag"":""X,X""}]",'+day(27)+'\r\n');
 assert.equal(rr[0].alliance_tag,'X,X');assert.deepEqual(JSON.parse(rr[0].player_history_json),[{alliance_tag:'X,X'}]);assert.equal(rr[0].roster_snapshot_at_utc,day(27));
 assert.throws(()=>A.parseCSV(p+'\n125,1'),/Inconsistent/);assert.throws(()=>A.parseCSV(p+'\n125,1,"unterminated'),/Unfinished/);assert.throws(()=>A.parseCSV('a,b\n1,2'),/columns/);
});
test('models live row counts as sightings and never converts absent alliances to zero-member evidence',()=>{
 const h=A.tagHistory([row('1','C',[event(10,'A'),event(12,'C')]),row('2','B',[event(10,'B')],day(12)),row('3','C',[event(10,'D')],day(27),'115')],'125');
 assert.equal(h.players,2);
 const [c]=A.summarizeTags(h,{alliance:'c'}),[a]=A.summarizeTags(h,{alliance:'A'}),[b]=A.summarizeTags(h,{alliance:'B'});
 assert.equal(a.introduction,'Seen in archive baseline');assert.equal(c.introduction,'First observed in selected period');assert.equal(a.current,0);assert.match(a.status,/Unknown/);assert.equal(b.current,0);assert.equal(c.current,1);
 assert.equal(c.last,Date.parse(day(12)),'file snapshot timestamp is not a player observation');
 assert.equal(h.tags.has('d'),false);
 assert.throws(()=>A.tagHistory([row('4','C',[],day(27),'115')],'125'),/selected server/);
});
test('rejects routes through blank and conflicting records and dedupes a repeated same-day observation',()=>{
 const h=A.tagHistory([
  row('1','D',[event(17,'D'),event(11,'A'),event(12,''),event(16,'C',['base_level']),event(12,'')]),
  row('2','C',[event(11,'A'),event(12,'B'),event(12,'X'),event(13,'C')]),
  row('3','C',[event(12,'C',['first_seen']),event(15,'A',['power'])])
 ],'125');
 assert.equal(h.conflicts,1);assert.equal(h.tags.has('x'),false);
 assert.deepEqual(h.routes,[{playerId:'1',from:'c',to:'d',after:Date.parse(day(16)),at:Date.parse(day(17))}]);
});
test('counts each player once per route, case-normalizes tags, and applies archive days and alliance filters',()=>{
 const h=A.tagHistory([
  row('1','B',[event(8,'a'),event(10,'B'),event(16,'A'),event(17,'b')]),
  row('2','B',[event(8,'A'),event(17,'B')]),
  row('3','C',[event(12,'X'),event(17,'C')])
 ],'125');
 assert.equal(A.movement(h,{alliance:'b'}).moves,3);
 let m=A.movement(h,{days:1,alliance:'B'});
 assert.equal(m.moves,2);assert.equal(m.people,2);assert.equal(m.inbound,2);assert.equal(m.outbound,0);assert.equal(m.routes[0].count,2);assert.equal(m.routes[0].first,Date.parse(day(17)));assert.equal(m.routes[0].last,Date.parse(day(17)));
});
test('reports concentration and spreading as an observation pattern, with a minimum sample size',()=>{
 const cluster=reverse=>Array.from({length:12},(_,i)=>row(String(i),'',reverse?[event(1,'A'),event(3,'X'+i%6)]:[event(1,'X'+i%6),event(3,'A')]));
 assert.match(A.movement(A.tagHistory(cluster(false),'125')).pattern,/concentrated/);
 assert.match(A.movement(A.tagHistory(cluster(true),'125')).pattern,/spread/);
 assert.match(A.movement(A.tagHistory(cluster(true).slice(0,5),'125')).pattern,/Insufficient/);
});
test('verifies zero only from an explicit complete evidence row; stable IDs support rename and reappearance',()=>{
 const v=A.verifiedHistory(roster([
  snap(17,[member('01','A',0)]),snap(19,[member('01','B',12)]),
  snap(13,[member('01','A',0)],{complete:false}),
  snap(11,[member('01','A',12),member('02','B',1)]),
  snap(15,[member('02','B',1),member('03','C',1)]),
  snap(16,[member('01','A',0)],{coverage_reference:''}),
  snap(20,[member('03','C',0)],{server:'115'})
 ]),'125');
 assert.equal(v.usable,4);
 const at=t=>v.events.find(e=>e.type===t);
 assert.equal(at('Zero members verified').at,Date.parse(day(17)));
 assert.equal(at('Zero members verified').prior.at,Date.parse(day(11)));
 assert.equal(at('Members observed again').at,Date.parse(day(19)));
 assert.equal(at('Tag changed').prior.tag,'A');
 assert.equal(at('First observed active by roster').tag,'C');
 assert.equal(v.latest.find(r=>r.id==='02').current,null,'omission remains unknown');
 assert.equal(v.latest.find(r=>r.id==='01').current,12);
});
test('a first zero is not a collapse, and conflicting complete records cannot prove zero',()=>{
 const v=A.verifiedHistory(roster([
  snap(11,[member('01','a',0),member('02','b',12)]),
  snap(12,[member('02','b',0),member('03','c',15)]),
  snap(12,[member('02','b',12)])
 ]),'125');
 assert.equal(v.events.some(e=>e.type==='Zero members verified'),false);
 assert.equal(v.latest.find(r=>r.id==='02').current,null);
 assert.deepEqual(A.verifiedHistory(null,'125'),{events:[],latest:[],usable:0});
});
