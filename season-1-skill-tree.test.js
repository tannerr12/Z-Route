"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const api=require("./season-1-skill-planner");
const {builds,plan}=require("./season-1-skill-tree");
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