/* Offline: node --test guild-power.test.js */
'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {rank,excludedTop,guildKey,knownPower}=require('./guild-power.js');
const sample=[
 {server:'125',id:'1',guild:'Alpha',power:200},
 {server:'125',id:'2',guild:'Alpha',power:''},
 {server:'125',id:'3',guild:'Beta',power:500},
 {server:'125',id:'4',guild:'Alpha',power:300},
 {server:'125',id:'5',guild:'NoData',power:null},
 {server:'125',id:'6',guild:'Unknown',power:9000},
 {server:'125',id:'7',guild:'',power:9000},
 {server:'115',id:'8',guild:'Beta',power:99999}
];
test('power rankings sum once per player and use deterministic tie-breaking',()=>{
 const result=rank(sample,'125');
 assert.equal(result.ranked.length,2);
 assert.deepEqual(result.ranked.map(g=>g.name),['Alpha','Beta']);
 assert.equal(result.ranked[0].totalPower,500n);
 assert.equal(result.ranked[0].members,3);
 assert.equal(result.ranked[0].knownMembers,2);
 assert.equal(result.ranked[0].missingMembers,1);
 assert.equal(result.unranked[0].name,'NoData');
 assert.equal(result.observedPlayers,7);
});
test('last duplicate player ID replaces earlier observation',()=>{
 const r=rank([{server:'125',id:'1',alliance:'A',power:30},
              {server:'125',id:'1',alliance:'B',power:70},
              {server:'125',id:'2',alliance:'B',power:20}],'125');
 assert.equal(r.ranked.length,1);
 assert.equal(r.ranked[0].totalPower,90n);
 assert.equal(r.ranked[0].members,2);
});
test('top-X excludes by guild membership, independent of other filters',()=>{
 const ranking=rank(sample,'125');
 assert.deepEqual([...excludedTop(ranking,1)],['alpha']);
 assert.deepEqual([...excludedTop(ranking,2)].sort(),['alpha','beta']);
 assert.deepEqual([...excludedTop(ranking,0)],[]);
 assert.deepEqual([...excludedTop(ranking,-5)],[]);
 assert.equal(excludedTop(ranking,100).has('nodata'),false);
 assert.equal(excludedTop(ranking,100).has(''),false);
});
test('guild casing combines and exact totals do not lose precision',()=>{
 const r=rank([{server:'125',id:'1',alliance:'D3AD',power:5000000000000000},
               {server:'125',id:'2',alliance:'d3ad',power:5000000000000000}],'125');
 assert.equal(r.ranked.length,1);
 assert.equal(r.ranked[0].totalPower,10000000000000000n);
 assert.equal(guildKey(' d3Ad '),'d3ad');
 assert.equal(knownPower(''),null);
 assert.equal(knownPower('not known'),null);
});
test('no power data yields no rank and no exclusions',()=>{
 const ranking=rank([{server:'115',id:'1',alliance:'A',power:''}],'115');
 assert.equal(ranking.ranked.length,0);
 assert.equal(ranking.unranked.length,1);
 assert.equal(excludedTop(ranking,10).size,0);
});
