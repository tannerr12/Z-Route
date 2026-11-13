/* The NPC default username format is Commander + exactly 7 letters/digits.
 * Only filter a complete match; legitimate Commander-prefixed names remain.
 */
(function(root){
'use strict';
function isGeneratedCommander(value){
 return typeof value==='string'&&/^Commander[A-Za-z0-9]{7}$/i.test(value.trim());
}
const api={isGeneratedCommander};
if(typeof module==='object'&&module.exports)module.exports=api;
else root.ZRouteAttackFilters=api;
})(typeof window==='undefined'?globalThis:window);
