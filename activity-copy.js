/* Z-Route Player Activity copy text.
 * Date-grouped chat summaries with literal <br> separators; no network calls.
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
 function dateParts(value){
  // Accepted event times: 2026.11.10 14:03:44, 2026-11-10T14:03:44, etc.
  const match=safeText(value).match(/^(\d{4})[-./](\d{2})[-./](\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?/);
  if(!match)return {day:'Unknown date',sort:''};
  const day=match[1]+'-'+match[2]+'-'+match[3];
  return {day,sort:day+'T'+(match[4]||'00')+':'+(match[5]||'00')+':'+(match[6]||'00')};
 }
 function chronological(rows){
  // Newest first, stable when event timestamps are identical. Times are not copied.
  return [...rows].sort((a,b)=>dateParts(b.timestamp).sort.localeCompare(dateParts(a.timestamp).sort));
 }
 function directionLabel(value){
  const direction=safeText(value).toLowerCase();
  if(direction==='incoming'||direction==='in')return 'IN';
  if(direction==='outgoing'||direction==='out')return 'OUT';
  return 'UNK'; // Do not guess unknown attack direction.
 }
 function attacks(rows){
  if(!Array.isArray(rows)||!rows.length)return '';
  const days=new Map();
  for(const row of chronological(rows)){
   const day=dateParts(row.timestamp).day;
   if(!days.has(day))days.set(day,new Map());
   const groups=days.get(day);
   const attacker=safeText(row.attacker)||'?';
   const victim=safeText(row.attacked)||'?';
   const direction=directionLabel(row.attack_direction);
   // Repeat counts are per-day, per-direction, per attacker/victim pair.
   const key=JSON.stringify([direction,attacker.toLowerCase(),victim.toLowerCase()]);
   if(groups.has(key))groups.get(key).count++;
   else groups.set(key,{attacker,victim,direction,count:1});
  }
  const lines=[];
  for(const [day,groups] of days){
   lines.push(day);
   for(const {attacker,victim,direction,count} of groups.values())
    lines.push(direction+' '+attacker+'->'+victim+(count>1?' x'+count:''));
  }
  return lines.join('<br>');
 }
 function changes(rows){
  if(!Array.isArray(rows)||!rows.length)return '';
  const days=new Map();
  for(const row of chronological(rows)){
   const day=dateParts(row.timestamp).day;
   if(!days.has(day))days.set(day,[]);
   const player=nameWithGuild(row.player,row.guild);
   const event=safeText(row.event)||'event';
   const actor=safeText(row.actor);
   days.get(day).push(player+' — '+event+(actor?' (by '+actor+')':''));
  }
  const lines=[];
  for(const [day,events] of days)lines.push(day,...events);
  return lines.join('<br>');
 }
 return {attacks,changes};
});
