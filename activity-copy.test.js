/* Offline: node --test activity-copy.test.js */
'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {attacks,changes}=require('./activity-copy.js');
test('compact attacks group non-adjacent repeat hits and omit coordinates and timestamp',()=>{
 const rows=[
  {timestamp:'2026.11.10 14:03:44',attacker:'Dinoo993',attacker_guild:'D3AD',attacked:'KarnagejL7',attacked_guild:'XENO',destination_server:'125',destination_x:'515',destination_y:'407',attack_direction:'outgoing'},
  {timestamp:'2026.11.10 15:00:00',attacker:'Raider',attacker_guild:'',attacked:'Defender',attacked_guild:'D3AD',attack_direction:'incoming'},
  {timestamp:'2026.11.10 16:00:00',attacker:'Dinoo993',attacked:'KarnagejL7'},
  {timestamp:'2026.11.10 16:01:00',attacker:'Dinoo993',attacked:'KarnagejL7'}
 ];
 assert.equal(attacks(rows),'Dinoo993->KarnagejL7 x3<br>Raider->Defender');
});
test('same victim hit by different players remains separate',()=>{
 const result=attacks([
  {attacker:'A',attacked:'B'},
  {attacker:'C',attacked:'B'},
  {attacker:'A',attacked:'B'},
  {attacker:'a',attacked:'b'}
 ]);
 assert.equal(result,'A->B x3<br>C->B');
});
test('compact attack copy has no header or unnecessary suffix',()=>{
 assert.equal(attacks([{attacker:'A',attacked:'B'}]),'A->B');
 assert.equal(attacks([]),'');
 assert.equal(changes([]),'');
 assert.equal(attacks(null),'');
});
test('join leave formatting is unchanged with br delimiters',()=>{
 const rows=[
  {timestamp:'2026.08.29 05:16:59',player:'Swtlyn',guild:'',event:'joined'},
  {timestamp:'2026.08.29 23:16:06',player:'rapture',guild:'',event:'removed',actor:'Gandolph'}
 ];
 const result=changes(rows);
 assert.ok(result.includes('Swtlyn — joined'));
 assert.ok(result.includes('rapture — removed (by Gandolph)'));
 assert.ok(!result.includes('[]'));
 assert.equal(result.split('<br>').length,3);
 assert.ok(!result.includes('\n'));
});
test('strips row breaks and tabs to avoid accidental extra messages',()=>{
 const result=attacks([{attacker:'Bad\nName\t',attacked:'Target'}]);
 assert.equal(result,'Bad Name->Target');
 const change=changes([{timestamp:'t',player:'Bad\nName\t',event:'left'}]);
 assert.equal(change.split('<br>').length,2);
 assert.ok(!change.includes('\n'));
 assert.ok(change.includes('Bad Name — left'));
});
