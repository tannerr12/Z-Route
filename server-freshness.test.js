/* Offline checks: node --test server-freshness.test.js */
'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {describe,parseTime,observedFromRows,reconcile}=require('./server-freshness.js');
const NOW=Date.parse('2026-11-09T08:00:00Z');
test('status changes at 24/72 hour boundaries',()=>{
 assert.equal(describe('2026-11-08T08:00:01Z',NOW).status,'Recent');
 assert.equal(describe('2026-11-08T08:00:00Z',NOW).status,'Aging');
 assert.equal(describe('2026-11-06T08:00:00Z',NOW).status,'Stale');
});
test('missing, ambiguous, and future timestamps are unknown',()=>{
 assert.equal(describe('',NOW).known,false);
 assert.equal(describe('2026-11-08T08:00:00',NOW).known,false);
 assert.equal(describe('2026-11-11T08:00:00Z',NOW).known,false);
 assert.equal(parseTime('abc',NOW),null);
});
test('per-server snapshots remain isolated and CSV overrides stale metadata',()=>{
 const servers=[{id:'115',last_scan_at_utc:'2026-11-08T17:11:12Z'},
                {id:'125',last_scan_at_utc:'2026-11-09T04:50:24Z'}];
 const observed=observedFromRows([{roster_snapshot_at_utc:'2026-11-09T05:00:00Z'}],NOW);
 reconcile(servers[1],observed,NOW);
 assert.equal(servers[0].last_scan_at_utc,'2026-11-08T17:11:12Z');
 assert.equal(servers[1].last_scan_at_utc,'2026-11-09T05:00:00Z');
});
