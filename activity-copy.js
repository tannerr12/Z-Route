/* Copy-friendly summaries of filtered Z-Route Player Activity records.
 * Produces Z-Route chat-ready text with literal <br> line breaks. No network calls.
 */
(function(root,factory){
 'use strict';
 const api=factory();
 if(typeof module==='object'&&module.exports)module.exports=api;
 if(root)root.ZRouteActivityCopy=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(){
 'use strict';
 function safeText(value){
  return String(value??'').replace(/[\r\n\t]+/g,' ').replace(/\s{2,}/g,' ').trim();
 }
 function guildTag(value){
  const name=safeText(value).replace(/^\[|\]$/g,'');
  return name&&!/^(unknown|none|no guild|n\/a|-)$/i.test(name)?'['+name+'] ':'';
 }
 function nameWithGuild(name,guild){return guildTag(guild)+(safeText(name)||'?')}
 function attacks(rows){
  if(!Array.isArray(rows)||!rows.length)return '';
  // Preserve the visible filter/sort order while collapsing repeat hits by
  // the same attacker against the same victim, even if non-consecutive.
  const grouped=new Map();
  for(const row of rows){
   const attacker=safeText(row.attacker)||'?';
   const victim=safeText(row.attacked)||'?';
   const key=JSON.stringify([attacker.toLocaleLowerCase(),victim.toLocaleLowerCase()]);
   if(grouped.has(key)){
    grouped.get(key).count++;
   }else{
    grouped.set(key,{attacker,victim,count:1});
   }
  }
  return [...grouped.values()].map(({attacker,victim,count})=>
   attacker+'->'+victim+(count>1?' x'+count:'')
  ).join('<br>');
 }
 function changes(rows){
  if(!Array.isArray(rows)||!rows.length)return '';
  const lines=rows.map(row=>{
   const date=safeText(row.timestamp)||'Unknown time';
   const player=nameWithGuild(row.player,row.guild);
   const event=safeText(row.event)||'event';
   const actor=safeText(row.actor);
   return [date,player+' — '+event+(actor?' (by '+actor+')':'')].join(' | ');
  });
  return ['Join / Leave — '+rows.length+' filtered record'+(rows.length===1?'':'s'),...lines].join('<br>');
 }
 return {attacks,changes};
});
