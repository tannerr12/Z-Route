/* Recruitment exclusion using D3AD's published Join/Leave history.
   Only exact event="removed" is eligible. Natural departures are not kicks.
   The alliance log has names rather than stable player IDs, so matches are
   exact normalized current-name / alias matches, not fuzzy contains matches.
   This source is D3AD's server-125 activity; do not use across servers. */
(function(root){
'use strict';
function nameKey(value){
 return String(value||'').normalize('NFKC').trim().replace(/\s+/g,' ').toLocaleLowerCase();
}
function kickedNames(rows){
 const names=new Set();
 for(const row of rows||[]){
  if(String(row.event||'').trim().toLowerCase()!=='removed')continue;
  const name=nameKey(row.player||row.username);
  if(name)names.add(name);
 }
 return names;
}
function wasRemoved(player,names){
 if(!player||!names||!names.size)return false;
 const candidates=[player.name,...(Array.isArray(player.aliases)?player.aliases:[])];
 return candidates.some(name=>names.has(nameKey(name)));
}
function filterCandidates(players,names,exclude,server){
 if(!exclude||String(server)!=='125')return players;
 return players.filter(player=>!wasRemoved(player,names));
}
root.ZRouteRecruitmentRemovals={nameKey,kickedNames,wasRemoved,filterCandidates};
})(typeof window!=='undefined'?window:globalThis);
