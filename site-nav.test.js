'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'site-nav.js'),'utf8');

function render(pathname){
  const make=tag=>({
    tag, children:[], attributes:{},
    append(...nodes){ this.children.push(...nodes); },
    appendChild(node){ this.append(node); },
    insertBefore(node){ this.children.unshift(node); },
    setAttribute(key,value){ this.attributes[key]=value; }
  });
  const main=make('main'), head=make('head');
  const document={
    readyState:'complete', head, createElement:make,
    querySelector:selector=>selector==='main'?main:main.children.find(n=>n.className==='zr-site-nav')
  };
  const context=vm.createContext({document,location:{pathname}});
  vm.runInContext(source,context);
  vm.runInContext(source,context); // A double include must not duplicate the navbar.
  assert.equal(main.children.length,1);
  const nav=main.children[0];
  assert.equal(nav.attributes['aria-label'],'Main navigation');
  return nav.children[0].children[1].children;
}

test('World Map navigation links to both history pages exactly once',()=>{
  const links=render('/Z-Route/index.html');
  for(const [route,label] of [['base-upgrades.html','Base Upgrades'],['alliance-history.html','Alliance History']]){
    const match=links.filter(a=>a.href==='./'+route);
    assert.equal(match.length,1);
    assert.equal(match[0].textContent,label);
    const html=fs.readFileSync(path.join(__dirname,route),'utf8');
    assert.match(html,/<main\b/i);
    assert.match(html,/<script\b[^>]*\bsrc=["'](?:\.\/)?site-nav\.js["']/i);
  }
});

test('both history URLs mark only their own link current, including project subpaths',()=>{
  for(const route of ['base-upgrades.html','alliance-history.html']){
    const current=render('/Z-Route/'+route).filter(a=>a.attributes['aria-current']==='page');
    assert.deepEqual(current.map(a=>a.href),['./'+route]);
  }
});

test('Season 1 guide is linked from the World Map and marks itself active',()=>{
  const links=render('/Z-Route/index.html');
  assert.equal(links.filter(a=>a.href==='./season-1.html'&&a.textContent==='Season 1 Guide').length,1);
  assert.deepEqual(render('/Z-Route/season-1.html').filter(a=>a.attributes['aria-current']==='page').map(a=>a.href),['./season-1.html']);
});
