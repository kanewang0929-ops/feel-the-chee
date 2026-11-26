"use strict";

// Exercise the shipped scripts against their public data contracts without a browser dependency.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const root = path.resolve(__dirname, "..");

function element(attributes = {}) {
  const classes = new Set();
  return {
    textContent: "", innerHTML: "", dataset: {}, hidden: false, attributes, listeners: {},
    classList: {add: value => classes.add(value), contains: value => classes.has(value), toggle(value, on) {if (on) classes.add(value); else classes.delete(value);}},
    setAttribute(key, value) {this.attributes[key] = value;},
    getAttribute(key) {return this.attributes[key];},
    addEventListener(name, handler) {this.listeners[name] = handler;},
    focus() {this.focused = true;}
  };
}

function batch(id, finishedAt) {
  const stats = {averageBestTotalHits:{mean:1.08,min:1.01,max:1.13},averageBestFrontHits:{mean:.75},averageBestBackHits:{mean:.33}};
  return {batchId:id,startedAt:"",finishedAt,durationSeconds:null,status:"completed",simulationCount:100,
    independentFirstPredictions:100,allFirstPredictionsDistinct:true,drawsEvaluatedPerSimulation:2749,
    dateRange:{earliest:"2008-09-15",latest:"2026-11-16"},joy:stats,kane:stats};
}

function fixtures() {
  const agent = {observations:2753,duel:{wins:950,losses:906,ties:897},modelVersion:"adaptive-v1",
    dailyTraining:{cyclesPerRun:1000000,updatedAt:"2026-11-25T23:04:36Z",accepted:true},weights:{front:{frequency:1}}};
  return {
    feed:{schemaVersion:1,updatedAt:new Date().toISOString(),batches:[batch("old","2026-11-24T22:32:00Z"),batch("new","2026-11-25T22:32:00Z")]},
    state:{agents:{joy:agent,kane:agent},modelVersion:"v1.0",generatedAt:"2026-11-25T23:30:00Z",livePredictionLock:{issue:"26136",date:"2026-11-28"}},
    dashboard:{summary:{dateRange:{latest:"2026-11-25"}},method:{dailyTraining:{ranToday:true}}},
    registry:{schemaVersion:1,promotionEnabled:false,experiments:[],batches:[{id:"new-1",archiveThrough:"2026-11-16"}]},
    report:{evaluationVersion:"chronological-holdout-v1",archive:{validDrawCount:2949},split:{counts:{finalTestDraws:551},finalTest:{lastDate:"2026-11-16"}},
      randomBaseline:{theoreticalExpectedTotalHitsPerTicket:1.047619},
      finalTestComparisons:{joy:{finalTest:{averageTotalHits:1.019964},differenceVsRandomMean:-.026922,empiricalOneSidedPValue:.75},kane:{finalTest:{averageTotalHits:1.029038}}}}
  };
}

async function page(data, scripts = ["simulation-dashboard.js", "model-operations.js"], hash = "") {
  const ids = [...fs.readFileSync(path.join(root,"simulation.html"),"utf8").matchAll(/\bid="([^"]+)"/g)].map(match=>match[1]);
  const nodes = Object.fromEntries(ids.map(id=>[id,element()]));
  for (const kind of ["live","batch","research"]) nodes[kind+"ArchiveDate"].dataset.state="loading";
  const buttons = ["evaluation","training","deployment"].map(name=>nodes["tab-"+name]);
  buttons.forEach((button,index)=>button.attributes["data-ops-tab"]=["evaluation","training","deployment"][index]);
  const listeners = {};
  const location = {hash,reload(){this.reloaded=true;}};
  const document = {
    getElementById:id=>nodes[id],querySelectorAll:()=>buttons,
    addEventListener(name,handler){listeners[name]=handler;},
    dispatchEvent(event){if(listeners[event.type])listeners[event.type](event);}
  };
  const context = vm.createContext({document,location,history:{replaceState(_state,_title,value){location.hash=value;}},
    window:{addEventListener(name,handler){listeners[name]=handler;}},console,Intl,Date,Event,AbortController,setTimeout,clearTimeout,
    fetch:async url=>{
      const key=url.includes("simulation-dashboard-history")?"feed":url.includes("model-state")?"state":url.includes("joy-kane-dashboard")?"dashboard":url.includes("registry")?"registry":"report";
      const value=data[key];
      if(value instanceof Error)throw value;
      if(typeof value==="number")return {ok:false,status:value};
      return {ok:true,json:async()=>value};
    }});
  for(const script of scripts)vm.runInContext(fs.readFileSync(path.join(root,"assets",script),"utf8"),context,{filename:script});
  for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve));
  return {nodes,buttons,location,listeners};
}

