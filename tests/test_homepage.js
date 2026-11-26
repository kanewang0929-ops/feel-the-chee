/* Run with: node --test tests/test_homepage.js */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const root = path.resolve(__dirname, "..");

function appContext(storage) {
  const context = vm.createContext({
    document: { querySelectorAll: () => [], getElementById: () => null },
    window: { addEventListener() {} }, location: { hash: "" }, history: {},
    localStorage: { getItem: key => storage?.[key] ?? null },
    console, Intl, AbortController, setTimeout, clearTimeout
  });
  const source = fs.readFileSync(path.join(root, "assets/app.js"), "utf8")
    .replace(/\nloadDraws\(\);\nloadForecast\(\);/, "");
  vm.runInContext(source, context);
  return context;
}

test("prediction display rejects duplicate, fractional and out-of-range tickets", () => {
  const app = appContext();
  const good = { front: [1, 2, 3, 4, 5], back: [1, 12] };
  assert.equal(app.validTicket(good), true);
  assert.equal(app.validTicket({ ...good, front: [1, 1, 3, 4, 5] }), false);
  assert.equal(app.validTicket({ ...good, back: [1, 12.5] }), false);
  assert.equal(app.validTicket({ ...good, front: [1, 2, 3, 4, 36] }), false);
  assert.equal(app.validTicket(null), false);
});

test("forecast age uses the Beijing date across a UTC midnight boundary", () => {
  const app = appContext();
  const now = new Date("2026-11-25T16:05:00Z");
  assert.equal(app.isPastTarget("2026-11-25", now), true);
  assert.equal(app.isPastTarget("2026-11-26", now), false);
  assert.equal(app.isPastTarget("2026-11-28", now), false);
  assert.equal(app.isPastTarget(null, now), false);
});

test("corrupt browser storage does not replace the published archive with sample data", () => {
  const app = appContext({ cheeDrawEdits: "{broken", cheeDeletedDraws: "null" });
  const base = [{ issue: "26135", date: "2026-11-25", front: "01 08 20 24 33", back: "03 04", status: "已同步" }];
  const rows = app.applyBrowserOverrides(base);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].front, base[0].front);
  assert.equal(rows[0]._sourceIssue, "26135");
});

test("a local issue edit keeps its original source key and is visibly marked", () => {
  const edit = { issue: "99999", date: "2026-11-25", front: "01 08 20 24 33", back: "03 04" };
  const app = appContext({ cheeDrawEdits: JSON.stringify({ "26135": edit }) });
  const rows = app.applyBrowserOverrides([{ ...edit, issue: "26135", status: "已同步" }]);
  assert.equal(rows[0].issue, "99999");
  assert.equal(rows[0]._sourceIssue, "26135");
  assert.equal(rows[0].status, "本地修改");
});

test("forecast metadata and locally edited text are escaped", () => {
  const app = appContext();
  const rendered = app.forecastCard({ label: '<img src=x onerror="bad()">', front: [1, 2, 3, 4, 5], back: [1, 2] });
  assert.equal(rendered.includes("<img"), false);
  assert.equal(rendered.includes("&lt;img"), true);
  assert.equal(app.escapeText('<button onclick="x">'), "&lt;button onclick=&quot;x&quot;&gt;");
});

test("learning view separates sealed legacy models from a ready quantum batch", () => {
  const app=appContext(), learning={innerHTML:""};
  app.document.getElementById=id=>id==="joyKaneLearning"?learning:null;
  vm.runInContext(fs.readFileSync(path.join(root,"assets/joy-kane.js"),"utf8").replace(/\nloadJoyKane\(\);\s*$/, ""),app);
  const state={modelVersion:"adaptive-v1",modelFamily:"legacy-adaptive-hit-model",backend:"legacy_classical",observations:null,
    dailyTraining:{cyclesPerRun:1000000,accepted:true,reason:"STALE_OPTIMIZER"},weights:{front:{frequency:1}}};
  app.renderJoyKaneLearning({agentStates:{joy:state,kane:state},trainedBatch:{status:"ready",id:"batch-1",completedCycles:100,selectedCycle:100}});
  assert.match(learning.innerHTML,/完整回放历史开奖记录 100 轮/);
  assert.match(learning.innerHTML,/既有模型 · 封存记录/);
  assert.match(learning.innerHTML,/使用第 100 轮/);
  assert.match(learning.innerHTML,/无序整票的负对数似然/);
  assert.doesNotMatch(learning.innerHTML,/每日搜索次数|验证集命中分变化|STALE_OPTIMIZER|信号权重|1,000,000/);
});

