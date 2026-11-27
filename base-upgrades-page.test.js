"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const all = name => fs.readFileSync(path.join(__dirname,name),"utf8");
class Element {
  #selected;
  constructor(tag,text="",value="") { this.tagName = tag; this.textContent=text; this.value=value; this.children=[]; this.listeners={}; }
  get value() { return this.#selected; }
  set value(value) { this.#selected = value; }
  get options() { return this.children; }
  get childElementCount() { return this.children.length; }
  setAttribute() {}
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = items; if(this.tagName==="select") this.value = items[0]?.value; }
  addEventListener(name,callback) { this.listeners[name] = callback; }
  focus() {}
}
const header="server,player_id,username,alliance_tag,player_history_json\n";
const source=(id,history)=>header+`${id},001,Player,D3AD,"${JSON.stringify(history).replaceAll('"','""')}"`;
const history = [
  {observed_at:"2026-11-25T18:00:00Z",base_level:"29",alliance_tag:"D3AD",fields:["power"]},
  {observed_at:"2026-11-26T18:00:00Z",base_level:"30",alliance_tag:"D3AD",fields:["base_level"]}
];
function launch() {
  const page = all("base-upgrades.html");
  const elements = Object.fromEntries([...page.matchAll(/<([a-z]+)[^>]* id="([^"]+)"/g)].map(m=>[m[2],new Element(m[1])]));
  const getById = id => elements[id];
  const reg = {default_server:125,servers:[{id:125,data:"data/servers/125/world-players.csv"},{id:115,data:"data/servers/115/world-players.csv"}]};
  let currentLocation = "https://example.test/Z-Route/base-upgrades.html?server=125&alliance=D3AD";
  const screen = {
    URL, AbortController, window:{location:{href:currentLocation}},
    history:{replaceState(_a,_b,url){currentLocation = url.toString();}},
    document:{getElementById:getById,createElement:tag=>new Element(tag),createTextNode:text=>new Element("#text",text)},
    Option: class extends Element { constructor(text,value) {super("option",text,value);} },
    fetch:async p=>{
      if(p==="./data/servers.json") return {ok:true,json:async()=>reg};
      if(p==="./data/servers/125/world-players.csv") return {ok:true,text:async()=>source("125",history)};
      if(p==="./data/servers/115/world-players.csv") return {ok:true,text:async()=>source("115",[])};
      throw Error("Unexpected data path: "+p);
    }
  };
  screen.window = Object.assign(screen,screen.window);
  const ctx = vm.createContext(screen);
  const scripts = [...page.matchAll(/<script .*?src="\.\/([^"]+)"/g)].map(m=>m[1]);
  assert.deepEqual(scripts,["site-nav.js","base-upgrades-model.js","base-upgrades-page.js"]);
  for (const script of scripts.slice(1)) vm.runInContext(all(script),ctx,{filename:script});
  return {getById, location:()=>currentLocation};
}
test("Base Upgrades entry-point scripts load the server and apply deep links, player grouping and server switches",async()=>{
  const {getById:el,location}=launch();
  await new Promise(setImmediate);
  assert.equal(el("server").value,"125");
  assert.equal(el("alliance").value,"tag:d3ad");
  assert.match(el("coverage").textContent,/Server 125: 1 of 1 player records/);
  assert.match(el("summary").textContent,/1 observed increase/);
  assert.equal(el("results").children[0].tagName,"div");
  assert.match(location(),/alliance=tag%3Ad3ad/);
  el("group").checked=true;
  el("group").listeners.change();
  const expanded=el("results").children[0];
  assert.equal(expanded.tagName,"details");
  assert.match(expanded.children[0].textContent,/Player · 1 observed increase/);
  expanded.open=true;expanded.listeners.toggle();
  assert.equal(expanded.children[1].tagName,"div");
  el("server").value="115";
  await el("server").listeners.change();
  assert.match(el("coverage").textContent,/Server 115: 0 of 1/);
  assert.match(el("summary").textContent,/No observed increases/);
  assert.equal(el("results").children.length,0);
  assert.match(location(),/server=115/);
});
