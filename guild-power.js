/* Shared guild power ranking for server map and recruitment.
   Totals are known, last-observed power, not real-time alliance strength. */
(function(root){
'use strict';
function guildKey(value){
 const key=String(value??'').trim().toLocaleLowerCase();
 return key==='unknown' ? '' : key;
}
function knownPower(raw){
 if(raw===undefined||raw===null||String(raw).trim()==='')return null;
 const value=Number(String(raw).trim());
 return Number.isSafeInteger(value)&&value>=0?value:null;
}
function rank(players,server){
 const deduped=new Map();
 for(const player of Array.isArray(players)?players:[]){
  if(!player||typeof player!=='object')continue;
  const srv=String(player.server??'').trim();
  if(server!==undefined&&server!==null&&srv!==String(server))continue;
  const id=String(player.id??player.player_id??'').trim();
  if(!srv||!id)continue;
  deduped.set(srv+':'+id,player);
 }
 const groups=new Map();
 for(const player of deduped.values()){
  const label=String(player.alliance??player.guild??player.alliance_tag??player.alliance_name??'').trim();
  const key=guildKey(label);
  if(!key)continue; // No alliance / Unknown is not ranked as a guild.
  let group=groups.get(key);
  if(!group){
   group={key,name:label,totalPower:0n,members:0,knownMembers:0,missingMembers:0,rank:null};
   groups.set(key,group);
  }
  group.members++;
  const power=knownPower(player.power);
  if(power===null)group.missingMembers++;
  else {group.totalPower+=BigInt(power);group.knownMembers++;}
 }
 const ranked=[...groups.values()].filter(g=>g.knownMembers>0).sort((a,b)=>
  a.totalPower===b.totalPower?a.name.localeCompare(b.name):
  a.totalPower>b.totalPower?-1:1);
 ranked.forEach((g,i)=>g.rank=i+1);
 const unranked=[...groups.values()].filter(g=>g.knownMembers===0).sort((a,b)=>a.name.localeCompare(b.name));
 return {ranked,unranked,byKey:groups,observedPlayers:deduped.size};
}
function excludedTop(ranking,count){
 const n=Number(count);
 if(!Number.isFinite(n)||n<=0)return new Set();
 const rows=ranking?.ranked??[];
 return new Set(rows.slice(0,Math.min(rows.length,Math.floor(n))).map(g=>g.key));
}
function compact(power){
 return new Intl.NumberFormat(undefined,{notation:'compact',maximumFractionDigits:2}).format(power);
}
const api={guildKey,knownPower,rank,excludedTop,compact};
if(typeof module==='object'&&module.exports)module.exports=api;
else root.ZRouteGuildPower=api;
})(typeof window==='undefined'?globalThis:window);
