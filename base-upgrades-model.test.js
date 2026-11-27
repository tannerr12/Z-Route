"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const model = require("./base-upgrades-model");
const fields = ["server", "player_id", "username", "alliance_tag", "player_history_json"];
const csv = (...rows) => "\ufeff" + [fields,...rows.map(([id,name,tag,observations,server="125"])=>[server,id,name,tag,
  typeof observations === "string" ? observations : JSON.stringify(observations)])]
  .map(row=>row.map(x=>'"'+String(x).replaceAll('"','""')+'"').join(",")).join("\r\n");
function obs(day,level,tag,changes=["base_level"],name="") {
  return {observed_at:`2026-11-${String(day).padStart(2,"0")}T10:00:00.000000+00:00`,
    fields:changes,base_level:level,alliance_tag:tag,username:name};
}

test("a first observation and a change marker without a higher level do not create upgrades",()=>{
  const r=model.build(csv(["01","First","D3AD",[obs(20,21,"D3AD"),obs(21,21,"D3AD"),obs(22,20,"D3AD")]]),125);
  assert.equal(r.playersWithHistory,1);
  assert.deepEqual(r.events,[]);
});
test("out-of-order histories, duplicate rows and quoted player names produce one event with a true observation window",()=>{
  const p=[obs(21,"23","d3ad",["base_level"],'Different, "name"'),obs(20,21,"D3AD",["first_seen"])];
  const r=model.build(csv(["0001",'A "quoted", name',"Other",p],["0001","A name","Other",p]),125);
  assert.equal(r.players,1);
  assert.equal(r.events.length,1);
  const [event]=r.events;
  assert.deepEqual([event.before,event.after,event.name,event.alliance],[21,23,'Different, "name"',"d3ad"]);
  assert.equal(new Date(event.previousTime).toISOString(),"2026-11-20T10:00:00.000Z");
  assert.equal(new Date(event.observedTime).toISOString(),"2026-11-21T10:00:00.000Z");
  assert.equal(model.filterEvents(r.events,"tag:d3ad").length,1);
  assert.equal(model.filterEvents(r.events,"tag:other").length,0);
});
test("membership transitions, reported membership changes and absent alliances remain unknown",()=>{
  const r=model.build(csv(
    ["01","A","NEW",[obs(20,20,"OLD"),obs(21,21,"NEW",["base_level","alliance_tag"])]],
    ["02","B","D3AD",[obs(20,20,"D3AD"),obs(21,21,"D3AD",["base_level","alliance_name"])]],
    ["03","C","D3AD",[obs(20,20,""),obs(21,21,"D3AD")]]
  ),"125");
  assert.equal(model.filterEvents(r.events,"unknown").length,3);
  assert.equal(model.filterEvents(r.events,"tag:d3ad").length,0);
  assert.equal(model.filterEvents(r.events,"known-only").length,0);
});
test("unknown levels and contradictory equal timestamps break the baseline",()=>{
  const r=model.build(csv(
    ["01","A","D3AD",[obs(17,19,"D3AD"),obs(18,null,"D3AD"),obs(19,23,"D3AD")]],
    ["02","B","D3AD",[obs(17,19,"D3AD"),obs(18,20,"D3AD"),obs(18,21,"D3AD"),obs(19,22,"D3AD")]]
  ),"125");
  assert.equal(r.ambiguousTimes,1);
  assert.deepEqual(r.events,[]);
});
test("reject mixed server or invalid headers; malformed history is reported without crashing",()=>{
  assert.throws(()=>model.build(csv(["01","Other","X",[],"115"]),"125"),/unexpected server/);
  assert.throws(()=>model.build("username,server\nA,125","125"),/fields are missing/);
  const r=model.build(csv(["01","Broken","X","not json"]),125);
  assert.equal(r.malformedHistories,1);
  assert.deepEqual(r.events,[]);
});
test("no upgrade inferred for a higher value without base-level change evidence; valid subsequent increases stay chronological",()=>{
  const h=[obs(17,19,"D3AD"),obs(18,20,"D3AD",["power"]),obs(19,21,"D3AD"),obs(20,22,"D3AD")];
  const r=model.build(csv(["01","A","D3AD",h],["02","A","D3AD",h]),125);
  assert.deepEqual(r.events.map(e=>e.after),[22,22,21,21]);
  assert.deepEqual(model.groups(r.events).map(g=>[g.id,g.events.length]),[["01",2],["02",2]]);
});
test("registry only fetches the corresponding site's published server export",()=>{
  const r=model.registry({default_server:125,servers:[
    {id:125,data:"data/servers/125/world-players.csv"}, {id:115,data:"data/servers/125/world-players.csv"},
    {id:124,data:"https://example.test/other.json"}, {id:113,data:"data/servers/113/world-players.csv"}
  ]});
  assert.deepEqual([...r.servers.keys()],["125","113"]);
  assert.equal(r.defaultServer,"125");
});
