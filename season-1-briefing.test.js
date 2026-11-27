const test=require("node:test"),assert=require("node:assert/strict");
const {readFileSync}=require("node:fs");
const {makeBrief,signature,restore,init}=require("./season-1-briefing.js");
const primary={city:"First 1 2",strongholds:"S1 - S2",staging:"X1 Y2; 9000 resistance",window:"Sat 16:00",coverage:"7 eligible"};
const fallback={...primary,city:"Second 3 4",window:"Sat 17:00"};
const extra={declarer:"A / B",rally:"C",garrison:"D",protection:"Ends 15:45",decision:"go"};
const checked={adjacent:true,window:true,ready:true};
test("no go call until the selected route and all essential checks are present",()=>{
 assert.match(makeBrief(primary,fallback,extra,{}).body,/DRAFT - NOT A GO CALL/);
 assert.match(makeBrief(primary,fallback,extra,{}).body,/owned adjacent stronghold check/);
 assert.equal(makeBrief(primary,fallback,extra,checked).call,"GO");
 assert.equal(makeBrief({...primary,window:""},fallback,extra,checked).call,"DRAFT - NOT A GO CALL");
 assert.equal(makeBrief(primary,fallback,{...extra,decision:"hold"},checked).call,"HOLD");
 const f=makeBrief(primary,fallback,{...extra,decision:"fallback"},checked);
 assert.equal(f.call,"USE FALLBACK");assert.match(f.body,/Target: Second 3 4/);assert.doesNotMatch(f.body,/First 1 2/);
 assert.equal(makeBrief(primary,{}, {...extra,decision:"fallback"},checked).ready,false);
});
test("fingerprints protect prior confirmations from changed route, protection or lineup",()=>{
 assert.notEqual(signature(primary,extra),signature(fallback,extra));
 assert.notEqual(signature(primary,extra),signature(primary,{...extra,protection:"Unknown"}));
 assert.notEqual(signature(primary,extra),signature(primary,{...extra,garrison:"New"}));
 assert.deepEqual(restore("{"),{});
});
test("actual page: route edits clear confirmations, then copy and clear stay local",async()=>{
 const html=readFileSync(__dirname+"/season-1.html","utf8");
 assert.match(html,/href="#battle-briefing"/);assert.match(html,/src=".\/season-1-briefing.js"/);
 const node=()=>({value:"",checked:false,textContent:"",events:{},addEventListener(k,cb){this.events[k]=cb},hasAttribute(k){return k==="data-route"},focus(){this.focused=true},select(){this.selected=true}});
 const map=Object.fromEntries([...html.matchAll(/\bid="([^"]+)"/g)].map(m=>[m[1],node()]));
 for(const [prefix,route] of [["primary",primary],["fallback",fallback]])for(const [k,v] of Object.entries(route))map[prefix+"-"+k].value=v;
 let saved="",clipboard="";
 const win={localStorage:{getItem:()=>saved,setItem:(_,s)=>{saved=s},removeItem:()=>{saved=""}},navigator:{clipboard:{async writeText(x){clipboard=x}}}};
 init({getElementById:id=>map[id]},win);
 const root=map["brief-controls"];
 for(const [k,v] of Object.entries(extra)){const target=map["brief-"+k];target.value=v;root.events.input({target});}
 for(const k of Object.keys(checked)){const target=map["brief-"+k];target.checked=true;root.events.change({target});}
 assert.match(map["brief-text"].value,/\| GO/);
 await map["brief-copy"].events.click();assert.match(clipboard,/\| GO/);
 const city=map["primary-city"];city.value="Changed";
 map["route-form"].events.input({target:city});
 assert.equal(map["brief-adjacent"].checked,false);
 assert.match(map["brief-text"].value,/DRAFT - NOT A GO CALL/);
 win.navigator={};await map["brief-copy"].events.click();assert.equal(map["brief-text"].selected,true);
 map["brief-clear"].events.click();assert.equal(saved,"");assert.equal(city.value,"Changed");
});
