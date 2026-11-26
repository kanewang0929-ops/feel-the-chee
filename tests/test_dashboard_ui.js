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
  return {batchId:id,engineVersion:"joy-kane-quantum-sim-v2",startedAt:"",finishedAt,durationSeconds:null,status:"completed",simulationCount:100,
    independentFirstPredictions:100,allFirstPredictionsDistinct:true,drawsEvaluatedPerSimulation:2749,
    dateRange:{earliest:"2008-09-15",latest:"2026-11-16"},joy:stats,kane:stats};
}

function fixtures() {
  const agent=name=>({observations:2953,modelVersion:"v2.0-quantum-chronological",modelFamily:name==="joy"?"quantum-circuit-born-machine":"split-step-quantum-walk",backend:"classical_statevector",
    parameters:{front:[.1,.2],back:[.3]},stateScope:"locked_prediction_snapshot",dailyTraining:{cyclesPerRun:1000000,updatedAt:"2026-11-25T23:04:36Z",accepted:true},weights:{front:{frequency:1}}});
  const agents={joy:agent("joy"),kane:agent("kane")};
  const trainedBatch={status:"ready",id:"quantum-batch",packageId:"package-1",generatedAt:"2026-11-25T23:20:00Z",archive:{lastDate:"2026-11-25"},cycleCount:100,completedCycles:100,selectedCycle:100,selectionPolicy:"fixed_final_cycle",agents};
  return {
    feed:{schemaVersion:1,updatedAt:new Date().toISOString(),batches:[batch("old","2026-11-24T22:32:00Z"),batch("new","2026-11-25T22:32:00Z")]},
    state:{agents,modelVersion:"v2.0-quantum-chronological",generatedAt:"2026-11-25T23:30:00Z"},
    dashboard:{modelVersion:"v2.0-quantum-chronological",runtimeVersion:"v2.0-quantum-chronological",summary:{scope:"live_predictions_only"},
      predictionGate:{status:"prediction_locked",reason:"Previous result scored and complete batch verified",lastScoredIssue:"26135"},trainedBatch,
      nextForecast:{targetIssue:"26136",targetDate:"2026-11-28",historyThroughDate:"2026-11-25"},livePredictionLock:{issue:"26136",date:"2026-11-28",lockedAt:"2026-11-25T23:30:00Z"},
      dataCoverage:{latestDate:"2026-11-25"},method:{training:{kind:"batch_only"}}},
    report:{evaluationVersion:"chronological-holdout-v1",archive:{validDrawCount:2949},split:{counts:{finalTestDraws:551},finalTest:{lastDate:"2026-11-16"}},
      randomBaseline:{theoreticalExpectedTotalHitsPerTicket:1.047619},
      finalTestComparisons:{joy:{finalTest:{averageTotalHits:1.019964},differenceVsRandomMean:-.026922,empiricalOneSidedPValue:.75},kane:{finalTest:{averageTotalHits:1.029038}}}}
  };
}

async function page(data, scripts = ["simulation-dashboard.js", "model-operations.js"], hash = "") {
  const ids = [...fs.readFileSync(path.join(root,"simulation.html"),"utf8").matchAll(/\bid="([^"]+)"/g)].map(match=>match[1]);
  const nodes = Object.fromEntries(ids.map(id=>[id,element()]));
  for (const kind of ["live","batch","verified"]) nodes[kind+"ArchiveDate"].dataset.state="loading";
  const buttons = ["evaluation","training","deployment"].map(name=>nodes["tab-"+name]);
  buttons.forEach((button,index)=>button.attributes["data-ops-tab"]=["evaluation","training","deployment"][index]);
  const listeners = {}, requests=[];
  const location = {hash,reload(){this.reloaded=true;}};
  const document = {
    getElementById:id=>nodes[id],querySelectorAll:()=>buttons,
    addEventListener(name,handler){listeners[name]=handler;},
    dispatchEvent(event){if(listeners[event.type])listeners[event.type](event);}
  };
  const context = vm.createContext({document,location,history:{replaceState(_state,_title,value){location.hash=value;}},
    window:{addEventListener(name,handler){listeners[name]=handler;}},console,Intl,Date,Event,AbortController,setTimeout,clearTimeout,
    fetch:async url=>{
      requests.push(url);
      const key=url.includes("simulation-dashboard-history")?"feed":url.includes("model-state")?"state":url.includes("joy-kane-dashboard")?"dashboard":"report";
      const value=data[key];
      if(value instanceof Error)throw value;
      if(typeof value==="number")return {ok:false,status:value};
      return {ok:true,json:async()=>value};
    }});
  for(const script of scripts)vm.runInContext(fs.readFileSync(path.join(root,"assets",script),"utf8"),context,{filename:script});
  for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve));
  return {nodes,buttons,location,listeners,requests};
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

