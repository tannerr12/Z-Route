'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const Z=require('./chopping-block.js');
const NOW=Date.parse('2026-11-20T12:00:00Z');
const model=()=>Z.roster([{server:'125',coordinate_source:'passive_network_world_xy',player_id:'1',username:'Player',alliance_tag:'D3AD'}]);

test('conflicting membership IDs do not create a new-join ranking exemption',()=>{
 const changes=[{player:'Player',player_id:'1',player_id_source:'conflicting_identity',event:'joined',game_event_time_utc:'2026-11-19T12:00:00Z'}];
 const result=Z.extractRange(Z.bounds(7,NOW),model(),[],[],[],[],changes,[]);
 assert.equal(result.rows[0].newJoin,false);
 const weekly=Z.extract('2026-11-16',model(),[],[],[],[],changes);
 assert.equal(weekly.rows[0].newJoin,false);
});

test('3/7/14 day bounds use UTC calendar days across a year boundary',()=>{
 for(const n of [3,7,14]){
  const b=Z.bounds(n,Date.parse('2027-01-02T00:01:00Z'));
  assert.equal((Date.parse(b.end)-Date.parse(b.start))/86400000,n);
  assert.equal(b.end,'2027-01-03');
 }
 assert.throws(()=>Z.bounds(5,NOW));
});

test('kill gains require a baseline and reject decreasing counters',()=>{
 const b=Z.bounds(3,NOW),p={history:[{observed_at:'2026-11-17T12:00:00Z',kills:100}],killsAt:'2026-11-20T11:00:00Z',kills:125};
 assert.equal(Z.killRange(p,b).value,25);
 assert.equal(Z.killRange({...p,history:[]},b).value,null);
 assert.equal(Z.killRange({...p,kills:90},b).value,null);
});

test('unavailable Frenzy does not flag absence, but a captured guild board does',()=>{
 assert.equal(Z.frenzyBoard(null,model()).available,false);
 const s={captured_at_utc:'2026-11-19T12:00:00Z',player_count:1,players:[{id:'2',server:125,guild:'D3AD',points:100}]};
 const r=Z.extractRange(Z.bounds(7,NOW),model(),[],[],[],[],[],[s]).rows[0];
 assert.equal(r.frenzy,0);
 assert.equal(r.frenzyRed,true);
});

test('an unknown finalized donation difference never becomes zero or a partial raw score',()=>{
 const b=Z.bounds(7,NOW),m=model();
 const raw=[{game_date:'2026-11-19',username:'Player',points:'50',captured_at:'2026-11-19T12:00:00Z'}];
 const derived=[{game_date:'2026-11-19',player_id:'1',username:'Player',points:'',source:'UNKNOWN_NO_BASELINE',captured_at:'2026-11-20T10:00:00Z'},
 {game_date:'2026-11-19',username:'Peer',points:'100',source:'VERIFIED',captured_at:'2026-11-20T10:00:00Z'}];
 const r=Z.extractRange(b,m,[],raw,[],[],[],[],derived).rows[0];
 assert.equal(r.donations,null);
});

test('finalized donation IDs disambiguate shared names and replace partial scores',()=>{
 const m=Z.roster([{server:'125',coordinate_source:'passive_network_world_xy',player_id:'1',username:'Player',alliance_tag:'D3AD',known_aliases_json:'["Shared"]'},
 {server:'125',coordinate_source:'passive_network_world_xy',player_id:'2',username:'Other',alliance_tag:'D3AD',known_aliases_json:'["Shared"]'}]);
 const raw=[{game_date:'2026-11-19',username:'Player',points:'50'}];
 const derived=[{game_date:'2026-11-19',player_id:'1',username:'Shared',points:'120',source:'VERIFIED'}];
 const r=Z.extractRange(Z.bounds(7,NOW),m,[],raw,[],[],[],[],derived).rows;
 assert.equal(r[0].donations,120);
 assert.equal(r[0].flagged,false);
 assert.equal(r[1].donations,0);
});
