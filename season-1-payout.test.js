const test=require("node:test"),assert=require("node:assert/strict");
const {readFileSync}=require("node:fs");
const {HOURS,producerRate,productionRates,product,queueSavings,limited,stamina,init}=require("./season-1-payout.js");
test("producer curves sum mixed levels and reject missing or invalid entries",()=>{
 assert.equal(producerRate("food","30, 1, 10"),123700);
 assert.equal(producerRate("oil","30, 25"),168300);
 assert.equal(producerRate("oil","0"),0);
 for(const bad of ["","30,","2.5","31","1, x","0,25"])assert.equal(producerRate("oil",bad),null,bad);
});
test("payout ranks apply the correct durations and do not reapply effective-rate buffs",()=>{
 assert.deepEqual(HOURS,[4,8,12,16,24]);
 const a=productionRates("oil","base",{base:259000,bonus:209.55,extra:50});
 assert.equal(product(a.normal,24),19241628);
 assert.equal(product(a.boosted,24),22349628);
 assert.deepEqual(productionRates("oil","effective",{effective:40,boosted:50,bonus:25,extra:50}),{normal:40,boosted:50});
 assert.deepEqual(productionRates("oil","levels",{levels:"30",bonus:-100,extra:-1}),{normal:0,boosted:null});
 assert.equal(product(null,4),null);
});
test("queue, reserve, healing and stamina limits",()=>{
 assert.deepEqual(queueSavings("research",5,50,3),{maxPerQueue:20,byQueue:[20,3],total:23});
 assert.deepEqual(queueSavings("build",1,1.25,""),{maxPerQueue:2,byQueue:[1.25,0],total:1.25});
 assert.deepEqual(limited(50,5,43),{max:250,result:43});
 assert.deepEqual(limited(1000,4,0),{max:4000,result:0});
 assert.deepEqual(limited(1000,4,""),{max:4000,result:null});
 assert.deepEqual(stamina(61),{bonus:30.5,total:91.5});
});
test("live calculator calculates from the actual page's fields",()=>{
 const html=readFileSync(__dirname+"/season-1.html","utf8");
 assert.match(html,/href="#payout-calculator"/);
 assert.match(html,/src=".\/season-1-payout.js"/);
 const node=(attributes={})=>({value:"",textContent:"",children:[],events:{},append(...c){this.children.push(...c)},replaceChildren(...c){this.children=c},querySelectorAll(){return []},addEventListener(k,cb){this.events[k]=cb},...attributes});
 const ids=Object.fromEntries([...html.matchAll(/\bid="([^"]+)"/g)].map(m=>[m[1],node()]));
 ids["production-mode"].value="base";
 ids["oil-base"].value="259000";ids["oil-bonus"].value="209.55";ids["oil-extra"].value="50";
 init({getElementById:id=>ids[id],createElement:()=>node()});
 assert.equal(ids["payout-controls"].hidden,false);
 const last=ids["production-output"].children.at(-1);
 assert.match(last.children[1].children[2].children[0].textContent,/19,241,628/);
 ids["queue-skill"].value="research";ids["queue-rank"].value="5";ids["queue-a"].value="22";ids["queue-b"].value="12";
 ids["payout-controls"].events.input();
 assert.match(ids["queue-output"].textContent,/32h total/);
});
