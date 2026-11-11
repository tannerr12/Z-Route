/* Chat-ready player location sharing for Z-Route. */
(function(root,factory){
 'use strict';
 const api=factory();
 if(typeof module==='object'&&module.exports)module.exports=api;
 if(root)root.ZRoutePlayerShare=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(){
 'use strict';
 function format(player){
  if(!player)return '';
  const name=String(player.name??'').trim();
  const server=String(player.server??'').trim();
  if(player.x==null||player.y==null||String(player.x).trim()===''||String(player.y).trim()==='')return '';
  const x=Number(player.x),y=Number(player.y);
  if(!name||!/^[0-9]+$/.test(server)||!Number.isSafeInteger(x)||!Number.isSafeInteger(y)||x<0||y<0)return '';
  const guild=String(player.guild??'').trim().replace(/^\[+|\]+$/g,'');
  const tag=guild&&!/^(unknown|none|no guild|n\/a|-)$/i.test(guild)?'['+guild+'] ':'';
  return tag+name+' [S:'+server+' X:'+x+' Y:'+y+']';
 }
 return {format};
});
