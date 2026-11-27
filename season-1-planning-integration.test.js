const test=require("node:test"),assert=require("node:assert/strict");
const {readFileSync,existsSync}=require("node:fs");
const {join}=require("node:path");
const page=readFileSync(join(__dirname,"season-1.html"),"utf8");
test("Season 1 planner links, labels, and local assets resolve",()=>{
  const ids=[...page.matchAll(/\bid="([^"]+)"/g)].map(([,id])=>id);
  assert.equal(new Set(ids).size,ids.length,"duplicate ID");
  const idSet=new Set(ids);
  for(const nav of ["payout-calculator","skill-planner","resistance-planner","routes","battle-briefing"]){
    assert.ok(idSet.has(nav),nav);
    assert.ok(page.includes('href="#'+nav+'"'),nav+" does not have a quick link");
  }
  for(const [,id] of page.matchAll(/\bfor="([^"]+)"/g))assert.ok(idSet.has(id),"unmatched label: "+id);
  for(const [,file] of page.matchAll(/\b(?:src|href)="\.\/([^"#?]+)"/g))assert.ok(existsSync(join(__dirname,file)),"missing "+file);
  assert.ok(page.indexOf('src="./season-1.js"')<page.indexOf('src="./season-1-briefing.js"'),"route must restore before briefing");
  assert.ok(page.indexOf('src="./season-1-payout.js"')<page.indexOf('src="./season-1-skill-planner.js"'),"payout must initialize before the skill planner");
  for(const input of ["Tanner Russell","[D3AD]","S125"]) assert.ok(!page.includes(input),"private data in generic public guide");
});