test("quantum model telemetry reports actual families and package data while legacy holdout stays labeled",async()=>{
  const {nodes,requests}=await page(fixtures());
  assert.match(nodes.holdoutMetrics.innerHTML,/1\.019964/);
  assert.match(nodes.holdoutMeta.textContent,/LEGACY MODELS ONLY.*551 final-test draws.*2026-11-16.*does not evaluate the quantum/);
  assert.equal(nodes.trainMode.textContent,"100 / 100");
  assert.match(nodes.trainLastRun.textContent,/07:20 Beijing/);
  assert.match(nodes.joyTrainingCard.innerHTML,/Quantum circuit Born machine/);
  assert.match(nodes.kaneTrainingCard.innerHTML,/Split-step quantum walk/);
  assert.match(nodes.joyTrainingCard.innerHTML,/Classical statevector simulation/);
  for(const id of ["joyTrainingCard","kaneTrainingCard"]){
    assert.doesNotMatch(nodes[id].innerHTML,/optimizer|Accepted trials|signal weights|Exploration setting|1,000,000|07:04/);
  }
  assert.equal(requests.some(url=>url.includes("registry")),false);
  assert.equal(nodes.gateStatus.textContent,"Next prediction locked");
  assert.equal(nodes.lastScoredIssue.textContent,"26135");
});

test("a missing eligible batch does not reuse an old optimizer timestamp",async()=>{
  const data=fixtures();data.dashboard.trainedBatch={status:"missing",reason:"No package"};
  const {nodes}=await page(data);
  assert.equal(nodes.trainLastRun.textContent,"—");
  assert.equal(nodes.trainMode.textContent,"WAITING");
  assert.equal(nodes.candidateStatus.textContent,"MISSING");
});

test("freshness compares the sealed cutoff and batch with the verified archive",async()=>{
  const {nodes}=await page(fixtures());
  assert.equal(nodes.liveArchiveDate.textContent,"2026-11-25");
  assert.equal(nodes.batchArchiveDate.textContent,"2026-11-16");
  assert.equal(nodes.verifiedArchiveDate.textContent,"2026-11-25");
  assert.match(nodes.archiveFreshness.textContent,/Newer verified draws/);
  assert.equal(nodes.archiveFreshness.classList.contains("attention"),true);
});

test("missing legacy report and failed model publication remain distinct",async()=>{
  const data=fixtures();data.report=404;data.state=500;
  const {nodes}=await page(data);
  assert.equal(nodes.holdoutMeta.textContent,"Legacy report not published");
  assert.equal(nodes.candidateStatus.textContent,"UNKNOWN");
  assert.equal(nodes.gateStatus.textContent,"UNAVAILABLE");
});

test("ready quantum batch never relabels an unresolved legacy ticket",async()=>{
  const data=fixtures();
  data.dashboard.modelVersion="legacy-locked-prediction";
  data.dashboard.predictionGate.status="awaiting_result";
  data.state.agents={joy:{modelFamily:"legacy-adaptive-hit-model",modelVersion:"joy-adaptive-hit-model-v1",backend:"legacy_classical",observations:null},kane:{modelFamily:"legacy-adaptive-hit-model",modelVersion:"kane-adaptive-hit-model-v1",backend:"legacy_classical",observations:null}};
  const {nodes}=await page(data);
  assert.equal(nodes.deployVersion.textContent,"legacy-locked-prediction");
  assert.equal(nodes.runtimeVersion.textContent,"v2.0-quantum-chronological");
  assert.match(nodes.joyTrainingCard.innerHTML,/Legacy adaptive model/);
  assert.doesNotMatch(nodes.joyTrainingCard.innerHTML,/Born machine|Split-step/);
  assert.match(nodes.batchPackageSummary.innerHTML,/Born machine.*Split-step/);
  assert.equal(nodes.gateStatus.textContent,"Awaiting actual draw");
});

test("pending publication has no active model or lock despite stale lock fields",async()=>{
  const data=fixtures();data.dashboard.predictionGate.status="awaiting_batch";
  const {nodes}=await page(data);
  assert.equal(nodes.deployIssue.textContent,"—");
  assert.equal(nodes.deployVersion.textContent,"No current ticket");
  assert.match(nodes.joyTrainingCard.innerHTML,/No current sealed prediction/);
  assert.equal(nodes.gateStatus.textContent,"Awaiting 100-cycle batch");
});

test("legacy batch scores remain labeled in history but are excluded from quantum charts",async()=>{
  const data=fixtures();data.feed.batches=[{...batch("legacy-only","2026-11-25T22:32:00Z"),engineVersion:"joy-kane-sim-v1"}];
  const {nodes}=await page(data);
  assert.match(nodes.batchStatus.textContent,/LEGACY/);
  assert.match(nodes.batchRows.innerHTML,/Legacy adaptive/);
  assert.match(nodes.historyChart.innerHTML,/Quantum v2 scores will appear/);
  assert.doesNotMatch(nodes.historyChart.innerHTML,/<svg/);
  assert.match(nodes.agentScores.innerHTML,/Quantum v2 results have not been published/);
});

test("mixed engine history plots only quantum batches while retaining both in the table",async()=>{
  const data=fixtures();
  data.feed.batches=[{...batch("legacy-score","2026-11-25T22:32:00Z"),engineVersion:"joy-kane-sim-v1"},batch("quantum-score","2026-11-26T22:32:00Z")];
  const {nodes}=await page(data);
  assert.match(nodes.historyChart.innerHTML,/batch quantum-score/);
  assert.doesNotMatch(nodes.historyChart.innerHTML,/batch legacy-score/);
  assert.match(nodes.batchRows.innerHTML,/legacy-score.*Legacy adaptive/);
  assert.match(nodes.batchRows.innerHTML,/quantum-score.*Quantum v2/);
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
