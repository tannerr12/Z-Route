/* Run: node --test table-sort.test.js */
'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {PLAYER_FIELDS,GUILD_FIELDS,nextSort,sortPlayers,sortGuilds}=require('./table-sort.js');
const players=[
 {id:'b',name:'Player 10',alliance:'B',level:20,power:100,kills:8,
  signal:{types:['move','power'],lastChangeAt:'2026-11-09T06:00:00Z'},x:500,y:200,shield:'unshielded'},
 {id:'a',name:'Player 2',alliance:'A',level:25,power:null,kills:10,
  signal:{types:[],lastChangeAt:''},x:300,y:100,shield:'shielded'},
 {id:'c',name:'Player 1',alliance:'C',level:23,power:200,kills:null,
  signal:{types:['kills'],lastChangeAt:'2026-11-09T07:00:00Z'},x:500,y:100,shield:'unknown'}
];
const ids=items=>items.map(x=>x.id);
test('numeric power sorting is numeric, reversible, and leaves unknown values last',()=>{
 assert.deepEqual(ids(sortPlayers(players,{key:'power',direction:'desc'})),['c','b','a']);
 assert.deepEqual(ids(sortPlayers(players,{key:'power',direction:'asc'})),['b','c','a']);
 assert.deepEqual(ids(sortPlayers(players,{key:'kills',direction:'desc'})),['a','b','c']);
 assert.deepEqual(ids(sortPlayers(players,{key:'level',direction:'asc'})),['b','c','a']);
});
test('name uses natural sort and location breaks ties by y',()=>{
 assert.deepEqual(ids(sortPlayers(players,{key:'player',direction:'asc'})),['c','a','b']);
 assert.deepEqual(ids(sortPlayers(players,{key:'location',direction:'asc'})),['a','c','b']);
});
test('activity count and actual date order control the entire set',()=>{
 assert.deepEqual(ids(sortPlayers(players,{key:'signals',direction:'desc'})),['b','c','a']);
 assert.deepEqual(ids(sortPlayers(players,{key:'lastChange',direction:'desc'})),['c','b','a']);
 assert.deepEqual(ids(sortPlayers(players,{key:'lastChange',direction:'asc'})),['b','c','a']);
});
test('column click toggles direction with sensible first direction',()=>{
 assert.deepEqual(nextSort({key:'lastChange',direction:'desc'},'power',PLAYER_FIELDS),
                  {key:'power',direction:'desc'});
 assert.deepEqual(nextSort({key:'power',direction:'desc'},'power',PLAYER_FIELDS),
                  {key:'power',direction:'asc'});
 assert.deepEqual(nextSort(null,'player',PLAYER_FIELDS),{key:'player',direction:'asc'});
 assert.deepEqual(nextSort(null,'guildPower',GUILD_FIELDS),{key:'guildPower',direction:'desc'});
});
test('guild leaderboard sorts by power, name, rank and measured coverage',()=>{
 const groups=[
  {name:'C',rank:1,totalPower:100n,members:3,knownMembers:3},
  {name:'A',rank:2,totalPower:250n,members:4,knownMembers:2},
  {name:'B',rank:null,totalPower:0n,members:4,knownMembers:0}
 ];
 assert.deepEqual(sortGuilds(groups,{key:'guildPower',direction:'desc'}).map(g=>g.name),['A','C','B']);
 assert.deepEqual(sortGuilds(groups,{key:'guildName',direction:'asc'}).map(g=>g.name),['A','B','C']);
 assert.deepEqual(sortGuilds(groups,{key:'guildCoverage',direction:'desc'}).map(g=>g.name),['C','A','B']);
 assert.deepEqual(sortGuilds(groups,{key:'rank',direction:'desc'}).map(g=>g.name),['A','C','B']);
});
test('sort does not mutate inputs or drop filtered players',()=>{
 const input=players.slice();
 const sorted=sortPlayers(input,{key:'power',direction:'desc'});
 assert.deepEqual(input,players);
 assert.equal(sorted.length,players.length);
 assert.equal(new Set(sorted.map(p=>p.id)).size,players.length);
});
