'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const history=require('./vs-membership.js');
const rows=[
 {source:'union_oplog_network',player:'Dinoo993',event:'joined',
  game_event_time_utc:'2026-11-02T03:16:49.291+00:00'},
 {source:'union_oplog_network',player:'Dinoo993',event:'removed',
  game_event_time_utc:'2026-11-10T14:11:52.274+00:00'},
 {source:'ocr_unverified',player:'Phantom',event:'joined',
  game_event_time_utc:'2026-11-01T12:00:00+00:00'}
];
test('member history brackets a midweek removal, without retroactive exclusion',()=>{
 const lookup=history.parse(rows);
 assert.equal(history.status(lookup,'Dinoo993','2026-11-02').kind,'changed');
 assert.equal(history.status(lookup,'Dinoo993','2026-11-09').kind,'changed');
 assert.equal(history.status(lookup,'Dinoo993','2026-11-16').kind,'former');
 assert.equal(history.status(lookup,'Dinoo993','2026-10-26').kind,'unknown');
});
test('name-only joins never fabricate verified status from OCR',()=>{
 const lookup=history.parse(rows);
 assert.equal(history.status(lookup,'Phantom','2026-11-09').kind,'unknown');
 assert.equal(history.status(lookup,'DINOo993','2026-11-16').kind,'former');
});
