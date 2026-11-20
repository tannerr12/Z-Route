/* Review flags use complete captured weekdays, never uncaptured days as zero. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.ZRouteAlliancePolicy=api;})(globalThis,function(){
'use strict';
function assess(rows,days,today,minimum=1000000,bottomPercent=15){
 const eligible=rows.filter(r=>!r.provisional&&r.rank!=null);
 const completed=days.filter(([day])=>day<today&&![0,6].includes(new Date(day+'T12:00:00Z').getUTCDay()));
 const donations=eligible.filter(r=>Number.isFinite(r.donations)).sort((a,b)=>a.donations-b.donations);
 const n=Math.ceil(donations.length*Math.max(0,Math.min(100,Number(bottomPercent)||0))/100);
 const cutoff=n?donations[n-1]?.donations:null;
 const flags=new Map(rows.map(r=>{
  const known=completed.length>0&&completed.every(([,s])=>!s.ambiguous.has(r.id));
  const average=known?completed.reduce((v,[,s])=>v+(s.map.get(r.id)??0),0)/completed.length:null;
  return [r.id,{average,belowMinimum:!r.provisional&&average!=null&&average<Math.max(0,Number(minimum)||0),lowDonor:eligible.includes(r)&&cutoff!=null&&Number.isFinite(r.donations)&&r.donations<=cutoff}];
 }));
 return {flags,completedDays:completed.length,cutoff,top:[...eligible].sort((a,b)=>b.score-a.score||a.name.localeCompare(b.name)).slice(0,20),bottom:[...eligible].sort((a,b)=>a.score-b.score||a.name.localeCompare(b.name)).slice(0,10)};
}
return {assess};
});
