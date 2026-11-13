/* Offline: node --test activity-filters.test.js */
'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {isGeneratedCommander}=require('./activity-filters.js');

test('only Commander plus exactly seven alphanumeric characters is excluded',()=>{
 for(const name of ['Commander1234567','CommanderA1b2C3d',
                    'COMMANDERabcdefg','commander0000000']){
  assert.equal(isGeneratedCommander(name),true,name);
 }
 for(const name of ['Commander2test','Commander123456','Commander12345678',
                    'Commander','Commander2PlayerX','Commander-123456',
                    'Commander John','MyCommander1234567','Commander_123456']){
  assert.equal(isGeneratedCommander(name),false,name);
 }
 assert.equal(isGeneratedCommander(null),false);
});
