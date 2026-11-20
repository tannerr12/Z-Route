'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
require('./recruitment-removals.js');
const R=globalThis.ZRouteRecruitmentRemovals;
const players=[{id:'1',name:'Player',aliases:['Old Name']},{id:'2',name:'Peer'}];

test('conflicting removal IDs cannot exclude either ID or a name fallback',()=>{
 const rows=[{event:'removed',player:'Player',player_id:'1',player_id_source:'conflicting_identity'}];
 const identity=R.removedIdentity(rows,players);
 assert.equal(R.wasRemoved(players[0],identity),false);
 assert.equal(R.wasRemoved({name:'Player'},identity),false);
 assert.equal(R.filterCandidates(players,identity,true,'125').length,2);
});

test('confirmed removals and unique aliases still exclude only on server 125',()=>{
 const identity=R.removedIdentity([{event:'removed',player:'Old Name'},{event:'left',player:'Peer',player_id:'2'}],players);
 assert.deepEqual(R.filterCandidates(players,identity,true,'125'),[players[1]]);
 assert.deepEqual(R.filterCandidates(players,identity,true,'115'),players);
 assert.deepEqual(R.filterCandidates(players,identity,false,'125'),players);
});

test('shared aliases never automatically exclude players',()=>{
 const same=[{id:'1',name:'One',aliases:['Shared']},{id:'2',name:'Two',aliases:['Shared']}];
 const identity=R.removedIdentity([{event:'removed',player:'Shared'}],same);
 assert.equal(identity.ambiguous.size,1);
 assert.deepEqual(R.filterCandidates(same,identity,true,'125'),same);
});
