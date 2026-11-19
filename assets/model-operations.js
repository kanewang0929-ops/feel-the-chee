(function () {
  "use strict";
  var ROOT = "https://raw.githubusercontent.com/kanewang0929-ops/feel-the-chee/main/data/";
  var $ = function (id) { return document.getElementById(id); };
  var esc = function (v) { return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) { return ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]; }); };
  var number = function (v, d) { var n = Number(v); return Number.isFinite(n) ? n.toFixed(d == null ? 3 : d) : "—"; };
  var count = function (v) { var n = Number(v); return Number.isFinite(n) ? Math.round(n).toLocaleString("en-US") : "—"; };
  var date = function (v) { if (!v) return "—"; var d = new Date(v); return Number.isFinite(d.getTime()) ? new Intl.DateTimeFormat("en-GB",{timeZone:"Asia/Shanghai",dateStyle:"medium",timeStyle:"short"}).format(d)+" Beijing" : "—"; };
  function row(label, value) { return "<div class='ops-data-row'><span>"+esc(label)+"</span><strong>"+esc(value)+"</strong></div>"; }
  function weightBars(weights) {
    if (!weights) return "<p class='muted'>No signal weights available.</p>";
    return Object.keys(weights).map(function (area) {
      var signals = weights[area] || {};
      return "<div class='weight-area'><h4>"+esc(area)+" weights</h4>"+Object.keys(signals).map(function (name) {
        var pct = Math.max(0,Math.min(100,Number(signals[name])*100));
        return "<div class='weight-row'><span>"+esc(name)+"</span><div class='weight-track'><i style='width:"+pct.toFixed(2)+"%'></i></div><b>"+pct.toFixed(1)+"%</b></div>";
      }).join("")+"</div>";
    }).join("");
  }
  function agentCard(name, agent) {
    var train = agent.dailyTraining || {};
    var duel = agent.duel || {};
    return row("Model version",agent.modelVersion||"—")+
      row("Observations",count(agent.observations))+
      row("Head-to-head",count(duel.wins)+" wins · "+count(duel.losses)+" losses · "+count(duel.ties)+" ties")+
      row("Optimizer",train.accepted===true?"Accepted":train.accepted===false?"Not accepted":"No recent accepted run")+
      row("Accepted trials",count(train.acceptedTrials))+
      row("Training score",number(train.trainScoreBefore)+" → "+number(train.trainScoreAfter))+
      row("Validation score",number(train.validationScoreBefore)+" → "+number(train.validationScoreAfter))+
      row("Untouched test diagnostic",number(train.untouchedTestScoreBefore)+" → "+number(train.untouchedTestScoreAfter))+
      row("Last optimizer update",date(train.updatedAt))+
      "<div class='weight-heading'>Current signal weights</div>"+weightBars(agent.weights);
  }
  function loadTraining(state, dashboard) {
    var agents = state.agents || {};
    var joy = agents.joy || {}, kane = agents.kane || {};
    var dashAgents = dashboard.agentStates || {};
    var trainJoy = (dashAgents.joy && dashAgents.joy.dailyTraining) || joy.dailyTraining || {};
    var trainKane = (dashAgents.kane && dashAgents.kane.dailyTraining) || kane.dailyTraining || {};
    var latest = [trainJoy.updatedAt,trainKane.updatedAt].filter(Boolean).sort().pop();
    $("trainingUpdated").textContent = "Model state refreshed "+date(state.generatedAt || dashboard.generatedAt);
    $("trainModelVersion").textContent = state.modelVersion || dashboard.modelVersion || "—";
    $("trainObservations").textContent = count(Math.min(Number(joy.observations||0),Number(kane.observations||0)));
    $("trainCycles").textContent = count(Math.max(Number(trainJoy.cyclesPerRun||0),Number(trainKane.cyclesPerRun||0)));
    $("trainLastRun").textContent = latest ? date(latest).split(" ").slice(0,3).join(" ") : "—";
    var skipped = trainJoy.skipped === true && trainKane.skipped === true;
    var ran = trainJoy.ranToday === true || trainKane.ranToday === true;
    $("trainRunState").textContent = skipped ? (trainJoy.reason || trainKane.reason || "Optimizer skipped by the minimum interval guard") : ran ? "Optimizer ran in the latest live workflow" : (trainJoy.reason || trainKane.reason || "Latest optimizer execution status is not recorded");
    $("joyTrainingCard").innerHTML = agentCard("Joy",joy);
    $("kaneTrainingCard").innerHTML = agentCard("Kane",kane);
    $("deployVersion").textContent = state.modelVersion || "—";
    var lock = state.livePredictionLock || dashboard.livePredictionLock || {};
    $("deployIssue").textContent = lock.issue || "—";
    $("deployLockDate").textContent = lock.date ? "Target draw "+lock.date+" · locked "+date(lock.lockedAt) : "No active lock in model-state file";
    $("deploymentUpdated").textContent = "Production state updated "+date(state.generatedAt);
  }
  function loadHoldout() {
    var url = "https://raw.githubusercontent.com/kanewang0929-ops/feel-the-chee/simulation-data/data/chronological-holdout-report.json";
    fetch(url+"?v="+Date.now(),{cache:"no-store"}).then(function(r){if(!r.ok)throw new Error("No published holdout report");return r.json();}).then(function(report){
      var cmp=report.finalTestComparisons||{};
      var baseline=report.randomBaseline||{};
      var html="<div class='ops-data-row'><span>Archive draws</span><strong>"+count(report.archive&&report.archive.validDrawCount)+"</strong></div>"+
        "<div class='ops-data-row'><span>Random expected hits</span><strong>"+number(baseline.theoreticalExpectedTotalHitsPerTicket,6)+"</strong></div>";
      ["joy","kane"].forEach(function(agent){
        var c=cmp[agent]||{}, observed=c.observed||{};
        html+="<div class='ops-data-row'><span>"+agent.toUpperCase()+" final-test average</span><strong>"+number(observed.averageTotalHits,6)+"</strong></div>"+
          "<div class='ops-data-row'><span>"+agent.toUpperCase()+" vs random mean</span><strong>"+number(c.differenceVsRandomMean,6)+"</strong></div>"+
          "<div class='ops-data-row'><span>"+agent.toUpperCase()+" empirical p-value</span><strong>"+number(c.empiricalOneSidedPValue,4)+"</strong></div>";
      });
      $("holdoutMetrics").innerHTML=html;
      $("holdoutMeta").textContent="Latest published chronological holdout · "+esc(report.evaluationVersion||"")+" · "+count(report.split&&report.split.counts&&report.split.counts.finalTestDraws)+" final-test draws";
    }).catch(function(){
      $("holdoutMetrics").innerHTML="<div class='empty-state'>No published holdout report yet. Run the chronological evaluation workflow to publish one here.</div>";
      $("holdoutMeta").textContent="No published holdout report";
    });
  }
  function initTabs() {
    var buttons=[].slice.call(document.querySelectorAll("[data-ops-tab]"));
    buttons.forEach(function(button){button.addEventListener("click",function(){
      var target=button.getAttribute("data-ops-tab");
      buttons.forEach(function(b){b.classList.toggle("active",b===button);});
      ["training","evaluation","deployment"].forEach(function(name){
        var panel=$("ops-"+name); if(panel){var active=name===target;panel.hidden=!active;panel.classList.toggle("active",active);}
      });
    });});
  }
  initTabs();
  Promise.all([
    fetch(ROOT+"joy-kane-model-state.json?v="+Date.now(),{cache:"no-store"}).then(function(r){if(!r.ok)throw new Error("Model state HTTP "+r.status);return r.json();}),
    fetch(ROOT+"joy-kane-dashboard.json?v="+Date.now(),{cache:"no-store"}).then(function(r){if(!r.ok)throw new Error("Dashboard HTTP "+r.status);return r.json();})
  ]).then(function(rows){loadTraining(rows[0],rows[1]);}).catch(function(error){
    $("trainingUpdated").textContent="Live model state unavailable · "+error.message;
    $("joyTrainingCard").textContent="Unable to load Joy model state.";
    $("kaneTrainingCard").textContent="Unable to load Kane model state.";
  });
  loadHoldout();
}());
