(function () {
  "use strict";
  var FEED_URL = "https://raw.githubusercontent.com/kanewang0929-ops/feel-the-chee/simulation-data/data/simulation-dashboard-history.json";
  var RANDOM_EXPECTED = 1.047619;
  var CURRENT_ENGINE = "joy-kane-quantum-sim-v2";
  var $ = function (id) { return document.getElementById(id); };
  var fmt = function (value, digits) { if (value === null || value === undefined || value === "") return "—"; var n = Number(value); return Number.isFinite(n) ? n.toFixed(digits == null ? 3 : digits) : "—"; };
  var fmtInt = function (value) { var n = value == null || value === "" ? NaN : Number(value); return Number.isFinite(n) ? Math.round(n).toLocaleString("en-US") : "—"; };
  var fmtDate = function (value) {
    if (!value) return "—";
    var d = new Date(value);
    if (!Number.isFinite(d.getTime())) return "—";
    return new Intl.DateTimeFormat("en-GB", { timeZone:"Asia/Shanghai", year:"numeric", month:"short", day:"2-digit", hour:"2-digit", minute:"2-digit", hour12:false }).format(d) + " Beijing";
  };
  var fmtDuration = function (seconds) {
    var n = seconds == null || seconds === "" ? NaN : Number(seconds); if (!Number.isFinite(n) || n < 0) return "—";
    n = Math.round(n);
    return (n >= 3600 ? Math.floor(n / 3600) + "h " : "") + Math.floor(n / 60 % 60) + "m " + String(n % 60).padStart(2, "0") + "s";
  };
  var esc = function (value) { return String(value == null ? "" : value).replace(/[&<>"']/g, function (c) { return ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" })[c]; }); };
  var metric = function (batch, agent, key) { return batch && batch[agent] && batch[agent][key] ? batch[agent][key].mean : null; };
  var batchDate = function (batch) { return batch.startedAt || batch.finishedAt || ""; };
  var currentEngine = function (batch) { return batch && batch.engineVersion === CURRENT_ENGINE; };
  var engineLabel = function (batch) { return currentEngine(batch) ? "Quantum v2" : !batch.engineVersion || /v1$/.test(batch.engineVersion) ? "Legacy adaptive" : "Legacy / other: " + String(batch.modelVersion || batch.engineVersion); };
  function archiveStatus(date, status) {
    var node = $("batchArchiveDate");
    if (node) { node.textContent = date || status; node.dataset.archiveDate = date || ""; node.dataset.state = status; }
    document.dispatchEvent(new Event("ftc:data-updated"));
  }

  function renderStatus(batch, feed) {
    if (!batch) {
      $("batchStatus").textContent = "WAITING"; $("batchStatus").className = "metric-value status-value";
      $("batchTime").textContent = "No batch has been published. Check the workflow for its current status.";
      $("runCount").innerHTML = "0<span class='metric-unit'> / 100</span>"; $("drawCount").textContent = "—"; $("runtime").textContent = "—";
      $("seedCheck").textContent = "Unique seeds are checked before a batch passes."; $("dateRange").textContent = "Complete historical walk-forward replay.";
      $("updatedAt").textContent = "Waiting for the first published batch";
      $("scheduleStatus").textContent = "NO PUBLISHED BATCH";
      archiveStatus(null, "Not published"); return;
    }
    var done = batch.status === "completed";
    $("batchStatus").textContent = done ? (currentEngine(batch) ? "COMPLETED" : "LEGACY / OTHER ENGINE") : String(batch.status || "UNKNOWN").toUpperCase();
    $("batchStatus").className = "metric-value status-value " + (done ? "completed" : "failed");
    $("batchTime").textContent = (batch.startedAt ? "Started " : "Published ") + fmtDate(batchDate(batch)) + " · Batch " + (batch.batchId || "—") + " · " + engineLabel(batch);
    $("scheduleStatus").textContent = done ? (currentEngine(batch) ? "LATEST QUANTUM BATCH PASSED" : "LATEST BATCH USES AN EARLIER ENGINE") : "LATEST BATCH " + String(batch.status || "UNKNOWN").toUpperCase();
    $("runCount").innerHTML = fmtInt(batch.simulationCount) + "<span class='metric-unit'> / 100</span>";
    $("drawCount").textContent = fmtInt(batch.drawsEvaluatedPerSimulation); $("runtime").textContent = fmtDuration(batch.durationSeconds);
    $("runtimeNote").textContent = batch.durationSeconds == null ? "Timing was not recorded for this batch." : "Runner time through feed publication.";
    $("seedCheck").textContent = fmtInt(batch.independentFirstPredictions) + " distinct first predictions · " + (batch.allFirstPredictionsDistinct ? "seed check passed" : "seed check not passed");
    var range = batch.dateRange || {};
    $("dateRange").textContent = range.earliest && range.latest ? range.earliest + " → " + range.latest : "Full archive range not available";
    $("updatedAt").textContent = "Feed refreshed " + fmtDate(feed.updatedAt || batch.finishedAt);
    archiveStatus(done ? range.latest : null, done ? "Published" : "Latest batch failed");
  }
  function renderAgents(batch) {
    if (!batch || batch.status !== "completed" || !batch.joy || !batch.kane) { $("agentScores").innerHTML = "<div class='empty-state'>No completed batch averages are available yet.</div>"; return; }
    if (!currentEngine(batch)) { $("agentScores").innerHTML = "<div class='empty-state'>The latest published batch uses " + esc(engineLabel(batch)) + ". Its historical scores remain in the table below. Quantum v2 results have not been published for this batch.</div>"; return; }
    function card(name, agent, colorClass) {
      var total = metric(batch, agent, "averageBestTotalHits"), front = metric(batch, agent, "averageBestFrontHits"), back = metric(batch, agent, "averageBestBackHits");
      if (total == null || total === "" || !Number.isFinite(Number(total))) return "<div class='agent-score'><div class='agent-name'>" + name + "</div><p class='caveat'>Score was not recorded for this batch.</p></div>";
      var range = batch[agent].averageBestTotalHits || {}, min = range.min, max = range.max;
      var width = Math.max(0, Math.min(100, (Number(total) / 1.5) * 100)), delta = Number(total) - RANDOM_EXPECTED;
      return "<div class='agent-score'><div class='agent-score-head'><span class='agent-name'>" + name + "</span><strong class='agent-score-number'>" + fmt(total, 4) + "</strong></div>" +
        "<div class='agent-score-sub'><span>Front " + fmt(front, 3) + " · Back " + fmt(back, 3) + "</span><span>" + (delta >= 0 ? "+" : "") + fmt(delta, 4) + " vs expectation</span></div>" +
        "<div class='score-track'><div class='score-fill " + colorClass + "' style='width:" + width + "%'></div></div>" +
        "<div class='agent-score-sub'><span>Seed-to-seed range</span><span>" + fmt(min, 4) + "–" + fmt(max, 4) + "</span></div></div>";
    }
    $("agentScores").innerHTML = card("JOY", "joy", "joy-fill") + card("KANE", "kane", "kane-fill");
  }
  function renderChart(batches) {
    var rows = (batches || []).filter(function (b) { return currentEngine(b) && b.status === "completed" && ["joy", "kane"].every(function (agent) { var value = metric(b, agent, "averageBestTotalHits"); return value != null && value !== "" && Number.isFinite(Number(value)); }); }).slice(0, 12).reverse();
    if (!rows.length) { $("historyChart").innerHTML = "<div class='empty-state'>Quantum v2 scores will appear after a complete 100-cycle batch is published. Legacy results remain in the table.</div>"; return; }
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
      rows.map(function (b, i) { return ["joy", "kane"].map(function (agent) { return "<circle cx='" + x(i) + "' cy='" + y(metric(b, agent, "averageBestTotalHits")) + "' r='4' fill='" + (agent === "joy" ? "#91aaff" : "#70e0b5") + "'><title>" + esc(agent.toUpperCase() + " · " + fmtDate(batchDate(b)) + " · " + fmt(metric(b, agent, "averageBestTotalHits"), 4) + " hits · batch " + b.batchId) + "</title></circle>"; }).join(""); }).join("") +
      rows.map(function (b, i) { if (rows.length > 7 && i % 2 && i !== rows.length - 1) return ""; var stamp = batchDate(b), d = new Date(stamp); var label = stamp && Number.isFinite(d.getTime()) ? new Intl.DateTimeFormat("en-GB", {timeZone:"Asia/Shanghai",month:"short",day:"2-digit"}).format(d) : "Batch " + (i + 1); return "<text x='" + x(i) + "' y='215' text-anchor='middle' fill='#aab8cf' font-size='10'>" + esc(label) + "</text>"; }).join("") + "</svg>";
    $("historyChart").innerHTML = svg;
  }
  function renderTable(batches) {
    var rows = (batches || []).slice(0, 30);
    if (!rows.length) { $("batchRows").innerHTML = "<tr><td colspan='9' class='empty-cell'>No batches have been published yet. The initial production run will appear here.</td></tr>"; $("historyMeta").textContent = "The dashboard retains the 30 most recent batches."; return; }
    $("batchRows").innerHTML = rows.map(function (b) {
      var completed = b.status === "completed";
      return "<tr><td>" + esc(b.batchId || "—") + "</td><td>" + esc(engineLabel(b)) + "</td><td>" + esc(fmtDate(batchDate(b))) + (!b.startedAt && b.finishedAt ? "<small class='date-note'>Published; start not recorded</small>" : "") + "</td><td><span class='table-status " + (completed ? "completed" : "failed") + "'>" + esc(String(b.status || "unknown").toUpperCase()) + "</span></td>" +
        "<td>" + esc(fmtInt(b.simulationCount)) + "</td><td>" + esc(fmt(metric(b, "joy", "averageBestTotalHits"), 4)) + "</td><td>" + esc(fmt(metric(b, "kane", "averageBestTotalHits"), 4)) + "</td><td>" + esc(fmtDuration(b.durationSeconds)) + "</td>" +
        "<td>" + (b.workflowRunUrl ? "<a class='run-link' href='" + esc(b.workflowRunUrl) + "' target='_blank' rel='noopener'>Logs ↗</a>" : "") + "</td></tr>";
    }).join("");
    $("historyMeta").textContent = "Showing " + rows.length + " recent batches with their engine labels. The chart includes Quantum v2 only; legacy scores do not evaluate the new models.";
  }

  function renderCycleHistory(batches) {
    var available=batches.filter(function(b){return b.status==="completed"&&Array.isArray(b.simulations)&&b.simulations.length>0;});
    var select=$("cycleBatchSelect");
    function display(batch){
      var rows=batch.simulations.slice().sort(function(a,b){return Number(a.simulationId)-Number(b.simulationId);});
      $("cycleHistoryCount").textContent=rows.length+" / "+batch.simulationCount+" recorded";
      $("cycleHistoryMeta").textContent=engineLabel(batch)+" · "+fmtDate(batchDate(batch))+" · "+batch.batchId+" · archive through "+((batch.dateRange||{}).latest||"not recorded");
      $("cycleHistoryRows").innerHTML=rows.map(function(s){
        function scores(a){return ["averageBestFrontHits","averageBestBackHits","averageBestTotalHits"].map(function(key){return "<td>"+esc(fmt((s[a]||{})[key],4))+"</td>";}).join("");}
        var chosen=currentEngine(batch)&&Number(s.simulationId)===Number(batch.selectedCycle);
        return "<tr><td>"+esc("#"+String(s.simulationId).padStart(3,"0")+(chosen?" · checkpoint":""))+"</td>"+scores("joy")+scores("kane")+"<td>"+esc(fmtInt(s.drawsEvaluated))+"</td></tr>";
      }).join("");
    }
    if(!available.length){
      select.disabled=true;
      $("cycleHistoryCount").textContent="NO RECORDS";
      $("cycleHistoryMeta").textContent="No individual simulation records are available in the retained feed.";
      $("cycleHistoryRows").innerHTML="<tr><td colspan='8' class='empty-cell'>No individual cycles published.</td></tr>";return;
    }
    select.innerHTML=available.map(function(b,i){return "<option value='"+i+"'>"+esc(fmtDate(batchDate(b))+" · "+engineLabel(b)+" · "+b.batchId)+"</option>";}).join("");
    var initial=available.findIndex(currentEngine);if(initial<0)initial=0;
    select.value=String(initial);select.disabled=false;display(available[initial]);
    select.addEventListener("change",function(){var b=available[Number(select.value)];if(b)display(b);});
  }
  function render(feed) {
    if (feed.schemaVersion !== 1 || !Array.isArray(feed.batches)) throw new Error("Unrecognized dashboard feed");
    var batches = Array.isArray(feed.batches) ? feed.batches.slice() : [];
    batches.sort(function (a, b) { return String(batchDate(b)).localeCompare(String(batchDate(a))); });
    renderStatus(batches[0] || null, feed); renderAgents(batches[0] || null); renderChart(batches); renderTable(batches); renderCycleHistory(batches);
    var stale = Date.now() - Date.parse(feed.updatedAt || batchDate(batches[0] || {})) > 36 * 60 * 60 * 1000;
    $("feedStatus").textContent = (stale ? "Feed: last publication over 36 hours ago" : "Feed: connected") + " · " + batches.length + " batch record(s) · All times Beijing (UTC+8)";
    if (stale) $("scheduleStatus").textContent = "FEED UPDATE OVERDUE";
  }
  var controller = new AbortController();
  var timer = setTimeout(function () { controller.abort(); }, 15000);
  fetch(FEED_URL + "?cache=" + Date.now(), { cache:"no-store", signal:controller.signal }).then(function (response) {
    if (!response.ok) throw new Error("Feed returned HTTP " + response.status);
    return response.json();
  }).then(render).catch(function (error) {
    $("batchStatus").textContent = "UNAVAILABLE";
    $("batchStatus").className = "metric-value status-value failed";
    $("batchTime").textContent = "Unable to check the latest batch. Use Refresh data to try again.";
    $("runCount").textContent = "—";
    $("updatedAt").textContent = "Could not load the simulation feed.";
    $("scheduleStatus").textContent = "FEED UNAVAILABLE";
    $("feedStatus").textContent = "Feed unavailable · " + (error.name === "AbortError" ? "Request timed out" : error.message);
    $("historyChart").innerHTML = "<div class='empty-state'>Replay history could not be loaded. Refresh data to retry.</div>";
    $("agentScores").innerHTML = "<div class='empty-state'>Scores are unavailable while the feed cannot be reached.</div>";
    $("batchRows").innerHTML = "<tr><td colspan='9' class='empty-cell'>Batch history is unavailable. The workflow link above remains available.</td></tr>";
    $("cycleHistoryCount").textContent="UNAVAILABLE";
    $("cycleHistoryMeta").textContent="Individual cycle history could not be loaded. Refresh to retry.";
    $("cycleHistoryRows").innerHTML="<tr><td colspan='8' class='empty-cell'>Simulation feed unavailable.</td></tr>";
    archiveStatus(null, "Unavailable");
  }).finally(function () { clearTimeout(timer); });
}());
