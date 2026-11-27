(function () {
  "use strict";
  const model = window.ZRouteBaseUpgrades;
  const byId = id => document.getElementById(id);
  const server = byId("server"), alliance = byId("alliance"), group = byId("group");
  const coverage = byId("coverage"), summary = byId("summary"), results = byId("results"), more = byId("more");
  const initial = new URL(window.location.href);
  const date = new Intl.DateTimeFormat("en-GB", {dateStyle:"medium", timeStyle:"medium", timeZone:"UTC"});
  const pageSize = 100, groupSize = 40;
  let registry, active = null, limit = pageSize, request = null, requestedAlliance = initial.searchParams.get("alliance");
  group.checked = initial.searchParams.get("group") === "player";

  function add(parent, tag, value, css) {
    const node = document.createElement(tag);
    if (value !== undefined) node.textContent = value;
    if (css) node.className = css;
    parent.append(node);
    return node;
  }
  function addTime(parent, timestamp, prefix) {
    if (prefix) parent.append(document.createTextNode(prefix));
    const node = add(parent, "time", date.format(timestamp));
    node.dateTime = new Date(timestamp).toISOString();
    node.title = node.dateTime;
  }

  function table(events, showPlayer) {
    const scroller = document.createElement("div");
    scroller.className = "scroller";
    scroller.tabIndex = 0;
    scroller.setAttribute("role","region");
    scroller.setAttribute("aria-label","Base upgrade table");
    const tableElement = add(scroller,"table");
    const headings = add(add(tableElement,"thead"),"tr");
    for (const label of ["First observed (UTC)", ...(showPlayer ? ["Player"] : []), "Base level", "Alliance"]) {
      add(headings,"th",label).scope = "col";
    }
    const rows = add(tableElement,"tbody");
    for (const event of events) {
      const row = add(rows,"tr");
      const first = add(row,"td");
      addTime(first,event.observedTime);
      addTime(add(first,"span",undefined,"detail"),event.previousTime,"After ");
      if (showPlayer) add(row,"td",event.name);
      const levels = add(row,"td",`${event.before} → ${event.after}`,"delta");
      if (event.after - event.before > 1) add(levels,"span","Intermediate levels not observed","detail");
      const membership = add(row,"td",event.alliance || "Unknown at upgrade",event.alliance ? "":"unknown");
      if (!event.alliance) add(membership,"span",`${event.priorTag || "No tag"} → ${event.observedTag || "No tag"} in observations`,"detail");
    }
    return scroller;
  }

  function saveFilters() {
    const url = new URL(window.location.href);
    url.searchParams.set("server", server.value);
    if (alliance.value) url.searchParams.set("alliance", alliance.value);
    else url.searchParams.delete("alliance");
    if (group.checked) url.searchParams.set("group", "player");
    else url.searchParams.delete("group");
    history.replaceState(null, "", url);
  }
  function render() {
    if (!active) return;
    saveFilters();
    const events = model.filterEvents(active.events, alliance.value);
    summary.textContent = events.length ? `${events.length.toLocaleString()} observed increase${events.length === 1 ? "" : "s"}. ${group.checked ? "Grouped by player." : "Newest observations first."}` :
      "No observed increases in this view. Incomplete history does not mean no upgrades occurred.";
    results.replaceChildren();
    more.hidden = true;
    if (!events.length) return;
    if (group.checked) {
      const groups = model.groups(events);
      for (const g of groups.slice(0,limit)) {
        const details = add(results,"details",undefined,"group");
        add(details,"summary",`${g.name} · ${g.events.length} observed increase${g.events.length === 1 ? "" : "s"}`);
        details.addEventListener("toggle", () => {
          if (details.open && details.childElementCount === 1) details.append(table(g.events,false));
        });
      }
      more.hidden = groups.length <= limit;
      more.textContent = "Show more players";
    } else {
      results.append(table(events.slice(0,limit), true));
      more.hidden = events.length <= limit;
      more.textContent = "Show more upgrades";
    }
  }
  function reset() { limit = group.checked ? groupSize : pageSize; render(); }

  async function get(path, signal) {
    const response = await fetch("./" + path, {cache:"no-store", signal});
    if (!response.ok) throw Error(`HTTP ${response.status}`);
    return response;
  }
  async function loadServer() {
    if (request) request.abort();
    const controller = new AbortController();
    const id = server.value;
    request = controller;
    active = null;
    coverage.className = "";
    coverage.textContent = `Loading Server ${id} Player History…`;
    alliance.disabled = group.disabled = true;
    alliance.replaceChildren(new Option("All alliances",""));
    summary.textContent = "";
    results.replaceChildren();
    more.hidden = true;
    try {
      const response = await get(registry.servers.get(id).data, controller.signal);
      const csv = await response.text();
      if (request !== controller) return;
      active = model.build(csv,id);
      const {players, playersWithHistory, malformedHistories, skippedObservations, ambiguousTimes} = active;
      coverage.textContent = `Server ${id}: ${playersWithHistory.toLocaleString()} of ${players.toLocaleString()} player records have dated history.` +
        (malformedHistories ? ` Skipped ${malformedHistories.toLocaleString()} malformed history record(s).` : "") +
        (skippedObservations ? ` Skipped ${skippedObservations.toLocaleString()} undated or invalid observation(s).` : "") +
        (ambiguousTimes ? ` Skipped ${ambiguousTimes.toLocaleString()} conflicting observation time(s).` : "");
      alliance.replaceChildren(new Option("All alliances",""),new Option("Alliance attributable","known-only"),
        new Option("Unknown at upgrade","unknown"), ...active.alliances.map(([key,label])=>new Option(label,"tag:"+key)));
      if (requestedAlliance) {
        const saved = [...alliance.options].find(option => option.value === requestedAlliance ||
          option.value === "tag:" + model.allianceKey(requestedAlliance));
        if (saved) alliance.value = saved.value;
      }
      requestedAlliance = null;
      alliance.disabled = group.disabled = false;
      reset();
    } catch (error) {
      if (request !== controller || controller.signal.aborted) return;
      requestedAlliance = null;
      coverage.className = "error";
      coverage.textContent = `Server ${id} Player History unavailable: ${error.message}`;
    }
  }

  server.addEventListener("change",loadServer);
  alliance.addEventListener("change",reset);
  group.addEventListener("change",reset);
  more.addEventListener("click",()=>{
    const previousLimit = limit;
    const scrollAt = window.scrollY;
    limit += group.checked ? groupSize : pageSize;
    render();
    const newlyVisible = group.checked ? results.querySelectorAll("summary")[previousLimit] : results.querySelectorAll("tbody tr")[previousLimit];
    if (newlyVisible && more.hidden) { newlyVisible.tabIndex = -1; newlyVisible.focus({preventScroll:true}); }
    window.scrollTo(0,scrollAt);
  });
  (async function () {
    try {
      registry = model.registry(await (await get("data/servers.json")).json());
      server.replaceChildren(...[...registry.servers.values()].map(e=>new Option(e.label,e.id)));
      const wanted = initial.searchParams.get("server");
      server.value = registry.servers.has(wanted) ? wanted : registry.defaultServer;
      server.disabled = false;
      await loadServer();
    } catch (error) {
      coverage.className = "error";
      coverage.textContent = `Server directory unavailable: ${error.message}`;
    }
  })();
})();