test("old batches show unknown runtime, dated publication fallback and newest batch first",async()=>{
  const {nodes}=await page(fixtures());
  assert.equal(nodes.runtime.textContent,"—");
  assert.match(nodes.runtimeNote.textContent,/not recorded/);
  assert.match(nodes.batchTime.textContent,/Published .*26 Nov 2026.*Beijing.*Batch new/);
  assert.ok(nodes.batchRows.innerHTML.indexOf("new")<nodes.batchRows.innerHTML.indexOf("old"));
  assert.match(nodes.batchRows.innerHTML,/Published; start not recorded/);
  assert.match(nodes.historyChart.innerHTML,/26 Nov/);
  assert.doesNotMatch(nodes.batchRows.innerHTML,/KST|0m 00s/);
});

test("recorded runtime rounds correctly and retains hours",async()=>{
  const data=fixtures();data.feed.batches=[{...batch("timed",new Date().toISOString()),startedAt:"2026-11-25T21:00:00Z",durationSeconds:7199.8}];
  const {nodes}=await page(data);
  assert.equal(nodes.runtime.textContent,"2h 0m 00s");
  assert.match(nodes.batchTime.textContent,/Started/);
});

test("feed failures stay unavailable instead of becoming a connected empty feed",async()=>{
  const data=fixtures();data.feed=new Error("Network unavailable");
  const {nodes}=await page(data);
  assert.equal(nodes.batchStatus.textContent,"UNAVAILABLE");
  assert.equal(nodes.scheduleStatus.textContent,"FEED UNAVAILABLE");
  assert.match(nodes.feedStatus.textContent,/Feed unavailable/);
  assert.doesNotMatch(nodes.feedStatus.textContent,/connected/);
  assert.equal(nodes.runCount.textContent,"—");
  assert.match(nodes.archiveFreshness.textContent,/could not be loaded/);
});

test("invalid feed is reported as unavailable",async()=>{
  const data=fixtures();data.feed={batches:[]};
  const {nodes}=await page(data);
  assert.equal(nodes.batchStatus.textContent,"UNAVAILABLE");
});

test("missing agent scores do not fabricate deltas or break valid batch metadata",async()=>{
  const data=fixtures();data.feed.batches=[batch("missing",new Date().toISOString())];
  data.feed.batches[0].joy={averageBestTotalHits:{mean:null}};
  const {nodes}=await page(data);
  assert.equal(nodes.batchStatus.textContent,"COMPLETED");
  assert.match(nodes.agentScores.innerHTML,/Score was not recorded/);
  assert.doesNotMatch(nodes.agentScores.innerHTML,/-1\.0476/);
});

test("holdout uses finalTest fields and optimizer status uses dashboard metadata",async()=>{
  const {nodes}=await page(fixtures());
  assert.match(nodes.holdoutMetrics.innerHTML,/1\.019964/);
  assert.match(nodes.holdoutMetrics.innerHTML,/1\.029038/);
  assert.match(nodes.holdoutMeta.textContent,/551 final-test draws.*2026-11-16/);
  assert.equal(nodes.trainRunState.textContent,"Optimizer ran in the latest live workflow");
  assert.match(nodes.trainLastRun.textContent,/07:04 Beijing/);
});

test("freshness comparison does not hide older replay and research archives",async()=>{
  const {nodes}=await page(fixtures());
  assert.equal(nodes.liveArchiveDate.textContent,"2026-11-25");
  assert.equal(nodes.batchArchiveDate.textContent,"2026-11-16");
  assert.equal(nodes.researchArchiveDate.textContent,"2026-11-16");
  assert.match(nodes.archiveFreshness.textContent,/newer draws/);
  assert.equal(nodes.archiveFreshness.classList.contains("attention"),true);
});

test("a missing report is different from a failed request; failed registry leaves candidates unknown",async()=>{
  const data=fixtures();data.report=404;data.registry=500;
  const {nodes}=await page(data);
  assert.equal(nodes.holdoutMeta.textContent,"Report not published");
  assert.equal(nodes.candidateStatus.textContent,"UNKNOWN");
  assert.equal(nodes.researchStatus.textContent,"UNAVAILABLE");
});

test("deep-linked tabs, arrow keys and refresh preserve selected section",async()=>{
  const {nodes,buttons,location}=await page(fixtures(),["simulation-dashboard.js","model-operations.js"],"#training");
  assert.equal(nodes["ops-training"].hidden,false);
  assert.equal(buttons[1].attributes["aria-selected"],"true");
  assert.equal(buttons[0].tabIndex,-1);
  let prevented=false;
  buttons[1].listeners.keydown({key:"ArrowRight",preventDefault(){prevented=true;}});
  assert.equal(prevented,true);
  assert.equal(location.hash,"#deployment");
  assert.equal(buttons[2].focused,true);
  assert.equal(nodes["ops-training"].hidden,true);
  assert.equal(nodes["ops-deployment"].hidden,false);
  nodes.refreshData.listeners.click();
  assert.equal(location.reloaded,true);
  assert.equal(location.hash,"#deployment");
});