test("local archive renders while the online request is pending and preserves edits and pagination", async () => {
  const storage = {};
  const app = appContext(storage);
  const records = Array.from({ length: 30 }, (_, index) => ({ issue: String(2000 - index), date: "2020-02-01", front: "01 08 20 24 33", back: "03 04", status: "已同步" }));
  let resolveOnline;
  const online = new Promise(resolve => { resolveOnline = resolve; });
  const renders = [];
  app.fetchLocalHistory = async () => ({ draws: records, meta: { source: "published" } });
  app.fetchLiveHistory = () => online;
  app.renderAdmin = () => renders.push(JSON.parse(vm.runInContext("JSON.stringify({draws,currentPage,syncMeta})", app)));
  const loading = app.loadDraws();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(renders.length, 1);
  assert.equal(renders[0].draws.length, 30);
  assert.equal(renders[0].syncMeta.refreshing, true);
  vm.runInContext("currentPage=3", app);
  storage.cheeDrawEdits = JSON.stringify({ "2000": { ...records[0], front: "02 08 20 24 33" } });
  resolveOnline({ draws: [{ ...records[0], issue: "2001", date: "2020-02-02" }, ...records], meta: { source: "online" } });
  await loading;
  assert.equal(renders.length, 2);
  assert.equal(renders[1].draws.length, 31);
  assert.equal(renders[1].draws.find(record => record.issue === "2000").front, "02 08 20 24 33");
  assert.equal(renders[1].draws.find(record => record.issue === "2000").status, "本地修改");
  assert.equal(renders[1].currentPage, 3);
});

test("an older, incomplete or future-dated online archive cannot displace the published snapshot", () => {
  const app = appContext();
  const current = { draws: [{ issue: "2000", date: "2020-02-01" }, { issue: "1999", date: "2020-01-31" }] };
  assert.equal(app.newerArchive({ draws: [{ issue: "1999", date: "2020-01-31" }, {}, {}] }, current), false);
  assert.equal(app.newerArchive({ draws: [{ issue: "2001", date: "2020-02-02" }] }, current), false);
  assert.equal(app.newerArchive({ draws: [{ issue: "9999", date: "2999-01-01" }, {}] }, current), false);
  assert.equal(app.newerArchive({ draws: current.draws }, current), false);
  assert.equal(app.newerArchive({ draws: [{ issue: "2001", date: "2020-02-02" }, ...current.draws] }, current), true);
});

function forecastPublication(status="prediction_locked",legacy=false){
  const ticket={label:"Main",front:[1,2,3,4,5],back:[1,12]};
  const agent=name=>({modelVersion:legacy?"adaptive-v1":"v2.0-quantum-chronological",modelFamily:legacy?"legacy-adaptive-hit-model":name==="joy"?"quantum-circuit-born-machine":"split-step-quantum-walk",backend:legacy?"legacy_classical":"classical_statevector"});
  return {modelVersion:legacy?"legacy-locked-prediction":"v2.0-quantum-chronological",runtimeVersion:"v2.0-quantum-chronological",generatedAt:"2026-11-26T12:00:00Z",
    predictionGate:{status,reason:"Gate detail"},agentStates:{joy:agent("joy"),kane:agent("kane")},
    nextForecast:{targetIssue:"26136",targetDate:"2026-11-28",historyCount:2953,historyThroughDate:"2026-11-25",joy:{...agent("joy"),results:[ticket]},kane:{...agent("kane"),results:[ticket]}},
    livePredictionLock:{issue:"26136",date:"2026-11-28",lockedAt:"2026-11-26T00:00:00Z"},
    trainedBatch:{status:"ready",agents:{joy:agent("joy"),kane:agent("kane")}}};
}

