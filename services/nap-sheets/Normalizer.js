/* No sheet contents or access credentials belong in this source file. */
var ZRouteNAP=(function(){
'use strict';
var text=v=>String(v==null?'':v).trim(),key=v=>text(v).normalize('NFC').toLowerCase();
function date(value){var raw=text(value),m=raw.match(/^(\d{1,2})\/(\d{1,2})(?:\/(\d{2}|\d{4}))?$/);if(!m||!m[3])return {raw,iso:null,warning:'Date needs an explicit year or review'};var year=Number(m[3]);if(year<100)year+=2000;var month=Number(m[1]),day=Number(m[2]),d=new Date(Date.UTC(year,month-1,day));if(d.getUTCFullYear()!==year||d.getUTCMonth()!==month-1||d.getUTCDate()!==day)return {raw,iso:null,warning:'Invalid date'};return {raw,iso:d.toISOString().slice(0,10),warning:''};}
// Infer only within the user-confirmed chronological sequence, anchored by explicit years.
function orderedDates(values,startRow){
 var next=null,nextDates=new Array(values.length),anchor=null,blocked=false;
 for(var n=values.length-1;n>=0;n--){nextDates[n]=next;var explicit=date(values[n]);if(explicit.iso)next=explicit.iso;}
 return values.map(function(value,index){
  var out=date(value),m=text(value).match(/^(\d{1,2})\/(\d{1,2})$/);out.inferredYear=false;out.yearSourceRow=null;
  if(out.iso){
   if(anchor&&out.iso<anchor.iso){out.warning='Date conflicts with chronological row order';blocked=true;}
   else {anchor={iso:out.iso,sourceRow:(startRow||1)+index};blocked=false;}
   return out;
  }
  if(!m||!anchor||blocked)return out;
  var year=Number(anchor.iso.slice(0,4)),month=Number(m[1]),day=Number(m[2]),previousMonth=Number(anchor.iso.slice(5,7));
  if(previousMonth===12&&month===1)year++;
  var candidate=date(month+'/'+day+'/'+year);
  if(!candidate.iso){out.warning=candidate.warning;return out;}
  if(candidate.iso<anchor.iso||nextDates[index]&&candidate.iso>nextDates[index]){out.warning='Missing year conflicts with chronological row order';blocked=true;return out;}
  out.iso=candidate.iso;out.warning='';out.inferredYear=true;out.yearSourceRow=anchor.sourceRow;
  anchor={iso:out.iso,sourceRow:anchor.sourceRow};return out;
 });
}
function parse(nap,contacts,backgrounds){
 var header=nap.findIndex(r=>r.some(c=>key(c)==='date')&&r.some(c=>['agressor','aggressor'].includes(key(c)))&&r.some(c=>key(c)==='victim'));
 if(header<0)throw Error('NAP headings changed; expected Date, Agressor and Victim. No records guessed.');
 var h=nap[header].map(key),di=h.indexOf('date'),ai=h.findIndex(c=>['agressor','aggressor'].includes(c)),vi=h.indexOf('victim'),ti=h.indexOf('attacked');
 if(ai<1||vi<1||ti<0||h[ai-1]!=='alliance'||h[vi-1]!=='alliance')throw Error('NAP alliance columns need review.');
 var records=[],summaries=[],seen=new Map(),warnings=[],dates=orderedDates(nap.slice(header+1).map(r=>r[di]),header+2);
 for(var i=header+1;i<nap.length;i++){
  var raw=nap[i].map(text);if(!raw.some(Boolean))continue;
  var when=dates[i-header-1],r={sourceRow:i+1,sourceRows:[i+1],date:when.raw,isoDate:when.iso,inferredYear:when.inferredYear,yearSourceRow:when.yearSourceRow,aggressorAlliance:raw[ai-1]||'',aggressor:raw[ai]||'',target:raw[ti]||'',victimAlliance:raw[vi-1]||'',victim:raw[vi]||'',columnG:raw[6]||'',authorizationRaw:raw[7]||'',coordinatorRaw:raw[8]||'',notes:raw.slice(9).filter(Boolean).join(' · '),warnings:[],raw:raw};
  if(when.warning)r.warnings.push(when.warning);
  if(!r.aggressor||r.aggressor==='?')r.warnings.push('Aggressor unknown');
  if(!r.victim||r.victim==='?')r.warnings.push('Victim unknown');
  var colors=(backgrounds&&backgrounds[i])||[];
  r.repeatFlag=colors.some(c=>key(c)==='#ff0000');r.leadershipFlag=colors.some(c=>key(c)==='#ffff00');
  if(key(r.victim)==='total'){summaries.push(r);continue;}
  var signature=JSON.stringify([when.iso,raw]);if(seen.has(signature)){var old=seen.get(signature);old.sourceRows.push(i+1);if(!old.warnings.includes('Identical rows: verify whether separate events'))old.warnings.push('Identical rows: verify whether separate events');old.repeatFlag=old.repeatFlag||r.repeatFlag;old.leadershipFlag=old.leadershipFlag||r.leadershipFlag;continue;}seen.set(signature,r);records.push(r);
 }
 var ch=contacts.findIndex(r=>r.some(c=>['allaince','alliance'].includes(key(c)))&&r.some(c=>key(c)==='contact'));
 if(ch<0)throw Error('NAPCont headings changed; contact directory not guessed.');
 var headings=contacts[ch].map(key),field=name=>headings.indexOf(name),guild=headings.findIndex(c=>['allaince','alliance'].includes(c));
 var directory=contacts.slice(ch+1).map((row,n)=>{var r=row.map(text);return {sourceRow:ch+n+2,alliance:r[guild]||'',language:r[field('language')]||'',contact:r[field('contact')]||'',position:r[field('position')]||'',discord:r[field('discord')]||'',notes:r.slice(5).filter(Boolean).join(' · ')};}).filter(r=>r.alliance);
 if(records.some(r=>r.warnings.length))warnings.push('Some incidents need date, identity or duplicate review.');
 warnings.push('Column G and authorization text are preserved as entered; they are not automatic penalties or case outcomes.');
 return {records,directory,summaries,warnings};
}
return {parse,date,key,orderedDates};
})();
if(typeof module==='object'&&module.exports)module.exports=ZRouteNAP;
