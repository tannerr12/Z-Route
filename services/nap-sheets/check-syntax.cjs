const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
for(const name of ['Code.gs','Normalizer.js'])new vm.Script(fs.readFileSync(path.join(__dirname,name),'utf8'),{filename:name});
for(const match of fs.readFileSync(path.join(__dirname,'Index.html'),'utf8').matchAll(/<script>([\s\S]*?)<\/script>/g))new vm.Script(match[1]);
console.log('NAP Apps Script and private-view syntax passed');
