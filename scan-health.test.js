'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const H=require('./scan-health.js');
const NOW=Date.parse('2026-11-20T12:00:00Z');
const player=(id,power='',kills='',stamp='2026-11-19T12:00:00Z')=>({server:'125',player_id:id,coordinate_source:'passive_network_world_xy',power,kills,roster_snapshot_at_utc:stamp,alliance_tag:'D3AD'});
test('field coverage counts zero as measured and blank/unsafe values as missing',()=>{
 const s=H.serverSummary({id:'125'},[player('1','0','0'),player('2','',null),player('3','-1','9007199254740992')],NOW);
 assert.equal(s.count,3);assert.equal(s.power,1);assert.equal(s.kills,1);assert.equal(s.status,'Aging');
});
test('server summaries isolate network records and deduplicate by newest capture',()=>{
 const rows=[player('1',100,10),player('1',200,20,'2026-11-20T01:00:00Z'),{...player('2',99,9),server:'115'},{...player('3',99,9),coordinate_source:'OCR'}];
 const s=H.serverSummary({id:'125'},rows,NOW);
 assert.equal(s.count,1);assert.equal(s.captured,Date.parse('2026-11-20T01:00:00Z'));
});
test('CSV timestamp is authoritative; registry freshness cannot mask empty or failed data',()=>{
 const e={id:'125',last_scan_at_utc:'2026-11-20T12:00:00Z'};
 assert.equal(H.serverSummary(e,[player('1',1,1,'2026-11-01T12:00:00Z')],NOW).status,'Stale');
 assert.equal(H.serverSummary(e,[],NOW).status,'Unknown');
 assert.equal(H.serverSummary(e,[],NOW,false).status,'Unavailable');
 assert.equal(H.timestamp('2026-11-21T00:00:00Z',NOW),null);
 assert.equal(H.timestamp('2026-11-19T12:00:00',NOW),null);
});
test('completed-day coverage respects 02:00 UTC game reset and Sunday VS schedule',()=>{
 const days=H.dailyCoverage([],[],[],{now:Date.parse('2026-11-20T01:00:00Z'),length:7});
 assert.equal(days.at(-1).date,'2026-11-18');assert.equal(days.length,7);
 assert.equal(days.find(d=>d.date==='2026-11-15').vs.state,'Not scheduled');
 assert.equal(days.at(-1).donations.state,'Missing');
});
test('finalized differences replace raw rows while explicit unknowns remain visible',()=>{
 const r={week_start:'2026-11-16',game_date:'2026-11-19',username:'Player',points:'100'};
 const d=H.dailyCoverage([], [r],[{...r,points:'',source:'UNKNOWN_NO_BASELINE'}],{now:NOW,length:7}).at(-1);
 assert.equal(d.donations.state,'Finalized / unknown rows');assert.equal(d.donations.unknown,1);assert.equal(d.donations.scored,0);
});
test('weekly VS totals cannot disguise missing daily captures',()=>{
 const rows=[{week_start:'2026-11-16',day:'WEEKLY',username:'Player',points:'10000'}];
 assert.equal(H.dailyCoverage(rows,[],[],{now:NOW,length:7}).at(-1).vs.state,'Missing');
});
test('invalid VS dates are ignored without crashing diagnostics',()=>{
 const rows=[{week_start:'2026-99-99',day:'MON',username:'Player',points:'10'}];
 assert.equal(H.dailyCoverage(rows,[],[],{now:NOW,length:7}).length,7);
});
test('log capture freshness and latest event time are separate; IDs deduplicate',()=>{
 const r={event_id:'a',scanned_at:'2026-11-19T12:00:00Z',game_event_time_utc:'2026-11-01T12:00:00Z'};
 const s=H.activitySummary([r,r,{...r,event_id:''}],NOW);
 assert.equal(s.events,1);assert.equal(s.unkeyed,1);assert.ok(s.captured>s.latestEvent);
});
test('warnings disclose missing feeds, stale maps and partial donation days',()=>{
 const days=H.dailyCoverage([],[],[],{now:NOW,length:7});
 const w=H.warnings([{server:'115',status:'Stale'}],days,{War:{available:false}}).join(' ');
 assert.match(w,/Server 115/);assert.match(w,/VS days/);assert.match(w,/donation days/);assert.match(w,/War feed/);
});
test('activity warning uses scan capture time rather than old event dates',()=>{
 const fresh=H.activitySummary([{scanned_at:'2026-11-20T10:00:00Z',game_event_time_utc:'2026-11-01T00:00:00Z'}],NOW);
 assert.deepEqual(H.warnings([],[],{}, {War:fresh},NOW),[]);
 const old={...fresh,captured:Date.parse('2026-11-10T00:00:00Z')};
 assert.match(H.warnings([],[],{},{War:old},NOW).join(' '),/three days old/);
});
