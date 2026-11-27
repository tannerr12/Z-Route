(function(){
  "use strict";
  const DATA={"engineer":[["accelerate-production","Accelerate Production",1,[4,8,12,16,24],"h of shelter output per use","Food, Metal and Oil; 23.5h cooldown."],["contribution-reward","Contribution Reward",1,[100],"% more Alliance Coins","Applies to Alliance Tech donations and helping allies."],["stamina-recovery","Stamina Recovery",5,[50],"% more stamina","Applies to the eligible daily free claim."],["demolition-specialist","Demolition Specialist",5,[100,200,300,400,500]," troop Destruction","Also unlocks Demolish Ruins."],["free-construction","Free Construction",10,[48,96,144,192,240]," min of free construction time"],["free-research","Free Research",10,[48,96,144,192,240]," min of free research time"],["build-now","Build Now",15,[2,4,6,8,10],"h removed per build queue","47.5h cooldown."],["instant-research","Instant Research",15,[4,8,12,16,20],"h removed per research queue","47.5h cooldown."],["team-fast-march","Team Fast March",20,[10,20,30,40,50],"% rally march speed","Only when joining or returning from a rally."],["siege-banner","Siege Banner",20,[100]," Destruction per flag","Nearby allied troops; up to 5 flag stacks; 30m duration; 71.5h cooldown."],["class-inspiration","Class Inspiration",25,[20,40,60],"% more Class EXP","While damaging City Durability."],["logistics-support","Logistics Support",25,[5,10,15,20,25],"% reduction to Drill Ground soldier death rate","While reinforcing an ally’s Base; does not stack."],["cooperative-construction","Cooperative Construction",30,[10,20],"% building speed","You and one ally for 1h; does not stack; 23.5h cooldown."],["cooperative-research","Cooperative Research",30,[10,20],"% research speed","You and one ally for 1h; does not stack; 23.5h cooldown."],["cost-efficiency","Cost Efficiency",35,[1,2,3,4,5],"% lower building resource cost"],["efficient-utilization","Efficient Utilization",35,[1,2,3,4,5],"% lower research resource cost"],["cooperative-healing","Cooperative Healing",40,[10,20,30,40,50],"% Hospital capacity","You and one ally for 4h; does not stack; 71.5h cooldown."],["friendship-shield","Friendship Shield",40,[1,2,4],"h of shield","You or one ally; does not stack; 71.5h cooldown."]],"war":[["instant-recall","Instant Recall",1,[1,2,3,4,5]," daily relocations with instant troop recall","Recalls all deployed troops on the eligible relocations."],["reserve-mobilization","Reserve Mobilization",1,[50,100,150,200,250]," highest-tier soldiers per use","Limited by Drill Ground room; 23.5h cooldown."],["drill-ground-maintenance","Drill Ground Maintenance",5,[2,4,6,8,10],"% Drill Ground capacity","Existing troops stay if the capacity drops; no additional troops can enter until there is room."],["hospital-maintenance","Hospital Maintenance",5,[2,4,6,8,10],"% Hospital capacity","Capacity loss can remove overflow wounded, lower tiers first."],["war-frenzy","War Frenzy",10,[1,2,3,4,5],"% damage during War Frenzy"],["field-emergency-care","Field Emergency Care",10,[1000,2000,3000,4000,5000]," untreated troops healed per use","Does not revive lost troops; 71.5h cooldown."],["press-the-advantage","Press the Advantage",15,[1,2,3,4,5],"% enemy soldier death rate","Only when attacking a burning Base."],["battle-prep-drill","Battle Prep Drill",15,[5,10,15,20,25],"% soldier training speed"],["scorched-land-march","Scorched Land March",20,[25,50],"% march speed in Scorched Land","Active during Capital Conquest."],["sustain-through-war","Sustain Through War",20,[10,20,30,40,50],"% daily plunder resource limit"],["battlefield-morale","Battlefield Morale",25,[2,4,6,8,10],"% troop morale"],["swift-reinforcement","Swift Reinforcement",25,[10,20,30,40,50],"% march speed when reinforcing an ally’s Base"],["rally-charge","Rally Charge",30,[1,2,3,4,5],"% squad damage in rallies","Joining or launching; does not stack."],["stealth","Stealth",30,[30]," min of Stealth","Hides personal information in Intel and Battle Reports; 47.5h cooldown."],["fire-support","Fire Support",35,[1,2,3,4,5],"% attacking soldier death rate","Only while reinforcing an ally’s Base."],["reinforcement-boost","Reinforcement Boost",35,[1,2,3,4,5],"% ATK, DEF and HP for defending heroes","When reinforcing an ally’s Base; does not stack."],["regressed","Regressed",40,[1000]," enemy wounded reduced one tier / day","Maximum; applies to a portion of enemy wounded."],["charge-banner","Charge Banner",40,[2],"% ATK per flag","Nearby allied Bases; up to 5 flag stacks; 30m duration; 71.5h cooldown."]],"shared":[["knowledge-1","Battlefield Knowledge I",1,[7500]," bonus Class EXP per monster","75,000 daily cap."],["lucky-hunt","Lucky Hunt",5,[5]," extra Mutant Shard drops / day","","knowledge-1"],["knowledge-2","Battlefield Knowledge II",10,[150000]," daily bonus Class EXP cap","7,500 bonus EXP per eligible monster kill.","lucky-hunt"],["knowledge-3","Battlefield Knowledge III",15,[15000]," bonus Class EXP per monster","150,000 daily cap remains.","knowledge-2"],["healing-expert","Healing Expert",20,[5]," virus stacks cured per use","10 Class EXP per cured stack; 1,000 daily EXP limit.","knowledge-3"],["infection-spread","Infection Spread",25,[300]," bonus Class EXP per pathogen stack spread","300,000 weekly limit.","healing-expert"],["pathogen-assault","γ Pathogen Assault",30,[2]," pathogen stacks added per cast","Targets Cities, Outposts, Capitols or Batteries; cap 30; 71.5h cooldown.","infection-spread"],["pathogen-boost","γ Pathogen Boost",35,[50],"% pathogen carry ratio","Applies to deployed troops.","pathogen-assault"],["virus-experiment","Virus Experiment",40,[50]," additional Virus Stack Limit","","pathogen-boost"]]};
  const KEY="z-route-season-1-skill-planner-v1";
  const validClass=id=>id==="war"?"war":"engineer";
  const int=(val,fallback,min,max)=>{
    if(!["number","string"].includes(typeof val)||String(val).trim()==="")return fallback;
    const n=Number(val);return Number.isInteger(n)&&n>=min&&n<=max?n:fallback;
  };
  function skills(classId){ return [...DATA[validClass(classId)],...DATA.shared]; }
  function normalize(classId,raw){
    const level=int(raw?.level,1,1,40);
    const budget=raw?.budget==null?null:int(raw.budget,null,0,1000);
    const ranks={};
    for(const [id,,,values] of skills(classId)){
      const rank=int(raw?.ranks?.[id],0,0,values.length);
      if(rank)ranks[id]=rank;
    }
    return {level,budget,ranks};
  }
  function spent(state){return Object.values(state.ranks).reduce((sum,num)=>sum+num,0)}
  const budgetOf=state=>state.budget??state.level;
  const rankOf=(state,id)=>state.ranks[id]||0;
  function canAdd(classId,state,id){
    const skill=skills(classId).find(row=>row[0]===id);
    if(!skill)return "Unknown skill.";
    const [,,level,values,,,prereq]=skill;
    if(rankOf(state,id)>=values.length)return "Maximum rank.";
    if(state.level<level)return "Unlocks at class Lv. "+level+".";
    if(prereq&&!prereqReady(classId,state,prereq))return "Requires "+nameOf(classId,prereq)+".";
    if(spent(state)>=budgetOf(state))return "No points available.";
    return "";
  }
  function prereqReady(classId,state,id){
    const skill=skills(classId).find(row=>row[0]===id);
    const before=skill?.[6];
    return Boolean(skill&&state.level>=skill[2]&&rankOf(state,id)&&(!before||prereqReady(classId,state,before)));
  }
  function canRemove(classId,state,id){
    if(!rankOf(state,id))return "Nothing to remove.";
    if(rankOf(state,id)===1){
      const linked=skills(classId).find(row=>row[6]===id&&rankOf(state,row[0]));
      if(linked)return "Remove "+linked[1]+" first.";
    }
    return "";
  }
  function adjust(classId,state,id,direction){
    const block=direction===1?canAdd(classId,state,id):direction===-1?canRemove(classId,state,id):"Invalid change.";
    if(block)return state;
    const ranks={...state.ranks};
    const value=rankOf(state,id)+direction;
    if(value)ranks[id]=value;else delete ranks[id];
    return {...state,ranks};
  }
  function audit(classId,state){
    const issues=[];
    if(spent(state)>budgetOf(state))issues.push("Over budget by "+(spent(state)-budgetOf(state))+" point(s).");
    for(const [id,name,level,,,,prereq] of skills(classId)){
      if(!rankOf(state,id))continue;
      if(level>state.level)issues.push(name+" is allocated before its level unlock.");
      if(prereq&&!prereqReady(classId,state,prereq))issues.push(name+" needs "+nameOf(classId,prereq)+".");
    }
    return issues;
  }
  function nameOf(classId,id){return skills(classId).find(item=>item[0]===id)?.[1]||id}
  function milestone(classId,level){
    const marks=classId==="war"?[[5,"Hospital Maintenance if you need more wounded capacity"],[10,"Field Emergency Care for untreated wounded"],[15,"Battle Prep Drill for training speed"],[30,"Rally Charge for regular PvP rally work"]]:[[5,"Stamina Recovery if you collect free stamina"],[10,"Free Research for shorter queues"],[15,"Instant Research for long research queues"],[20,"Siege Banner if assigned to city fights"],[30,"Cooperative Research if you coordinate with an ally"]];
    const found=marks.find(([at])=>at>level);
    return found?"Planning suggestion: Lv. "+found[0]+" opens "+found[1]+".":"Compare current upgrades by their next-rank gain.";
  }
  function outputDelta(rates,hours=8){
    if(!rates||typeof rates!=="object")return [];
    return ["food","metal","oil"].flatMap(id=>{
      const item=rates[id];
      if(!item||!Number.isFinite(item.normal)&&!Number.isFinite(item.boosted))return [];
      return [{id,normal:Number.isFinite(item.normal)?item.normal*hours:null,boosted:Number.isFinite(item.boosted)?item.boosted*hours:null}];
    });
  }
  function init(doc,win){
    const get=id=>doc.getElementById(id);
    const root=get("skill-planner-controls");if(!root)return;
    let restored={};try{restored=JSON.parse(win.localStorage.getItem(KEY))||{}}catch{}
    let classId=validClass(restored.classId);
    const builds={engineer:normalize("engineer",restored.engineer),war:normalize("war",restored.war)};
    const state=()=>builds[classId];
    const rows=get("skill-rows"), selector=get("skill-class"), level=get("skill-level"), budget=get("skill-budget"), only=get("skill-only-unlocked");
    const fmt=new Intl.NumberFormat("en",{maximumFractionDigits:2});
    let refs=[];
    function tag(node,value,cls){const item=doc.createElement(node);item.textContent=value;if(cls)item.className=cls;return item}
    function save(){try{win.localStorage.setItem(KEY,JSON.stringify({classId,...builds}))}catch{}}
    function renderInputs(){selector.value=classId;level.value=state().level;budget.value=state().budget??""}
    function renderRows(){
      refs=[];const fragments=[];
      for(const [title,list] of [[classId==="war"?"War Leader":"Engineer",DATA[classId]],["Shared Season 1",DATA.shared]]){
        const section=tag("section","","skill-tree");const heading=tag("h3",title);section.append(heading);
        const grid=tag("div","","skill-cards");
        for(const skill of list){
          const [id,name,unlock,values,unit,context,pre]=skill;
          const card=tag("article","","skill-card"), rank=tag("span","","skill-rank");
          const effect=tag("p","","skill-effect"),reason=tag("p","","skill-reason");
          const minus=tag("button","−"),plus=tag("button","+");
          for(const [button,verb,direction] of [[minus,"Remove", -1],[plus,"Add",1]]){
            button.type="button";button.setAttribute("aria-label",verb+" one rank: "+name);
            button.addEventListener("click",()=>{builds[classId]=adjust(classId,state(),id,direction);save();update()});
          }
          const buttons=tag("div","","skill-buttons");buttons.append(minus,rank,plus);
          const text="Class Lv. "+unlock+(pre?" · Requires "+nameOf(classId,pre):"");
          card.append(tag("h4",name),tag("p",text,"skill-meta"),effect,buttons,reason);
          if(context)card.append(tag("p",context,"skill-context"));
          grid.append(card);refs.push({card,rank,effect,reason,plus,minus,skill,values,unit});
        }
        section.append(grid);fragments.push(section);
      }
      rows.replaceChildren(...fragments);
    }
    function update(){
      const s=state(),issues=audit(classId,s),used=spent(s),remaining=budgetOf(s)-used;
      get("skill-summary").textContent=used+" / "+budgetOf(s)+" points spent · "+(remaining<0?Math.abs(remaining)+" over budget":remaining+" available");
      get("skill-warning").textContent=issues.join(" ");
      get("skill-milestone").textContent=milestone(classId,s.level);
      for(const {card,rank,effect,reason,plus,minus,skill,values,unit} of refs){
        const [id,,unlock]=skill,current=rankOf(s,id),next=values[current],currentEffect=current?values[current-1]:0;
        card.hidden=only.checked&&unlock>s.level&&!current;
        rank.textContent=current+" / "+values.length;
        effect.textContent=(current?"Current: "+fmt.format(currentEffect)+unit+". ":"")+(next===undefined?"":(current?"Next: +"+fmt.format(next-currentEffect)+unit+".":"Rank 1: "+fmt.format(next)+unit+"."));
        const add=canAdd(classId,s,id),remove=canRemove(classId,s,id);
        plus.disabled=Boolean(add);minus.disabled=Boolean(remove);
        reason.textContent=add+(remove&&current?" "+remove:"");
      }
    }
    function production(rates){
      const target=get("skill-production-marginal");
      const delta=outputDelta(rates);
      target.textContent=delta.length?"Extra per use with your calculator rates: "+delta.map(({id,normal,boosted})=>id[0].toUpperCase()+id.slice(1)+": "+[normal===null?null:"+"+fmt.format(normal)+" normal",boosted===null?null:"+"+fmt.format(boosted)+" buffed"].filter(Boolean).join(" / ")).join(" · ")+".":"Enter hourly rates or producer levels in the payout calculator to see the extra payout using your own stats.";
    }
    doc.addEventListener("zroute:production-rates",e=>production(e.detail));
    production(get("production-output")?.zrProductionRates);
    selector.addEventListener("change",()=>{classId=validClass(selector.value);renderInputs();renderRows();update();save()});
    function readInput(field,type,min,max){
      if(field.validity&&!field.validity.valid)return;
      const next=type==="budget"&&field.value.trim()===""?null:int(field.value,undefined,min,max);
      if(next===undefined)return;
      builds[classId]={...state(),[type]:next};save();update();
    }
    for(const event of ["input","change"]){
      level.addEventListener(event,()=>readInput(level,"level",1,40));
      budget.addEventListener(event,()=>readInput(budget,"budget",0,1000));
    }
    only.addEventListener("change",update);
    get("skill-reset").addEventListener("click",()=>{
      if(!spent(state())||!win.confirm("Clear all points in this class build?"))return;
      builds[classId]={...state(),ranks:{}};save();update();
    });
    renderInputs();renderRows();update();root.hidden=false;
  }
  if(typeof module==="object"&&module.exports)module.exports={DATA,skills,normalize,spent,budgetOf,canAdd,canRemove,adjust,audit,outputDelta,milestone,init};
  else {
    window.ZRouteSkillPlanner=Object.freeze({DATA,skills,normalize,spent,budgetOf,adjust,audit});
    init(document,window);
  }
})();
