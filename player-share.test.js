/* Offline: node --test player-share.test.js */
'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {format}=require('./player-share.js');

test('copies a tagged player in game share format',()=>{
 assert.equal(format({guild:'D3AD',name:'GolferGirl124',server:'125',x:510,y:443}),
  '[D3AD] GolferGirl124 [S:125 X:510 Y:443]');
 assert.equal(format({guild:'[TU88]',name:'Commander2ucnNsF',server:'125',x:945,y:495}),
  '[TU88] Commander2ucnNsF [S:125 X:945 Y:495]');
});
test('players without an alliance do not get a placeholder guild tag',()=>{
 for(const guild of ['',null,'Unknown','None','No Guild','N/A']){
  assert.equal(format({guild,name:'Sean4021',server:'125',x:182,y:931}),
   'Sean4021 [S:125 X:182 Y:931]');
 }
});
test('preserves server and coordinates across servers',()=>{
 assert.equal(format({guild:'acd',name:'Commander2qiX1Nj',server:115,x:651,y:300}),
  '[acd] Commander2qiX1Nj [S:115 X:651 Y:300]');
});
test('rejects missing or malformed locations',()=>{
 assert.equal(format({guild:'D3AD',name:'Test',server:'125',x:null,y:20}), '');
 assert.equal(format({guild:'D3AD',name:'Test',server:'?',x:2,y:20}), '');
 assert.equal(format({guild:'D3AD',name:'',server:125,x:2,y:20}), '');
});
