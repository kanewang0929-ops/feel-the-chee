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

test("Joy and Kane learning display ignores legacy optimizer fields and describes one ticket per draw", () => {
  const app = appContext();
  const learning = { innerHTML: "" };
  const audit = { innerHTML: "", querySelector: () => null };
  app.document.getElementById = id => id === "joyKaneLearning" ? learning : id === "joyKaneAudit" ? audit : null;
  const source = fs.readFileSync(path.join(root, "assets/joy-kane.js"), "utf8").replace(/\nloadJoyKane\(\);\s*$/, "");
  vm.runInContext(source, app);
  const state = {
    modelVersion: "adaptive-v1", observations: 2753, exploration: .08,
    updatedAt: "2026-11-25T23:25:00Z", weights: { front: { frequency: 1 }, back: { frequency: 1 } },
    dailyTraining: { cyclesPerRun: 1000000, updatedAt: "2026-11-25T23:04:36Z", accepted: true,
      skipped: true, reason: "STALE_OPTIMIZER_REASON", validationScoreBefore: 998, validationScoreAfter: 999 }
  };
  app.renderJoyKaneLearning({ agentStates: { joy: state, kane: state }, summary: {}, method: { dailyTraining: { ranToday: true } } });
  assert.match(learning.innerHTML, /完整回放历史开奖记录 100 轮/);
  assert.match(learning.innerHTML, /探索强度.*0\.080/);
  assert.match(learning.innerHTML, /2026\/11\/26 07:25/);
  assert.match(learning.innerHTML, /提前封存的唯一一组号码/);
  assert.doesNotMatch(learning.innerHTML, /每日搜索次数|验证集命中分变化|每天各进行一百万|STALE_OPTIMIZER_REASON|未触碰最后一段|1,000,000|07:04/);
  app.renderJoyKaneAudit();
  assert.match(audit.innerHTML, /Joy · 1组预测及命中/);
  assert.match(audit.innerHTML, /Kane · 1组预测及命中/);
  assert.doesNotMatch(audit.innerHTML, /三组预测|3组预测/);
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

async function renderChee(target, options = {}) {
  const payload = JSON.parse(fs.readFileSync(path.join(root, "data/chee-forecast.json"), "utf8"));
  const nodes = Object.fromEntries(["description", "badge", "bars", "list", "status"].map(name => [name, { textContent: "", innerHTML: "", hidden: false, classList: { toggle() {} } }]));
  const selectors = { ".section-head .muted": "description", ".section-head .badge": "badge", ".chee-bars": "bars", ".forecast-list": "list" };
  const card = { dataset: {}, querySelector: selector => nodes[selectors[selector]] };
  let boot;
  let requests = 0;
  const context = vm.createContext({
    document: { readyState: "loading", addEventListener: (_event, callback) => { boot = callback; }, getElementById: id => id === "cheePredictionCard" ? card : id === "cheeStatus" ? nodes.status : null },
    fetch: async () => { requests++; if (options.fail) throw new Error("offline"); return { ok: true, json: async () => payload }; },
    loadDuelPayload: async () => ({ nextForecast: target?.(payload) }),
    isPastTarget: () => Boolean(options.past),
    window: { dispatchEvent() {} }, CustomEvent: class {},
    AbortController, setTimeout, clearTimeout, console: { error() {} }
  });
  vm.runInContext(fs.readFileSync(path.join(root, "assets/chee-runtime.js"), "utf8"), context);
  await boot();
  return { payload, card, nodes, requests };
}

test("a stale Chee draw is collapsed and cannot look like the current prediction", async () => {
  const { card, nodes } = await renderChee(() => ({ targetIssue: "99999", targetDate: "2099-01-01" }));
  assert.equal(card.dataset.cheeCurrent, "false");
  assert.equal(nodes.bars.hidden, true);
  assert.equal(nodes.list.innerHTML.startsWith('<details class="archived-formula">'), true);
  assert.equal(nodes.badge.textContent, "历史结果 · 待更新");
  assert.equal(nodes.status.textContent.includes("99999"), true);
});

test("matching Chee issue and date show both current formula results", async () => {
  const { card, nodes } = await renderChee(payload => ({ targetIssue: payload.targetIssue, targetDate: payload.targetDate }));
  assert.equal(card.dataset.cheeCurrent, "true");
  assert.equal(nodes.bars.hidden, false);
  assert.equal(nodes.list.innerHTML.includes("<details"), false);
  assert.equal((nodes.list.innerHTML.match(/class="forecast"/g) || []).length, 2);
});

test("unknown live target is explicitly unverified rather than labelled current", async () => {
  const { card, nodes } = await renderChee();
  assert.equal(card.dataset.cheeCurrent, "false");
  assert.equal(nodes.badge.textContent.includes("期次未核验"), true);
});

test("even matching snapshots are historical when their target date has passed", async () => {
  const { card, nodes } = await renderChee(payload => ({ targetIssue: payload.targetIssue, targetDate: payload.targetDate }), { past: true });
  assert.equal(card.dataset.cheeCurrent, "false");
  assert.equal(nodes.bars.hidden, true);
  assert.equal(nodes.status.textContent.includes("日期已过"), true);
});

test("missing Chee sources resolve to an honest unavailable state without retrying forever", async () => {
  const { card, nodes, requests } = await renderChee(undefined, { fail: true });
  assert.equal(requests, 2);
  assert.equal(card.dataset.cheeLoaded, "false");
  assert.equal(nodes.bars.hidden, true);
  assert.equal(nodes.list.innerHTML.includes("公式结果暂不可用"), true);
  assert.equal(nodes.list.innerHTML.includes("offline"), false);
});
