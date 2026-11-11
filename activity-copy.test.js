/* Offline: node --test activity-copy.test.js */
'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {attacks,changes}=require('./activity-copy.js');

test('attacks: newest day first, repeated hits grouped within day, times omitted',()=>{
 const rows=[
  {timestamp:'2026.11.09 12:30:00',attacker:'A',attacked:'B',attack_direction:'outgoing'},
  {timestamp:'2026.11.10 10:30:00',attacker:'A',attacked:'B',attack_direction:'outgoing',destination_x:'123'},
  {timestamp:'2026.11.10 12:30:00',attacker:'C',attacked:'D',attack_direction:'incoming'},
  {timestamp:'2026.11.10 10:35:00',attacker:'A',attacked:'B',attack_direction:'outgoing'},
  {timestamp:'2026.11.10 11:00:00',attacker:'A',attacked:'B',attack_direction:'outgoing'},
 ];
 assert.equal(attacks(rows),
  '2026-11-10<br>IN C->D<br>OUT A->B x3<br>2026-11-09<br>OUT A->B');
});

test('same pair in different attack directions does not merge',()=>{
 assert.equal(attacks([
  {timestamp:'2026-11-10 01:00:00',attacker:'A',attacked:'B',attack_direction:'outgoing'},
  {timestamp:'2026-11-10 02:00:00',attacker:'A',attacked:'B',attack_direction:'incoming'},
  {timestamp:'2026-11-10 03:00:00',attacker:'a',attacked:'b',attack_direction:'outgoing'},
  {timestamp:'2026-11-10 04:00:00',attacker:'C',attacked:'D',attack_direction:'unknown'},
 ]),'2026-11-10<br>UNK C->D<br>OUT a->b x2<br>IN A->B');
});

test('attack copy omits times, coordinates and unnecessary headers',()=>{
 const result=attacks([{timestamp:'2026.11.10 14:03:44',attacker:'Dinoo993',
  attacker_guild:'D3AD',attacked:'KarnagejL7',attacked_guild:'XENO',
  destination_server:'125',destination_x:'515',destination_y:'407',
  attack_direction:'outgoing'}]);
 assert.equal(result,'2026-11-10<br>OUT [D3AD] Dinoo993->[XENO] KarnagejL7');
 assert.ok(!result.includes('14:03:44'));
 assert.ok(!result.includes('515'));
 assert.ok(!result.includes('\n'));
 assert.equal(attacks([]),'');
 assert.equal(attacks(null),'');
});

test('join/leave grouped by day, no individual time, no loss of removal actor',()=>{
 const result=changes([
  {timestamp:'2026.08.29 05:16:59',player:'Swtlyn',guild:'',event:'joined'},
  {timestamp:'2026.08.30 09:00:00',player:'Aaron',guild:'D3AD',event:'left'},
  {timestamp:'2026.08.29 23:16:06',player:'rapture',guild:'',event:'removed',actor:'Gandolph'}
 ]);
 assert.equal(result,'2026-08-30<br>[D3AD] Aaron — left<br>2026-08-29<br>rapture — removed (by Gandolph)<br>Swtlyn — joined');
 assert.equal(changes([]),'');
});

test('unknown dates, sanitized whitespace, explicit <br> separators',()=>{
 assert.equal(attacks([{attacker:'Bad\nName\t',attacked:'Target',attack_direction:''}]),
  'Unknown date<br>UNK Bad Name->Target');
 const result=changes([{timestamp:'t',player:'Bad\nName\t',event:'left'}]);
 assert.equal(result,'Unknown date<br>Bad Name — left');
});

test('known guilds appear for both sides and distinct guilds are not merged',()=>{
 const result=attacks([
  {timestamp:'2026-11-10 17:00:00',attacker:'Dinoo993',attacker_guild:'D3AD',attacked:'KarnagejL7',attacked_guild:'XENO',attack_direction:'outgoing'},
  {timestamp:'2026-11-10 16:00:00',attacker:'Dinoo993',attacker_guild:'[D3AD]',attacked:'KarnagejL7',attacked_guild:'[XENO]',attack_direction:'outgoing'},
  {timestamp:'2026-11-10 15:00:00',attacker:'Dinoo993',attacker_guild:'D3AD',attacked:'KarnagejL7',attacked_guild:'wAz',attack_direction:'outgoing'},
  {timestamp:'2026-11-10 14:00:00',attacker:'Raider',attacker_guild:'Unknown',attacked:'Defender',attacked_guild:'D3AD',attack_direction:'incoming'}
 ]);
 assert.equal(result,'2026-11-10<br>OUT [D3AD] Dinoo993->[XENO] KarnagejL7 x2<br>OUT [D3AD] Dinoo993->[wAz] KarnagejL7<br>IN Raider->[D3AD] Defender');
});
