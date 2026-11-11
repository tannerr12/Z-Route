/* Offline: node --test activity-copy.test.js */
'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {attacks,changes}=require('./activity-copy.js');
test('attacks copy ordered matches and location details',()=>{
 const rows=[
  {timestamp:'2026.11.10 14:03:44',attacker:'Dinoo993',attacker_guild:'D3AD',attacked:'KarnagejL7',attacked_guild:'XENO',destination_server:'125',destination_x:'515',destination_y:'407',attack_direction:'outgoing'},
  {timestamp:'2026.11.10 15:00:00',attacker:'Raider',attacker_guild:'',attacked:'Defender',attacked_guild:'D3AD',attack_direction:'incoming'}
 ];
 const result=attacks(rows);
 assert.ok(result.startsWith('Attacks — 2 filtered records'));
 assert.ok(result.includes('[D3AD] Dinoo993 → [XENO] KarnagejL7 [S:125 X:515 Y:407] | Our attack'));
 assert.ok(result.includes('Raider → [D3AD] Defender | Attack on D3AD'));
 assert.ok(result.indexOf('Dinoo993')<result.indexOf('Raider'));
});
test('changes copy join, left, and removal actor without invented guild',()=>{
 const rows=[
  {timestamp:'2026.08.29 05:16:59',player:'Swtlyn',guild:'',event:'joined'},
  {timestamp:'2026.08.29 23:16:06',player:'rapture',guild:'',event:'removed',actor:'Gandolph'}
 ];
 const result=changes(rows);
 assert.ok(result.includes('Swtlyn — joined'));
 assert.ok(result.includes('rapture — removed (by Gandolph)'));
 assert.ok(!result.includes('[]'));
});
test('formats optional guild and suppresses invalid coordinate fragments',()=>{
 const result=attacks([{timestamp:'now',attacker:'A',attacker_guild:'[ABC]',attacked:'B',attacked_guild:'Unknown',destination_server:'125',destination_x:'',destination_y:'5'}]);
 assert.ok(result.includes('[ABC] A → B'));
 assert.ok(!result.includes('[S:125'));
 assert.equal(attacks([]),'');
 assert.equal(changes([]),'');
});
test('strips row breaks and tabs to avoid accidental extra messages',()=>{
 const result=changes([{timestamp:'t',player:'Bad\nName\t',event:'left'}]);
 assert.equal(result.split('\n').length,2);
 assert.ok(result.includes('Bad Name — left'));
});
