const {test}=require("node:test");
const assert=require("node:assert/strict");
const {DATA,skills,normalize,spent,budgetOf,canAdd,canRemove,adjust,audit,outputDelta,milestone}=require("./season-1-skill-planner.js");
test("both classes have 18 class skills and nine shared skills, all within cap",()=>{
  assert.deepEqual([DATA.engineer.length,DATA.war.length,DATA.shared.length],[18,18,9]);
  for(const type of ["engineer","war"]){
    const rows=skills(type);
    assert.equal(new Set(rows.map(r=>r[0])).size,27);
    assert.ok(rows.every(r=>r[2]<=40&&r[3].length>=1&&r[3].length<=5));
  }
});
test("level gates and real budget override are respected, even at zero",()=>{
  let s=normalize("engineer",{level:5});
  assert.equal(budgetOf(s),5);
  assert.match(canAdd("engineer",s,"instant-research"),/Lv. 15/);
  assert.match(canAdd("engineer",{...s,budget:0},"stamina-recovery"),/No points/);
  for(let i=0;i<5;i++)s=adjust("engineer",s,"accelerate-production",1);
  assert.equal(spent(s),5);assert.match(canAdd("engineer",s,"stamina-recovery"),/No points/);
  assert.match(canAdd("engineer",s,"accelerate-production"),/Maximum/);
});
test("shared skill prerequisite is bidirectional on add and remove",()=>{
  let s=normalize("war",{level:20,budget:8});
  assert.match(canAdd("war",s,"lucky-hunt"),/Battlefield Knowledge I/);
  s=adjust("war",s,"knowledge-1",1);s=adjust("war",s,"lucky-hunt",1);s=adjust("war",s,"knowledge-2",1);
  assert.match(canRemove("war",s,"knowledge-1"),/Lucky Hunt/);
  assert.strictEqual(adjust("war",s,"knowledge-1",-1),s);
  s=adjust("war",s,"knowledge-2",-1);s=adjust("war",s,"lucky-hunt",-1);s=adjust("war",s,"knowledge-1",-1);
  assert.equal(spent(s),0);
});
test("lowered class level flags existing ranks without deleting and validates restored input",()=>{
  const s=normalize("engineer",{level:5,budget:0,ranks:{"instant-research":2,"reserve-mobilization":4,"knowledge-2":1,"accelerate-production":100}});
  assert.equal(spent(s),3);
  assert.match(audit("engineer",s).join(" "),/Over budget by 3/);
  assert.match(audit("engineer",s).join(" "),/Instant Research.*level unlock/);
  assert.match(audit("engineer",s).join(" "),/Battlefield Knowledge II needs Lucky Hunt/);
  assert.match(milestone("engineer",10),/Instant Research/);
});
test("marginal is the exact 8-hour difference for each supplied normal/buffed rate",()=>{
  assert.deepEqual(outputDelta({oil:{normal:125000,boosted:300000},food:{normal:0,boosted:null},metal:{normal:null,boosted:2}}),
    [{id:"food",normal:0,boosted:null},{id:"metal",normal:null,boosted:16},{id:"oil",normal:1000000,boosted:2400000}]);
  assert.deepEqual(outputDelta(null),[]);
});
test("entry fragment mounts, spends, toggles class, and reads live payout data",()=>{
  const html=require("node:fs").readFileSync(__dirname+"/season-1.html","utf8");
  const elem=()=>({children:[],events:{},attrs:{},checked:false,value:"",addEventListener(k,cb){this.events[k]=cb},setAttribute(k,v){this.attrs[k]=v},append(...children){this.children.push(...children)},replaceChildren(...children){this.children=children}});
  const ids=Object.fromEntries([...html.matchAll(/\bid="([^"]+)"/g)].map(m=>[m[1],elem()]));
  const vals={};
  const win={localStorage:{getItem:k=>vals[k],setItem:(k,v)=>{vals[k]=v}},confirm:()=>true};
  ids["production-output"]={zrProductionRates:{oil:{normal:100,boosted:125}}};
  const listeners={};
  const doc={getElementById:id=>ids[id],createElement:elem,addEventListener:(key,cb)=>{listeners[key]=cb}};
  require("./season-1-skill-planner.js").init(doc,win);
  assert.equal(ids["skill-planner-controls"].hidden,false);
  assert.match(ids["skill-production-marginal"].textContent,/Oil: \+800 normal \/ \+1,000 buffed/);
  const first=ids["skill-rows"].children[0].children[1].children[0];
  first.children[3].children[2].events.click();
  assert.match(ids["skill-summary"].textContent,/1 \/ 1 points spent/);
  ids["skill-class"].value="war";ids["skill-class"].events.change();
  assert.match(ids["skill-summary"].textContent,/0 \/ 1 points spent/);
  listeners["zroute:production-rates"]({detail:{food:{normal:200,boosted:null}}});
  assert.match(ids["skill-production-marginal"].textContent,/Food: \+1,600 normal/);
});
