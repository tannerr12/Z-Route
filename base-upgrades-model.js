/* Pure model for the Z-Route Base Upgrades page. */
(function (root, factory) {
  "use strict";
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ZRouteBaseUpgrades = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  const required = ["server", "player_id", "username", "alliance_tag", "player_history_json"];
  const clean = value => typeof value === "string" ? value.trim() : "";
  const compare = (a, b) => a < b ? -1 : a > b ? 1 : 0;
  const allianceKey = tag => clean(tag).toLowerCase();
  const levelOf = value => {
    const n = typeof value === "number" ? value : /^\d+$/.test(clean(value)) ? Number(value) : NaN;
    return Number.isSafeInteger(n) && n > 0 ? n : null;
  };
  function timeOf(raw) {
    if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/i.test(clean(raw))) return null;
    const time = Date.parse(raw.trim());
    return Number.isFinite(time) ? time : null;
  }

  // Visit one RFC-style CSV record at a time so the 29 MB server-125 file
  // does not produce a second giant collection of intermediate CSV objects.
  function visitCsv(source, visit) {
    const text = String(source).replace(/^\uFEFF/, "");
    let row = [], field = "", quoted = false, header = null;
    function emit() {
      row.push(field.replace(/\r$/, ""));
      if (!header) {
        header = row.map(value => value.trim().toLowerCase());
        if (!required.every(key => header.includes(key))) throw Error("Player History fields are missing");
      } else if (row.some(value => value !== "")) {
        if (row.length !== header.length) throw Error("A Player History row is malformed");
        visit(Object.fromEntries(header.map((key, i) => [key, row[i]])));
      }
      row = []; field = "";
    }
    for (let i = 0; i < text.length; i++) {
      const ch = text[i];
      if (quoted) {
        if (ch === '"' && text[i + 1] === '"') { field += '"'; i++; }
        else if (ch === '"') quoted = false;
        else field += ch;
      } else if (ch === '"' && field === "") {
        quoted = true;
      } else if (ch === ",") {
        row.push(field); field = "";
      } else if (ch === "\n") {
        emit();
      } else {
        field += ch;
      }
    }
    if (quoted) throw Error("Player History CSV contains an unclosed field");
    if (row.length || field) emit();
    if (!header) throw Error("Player History is empty");
  }

  function build(source, server) {
    server = String(server);
    const players = new Map(), allianceLabels = new Map();
    let playersWithHistory = 0, malformedHistories = 0, skippedObservations = 0, ambiguousTimes = 0;
    const remember = tag => {
      if (tag && !allianceLabels.has(allianceKey(tag))) allianceLabels.set(allianceKey(tag), tag);
    };
    visitCsv(source, row => {
      if (clean(row.server) !== server) throw Error("Published history includes an unexpected server");
      const id = clean(row.player_id);
      if (!id) return;
      const name = clean(row.username);
      const tag = clean(row.alliance_tag);
      remember(tag);
      let p = players.get(id);
      if (!p) players.set(id, p = {id, name, observations: new Map()});
      else if (!p.name && name) p.name = name;
      if (!row.player_history_json.trim()) return;
      let entries;
      try { entries = JSON.parse(row.player_history_json); }
      catch { malformedHistories++; return; }
      if (!Array.isArray(entries)) { malformedHistories++; return; }
      for (const e of entries) {
        if (!e || typeof e !== "object") { skippedObservations++; continue; }
        const time = timeOf(e.observed_at), level = levelOf(e.base_level);
        // Do not compare across undated snapshots. They cannot establish a time bound.
        if (time === null) { skippedObservations++; continue; }
        const tag = clean(e.alliance_tag);
        remember(tag);
        const item = {time, level, tag, name: clean(e.username), changed: Array.isArray(e.fields) && e.fields.includes("base_level"),
          membershipChanged: Array.isArray(e.fields) && e.fields.some(f => f === "alliance_tag" || f === "alliance_name")};
        const group = p.observations.get(time) || [];
        if (!group.some(prev => prev.level === item.level && allianceKey(prev.tag) === allianceKey(item.tag) &&
          prev.name === item.name && prev.changed === item.changed && prev.membershipChanged === item.membershipChanged)) group.push(item);
        p.observations.set(time, group);
      }
    });

    const events = [];
    for (const p of players.values()) {
      const ordered = [...p.observations].sort(([x], [y]) => x - y);
      if (ordered.length) playersWithHistory++;
      let previous = null;
      for (const [time, seq] of ordered) {
        // If equal-time observations disagree, no chronology exists to safely
        // read a transition at that instant (including unknown level).
        if (new Set(seq.map(e => e.level)).size !== 1 || seq[0].level === null) {
          if (seq.length > 1) ambiguousTimes++;
          previous = null;
          continue;
        }
        const tags = new Set(seq.map(e => allianceKey(e.tag)));
        const tag = tags.size === 1 ? seq[0].tag : "";
        const current = {time, level: seq[0].level, tag,
          name: seq.map(e => e.name).filter(Boolean).sort(compare)[0] || "",
          changed: seq.some(e => e.changed), membershipChanged: seq.some(e => e.membershipChanged)};
        // Require the recorded base-level marker as well as a strictly
        // increasing comparison against a dated earlier observation.
        if (previous && current.changed && current.level > previous.level) {
          const tagAtBoth = !current.membershipChanged && !!tag && allianceKey(tag) === allianceKey(previous.tag);
          events.push({id: p.id, name: current.name || previous.name || p.name || "Unknown player",
            previousTime: previous.time, observedTime: time, before: previous.level, after: current.level,
            alliance: tagAtBoth ? (allianceLabels.get(allianceKey(tag)) || tag) : null,
            priorTag: previous.tag || null, observedTag: tag || null});
        }
        previous = current;
      }
    }
    events.sort((a, b) => b.observedTime - a.observedTime || compare(a.name,b.name) || compare(a.id,b.id));
    const alliances = [...allianceLabels.entries()].sort((a,b)=>a[1].localeCompare(b[1]));
    return {events, alliances, players:players.size, playersWithHistory, malformedHistories, skippedObservations, ambiguousTimes};
  }

  function filterEvents(events, alliance) {
    if (alliance === "known-only") return events.filter(e => e.alliance !== null);
    if (alliance === "unknown") return events.filter(e => e.alliance === null);
    if (alliance.startsWith("tag:")) return events.filter(e => allianceKey(e.alliance) === alliance.slice(4));
    return events;
  }
  function groups(events) {
    const output = new Map();
    for (const event of events) {
      if (!output.has(event.id)) output.set(event.id, {id: event.id, name: event.name, events: []});
      output.get(event.id).events.push(event);
    }
    return [...output.values()].sort((a,b)=>a.name.localeCompare(b.name)||compare(a.id,b.id));
  }
  function registry(raw) {
    const servers = new Map();
    for (const item of Array.isArray(raw?.servers) ? raw.servers : []) {
      const id = String(item?.id ?? "");
      if (!/^\d{1,6}$/.test(id)) continue;
      if (item.data !== `data/servers/${id}/world-players.csv` &&
          !(id === String(raw.default_server) && item.data === "data/world-players.csv")) continue;
      servers.set(id,{id,label: clean(item.label) || `Server ${id}`,data:item.data});
    }
    if (!servers.size) throw Error("No servers are registered");
    return {servers, defaultServer: servers.has(String(raw.default_server)) ? String(raw.default_server) : servers.keys().next().value};
  }
  return {allianceKey, build, filterEvents, groups, registry};
});
