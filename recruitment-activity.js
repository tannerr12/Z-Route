/* Pure, offline recruitment signals from observed player history. */
(function (root) {
  'use strict';
  const ORDER = ['guild', 'rename', 'move', 'shield', 'power', 'kills'];
  const DAY_MS = 24 * 60 * 60 * 1000;

  function summarize(history, nowMs = Date.now(), days = 7) {
    const latest = Object.create(null);
    const cutoff = nowMs - days * DAY_MS;
    for (const event of Array.isArray(history) ? history : []) {
      if (!event || !Array.isArray(event.fields)) continue;
      // First sightings, including initial shield status, are not activity changes.
      if (event.fields.includes('first_seen')) continue;
      const when = Date.parse(event.observed_at || '');
      if (!Number.isFinite(when) || when < cutoff || when > nowMs) continue;
      const types = [];
      if (event.fields.includes('alliance_tag')) types.push('guild');
      if (event.fields.includes('username')) types.push('rename');
      if (event.fields.includes('x') || event.fields.includes('y')) types.push('move');
      if (event.fields.includes('bubble_status')) types.push('shield');
      // Changes must have been measured against an earlier known value by
      // the scanner. First-seen (unknown -> known) is never a change.
      if (event.fields.includes('power')) types.push('power');
      if (event.fields.includes('kills')) types.push('kills');
      for (const type of types) {
        if (!(type in latest) || when > latest[type]) latest[type] = when;
      }
    }
    const types = ORDER.filter(type => type in latest);
    const lastChangeAt = types.length
      ? new Date(Math.max(...types.map(type => latest[type]))).toISOString()
      : '';
    return { types, lastChangeAt };
  }

  // An activity multi-select matches ANY selected signal.
  // "none" can be selected explicitly to include players with no observed
  // changes, but it is intentionally excluded from the default filters.
  function matchesSelected(types, selected) {
    const detected = Array.isArray(types) ? types : [];
    const chosen = Array.from(selected || []);
    if (!chosen.length) return false;
    return (chosen.includes('none') && detected.length === 0) ||
      detected.some(type => chosen.includes(type));
  }

  const api = { summarize, matchesSelected };
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.ZRouteRecruitment = api;
})(typeof window === 'undefined' ? globalThis : window);