function forecastView(payload){
  const app=appContext();
  const element=()=>({textContent:"",innerHTML:"",classList:{toggle(){}}});
  const nodes=Object.fromEntries(["homeLockStatus","homeLockDetail","homeUpdatedAt","homeVersion","homeArchiveCount","homeArchiveThrough","next"].map(id=>[id,element()]));
  const cards={};
  for(const id of ["aiPredictionCard","kanePredictionCard"]){
    const parts=Object.fromEntries([".forecast-list",".section-head .muted",".section-head .badge",".forecast-meta",".agent-role"].map(selector=>[selector,element()]));
    cards[id]={parts,querySelector:selector=>parts[selector]};
  }
  app.document.getElementById=id=>cards[id]||nodes[id]||null;
  app.document.querySelector=selector=>selector===".next"?nodes.next:selector.startsWith("#aiPredictionCard ")?cards.aiPredictionCard.querySelector(selector.slice(18)):null;
  app.renderHomeSummary(payload);
  app.renderAgentForecast(payload,"joy");app.renderAgentForecast(payload,"kane");
  return {app,nodes,cards};
}

test("homepage loads only Joy and Kane official prediction sources",()=>{
  const html=fs.readFileSync(path.join(root,"index.html"),"utf8");
  assert.match(html,/id="aiPredictionCard"/);assert.match(html,/id="kanePredictionCard"/);
  assert.doesNotMatch(html,/id="cheePredictionCard"|chee-runtime\.js/);
  const app=appContext();
  assert.equal(typeof app.loadCheeForecast,"undefined");assert.equal(typeof app.renderChee,"undefined");assert.equal(typeof app.renderAiLearning,"undefined");
});

test("awaiting a batch or blocked gate hides stale tickets without substitute predictions",()=>{
  for(const status of ["awaiting_batch","blocked"]){
    const payload=forecastPublication(status);
    const {app,nodes,cards}=forecastView(payload);
    assert.equal(app.officialPrediction(payload,"joy").results.length,0);
    assert.equal(app.officialPrediction(payload,"kane").results.length,0);
    for(const card of Object.values(cards))assert.doesNotMatch(card.parts[".forecast-list"].innerHTML,/class="ball/);
    assert.match(nodes.homeVersion.textContent,/尚未发布/);
    assert.doesNotMatch(nodes.homeLockStatus.textContent,/已封存/);
  }
});

test("unresolved legacy ticket keeps its provenance even with a quantum runtime and ready package",()=>{
  const payload=forecastPublication("awaiting_result",true);
  payload.trainedBatch.agents={joy:{modelFamily:"quantum-circuit-born-machine"},kane:{modelFamily:"split-step-quantum-walk"}};
  const {nodes,cards}=forecastView(payload);
  assert.match(nodes.homeLockStatus.textContent,/等待当前期实际开奖结果/);
  assert.match(nodes.homeVersion.textContent,/既有封存模型/);
  for(const card of Object.values(cards)){
    assert.match(card.parts[".forecast-list"].innerHTML,/class="ball/);
    assert.match(card.parts[".agent-role"].textContent,/既有模型/);
    assert.doesNotMatch(card.parts[".agent-role"].textContent,/Born|游走/);
  }
});

test("active quantum tickets display distinct model families and classical execution",()=>{
  const {nodes,cards}=forecastView(forecastPublication());
  assert.match(cards.aiPredictionCard.parts[".agent-role"].textContent,/Born.*经典模拟/);
  assert.match(cards.kanePredictionCard.parts[".agent-role"].textContent,/量子游走.*经典模拟/);
  assert.match(nodes.homeArchiveThrough.textContent,/2026-11-25/);
  assert.match(nodes.homeLockStatus.textContent,/已封存/);
});

test("legacy JSON is never relabeled quantum and malformed or unmatched locks suppress tickets",()=>{
  const app=appContext(), payload=forecastPublication();
  delete payload.predictionGate;
  payload.modelVersion="v1.0";payload.agentStates={};
  assert.equal(app.officialPrediction(payload,"joy").legacy,true);
  assert.match(app.officialPrediction(payload,"joy").modelLabel,/既有模型/);
  payload.livePredictionLock.issue="99999";
  assert.equal(app.officialPrediction(payload,"joy").results.length,0);
  assert.match(forecastView(payload).nodes.homeLockStatus.textContent,/未通过核验/);
  payload.livePredictionLock.issue="26136";
  payload.nextForecast.joy.results.push(payload.nextForecast.joy.results[0]);
  assert.equal(app.officialPrediction(payload,"joy").results.length,0);
  assert.equal(app.officialPrediction(payload,"chee").results.length,0);
});
