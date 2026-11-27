(function(){
  "use strict";
  const KEY="z-route-season-1-guide-v1";
  const ROLES=Object.freeze({
    "":{card:"",text:"Choose the class that matches your main assignment."},
    growth:{card:"engineer",text:"Start Engineer. Prioritize research and production skills you will use regularly."},
    support:{card:"engineer",text:"Start Engineer. Consider ally support and reinforcement skills as they unlock."},
    combat:{card:"war-leader",text:"Start War Leader. Build for the rally or frontline job your officers assigned."},
    flex:{card:"",text:"Ask which role needs coverage first. Pick Engineer for development and support or War Leader if you will regularly lead fights."}
  });
  const FIELDS=Object.freeze({city:"Target city",strongholds:"Connected strongholds",staging:"Staging and resistance",window:"Declaration window",coverage:"Ready marches and coverage"});
  const own=(o,k)=>Object.prototype.hasOwnProperty.call(o,k);
  function decode(value){
    try{const s=JSON.parse(value);return s&&typeof s==="object"&&!Array.isArray(s)?s:{}}
    catch{return {}}
  }
  function role(value){return own(ROLES,value)?ROLES[value]:ROLES[""]}
  function readText(s,k){return own(s,k)&&typeof s[k]==="string"?s[k].slice(0,160):""}
  function formatRoute(s){
    const out=["Z-Route Season 1 route plan"];
    for(const type of ["primary","fallback"]){
      out.push("",type==="primary"?"Primary route":"Fallback route");
      for(const [key,label] of Object.entries(FIELDS))out.push(label+": "+(readText(s,type+"-"+key).trim()||"Not set"));
    }
    return out.join("\n");
  }
  function init(doc,win){
    const byId=(id)=>doc.getElementById(id);
    const state=()=>({checks:{},fields:{},role:""});
    let s=state(), storage;
    try{storage=win.localStorage;s={...s,...decode(storage.getItem(KEY))}}catch{storage=null}
    const checks=[...doc.querySelectorAll("[data-check]")];
    const inputs=[...doc.querySelectorAll("[data-route]")];
    const select=byId("class-role"),status=byId("route-status");
    const warning="Browser storage is unavailable. Changes will not survive reload.";
    if(!storage)status.textContent=warning;
    function save(){
      const next=state();
      for(const box of checks)next.checks[box.dataset.check]=box.checked;
      for(const input of inputs)next.fields[input.id]=input.value;
      next.role=select.value;
      try{if(!storage)throw new Error();storage.setItem(KEY,JSON.stringify(next));}
      catch{status.textContent=warning}
    }
    function updateProgress(){
      const done=checks.filter(box=>box.checked).length;
      byId("progress").max=checks.length;byId("progress").value=done;
      byId("progress-text").textContent=done+" of "+checks.length+" complete";
    }
    function updateRole(){
      const pick=role(select.value);
      byId("class-result").textContent=pick.text;
      for(const id of ["engineer","war-leader"])byId(id).classList.toggle("recommended",pick.card===id);
    }
    for(const box of checks){
      box.checked=s.checks?.[box.dataset.check]===true;
      box.addEventListener("change",()=>{updateProgress();save()});
    }
    for(const input of inputs){
      input.value=readText(s.fields&&typeof s.fields==="object"?s.fields:{},input.id);
      input.addEventListener("input",()=>{save();byId("plan-text").hidden=true;byId("plan-label").hidden=true});
    }
    select.value=typeof s.role==="string"&&own(ROLES,s.role)?s.role:"";
    select.addEventListener("change",()=>{updateRole();save()});
    byId("route-form").addEventListener("submit",e=>e.preventDefault());
    byId("copy-plan").addEventListener("click",async()=>{
      const value=formatRoute(Object.fromEntries(inputs.map(input=>[input.id,input.value])));
      const manual=byId("plan-text"),label=byId("plan-label");
      try{
        await win.navigator.clipboard.writeText(value);
        status.textContent="Copied. Share it only where you intend to.";
        manual.hidden=true;label.hidden=true;
      }catch{
        manual.value=value;manual.hidden=false;label.hidden=false;manual.focus();manual.select();
        status.textContent="Select and copy the route plan below.";
      }
    });
    updateProgress();updateRole();
  }
  if(typeof module==="object"&&module.exports)module.exports={decode,role,formatRoute,init};
  else init(document,window);
})();
