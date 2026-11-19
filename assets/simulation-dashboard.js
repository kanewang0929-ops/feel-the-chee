(function () {
  "use strict";
  var FEED_URL = "https://raw.githubusercontent.com/kanewang0929-ops/feel-the-chee/simulation-data/data/simulation-dashboard-history.json";
  var RANDOM_EXPECTED = 1.047619;
  var $ = function (id) { return document.getElementById(id); };
  var fmt = function (value, digits) { var n = Number(value); return Number.isFinite(n) ? n.toFixed(digits == null ? 3 : digits) : "—"; };
  var fmtInt = function (value) { var n = Number(value); return Number.isFinite(n) ? Math.round(n).toLocaleString("en-US") : "—"; };
  var fmtDate = function (value) {
    if (!value) return "—";
    var d = new Date(value);
    if (!Number.isFinite(d.getTime())) return String(value);
    return new Intl.DateTimeFormat("en-GB", { timeZone:"Asia/Seoul", year:"numeric", month:"short", day:"2-digit", hour:"2-digit", minute:"2-digit", hour12:false }).format(d) + " KST";
  };
  var fmtDuration = function (seconds) {
    var n = Number(seconds); if (!Number.isFinite(n) || n < 0) return "—";
    return Math.floor(n / 60) + "m " + String(Math.round(n % 60)).padStart(2, "0") + "s";
  };
  var esc = function (value) { return String(value == null ? "" : value).replace(/[&<>"']/g, function (c) { return ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" })[c]; }); };
  var metric = function (batch, agent, key) { return batch && batch[agent] && batch[agent][key] ? batch[agent][key].mean : null; };

  function renderStatus(batch, feed) {
    if (!batch) {
      $("batchStatus").textContent = "WAITING"; $("batchStatus").className = "metric-value status-value";
      $("batchTime").textContent = "Schedule is enabled. The first 100-run batch is queued on the production workflow.";
      $("runCount").innerHTML = "0<span class='metric-unit'> / 100</span>"; $("drawCount").textContent = "—"; $("runtime").textContent = "—";
      $("seedCheck").textContent = "Unique seeds are checked before a batch passes."; $("dateRange").textContent = "Complete historical walk-forward replay.";
      $("updatedAt").textContent = "Waiting for the first published batch"; return;
    }
    var done = batch.status === "completed";
    $("batchStatus").textContent = done ? "COMPLETED" : String(batch.status || "UNKNOWN").toUpperCase();
    $("batchStatus").className = "metric-value status-value " + (done ? "completed" : "failed");
    $("batchTime").textContent = "Started " + fmtDate(batch.startedAt) + " · Batch " + (batch.batchId || "—");
    $("runCount").innerHTML = fmtInt(batch.simulationCount) + "<span class='metric-unit'> / 100</span>";
    $("drawCount").textContent = fmtInt(batch.drawsEvaluatedPerSimulation); $("runtime").textContent = fmtDuration(batch.durationSeconds);
    $("seedCheck").textContent = fmtInt(batch.independentFirstPredictions) + " distinct first predictions · " + (batch.allFirstPredictionsDistinct ? "seed check passed" : "seed check not passed");
    var range = batch.dateRange || {};
    $("dateRange").textContent = range.earliest && range.latest ? range.earliest + " → " + range.latest : "Full archive range not available";
    $("updatedAt").textContent = "Feed refreshed " + fmtDate(feed.updatedAt || batch.finishedAt);
  }
  function renderAgents(batch) {
    if (!batch || batch.status !== "completed" || !batch.joy || !batch.kane) { $("agentScores").innerHTML = "<div class='empty-state'>No completed batch averages are available yet.</div>"; return; }
    function card(name, agent, colorClass) {
      var total = metric(batch, agent, "averageBestTotalHits"), front = metric(batch, agent, "averageBestFrontHits"), back = metric(batch, agent, "averageBestBackHits");
      var min = batch[agent].averageBestTotalHits.min, max = batch[agent].averageBestTotalHits.max;
      var width = Math.max(0, Math.min(100, (Number(total) / 1.5) * 100)), delta = Number(total) - RANDOM_EXPECTED;
      return "<div class='agent-score'><div class='agent-score-head'><span class='agent-name'>" + name + "</span><strong class='agent-score-number'>" + fmt(total, 4) + "</strong></div>" +
        "<div class='agent-score-sub'><span>Front " + fmt(front, 3) + " · Back " + fmt(back, 3) + "</span><span>" + (delta >= 0 ? "+" : "") + fmt(delta, 4) + " vs expectation</span></div>" +
        "<div class='score-track'><div class='score-fill " + colorClass + "' style='width:" + width + "%'></div></div>" +
        "<div class='agent-score-sub'><span>Seed-to-seed range</span><span>" + fmt(min, 4) + "–" + fmt(max, 4) + "</span></div></div>";
    }
    $("agentScores").innerHTML = card("JOY", "joy", "joy-fill") + card("KANE", "kane", "kane-fill");
  }
  function renderChart(batches) {
    var rows = (batches || []).filter(function (b) { return b.status === "completed" && b.joy && b.kane; }).slice(0, 12).reverse();
    if (!rows.length) { $("historyChart").innerHTML = "<div class='empty-state'>The chart will appear after the first 100-run batch is complete.</div>"; return; }
    var values = [];
    rows.forEach(function (b) { values.push(metric(b, "joy", "averageBestTotalHits")); values.push(metric(b, "kane", "averageBestTotalHits")); });
    values.push(RANDOM_EXPECTED); values = values.map(Number).filter(Number.isFinite);
    var min = Math.min.apply(null, values) - 0.035, max = Math.max.apply(null, values) + 0.035;
    if (max - min < 0.08) { min -= 0.025; max += 0.025; }
    var left = 34, right = 742, top = 18, bottom = 192;
    var x = function (i) { return rows.length === 1 ? (left + right) / 2 : left + (right - left) * i / (rows.length - 1); };
    var y = function (v) { return bottom - (Number(v) - min) / (max - min) * (bottom - top); };
    var joyPts = rows.map(function (b, i) { return x(i) + "," + y(metric(b, "joy", "averageBestTotalHits")); }).join(" ");
    var kanePts = rows.map(function (b, i) { return x(i) + "," + y(metric(b, "kane", "averageBestTotalHits")); }).join(" ");
    var baseY = y(RANDOM_EXPECTED);
    var ticks = [min, (min + max) / 2, max];
    var svg = "<svg viewBox='0 0 760 225' role='img' aria-label='Average Joy and Kane historical replay scores by daily batch'>" +
      ticks.map(function (t) { return "<line x1='30' y1='" + y(t) + "' x2='746' y2='" + y(t) + "' stroke='rgba(185,200,226,.10)' stroke-width='1'/><text x='25' y='" + (y(t) + 4) + "' text-anchor='end' fill='#8392ad' font-size='10'>" + fmt(t, 3) + "</text>"; }).join("") +
      "<line x1='30' y1='" + baseY + "' x2='746' y2='" + baseY + "' stroke='#e8bd69' stroke-width='1.5' stroke-dasharray='5 5'/>" +
      "<polyline points='" + joyPts + "' fill='none' stroke='#91aaff' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'/>" +
      "<polyline points='" + kanePts + "' fill='none' stroke='#70e0b5' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'/>" +
      rows.map(function (b, i) { return "<circle cx='" + x(i) + "' cy='" + y(metric(b, "joy", "averageBestTotalHits")) + "' r='3.8' fill='#91aaff'/><circle cx='" + x(i) + "' cy='" + y(metric(b, "kane", "averageBestTotalHits")) + "' r='3.8' fill='#70e0b5'/>"; }).join("") +
      rows.map(function (b, i) { if (rows.length > 7 && i % 2) return ""; return "<text x='" + x(i) + "' y='215' text-anchor='middle' fill='#8392ad' font-size='9'>" + esc((b.startedAt || "").slice(5, 10)) + "</text>"; }).join("") + "</svg>";
    $("historyChart").innerHTML = svg;
  }
  function renderTable(batches) {
    var rows = (batches || []).slice(0, 30);
    if (!rows.length) { $("batchRows").innerHTML = "<tr><td colspan='8' class='empty-cell'>No batches have been published yet. The initial production run will appear here.</td></tr>"; $("historyMeta").textContent = "The dashboard retains the 30 most recent batches."; return; }
    $("batchRows").innerHTML = rows.map(function (b) {
      var completed = b.status === "completed";
      return "<tr><td>" + esc(b.batchId || "—") + "</td><td>" + esc(fmtDate(b.startedAt)) + "</td><td><span class='table-status " + (completed ? "completed" : "failed") + "'>" + esc(String(b.status || "unknown").toUpperCase()) + "</span></td>" +
        "<td>" + esc(fmtInt(b.simulationCount)) + "</td><td>" + esc(fmt(metric(b, "joy", "averageBestTotalHits"), 4)) + "</td><td>" + esc(fmt(metric(b, "kane", "averageBestTotalHits"), 4)) + "</td><td>" + esc(fmtDuration(b.durationSeconds)) + "</td>" +
        "<td>" + (b.workflowRunUrl ? "<a class='run-link' href='" + esc(b.workflowRunUrl) + "' target='_blank' rel='noopener'>Logs ↗</a>" : "") + "</td></tr>";
    }).join("");
    $("historyMeta").textContent = "Showing " + rows.length + " recent batches. Full workflow logs and downloadable audit artifacts are linked per run.";
  }
  function render(feed) {
    var batches = Array.isArray(feed.batches) ? feed.batches.slice() : [];
    batches.sort(function (a, b) { return String(b.startedAt || "").localeCompare(String(a.startedAt || "")); });
    renderStatus(batches[0] || null, feed); renderAgents(batches[0] || null); renderChart(batches); renderTable(batches);
    $("feedStatus").textContent = "Feed: connected · " + batches.length + " batch record(s)";
  }
  fetch(FEED_URL + "?cache=" + Date.now(), { cache:"no-store" }).then(function (response) {
    if (!response.ok) throw new Error("Feed returned HTTP " + response.status);
    return response.json();
  }).then(render).catch(function (error) {
    $("feedStatus").textContent = "Feed unavailable · " + error.message;
    $("updatedAt").textContent = "The first dashboard feed has not been published yet.";
    render({ batches:[], schedule:{enabled:true} });
  });
}());
