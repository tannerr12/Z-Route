(function () {
"use strict";
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
    [16,"drill-ground-maintenance",5],[20,"healing-expert",1],[24,"war-frenzy",4],
    [25,"swift-reinforcement",1],[25,"battlefield-morale",1],[28,"battlefield-morale",4],
    [30,"battlefield-morale",5],[30,"rally-charge",1],[32,"swift-reinforcement",3],
    [35,"reinforcement-boost",3],[37,"reinforcement-boost",5],
    [39,"swift-reinforcement",5],[40,"charge-banner",1]
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

function init(doc,api) {
  const $=id=>doc.getElementById(id);
  const role=$("tree-role"), level=$("tree-level"), extra=$("tree-extra");
  if(!role||!api)return;
  function node(tag,value,cls){
    const el=doc.createElement(tag); if(value)el.textContent=value; if(cls)el.className=cls; return el;
  }
  function render(){
    const lv=Number(level.value), ex=Number(extra.value||"0");
    if(!Number.isInteger(lv)||lv<1||lv>40||!Number.isInteger(ex)||ex<0||ex>10)return;
    const {build,state,order,targets,next,remaining}=plan(api,role.value,lv,ex);
    $("tree-about").textContent=build.label+". "+build.why;
    $("tree-budget").textContent=api.spent(state)+" of "+api.budgetOf(state)+" points allocated ("+remaining+" unspent).";
    $("tree-next").textContent=!next?"Path complete. Keep remaining points or customize your build.":next.at>lv?(remaining?"Bank "+remaining+" point"+(remaining===1?"":"s")+". ":"") + "At class Lv. "+next.at+", take "+next.name+" rank "+next.rank+".":remaining===0?"Next point: "+next.name+" rank "+next.rank+".":"Next: "+next.name+" rank "+next.rank+".";
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
    function card([id,name,unlock,values,unit,context,prereq]){
      const el=node("article","","tree-node");
      el.dataset.plan=String(Boolean(targets[id]));
      el.dataset.next=String(next?.id===id);
      el.append(node("h5",name),node("p","Unlock Lv. "+unlock+" · "+values.length+" max · 1 point / rank"),
        node("p",targets[id]?"Build: "+(state.ranks[id]||0)+" / "+targets[id]+" ranks":"Not in selected build"));
      if(prereq)el.append(node("p","Requires "+names.get(prereq)+"."));
      el.append(node("p","Rank 1: "+new Intl.NumberFormat("en").format(values[0])+unit+"."));
      if(context)el.append(node("p",context));
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
  }
  for(const field of [role,level,extra])field.addEventListener("change",render);
  for(const field of [level,extra])field.addEventListener("input",render);
  render();
}
if(typeof module==="object"&&module.exports)module.exports={builds,plan,init};
else init(document,window.ZRouteSkillPlanner);
})();
