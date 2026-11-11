/* Copy-friendly summaries of filtered Z-Route Player Activity records.
 * Produces plain text only; no chat markup and no network calls.
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
 function coords(row){
  const server=safeText(row.destination_server),x=safeText(row.destination_x),y=safeText(row.destination_y);
  if(!/^\d+$/.test(server)||!/^\d+$/.test(x)||!/^\d+$/.test(y))return '';
  return '[S:'+server+' X:'+x+' Y:'+y+']';
 }
 function attackDirection(value){
  const key=safeText(value).toLowerCase();
  return key==='outgoing'?'Our attack':key==='incoming'?'Attack on D3AD':key==='unknown'?'Unclassified':key;
 }
 function attacks(rows){
  if(!Array.isArray(rows)||!rows.length)return '';
  const lines=rows.map(row=>{
   const date=safeText(row.timestamp)||'Unknown time';
   const who=nameWithGuild(row.attacker,row.attacker_guild);
   const target=nameWithGuild(row.attacked,row.attacked_guild);
   const pos=coords(row);
   const direction=attackDirection(row.attack_direction);
   const outcome=safeText(row.outcome);
   return [date,who+' → '+target+(pos?' '+pos:''),direction,outcome].filter(Boolean).join(' | ');
  });
  return ['Attacks — '+rows.length+' filtered record'+(rows.length===1?'':'s'),...lines].join('\n');
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
  return ['Join / Leave — '+rows.length+' filtered record'+(rows.length===1?'':'s'),...lines].join('\n');
 }
 return {attacks,changes};
});
