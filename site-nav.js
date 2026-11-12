/* One consistent navigation across all Z-Route pages.
 * Keep labels/routes here so any future page is added only once.
 */
(function(){
  "use strict";
  const links=[
    ["index.html","World Map"],
    ["recruitment.html","Recruitment"],
    ["activity.html","Player Activity"],
    ["vs.html","VS Analytics"],
    ["donations.html","Donations"],
    ["review.html","Performance Review"],
    ["tools.html","Tools Hub"],
    ["equipment.html","Equipment"]
  ];
  const styles=`
    .zr-site-nav{display:block!important;width:100%;line-height:normal;box-sizing:border-box;margin:0 0 23px;padding:12px 14px;
      border:1px solid #334c66;border-radius:14px;background:#102035;
      color:#e9f1fc;box-shadow:0 4px 20px #0002}
    .zr-site-nav *{box-sizing:border-box}
    .zr-site-nav-inner{display:flex;align-items:center;gap:15px;flex-wrap:wrap}
    .zr-site-brand{font:750 16px/1.2 system-ui,-apple-system,Segoe UI,sans-serif;
      letter-spacing:.08em;white-space:nowrap;text-decoration:none;
      color:#f0f6ff!important;padding:8px 5px}
    .zr-site-links{display:flex;flex-wrap:wrap;align-items:center;gap:6px;
      font:500 13px/1.4 system-ui,-apple-system,Segoe UI,sans-serif}
    .zr-site-links a{display:inline-flex;align-items:center;white-space:nowrap;
      text-decoration:none;color:#bad0e8!important;border:1px solid transparent;
      border-radius:8px;padding:8px 10px;transition:background .15s,color .15s}
    .zr-site-links a:hover,.zr-site-links a:focus-visible{
      background:#203c56;color:#fff!important;border-color:#405c77;outline:none}
    .zr-site-links a[aria-current="page"]{background:#254864;
      border-color:#5493c1;color:#fff!important;font-weight:750}
    @media(max-width:750px){
      .zr-site-nav{padding:9px 10px;margin-bottom:16px}
      .zr-site-nav-inner{display:block}
      .zr-site-brand{display:inline-block;margin-bottom:5px}
      .zr-site-links{flex-wrap:nowrap;overflow-x:auto;gap:3px;
        scrollbar-width:thin;padding:2px 0 7px}
      .zr-site-links a{padding:8px 10px}
    }
    @media(prefers-reduced-motion:reduce){
      .zr-site-links a{transition:none}
    }`;
  function render(){
    const main=document.querySelector("main");
    if(!main||document.querySelector(".zr-site-nav"))return;
    const style=document.createElement("style");
    style.textContent=styles;document.head.appendChild(style);
    const nav=document.createElement("nav");
    nav.className="zr-site-nav";
    nav.setAttribute("aria-label","Main navigation");
    const inner=document.createElement("div");
    inner.className="zr-site-nav-inner";
    const brand=document.createElement("a");
    brand.className="zr-site-brand";
    brand.href="./index.html";
    brand.textContent="Z-ROUTE";
    brand.setAttribute("aria-label","Z-Route home — World Map");
    const linksNode=document.createElement("div");
    linksNode.className="zr-site-links";
    const current=decodeURIComponent(location.pathname.split("/").pop()||"index.html");
    links.forEach(([href,label])=>{
      const a=document.createElement("a");a.href="./"+href;
      a.textContent=label;
      if(current===href || (current==="legacy-map.html" && href==="index.html")){
        a.setAttribute("aria-current","page");
      }
      linksNode.appendChild(a);
    });
    inner.append(brand,linksNode);nav.appendChild(inner);
    main.insertBefore(nav,main.firstChild);
  }
  if(document.readyState==="loading"){
    document.addEventListener("DOMContentLoaded",render,{once:true});
  }else{render()}
})();
