/* NAP counts are linked report groups, not confirmed violations. */
(function(root,factory){const api=factory(typeof module==='object'&&module.exports?require('./nap-model'):root.ZRouteNAP);if(typeof module==='object'&&module.exports)module.exports=api;else root.ZRouteRecruitmentNAP=api;})(globalThis,function(NAP){
'use strict';
function counts(snapshot,index){if(snapshot?.schema_version!==1||!Array.isArray(snapshot.normalized?.records))throw Error('Invalid NAP snapshot');const map=new Map();let unresolved=0;for(const row of NAP.link(snapshot,index)){const match=row.aggressor;if(!match.id){unresolved++;continue;}if(!map.has(match.id))map.set(match.id,{count:0,fuzzy:0});const r=map.get(match.id);r.count++;if(match.status==='fuzzy_history')r.fuzzy++;}return {map,unresolved};}
function threshold(raw){if(String(raw??'').trim()==='')return null;const value=Number(raw);return Number.isSafeInteger(value)&&value>=0?value:null;}
function passes(count,raw){const max=threshold(raw);return max===null||count===null||count===undefined||count<max;}
function annotate(player,result,available){const known=available&&String(player.server)==='125',record=known?result.map.get(String(player.id)):null;return {...player,napCount:known?(record?.count||0):null,napFuzzy:known?(record?.fuzzy||0):null};}
return {counts,threshold,passes,annotate};
});
