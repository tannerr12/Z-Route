/* Run offline: node --test recruitment-activity.test.js */
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { summarize } = require('./recruitment-activity.js');

const NOW = Date.parse('2026-11-08T20:00:00Z');
const evt = (daysAgo, fields) => ({
  observed_at: new Date(NOW - daysAgo * 86400000).toISOString(),
  fields
});

test('first sighting and initial shield do not count as activity', () => {
  assert.deepEqual(summarize([evt(1, ['first_seen', 'bubble_status'])], NOW).types, []);
});

test('movement, rename, guild and bubble transitions count within seven days', () => {
  const events = [
    evt(6, ['x', 'y']),
    evt(5, ['username']),
    evt(3, ['alliance_tag']),
    evt(1, ['bubble_status'])
  ];
  assert.deepEqual(summarize(events, NOW).types, ['guild', 'rename', 'move', 'shield']);
  assert.equal(summarize(events, NOW).lastChangeAt, evt(1, []).observed_at);
});

test('events before the window and future events do not count', () => {
  const events = [evt(8, ['username']), evt(-1, ['alliance_tag']), evt(2, ['first_seen'])];
  assert.deepEqual(summarize(events, NOW).types, []);
});

test('observations without changed fields do not prove activity', () => {
  assert.deepEqual(summarize([evt(1, []), evt(0, ['base_level'])], NOW).types, []);
  assert.deepEqual(summarize(undefined, NOW).types, []);
});

test('one coordinate change counts as movement', () => {
  assert.deepEqual(summarize([evt(7, ['y'])], NOW).types, ['move']);
});

test('measured power and kill-count changes qualify as observed activity', () => {
  assert.deepEqual(
    summarize([evt(2,['power']),evt(1,['kills'])],NOW).types,
    ['power','kills']
  );
  assert.deepEqual(
    summarize([evt(1,['first_seen','power','kills'])],NOW).types,
    []
  );
});
