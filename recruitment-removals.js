/* D3AD historical removals for Server 125.
 * Confirmed player IDs are preferred. If an event lacks an ID, only a
 * unique exact current-name / known-alias match in the loaded roster may
 * establish identity. Ambiguous names are never auto-excluded.
 * Voluntary "left" and "joined" events do not qualify.
 */
(function(root){
'use strict';
function nameKey(value){
 return String(value||'').normalize('NFKC').trim().replace(/\s+/g,' ').toLocaleLowerCase();
}
function playerId(player){
 return String(player?.id??player?.player_id??'').trim();
}
function rosterCandidates(players){
 const names=new Map();
 for(const p of players||[]){
  const id=playerId(p);
  if(!id)continue;
  const aliases=Array.isArray(p.aliases)?p.aliases:[];
  for(const name of [p.name||p.username,...aliases]){
   const key=nameKey(name);
   if(!key)continue;
   if(!names.has(key))names.set(key,new Set());
   names.get(key).add(id);
  }
 }
 return names;
}
function removedIdentity(rows,players){
 const ids=new Set(),unresolved=new Set(),ambiguous=new Set();
 const known=rosterCandidates(players);
 let removedEvents=0,publishedIds=0,rosterMatched=0;
 for(const row of rows||[]){
  if(String(row.event||'').trim().toLowerCase()!=='removed')continue;
  removedEvents++;
  const id=String(row.player_id||'').trim();
  if(id){
   ids.add(id);publishedIds++;continue;
  }
  const name=nameKey(row.player||row.username);
  if(!name)continue;
  const candidates=known.get(name);
  if(candidates?.size===1){
   ids.add([...candidates][0]);rosterMatched++;
  }else if(candidates?.size>1){
   ambiguous.add(name);
  }else{
   unresolved.add(name);
  }
 }
 return {ids,unresolved,ambiguous,removedEvents,publishedIds,rosterMatched};
}
function wasRemoved(player,identity){
 if(!player||!identity)return false;
 const id=playerId(player);
 if(id&&identity.ids.has(id))return true;
 // A currently unknown roster identity can still be excluded by name,
 // but never use this fallback for known, nonmatching player IDs.
 if(id)return false;
 const names=[player.name||player.username,...(Array.isArray(player.aliases)?player.aliases:[])];
 return names.some(name=>identity.unresolved.has(nameKey(name)));
}
function filterCandidates(players,identity,exclude,server){
 if(!exclude||String(server)!=='125')return players;
 return players.filter(player=>!wasRemoved(player,identity));
}
root.ZRouteRecruitmentRemovals={nameKey,playerId,rosterCandidates,
 removedIdentity,wasRemoved,filterCandidates};
})(typeof window!=='undefined'?window:globalThis);
