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

test('3/7/14 day bounds use game UTC-2 calendar days across a year boundary',()=>{
 for(const n of [3,7,14]){
  const b=Z.bounds(n,Date.parse('2027-01-02T02:01:00Z'));
  assert.equal((Date.parse(b.end)-Date.parse(b.start))/86400000,n);
  assert.equal(b.end,'2027-01-03');
 }
 assert.throws(()=>Z.bounds(5,NOW));
});

test('rolling game days reset at 02:00 UTC and kill baselines use that boundary',()=>{
 assert.equal(Z.bounds(3,Date.parse('2026-11-20T01:59:59Z')).today,'2026-11-19');
 const b=Z.bounds(3,Date.parse('2026-11-20T03:00:00Z'));
 assert.equal(b.today,'2026-11-20');
 assert.equal(b.startUtcMs,Date.parse('2026-11-18T02:00:00Z'));
 const p={history:[{observed_at:'2026-11-18T01:59:00Z',kills:10}],killsAt:'2026-11-18T02:30:00Z',kills:20};
 assert.equal(Z.killRange(p,b).value,10);
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

 test('optional power and activity weights preserve missing inputs',()=>{const Z=require('./chopping-block');const rows=[{id:'1',name:'A',vs:1,donations:1,kills:0,frenzy:0,power:100,activity:2},{id:'2',name:'B',vs:1,donations:1,kills:0,frenzy:0,power:null,activity:1}];const r=Z.rank(rows,{vs:0,donations:0,frenzy:0,kills:0,power:10,activity:15});assert.equal(r.rows.find(x=>x.id==='2').provisional,true);assert.ok(!r.rows.find(x=>x.id==='1').provisional);});
