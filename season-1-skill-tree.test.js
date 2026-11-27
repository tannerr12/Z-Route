"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const api=require("./season-1-skill-planner");
const {builds,sheetTargets,guidance,plan}=require("./season-1-skill-tree");
for(const [id,build] of Object.entries(builds)) {
  test(id+": every level and allowed bonus respects rank, cost and prerequisites",()=>{
    for(let extra=0;extra<=10;extra++) {
      let prior={};
      for(let lv=1;lv<=40;lv++) {
        const {state,order,remaining}=plan(api,id,lv,extra);
        assert.deepEqual(api.audit(build.classId,state),[],id+" at "+lv);
        assert.equal(api.spent(state)+remaining,lv+extra);
        assert.equal(api.spent(state),order.reduce((total,s)=>total+s.applied,0));
        for(const [skill,rank] of Object.entries(prior)) assert.ok(state.ranks[skill]>=rank);
        prior=state.ranks;
      }
    }
  });
  test(id+": milestones fit without bonus points and final targets are complete",()=>{
    const final=plan(api,id,40);
    assert.equal(final.next,null);
    assert.deepEqual(final.state.ranks,final.targets);
    final.order.forEach((s,i)=>assert.equal(plan(api,id,s.at).order[i].applied,s.cost,s.name+" at "+s.at));
  });
}
test("community targets are distinct from legal role allocations",()=>{
  assert.equal(sheetTargets.engineer.length,api.DATA.engineer.length);
  assert.equal(sheetTargets.war.length,api.DATA.war.length);
  assert.equal(sheetTargets.engineer.reduce((a,b)=>a+b,0)+5,63);
  assert.match(guidance(0,5),/saved points/i);
  assert.match(guidance(3,0),/role-specific/i);
  assert.match(guidance(5,5),/matches/i);
});
test("role-specific featured milestones",()=>{
  assert.equal(plan(api,"growth",15).state.ranks["instant-research"],4);
  assert.equal(plan(api,"siege",19).state.ranks["siege-banner"],undefined);
  assert.equal(plan(api,"siege",20).state.ranks["siege-banner"],1);
  assert.equal(plan(api,"rally",30).state.ranks["rally-charge"],1);
  assert.equal(plan(api,"defense",35).state.ranks["reinforcement-boost"],3);
});
test("page loads shared planner first; all controls work and keep separate semantic lanes",()=>{
  const html=fs.readFileSync("season-1-skill-tree.html","utf8");
  assert.ok(html.indexOf("season-1-skill-planner.js")<html.indexOf("season-1-skill-tree.js"));
  assert.match(fs.readFileSync("season-1.html","utf8"),/href="\.\/season-1-skill-tree.html"/);
  class Element{
    constructor(tag){this.tag=tag; this.dataset={};this.children=[];this.listeners={};}
    append(...items){this.children.push(...items);}
    replaceChildren(...items){this.children=items;}
    addEventListener(event,f){this.listeners[event]=f;}
  }
  const ids=Object.fromEntries([...html.matchAll(/id="(tree-[^"]+)"/g)].map(([,id])=>[id,new Element()]));
  const document={getElementById:id=>ids[id],createElement:tag=>new Element(tag)};
  ids["tree-role"].value="growth";ids["tree-level"].value="15";ids["tree-extra"].value="0";
  const browser=vm.createContext({window:{},document});
  for(const n of ["season-1-skill-planner.js","season-1-skill-tree.js"]) vm.runInContext(fs.readFileSync(n,"utf8"),browser);
  assert.match(ids["tree-about"].textContent,/Engineer/);
  assert.match(ids["tree-budget"].textContent,/15 points/);
  assert.ok(ids["tree-order"].children.length>10);
  ids["tree-role"].value="rally";ids["tree-role"].listeners.change();
  assert.match(ids["tree-about"].textContent,/War Leader/);
  ids["tree-level"].value="40";ids["tree-level"].listeners.input();
  ids["tree-extra"].value="4";ids["tree-extra"].listeners.change();
  assert.match(ids["tree-budget"].textContent,/44 points/);
  assert.match(ids["tree-next"].textContent,/Path complete/);
  const nodes=ids["tree-branches"].children;
  assert.equal(nodes.length,2);
  const chain=nodes[1].children[1];
  assert.equal(chain.children.length,9);
  assert.ok(chain.children[1].children[0].children.some(e=>e.textContent==="Requires Battlefield Knowledge I."));
});
test("tracks ranks, blocks invalid spending, saves independently and round trips JSON",async()=>{
  const html=fs.readFileSync("season-1-skill-tree.html","utf8");
  let storage=new Map(), exported, downloads=0, revoked=0;
  function mount(){
    class Element{
      constructor(tag){this.tag=tag;this.dataset={};this.children=[];this.listeners={};this.checked=false;}
      append(...items){this.children.push(...items);}
      replaceChildren(...items){this.children=items;}
      addEventListener(event,f){this.listeners[event]=f;}
      setAttribute(){}
      focus(){}
      click(){downloads++;}
      remove(){}
    }
    const ids=Object.fromEntries([...html.matchAll(/id="(tree-[^"]+)"/g)].map(([,id])=>[id,new Element()]));
    function get(root,id){return root.id===id?root:root.children.map(x=>get(x,id)).find(Boolean);}
    const document={getElementById:id=>ids[id]||get(ids["tree-branches"],id),createElement:tag=>new Element(tag),body:new Element()};
    Object.assign(ids["tree-role"],{value:"growth"});
    Object.assign(ids["tree-level"],{value:"15"});
    Object.assign(ids["tree-extra"],{value:"0"});
    const window={localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},
      Blob:class {constructor(parts){exported=parts.join("");}},
      URL:{createObjectURL:()=>"blob:build",revokeObjectURL:()=>revoked++},setTimeout:f=>f()};
    const browser=vm.createContext({window,document});
    for(const n of ["season-1-skill-planner.js","season-1-skill-tree.js"]) vm.runInContext(fs.readFileSync(n,"utf8"),browser);
    return {ids,lookup:document.getElementById};
  }
  let {ids,lookup}=mount();
  const click=id=>lookup(id).listeners.click();
  function set(id,attributes){Object.assign(ids[id],attributes);return ids[id].listeners.change();}
  set("tree-track",{checked:true});
  assert.match(ids["tree-next"].textContent,/Next legal pick: Battlefield Knowledge I/);
  assert.equal(lookup("rank-lucky-hunt-up").disabled,true);
  click("rank-knowledge-1-up");click("rank-lucky-hunt-up");
  assert.equal(lookup("rank-knowledge-1-down").disabled,true);
  click("rank-instant-research-up");
  set("tree-level",{value:"5"});assert.equal(ids["tree-level"].value,15);
  assert.match(ids["tree-file-status"].textContent,/before its level unlock/);
  click("tree-export");assert.equal(downloads,1);assert.equal(revoked,1);
  const parsed=JSON.parse(exported);
  assert.deepEqual(parsed.ranks,{"instant-research":1,"knowledge-1":1,"lucky-hunt":1});
  set("tree-role",{value:"rally"});click("rank-instant-recall-up");
  set("tree-role",{value:"growth"});
  assert.match(ids["tree-budget"].textContent,/3 of 15/);
  ({ids,lookup}=mount());assert.match(ids["tree-budget"].textContent,/3 of 15/);
  set("tree-role",{value:"rally"});assert.match(ids["tree-budget"].textContent,/1 of 1/);
  await set("tree-import",{files:[{size:100,text:async()=>JSON.stringify({...parsed,ranks:{"lucky-hunt":1}})}]});
  assert.match(ids["tree-file-status"].textContent,/needs Battlefield Knowledge I.*not changed/);
  assert.equal(ids["tree-role"].value,"rally");
  await set("tree-import",{files:[{size:100,text:async()=>exported}]});
  assert.match(ids["tree-file-status"].textContent,/Loaded your Engineer build/);
  assert.match(ids["tree-budget"].textContent,/3 of 15/);
});
test("rejects unknown, foreign, over-budget and out-of-range ranks",()=>{
  const {decode,fileFor}=require("./season-1-skill-tree");
  const base=fileFor(api,"growth",15,0,{"instant-research":1});
  for(const [override,re] of [
    [{version:2},/version 1/],[{classId:"war"},/do not match/],
    [{ranks:{foo:1}},/Unknown skill/],[{ranks:{"instant-research":6}},/rank from 0 to 5/],
    [{level:14},/allocated before/],[{extra:11},/Bonus points/],
    [{level:1,ranks:{"accelerate-production":2}},/Over budget/],
    [{ranks:JSON.parse('{"__proto__":2}')},/Unknown skill/]
  ])assert.throws(()=>decode(api,{...base,...override}),re);
});
