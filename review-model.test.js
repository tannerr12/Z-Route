'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const R=require('./review-model.js');
const roster=(id,name,aliases=[])=>({server:'125',coordinate_source:'passive_network_world_xy',player_id:id,username:name,alliance_tag:'D3AD',known_aliases_json:JSON.stringify(aliases)});
const opts={week:'2026-11-16',today:'2026-11-20',excludeToday:true,excludeJoined:false,excludeLeft:false,donGoal:25200,vsGoal:1000000,guild:'D3AD'};
const vs=(username,points,day='MON')=>({week_start:opts.week,day,username,points:String(points),captured_at:'2026-11-19T12:00:00Z'});
const donation=(captured_at,points=12000)=>({week_start:'2026-11-09',username:'Player',points:String(points),captured_at});

test('a past week does not turn a Wednesday donation snapshot into seven days',()=>{
 const m=R.build({don:[donation('2026-11-11T18:00:00Z')]},{...opts,week:'2026-11-09'});
 assert.equal(m.donationDays,3);
 assert.equal(m.effectiveDonGoal,10800);
 assert.equal(m.rows[0].lowDon,false);
});

test('a capture after weekly reset covers all seven days of the selected week',()=>{
 const m=R.build({don:[donation('2026-11-16T00:01:00Z')]},{...opts,week:'2026-11-09'});
 assert.equal(m.donationDays,7);
 assert.equal(m.rows[0].lowDon,true);
});

test('conflicting membership IDs cannot exclude a current member',()=>{
 const changes=[{player:'Player',player_id:'1',player_id_source:'conflicting_identity',event:'removed',game_event_time_utc:'2026-11-17T12:00:00Z'}];
 const m=R.build({roster:[roster('1','Player')],changes,vs:[vs('Peer',2000000)]},{...opts,excludeLeft:true});
 assert.ok(m.rows.some(r=>r.id==='id:1'));
 assert.equal(m.excluded.left,0);
});

test('verified joins and departures still obey their exclusion switches',()=>{
 const changes=[{player:'Player',player_id:'1',event:'joined',game_event_time_utc:'2026-11-17T12:00:00Z'}];
 const input={roster:[roster('1','Player')],changes};
 assert.equal(R.build(input,{...opts,excludeJoined:true}).rows.length,0);
 assert.equal(R.build(input,opts).rows[0].joinedWeek,true);
 changes[0].event='removed';
 assert.equal(R.build(input,{...opts,excludeLeft:true}).rows.length,0);
});

test('zero-fill uses the roster, while missing scans remain unknown',()=>{
 const m=R.build({roster:[roster('1','Player')],vs:[vs('Peer',2000000)]},opts);
 const p=m.rows.find(r=>r.id==='id:1');
 assert.equal(p.vs.get('MON'),0);
 assert.equal(p.vs.has('TUE'),false);
 assert.deepEqual(p.missingEntry,['MON']);
 assert.ok(p.missing.includes('TUE'));
 assert.equal(p.don,null);
});

test('shared aliases stay ambiguous and do not produce false bad standings',()=>{
 const input={roster:[roster('1','One',['Shared']),roster('2','Two',['Shared'])],vs:[vs('Shared',1)]};
 const m=R.build(input,opts);
 assert.ok(m.rows.every(r=>r.identityAmbiguous));
 assert.deepEqual(R.bad(m.rows,'all'),[]);
});

test('exclude today removes current-day scores and current cumulative donations',()=>{
 const input={vs:[vs('Player',2000000,'THU'),vs('Player',1,'FRI')],don:[{...donation('2026-11-20T12:00:00Z'),week_start:opts.week}]};
 const m=R.build(input,opts);
 assert.ok(!m.activeDays.includes('FRI'));
 assert.equal(m.rows[0].vs.has('FRI'),false);
 assert.equal(m.rows[0].don,null);
});

test('bad-standings selection respects visible search and category',()=>{
 const rows=[{name:'Low Don',aliases:[],review:true,lowDon:true,vsIssues:false},{name:'Low VS',aliases:[],review:true,lowDon:false,vsIssues:true}];
 assert.deepEqual(R.bad(R.visible(rows,'all','Don'),'all'),[rows[0]]);
 assert.deepEqual(R.bad(rows,'vs'),[rows[1]]);
});

test('verified pre-day baseline retains priority and its own target coverage',()=>{
 const input={roster:[roster('1','Player')],baselines:[{week_start:opts.week,game_date:'2026-11-19',player_id:'1',pre_day_total:'12000',captured_at:'2026-11-19T12:00:00Z'}],
 don:[{...donation('2026-11-19T12:00:00Z',15000),week_start:opts.week}]};
 const m=R.build(input,opts);
 assert.equal(m.rows[0].don,12000);
 assert.equal(m.donationDays,3);
 assert.equal(m.effectiveDonGoal,10800);
 assert.match(m.donationSource,/pre-day verified/);
});

test('unknown finalized donations remain unknown and override partial raw scores',()=>{
 const input={roster:[roster('1','Player')],dailyDon:[{week_start:opts.week,game_date:'2026-11-19',username:'Player',points:'50'}],
 derivedDon:[{week_start:opts.week,game_date:'2026-11-19',player_id:'1',username:'Player',points:'',source:'UNKNOWN_NO_BASELINE'},
 {week_start:opts.week,game_date:'2026-11-19',username:'Peer',points:'120',source:'VERIFIED'}]};
 const m=R.build(input,opts);
 assert.equal(m.rows.find(r=>r.id==='id:1').don,null);
 assert.deepEqual(m.finalizedDays,['2026-11-19']);
});
