/* Season 1 client tables: JeffxLabs/ZR:Reference, progression.json IDs 20003–20007, 20009. */
(function () {
  "use strict";
  const labResistance = [0,400,800,1300,1800,2400,3100,3900,4900,5900,7100,8300,9800,11300,13200,15100,18100,21100,25100,29100,34100,39100,45100,51100,57100,63100,71100,80100,89100,98100,108100];
  const labCost = [0,0,5000,15000,44800,89600,125400,163100,195700,234800,281800,338100,405800,486900,584300,701200,771300,848400,933300,1030000,1130000,1240000,1370000,1500000,1650000,1820000,2160000,2510000,2860000,3460000,4320000];
  const refineryOutput = [0,100,200,400,600,900,1300,1800,2400,3200,4200,5200,6300,7400,8600,9900,11200,12600,14100,15700,17400,19100,20900,22700,24600,26500,28500,30500,32600,34700,36900];
  const refineryCost = [0,700,1400,2800,5600,11200,16800,25200,37800,56700,85100,93600,102900,113200,124500,137000,150700,165700,182300,200500,220600,231600,243200,255400,268100,281500,295600,310400,325900,342200,359300];
  const labels = ["Refinery I", "Refinery II", "Refinery III", "Refinery IV", "Weekly Pass refinery"];

  function gate(index, level, refinery, lab) {
    if (index === 4 && level === 0) return "Requires an active Weekly Pass";
    if (index === 0 && level === 0 && lab < 1) return "Requires Virus Lab Lv. 1";
    if (index === 0 && level === 5 && refinery[1] < 5) return "Requires Refinery II Lv. 5 per season guide";
    if (index === 1 && level === 0 && refinery[0] < 5) return "Requires Refinery I Lv. 5";
    if (index === 2 && level === 0 && refinery[1] < 10) return "Requires Refinery II Lv. 10";
    if (index === 3 && level === 0 && refinery[2] < 10) return "Requires Refinery III Lv. 10";
    return "";
  }

  function plan(input) {
    const { lab, protein, target = null, bonus = 0, refinery, rate = null } = input;
    const level = n => Number.isInteger(n) && n >= 0 && n <= 30;
    const amount = n => Number.isSafeInteger(n) && n >= 0 && n <= 1000000000000;
    if (!level(lab) || !amount(protein) || !amount(bonus) || (target !== null && (!amount(target) || target < 1))
      || !Array.isArray(refinery) || refinery.length !== labels.length || !Array.from(refinery).every(level)
      || (rate !== null && (!Number.isFinite(rate) || rate < 0 || rate > 1000000000000))) return null;
    const resistance = n => labResistance[n] + bonus;
    const tableRate = refinery.reduce((sum, lvl) => sum + refineryOutput[lvl], 0);
    const hourly = rate === null ? tableRate : rate;
    let affordable = lab;
    let spend = 0;
    while (affordable < 30 && spend + labCost[affordable + 1] <= protein) {
      spend += labCost[++affordable];
    }
    const steps = [];
    let cumulative = 0;
    if (target === null || target > resistance(lab)) {
      for (let next = lab + 1; next <= 30; next++) {
        cumulative += labCost[next];
        steps.push({ level: next, resistance: resistance(next), cost: labCost[next], cumulative, gain: labResistance[next] - labResistance[next - 1] });
        if (target === null || resistance(next) >= target) break;
      }
    }
    const targetLevel = target === null ? null : target <= resistance(lab) ? lab :
      steps.length && steps[steps.length - 1].resistance >= target ? steps[steps.length - 1].level : null;
    const targetCost = targetLevel === null ? null : targetLevel === lab ? 0 : cumulative;
    const deficit = targetCost === null ? null : Math.max(0, targetCost - protein);
    const hours = shortage => shortage === 0 ? 0 : shortage === null || hourly === 0 ? null : shortage / hourly;
    const options = refinery.map((lvl, index) => lvl === 30 ? { name: labels[index], level: lvl } : {
      name: labels[index], level: lvl, to: lvl + 1,
      gain: refineryOutput[lvl + 1] - refineryOutput[lvl],
      uranium: index === 4 && lvl === 0 ? 0 : refineryCost[lvl + 1],
      gate: gate(index, lvl, refinery, lab)
    });
    const next = lab < 30 ? { level: lab + 1, resistance: resistance(lab + 1), cost: labCost[lab + 1] } : null;
    return { current: resistance(lab), affordable, spend, balance: protein - spend, affordableResistance: resistance(affordable),
      ceiling: resistance(30), targetLevel, targetCost, deficit, eta: hours(deficit), next,
      nextDeficit: next ? Math.max(0, next.cost - protein) : null,
      nextEta: next ? hours(Math.max(0, next.cost - protein)) : null,
      tableRate, hourly, hasOverride: rate !== null, options, steps };
  }

  if (typeof module === "object" && module.exports) module.exports = { plan };
  if (typeof document === "undefined") return;
  const root = document.querySelector("[data-zr-resistance]");
  if (!root) return;
  const result = root.querySelector("[data-rp-results]");
  const refineryList = root.querySelector("[data-rp-refineries]");
  const read = field => {
    const input = root.querySelector('[data-rp="' + field + '"]');
    if (input.validity.badInput) return NaN;
    return input.value.trim() === "" ? null : Number(input.value);
  };
  const formatter = new Intl.NumberFormat("en", { maximumFractionDigits: 2 });
  const fmt = n => formatter.format(n);
  const time = n => n === null ? "no ETA at the current rate" :
    !Number.isFinite(n) ? "ETA unavailable at this production rate" :
    n < 1 ? fmt(Math.ceil(n * 60)) + " min" :
    n > 72 ? fmt(n / 24) + " days" : fmt(n) + " hr";
  function add(to, tag, value) {
    const el = document.createElement(tag);
    el.textContent = value;
    to.appendChild(el);
    return el;
  }

  function update() {
    const lab = read("lab");
    const target = read("target");
    const model = plan({ lab, protein: read("protein") ?? 0, target, bonus: read("bonus") ?? 0,
      refinery: ["r1", "r2", "r3", "r4", "pass"].map(k => read(k) ?? 0), rate: read("rate") });
    result.replaceChildren();
    refineryList.replaceChildren();
    if (!model) {
      add(result, "p", "Enter a Lab level from 0 to 30 and valid whole levels and amounts. The optional hourly rate can have decimals.");
      return;
    }
    add(result, "p", "Current resistance: " + fmt(model.current) + ". With your protein alone: Lab Lv. " + model.affordable +
      " (" + fmt(model.affordableResistance) + " resistance, " + fmt(model.balance) + " protein left).");
    if (lab === 0) add(result, "p", "Repairing the Lab first requires Base Lv. 10 and the relevant season task.");
    add(result, "p", "Production used: " + fmt(model.hourly) + " protein/hr (" + (model.hasOverride ? "your override" : "base client table") + ").");
    if (target !== null) {
      if (model.targetLevel === null) add(result, "p", "The target exceeds the Lab Lv. 30 ceiling at your entered bonus (" + fmt(model.ceiling) + ").");
      else if (model.targetLevel === lab) add(result, "p", "Your current resistance already meets the target.");
      else add(result, "p", "Target: Lab Lv. " + model.targetLevel + ", " + fmt(model.targetCost) + " protein total. " +
        (model.deficit === 0 ? "You have enough protein." :
          fmt(model.deficit) + " more protein needed; " + (model.eta === null ? time(null) + "." : "roughly " + time(model.eta) + " from production alone.")));
    }
    if (model.next) add(result, "p", "Next upgrade: Lab Lv. " + model.next.level + ", " + fmt(model.next.resistance) +
      " resistance for " + fmt(model.next.cost) + " protein. " + (model.nextDeficit === 0 ? "Affordable now." :
        fmt(model.nextDeficit) + " short (" + time(model.nextEta) + ")."));
    else add(result, "p", "Your Lab is at its maximum level.");
    if (target !== null && model.targetLevel !== null && model.steps.length > 1) {
      const route = add(result, "details", "");
      add(route, "summary", "Lab upgrade path (" + model.steps.length + " steps)");
      const list = add(route, "ol", "");
      for (const row of model.steps) add(list, "li", "Lv. " + row.level + ": +" + fmt(row.gain) + " resistance, " +
        fmt(row.cost) + " protein (" + fmt(row.cumulative) + " cumulative)");
    }
    for (const row of model.options) add(refineryList, "li", row.name + (row.to == null ? " is at Lv. 30." :
      " to Lv. " + row.to + ": +" + fmt(row.gain) + " protein/hr for " + fmt(row.uranium) + " Uranium Crystals." + (row.gate ? " " + row.gate + "." : "")));
  }
  root.addEventListener("input", update);
  update();
  root.hidden = false;
})();
