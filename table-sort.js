/* Client-side sorting of the full filtered roster (not only visible rows). */
(function(root){
'use strict';
const textOrder=new Intl.Collator(undefined,{numeric:true,sensitivity:'base'});
const PLAYER_FIELDS=new Set(['player','alliance','level','power','kills','signals','lastChange','location','shield']);
const GUILD_FIELDS=new Set(['rank','guildName','guildPower','guildCoverage']);
const DESC_FIRST=new Set(['level','power','kills','signals','lastChange','guildPower','guildCoverage']);
function nextSort(current,key,fields){
 if(!fields.has(key))return current;
 if(current&&current.key===key){
  return {key,direction:current.direction==='asc'?'desc':'asc'};
 }
 return {key,direction:DESC_FIRST.has(key)?'desc':'asc'};
}
function numberOrNull(value){
 if(value===null||value===undefined||String(value).trim()==='')return null;
 const number=Number(value);
 return Number.isFinite(number)?number:null;
}
function timestamp(value){
 if(!value)return null;
 const n=Date.parse(value);
 return Number.isFinite(n)?n:null;
}
function compareValues(a,b,direction){
 const aMissing=a===null||a===undefined, bMissing=b===null||b===undefined;
 if(aMissing||bMissing)return aMissing===bMissing?0:aMissing?1:-1;
 const cmp=(typeof a==='string'||typeof b==='string')
  ?textOrder.compare(String(a),String(b)):a===b?0:a>b?1:-1;
 return direction==='desc'?-cmp:cmp;
}
function playerValue(p,key){
 switch(key){
 case 'player':return p.name||'';
 case 'alliance':return p.alliance||'Unallied';
 case 'level':return numberOrNull(p.level);
 case 'power':return numberOrNull(p.power);
 case 'kills':return numberOrNull(p.kills);
 case 'signals':return p.signal?.types?.length??0;
 case 'lastChange':return timestamp(p.signal?.lastChangeAt);
 case 'location':return numberOrNull(p.x);
 case 'shield':return p.shield||'unknown';
 default:return null;
 }
}
function sortPlayers(players,sort={key:'lastChange',direction:'desc'}){
 if(!Array.isArray(players))return [];
 const key=PLAYER_FIELDS.has(sort?.key)?sort.key:'lastChange';
 const direction=sort?.direction==='asc'?'asc':'desc';
 return [...players].sort((a,b)=>{
  let cmp=compareValues(playerValue(a,key),playerValue(b,key),direction);
  if(!cmp&&key==='location')cmp=compareValues(numberOrNull(a.y),numberOrNull(b.y),direction);
  if(!cmp&&key==='lastChange'){
   cmp=compareValues(playerValue(a,'signals'),playerValue(b,'signals'),'desc');
   if(!cmp)cmp=compareValues(playerValue(a,'level'),playerValue(b,'level'),'desc');
  }
  if(!cmp)cmp=compareValues(a.name||'',b.name||'','asc');
  if(!cmp)cmp=compareValues(String(a.id||''),String(b.id||''),'asc');
  return cmp;
 });
}
function guildValue(g,key){
 switch(key){
 case 'rank':return numberOrNull(g.rank);
 case 'guildName':return g.name||'';
 case 'guildPower':return g.knownMembers?g.totalPower:null;
 case 'guildCoverage':return g.members?g.knownMembers/g.members:null;
 default:return null;
 }
}
function sortGuilds(guilds,sort={key:'rank',direction:'asc'}){
 if(!Array.isArray(guilds))return [];
 const key=GUILD_FIELDS.has(sort?.key)?sort.key:'rank';
 const direction=sort?.direction==='desc'?'desc':'asc';
 return [...guilds].sort((a,b)=>{
  let cmp=compareValues(guildValue(a,key),guildValue(b,key),direction);
  if(!cmp&&key==='guildCoverage')cmp=compareValues(a.knownMembers,b.knownMembers,direction);
  if(!cmp&&key!=='rank')cmp=compareValues(guildValue(a,'rank'),guildValue(b,'rank'),'asc');
  if(!cmp)cmp=compareValues(a.name||'',b.name||'','asc');
  return cmp;
 });
}
const api={PLAYER_FIELDS,GUILD_FIELDS,nextSort,sortPlayers,sortGuilds};
if(typeof module==='object'&&module.exports)module.exports=api;
else root.ZRouteTableSort=api;
})(typeof window==='undefined'?globalThis:window);
