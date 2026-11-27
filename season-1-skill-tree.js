(function () {
"use strict";
// Community targets in the same unlock order as the client-derived class catalog.
const sheetTargets=Object.freeze({"engineer":[5,1,1,5,5,5,5,5,5,1,0,0,2,2,5,5,5,1],"war":[3,0,5,5,5,0,0,0,2,0,5,0,5,0,0,0,1,1]});
function guidance(target,desired){
  if(desired===undefined)return target?"Shared pick for seasonal progression.":"Not on the community sheet.";
  if(target===desired)return "Community target: "+desired+" (matches).";
  const reason=target===0?"Saved points for this role":target>desired?"Role-specific addition":"Trimmed to fit this role";
  return "Community target: "+desired+". "+reason+".";
}
const builds = {
  growth: {classId:"engineer", label:"Engineer | Growth / Research", why:"For long queues and daily production. Fill both research queues before using Instant Research.", steps:[
    [1,"knowledge-1",1],[2,"contribution-reward",1],[3,"accelerate-production",1],
    [5,"stamina-recovery",1],[5,"lucky-hunt",1],[9,"accelerate-production",5],
    [10,"knowledge-2",1],[15,"instant-research",4],[15,"knowledge-3",1],
    [16,"instant-research",5],[17,"build-now",1],[21,"build-now",5],
    [26,"free-research",5],[30,"cooperative-research",2],[30,"cooperative-construction",2],
    [35,"efficient-utilization",5],[40,"cost-efficiency",5]
  ]},
  siege: {classId:"engineer", label:"Engineer | City / Siege Support", why:"For assigned City work. Build Destruction early, then coordinate Banner placement and temporary hospital capacity.", steps:[
    [1,"knowledge-1",1],[2,"contribution-reward",1],[5,"stamina-recovery",1],
    [5,"lucky-hunt",1],[5,"demolition-specialist",1],[9,"demolition-specialist",5],
    [10,"knowledge-2",1],[15,"knowledge-3",1],[15,"instant-research",3],[15,"build-now",1],
    [19,"instant-research",5],[20,"siege-banner",1],[21,"team-fast-march",3],
    [23,"team-fast-march",5],[24,"healing-expert",1],[28,"build-now",5],
    [30,"cooperative-research",2],[33,"cooperative-construction",2],[34,"accelerate-production",1],
    [40,"cooperative-healing",5],[40,"friendship-shield",1]
  ]},
  rally: {classId:"war", label:"War Leader | Rally Lead", why:"For regular rally leaders. Protect your troop pool early, then prioritize Rally Charge and coordinate Charge Banner.", steps:[
    [1,"knowledge-1",1],[2,"instant-recall",1],[5,"lucky-hunt",1],
    [5,"hospital-maintenance",2],[8,"drill-ground-maintenance",3],[10,"knowledge-2",1],
    [10,"war-frenzy",1],[14,"war-frenzy",5],[15,"knowledge-3",1],
    [17,"instant-recall",3],[19,"hospital-maintenance",4],[20,"scorched-land-march",1],
    [21,"scorched-land-march",2],[22,"hospital-maintenance",5],[24,"drill-ground-maintenance",5],
    [25,"battlefield-morale",1],[29,"battlefield-morale",5],[30,"rally-charge",1],
    [34,"rally-charge",5],[35,"healing-expert",1],[40,"charge-banner",1],[40,"regressed",1]
  ]},
  defense: {classId:"war", label:"War Leader | Garrison / Recovery", why:"For defenders and reinforcement crews. Protect hospital and troop capacity first; favor buffs that apply when reinforcing an ally.", steps:[
    [1,"knowledge-1",1],[2,"instant-recall",1],[5,"hospital-maintenance",2],[5,"lucky-hunt",1],
    [8,"hospital-maintenance",5],[10,"field-emergency-care",1],[10,"knowledge-2",1],
    [13,"drill-ground-maintenance",3],[15,"knowledge-3",1],[15,"drill-ground-maintenance",4],
    [16,"drill-ground-maintenance",5],[20,"healing-expert",1],[22,"instant-recall",3],[24,"war-frenzy",5],
    [25,"battlefield-morale",1],[28,"battlefield-morale",4],
    [30,"battlefield-morale",5],[30,"rally-charge",1],[32,"rally-charge",3],
    [35,"reinforcement-boost",3],[37,"reinforcement-boost",5],
    [39,"scorched-land-march",2],[40,"charge-banner",1]
  ]}
};
function plan(api, role, level, extra=0) {
  const build=builds[role];
  if (!build) throw new RangeError("Unknown role");
  const state0=api.normalize(build.classId,{level,budget:level+extra});
  const choices=api.skills(build.classId);
  const byId=new Map(choices.map(row=>[row[0],row]));
  const targets={};
  let next=null, state=state0, last=0, blocked=false;
  const order=build.steps.map(([at,id,target])=>{
    const row=byId.get(id);
    const prior=targets[id]||0;
    if (!row||at<last||at<row[2]||target<=prior||target>row[3].length) throw new Error("Invalid path: "+role+" "+id);
    if (row[6]&&!targets[row[6]]) throw new Error("Unmet prerequisite in path: "+role+" "+id);
    targets[id]=target;
    last=at;
    const item={at,id,name:row[1],from:prior+1,target,cost:target-prior,applied:0};
    if (!blocked&&at<=level) for(let rank=prior;rank<target;rank++){
      const changed=api.adjust(build.classId,state,id,1);
      if(changed===state) break;
      state=changed; item.applied++;
    }
    if (item.applied<item.cost) {
      if (!next) next={...item,rank:item.from+item.applied};
      blocked=true;
    }
    return item;
  });
  return {build,state,order,targets,next,remaining:api.budgetOf(state)-api.spent(state)};
}

const FORMAT="zroute-season-1-skill-build";
const STORE="zroute-season-1-skill-tree-v1";
function decode(api,data){
  if(!data||data.format!==FORMAT||data.version!==1)throw Error("Choose a Season 1 skill build JSON (version 1).");
  if(typeof data.role!=="string"||!Object.hasOwn(builds,data.role))throw Error("Choose a known role in the file.");
  const build=builds[data.role];
  if(data.classId!==build.classId)throw Error("The role and class in the file do not match.");
  if(!Number.isInteger(data.level)||data.level<1||data.level>40)throw Error("Class level must be 1 to 40.");
  if(!Number.isInteger(data.extra)||data.extra<0||data.extra>10)throw Error("Bonus points must be 0 to 10.");
  if(!data.ranks||typeof data.ranks!=="object"||Array.isArray(data.ranks))throw Error("The file is missing skill ranks.");
  const byId=new Map(api.skills(build.classId).map(row=>[row[0],row]));
  for(const [id,n] of Object.entries(data.ranks)){
    const row=byId.get(id);
    if(!row)throw Error("Unknown skill in this class: "+id.slice(0,80)+".");
    if(!Number.isInteger(n)||n<0||n>row[3].length)throw Error(row[1]+" needs a rank from 0 to "+row[3].length+".");
  }
  const s=api.normalize(build.classId,{level:data.level,budget:data.level+data.extra,ranks:data.ranks});
  const issues=api.audit(build.classId,s);
  if(issues.length)throw Error(issues[0]+" Edit the JSON or export a valid build.");
  return {format:FORMAT,version:1,role:data.role,classId:build.classId,level:data.level,extra:data.extra,ranks:s.ranks};
}
function fileFor(api,role,level,extra,ranks){
  return decode(api,{format:FORMAT,version:1,role,classId:builds[role].classId,level,extra,ranks});
}
function suggest(api,role,s){
  const {build,order}=plan(api,role,s.level,s.budget-s.level);
  const later=order.filter(x=>(s.ranks[x.id]||0)<x.target);
  const ready=later.find(x=>x.at<=s.level&&!api.canAdd(build.classId,s,x.id));
  return ready?{item:ready,rank:(s.ranks[ready.id]||0)+1,canBuy:true}:
    later.length?{item:later[0],rank:(s.ranks[later[0].id]||0)+1,canBuy:false}:null;
}
function init(doc,api,win) {
  const $=id=>doc.getElementById(id);
  const role=$("tree-role"), level=$("tree-level"), extra=$("tree-extra");
  if(!role||!api)return;
  const track=$("tree-track"),exportBtn=$("tree-export"),importInput=$("tree-import"),status=$("tree-file-status");
  const saved={};
  let viewRole=role.value, focusNext=null;
  function message(value){status.textContent=value;}
  try{
    const stored=JSON.parse(win.localStorage.getItem(STORE));
    for(const key of ["engineer","war"]){
      try{const v=decode(api,stored?.builds?.[key]); if(v.classId===key)saved[key]=v;}catch{}
    }
    if(stored?.active&&Object.hasOwn(builds,stored.role)){
      viewRole=stored.role; role.value=viewRole; track.checked=true;
      const v=saved[builds[viewRole].classId];
      if(v){level.value=v.level;extra.value=v.extra;}
    }
  }catch{}
  function persist(){
    try{win.localStorage.setItem(STORE,JSON.stringify({role:viewRole,active:track.checked,builds:saved}));}
    catch{message("This browser could not save your build. Export JSON to keep it.");}
  }
  function current(roleId=viewRole){
    const key=builds[roleId].classId;
    return saved[key]||fileFor(api,roleId,1,0,{});
  }
  function record(payload){
    saved[payload.classId]=payload;
    persist();
  }
  function loadInputs(payload){
    level.value=payload.level; extra.value=payload.extra;
  }
  function changeNumbers(){
    if(!track.checked){render();return;}
    const v=current(), lv=Number(level.value), ex=Number(extra.value||"0");
    try{record(fileFor(api,viewRole,lv,ex,v.ranks));message("");}
    catch(e){loadInputs(v);message(e.message.replace(" Edit the JSON or export a valid build."," Remove affected ranks before lowering the level or budget."));}
    render();
  }
  function changeRank(id,delta){
    const v=current();
    const s=api.normalize(v.classId,{level:v.level,budget:v.level+v.extra,ranks:v.ranks});
    const after=api.adjust(v.classId,s,id,delta);
    if(after===s)return;
    message("");
    record(fileFor(api,viewRole,v.level,v.extra,after.ranks));
    focusNext="rank-"+id+(delta===1?"-up":"-down");
    render();
  }
  exportBtn.addEventListener("click",()=>{
    const v=current();
    const data=fileFor(api,viewRole,v.level,v.extra,v.ranks);
    const url=win.URL.createObjectURL(new win.Blob([JSON.stringify(data,null,2)+"\n"],{type:"application/json"}));
    const a=node("a"); a.href=url; a.download="z-route-season-1-"+v.classId+".json";
    doc.body.append(a);a.click();a.remove();
    win.setTimeout(()=>win.URL.revokeObjectURL(url),2000);
    message("Build exported.");
  });
  importInput.addEventListener("change",async()=>{
    const file=importInput.files?.[0];importInput.value="";
    if(!file)return;
    try{
      if(file.size>65536)throw Error("That file is larger than 64 KB.");
      let data;
      try{data=JSON.parse(await file.text());}catch{throw Error("That file is not valid JSON.");}
      const payload=decode(api,data);
      track.checked=true; viewRole=payload.role; role.value=viewRole;
      record(payload);loadInputs(payload);render();message("Loaded your "+(payload.classId==="war"?"War Leader":"Engineer")+" build.");
    }catch(e){message(e.message+" Your saved build was not changed.");}
  });
  function node(tag,value,cls){
    const el=doc.createElement(tag); if(value)el.textContent=value; if(cls)el.className=cls; return el;
  }
  function render(){
    const lv=Number(level.value), ex=Number(extra.value||"0");
    if(!Number.isInteger(lv)||lv<1||lv>40||!Number.isInteger(ex)||ex<0||ex>10)return;
    const {build,order,targets,next,remaining:planRemaining,state:pathState}=plan(api,viewRole,lv,ex);
    const tracked=track.checked, v=tracked?current():null;
    const state=tracked?api.normalize(build.classId,{level:v.level,budget:v.level+v.extra,ranks:v.ranks}):pathState;
    const remaining=tracked?api.budgetOf(state)-api.spent(state):planRemaining;
    const suggestion=tracked?suggest(api,viewRole,state):null;
    exportBtn.disabled=!tracked;
    $("tree-about").textContent=build.label+". "+build.why;
    $("tree-budget").textContent=api.spent(state)+" of "+api.budgetOf(state)+" points allocated ("+remaining+" unspent).";
    $("tree-next").textContent=!next?"Path complete. Keep remaining points or customize your build.":next.at>lv?(remaining?"Bank "+remaining+" point"+(remaining===1?"":"s")+". ":"") + "At class Lv. "+next.at+", take "+next.name+" rank "+next.rank+".":remaining===0?"Next point: "+next.name+" rank "+next.rank+".":"Next: "+next.name+" rank "+next.rank+".";
    if(tracked) {
      const pick=suggestion&&suggestion.item.name+" rank "+suggestion.rank;
      $("tree-next").textContent=!suggestion?"Your build meets every target for this role.":
        suggestion.canBuy?"Next legal pick: "+pick+".":
        "Next target: "+pick+". "+(remaining===0?"No points available.":suggestion.item.at>lv?"Planned at class Lv. "+suggestion.item.at+".":"Check the skill’s prerequisite below.");
    }
    let labeled=false;
    $("tree-order").replaceChildren(...order.map(step=>{
      const ranks=step.from===step.target?"rank "+step.target:"ranks "+step.from+"–"+step.target;
      const li=node("li",step.name+" "+ranks);
      const active=step.applied<step.cost&&!labeled;
      if(active)labeled=true;
      li.dataset.state=step.applied===step.cost?"done":active?"next":"later";
      const phase=li.dataset.state==="done"?"Allocated":active?"Next":"Later";
      const progress=step.applied&&step.applied<step.cost?" · "+step.applied+"/"+step.cost+" allocated":"";
      li.append(node("span",phase+" · Lv. "+step.at+"+ · "+step.cost+" pt"+(step.cost===1?"":"s")+progress,"tree-chip"));
      return li;
    }));
    const names=new Map(api.skills(build.classId).map(row=>[row[0],row[1]]));
    const community=new Map(api.DATA[build.classId].map((row,i)=>[row[0],sheetTargets[build.classId][i]]));
    function card([id,name,unlock,values,unit,context,prereq]){
      const el=node("article","","tree-node");
      el.dataset.plan=String(Boolean(targets[id]));
      el.dataset.next=String((tracked?suggestion?.item:next)?.id===id);
      el.append(node("h5",name),node("p","Unlock Lv. "+unlock+" · "+values.length+" max · 1 point / rank"),
        node("p",targets[id]?(tracked?"Route target: "+targets[id]+" rank"+(targets[id]===1?"":"s"):"Build: "+(state.ranks[id]||0)+" / "+targets[id]+" ranks"):"Not in selected route"));
      el.append(node("p",guidance(targets[id]||0,community.get(id)),"tree-hint"));
      if(prereq)el.append(node("p","Requires "+names.get(prereq)+"."));
      el.append(node("p","Rank 1: "+new Intl.NumberFormat("en").format(values[0])+unit+"."));
      if(context)el.append(node("p",context));
      if(tracked){
        const controls=node("div","","tree-rank-buttons"), chosen=state.ranks[id]||0;
        const rankText=node("span","Your rank: "+chosen);
        el.append(rankText);
        for(const [delta,sign,check,action] of [[-1,"−",api.canRemove,"Remove"],[1,"+",api.canAdd,"Add"]]){
          const btn=node("button",sign);btn.type="button";
          btn.id="rank-"+id+(delta===1?"-up":"-down");
          btn.setAttribute("aria-label",action+" rank: "+name);
          const reason=check(build.classId,state,id);
          btn.disabled=Boolean(reason);
          btn.addEventListener("click",()=>changeRank(id,delta));
          controls.append(btn);
          if(delta===1&&reason)controls.append(node("span",reason,"tree-hint"));
        }
        el.append(controls);
      }
      return el;
    }
    const classTree=node("section"), shared=node("section");
    classTree.append(node("h3",build.classId==="war"?"War Leader unlocks":"Engineer unlocks"));
    const rows=api.DATA[build.classId];
    for(const unlock of new Set(rows.map(row=>row[2]))){
      const tier=node("div","","tree-tier");
      tier.append(node("h4","Class Lv. "+unlock),...rows.filter(row=>row[2]===unlock).map(card));
      classTree.append(tier);
    }
    shared.append(node("h3","Shared prerequisite chain"));
    const chain=node("ol","","tree-shared");
    for(const row of api.DATA.shared){
      const item=node("li"); item.append(card(row)); chain.append(item);
    }
    shared.append(chain);
    $("tree-branches").replaceChildren(classTree,shared);
    if(focusNext){
      const button=$(focusNext);
      if(button?.disabled)$(focusNext.replace(/-(up|down)$/,m=>m==="-up"?"-down":"-up"))?.focus();
      else button?.focus();
      focusNext=null;
    }
  }
  role.addEventListener("change",()=>{
    viewRole=role.value;
    if(track.checked){loadInputs(current());persist();}
    render();
  });
  track.addEventListener("change",()=>{
    if(track.checked) {
      const key=builds[viewRole].classId;
      if(!saved[key]){
        const lv=Number(level.value), ex=Number(extra.value);
        record(fileFor(api,viewRole,Number.isInteger(lv)&&lv>=1&&lv<=40?lv:15,Number.isInteger(ex)&&ex>=0&&ex<=10?ex:0,{}));
      }
      loadInputs(current());
    }
    persist();render();
  });
  for(const field of [level,extra]){
    field.addEventListener("change",changeNumbers);
    field.addEventListener("input",()=>{if(!track.checked)render();});
  }
  render();
}
if(typeof module==="object"&&module.exports)module.exports={builds,sheetTargets,guidance,plan,decode,fileFor,suggest,init};
else init(document,window.ZRouteSkillPlanner,window);
})();
