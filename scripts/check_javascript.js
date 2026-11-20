/* Dependency-free syntax checks for the static dashboard and its inline scripts. */
'use strict';
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const root=path.resolve(__dirname,'..');
let checked=0;
for(const directory of [root,__dirname]){
 for(const entry of fs.readdirSync(directory,{withFileTypes:true})){
  if(!entry.isFile())continue;
  const file=path.join(directory,entry.name),source=fs.readFileSync(file,'utf8');
  if(entry.name.endsWith('.js')){
   new vm.Script(source,{filename:file});checked++;
  }else if(entry.name.endsWith('.html')){
   if(!source.trim())throw new Error('Empty or incomplete standalone HTML page: '+file);
   let index=0;
   for(const match of source.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)){
    if(/\bsrc\s*=|\btype\s*=\s*["']application\//i.test(match[1]))continue;
    new vm.Script(match[2],{filename:file+':inline-'+ ++index});checked++;
   }
  }
 }
}
console.log('Syntax checked '+checked+' JavaScript files and inline scripts.');
