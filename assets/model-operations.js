(function () {
  "use strict";
  // Keep live telemetry on the same deployed snapshot as the prediction page.
  var ROOT = "./data/";
  var $ = function (id) { return document.getElementById(id); };
  var esc = function (v) { return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) { return ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]; }); };
  var number = function (v, d) { var n = v == null || v === "" ? NaN : Number(v); return Number.isFinite(n) ? n.toFixed(d == null ? 3 : d) : "—"; };
  var count = function (v) { var n = v == null || v === "" ? NaN : Number(v); return Number.isFinite(n) ? Math.round(n).toLocaleString("en-US") : "—"; };
  var date = function (v) { if (!v) return "—"; var d = new Date(v); return Number.isFinite(d.getTime()) ? new Intl.DateTimeFormat("en-GB",{timeZone:"Asia/Shanghai",dateStyle:"medium",timeStyle:"short"}).format(d)+" Beijing" : "—"; };
  function fetchJSON(url) {
    var controller = new AbortController();
    var timer = setTimeout(function () { controller.abort(); }, 15000);
    return fetch(url+(url.indexOf("?")<0?"?":"&")+"v="+Date.now(),{cache:"no-store",signal:controller.signal}).then(function(r){
      if(!r.ok){var error=new Error("HTTP "+r.status);error.status=r.status;throw error;}
      return r.json();
    }).finally(function(){clearTimeout(timer);});
  }
  function archiveStatus(kind, value, status) {
    var node = $(kind+"ArchiveDate");
    if(node){node.textContent=value||status;node.dataset.archiveDate=value||"";node.dataset.state=status;}
    updateFreshness();
  }
  function updateFreshness() {
    var note=$("archiveFreshness"), names=["live","batch","research"];
    if(!note)return;
    var nodes=names.map(function(name){return $(name+"ArchiveDate");});
    if(nodes.some(function(node){return !node || node.dataset.state==="loading";}))return;
    var dates=nodes.map(function(node){return node.dataset.archiveDate;});
    var unavailable=nodes.some(function(node){return node.dataset.state==="Unavailable";});
    note.className="freshness-note";
    if(unavailable){note.textContent="Some data could not be loaded. Refresh data to retry; a missing feed does not mean a model or workflow has stopped.";note.classList.add("attention");return;}
    if(dates[0] && (dates[1] && dates[1]<dates[0] || dates[2] && dates[2]<dates[0])){
      note.textContent="The live models include newer draws than the replay or research results. Compare their archive dates before comparing scores.";
      note.classList.add("attention");
    }else if(dates.every(Boolean) && dates.every(function(value){return value===dates[0];})){
      note.textContent="Live models, replay and research cover the same latest draw. Each published evaluation keeps its own recorded data cutoff.";
    }else{
      note.textContent="Each date is the latest draw used by that stage. A successful website deployment does not itself run a new evaluation.";
    }
  }
  document.addEventListener("ftc:data-updated",updateFreshness);
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
      row("Last optimizer decision",train.accepted===true?"Accepted":train.accepted===false?"Not accepted":"Not recorded")+
      row("Accepted trials",count(train.acceptedTrials))+
      row("Training score",number(train.trainScoreBefore)+" → "+number(train.trainScoreAfter))+
      row("Validation score",number(train.validationScoreBefore)+" → "+number(train.validationScoreAfter))+
      row("Historical test diagnostic",number(train.untouchedTestScoreBefore)+" → "+number(train.untouchedTestScoreAfter))+
      row("Last optimizer update",date(train.updatedAt))+
      "<div class='weight-heading'>Current signal weights</div>"+weightBars(agent.weights);
  }
  function loadTraining(state, dashboard) {
    if(!state.agents || !state.agents.joy || !state.agents.kane || !dashboard.summary)throw new Error("Incomplete live model data");
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
    $("trainLastRun").textContent = date(latest);
    var skipped = trainJoy.skipped === true && trainKane.skipped === true;
    var ran = Boolean(dashboard.method && dashboard.method.dailyTraining && dashboard.method.dailyTraining.ranToday);
    $("trainRunState").textContent = skipped ? (trainJoy.reason || trainKane.reason || "Optimizer skipped by the minimum interval guard") : ran ? "Optimizer ran in the latest live workflow" : (trainJoy.reason || trainKane.reason || "Latest optimizer execution status is not recorded");
    $("joyTrainingCard").innerHTML = agentCard("Joy",joy);
    $("kaneTrainingCard").innerHTML = agentCard("Kane",kane);
    $("deployVersion").textContent = state.modelVersion || "—";
    var lock = state.livePredictionLock || dashboard.livePredictionLock || {};
    $("deployIssue").textContent = lock.issue || "—";
    $("deployLockDate").textContent = lock.date ? "Target draw "+lock.date+" · locked "+date(lock.lockedAt) : "No active lock in model-state file";
    $("deploymentUpdated").textContent = "Production state updated "+date(state.generatedAt);
    archiveStatus("live",(dashboard.summary.dateRange||{}).latest,"Published");
  }
  function loadHoldout() {
    var url = "https://raw.githubusercontent.com/kanewang0929-ops/feel-the-chee/simulation-data/data/chronological-holdout-report.json";
    fetchJSON(url).then(function(report){
      if(!report.finalTestComparisons || !report.randomBaseline)throw new Error("Unrecognized holdout report");
      var cmp=report.finalTestComparisons||{};
      var baseline=report.randomBaseline||{};
      var html="<div class='ops-data-row'><span>Archive draws</span><strong>"+count(report.archive&&report.archive.validDrawCount)+"</strong></div>"+
        "<div class='ops-data-row'><span>Random expected hits</span><strong>"+number(baseline.theoreticalExpectedTotalHitsPerTicket,6)+"</strong></div>";
      ["joy","kane"].forEach(function(agent){
        var c=cmp[agent]||{}, observed=c.finalTest||{};
        html+="<div class='ops-data-row'><span>"+agent.toUpperCase()+" final-test average</span><strong>"+number(observed.averageTotalHits,6)+"</strong></div>"+
          "<div class='ops-data-row'><span>"+agent.toUpperCase()+" vs random mean</span><strong>"+number(c.differenceVsRandomMean,6)+"</strong></div>"+
          "<div class='ops-data-row'><span>"+agent.toUpperCase()+" empirical p-value</span><strong>"+number(c.empiricalOneSidedPValue,4)+"</strong></div>";
      });
      $("holdoutMetrics").innerHTML=html;
      var finalTest=(report.split||{}).finalTest||{};
      $("holdoutMeta").textContent="Published historical evaluation · "+(report.evaluationVersion||"")+" · "+count(report.split&&report.split.counts&&report.split.counts.finalTestDraws)+" final-test draws"+(finalTest.lastDate?" · through "+finalTest.lastDate:"");
    }).catch(function(error){
      var missing=error.status===404;
      $("holdoutMetrics").innerHTML="<div class='empty-state'>"+(missing?"The historical report has not been published to the dashboard. Check the evaluation workflow and its artifacts.":"The historical report could not be loaded. Refresh data to retry.")+"</div>";
      $("holdoutMeta").textContent=missing?"Report not published":"Report temporarily unavailable";
    });
  }
  function loadResearch() {
    var base = "https://raw.githubusercontent.com/kanewang0929-ops/feel-the-chee/simulation-data/data/research/";
    var browse = "https://github.com/kanewang0929-ops/feel-the-chee/blob/simulation-data/data/research/";
    fetchJSON(base+"registry.json").then(function(registry){
      if(registry.schemaVersion!==1 || registry.promotionEnabled!==false || !Array.isArray(registry.experiments) || !Array.isArray(registry.batches))throw new Error("Invalid registry");
      var experiments=registry.experiments, batches=registry.batches, last=batches[batches.length-1]||{};
      $("researchStatus").textContent="RESEARCH ONLY";
      var html=row("Recorded experiments",count(experiments.length))+row("Research batches",count(batches.length))+
        row("Research archive through",last.archiveThrough||"—")+row("Last batch",last.id||"—");
      ["joy","kane"].forEach(function(agent){
        var p=(registry.production||{})[agent]||{};
        html+=row(agent.toUpperCase()+" production snapshot",p.snapshotId?p.snapshotId.slice(0,12):"—");
      });
      $("researchSummary").innerHTML=html;
      $("researchRows").innerHTML=experiments.slice(-30).reverse().map(function(r){
        var id=String(r.id||"");
        var link=/^[a-f0-9]{64}$/.test(id)?"<a href='"+browse+"candidates/"+id+".json' target='_blank' rel='noopener'>"+id.slice(0,10)+" ↗</a>":"—";
        var decision={research_only:"Research only",not_improved:"No improvement"}[r.decision]||r.decision;
        return "<tr><td>"+esc(String(r.agent||"").toUpperCase())+"</td><td>"+esc(String((r.configuration||{}).name||"").replace(/_/g," "))+"</td><td>"+number(r.score,4)+"</td><td>"+number(r.researchBaseline,4)+"</td><td>"+esc(decision)+"</td><td>"+link+"</td></tr>";
      }).join("")||"<tr><td colspan='6'>No experiments recorded.</td></tr>";
      $("candidateStatus").textContent=experiments.length?"RESEARCH ONLY":"NOT READY";
      $("candidateDetail").textContent=experiments.length+" experimental packages; none eligible for promotion.";
      $("approvalStatus").textContent="Promotion blocked. Fresh prospective evidence, production comparison and approval are required.";
      archiveStatus("research",last.archiveThrough,batches.length?"Published":"Not published");
    }).catch(function(e){
      var missing=e.status===404;
      $("researchStatus").textContent=missing?"NOT PUBLISHED":"UNAVAILABLE";
      $("researchSummary").textContent=missing?"No research registry has been published yet.":"Research data could not be loaded. Refresh data to retry.";
      $("candidateStatus").textContent="UNKNOWN";
      $("candidateDetail").textContent="Candidate data unavailable. Automatic promotion is disabled.";
      archiveStatus("research",null,missing?"Not published":"Unavailable");
    });
  }
  function initTabs() {
    var buttons=[].slice.call(document.querySelectorAll("[data-ops-tab]"));
    var names=["evaluation","training","deployment"];
    function activate(target,focus,writeHash){
      if(names.indexOf(target)<0)target="evaluation";
      buttons.forEach(function(b){var active=b.getAttribute("data-ops-tab")===target;b.classList.toggle("active",active);b.setAttribute("aria-selected",String(active));b.tabIndex=active?0:-1;if(active&&focus)b.focus();});
      ["training","evaluation","deployment"].forEach(function(name){
        var panel=$("ops-"+name); if(panel){var active=name===target;panel.hidden=!active;panel.classList.toggle("active",active);}
      });
      if(writeHash)history.replaceState(null,"","#"+target);
    }
    buttons.forEach(function(button,index){
      button.addEventListener("click",function(){activate(button.getAttribute("data-ops-tab"),false,true);});
      button.addEventListener("keydown",function(event){
        var next=event.key==="ArrowRight"?(index+1)%buttons.length:event.key==="ArrowLeft"?(index+buttons.length-1)%buttons.length:event.key==="Home"?0:event.key==="End"?buttons.length-1:null;
        if(next!==null){event.preventDefault();activate(buttons[next].getAttribute("data-ops-tab"),true,true);}
      });
    });
    window.addEventListener("hashchange",function(){activate(location.hash.slice(1),false,false);});
    activate(location.hash.slice(1),false,false);
    $("refreshData").addEventListener("click",function(){location.reload();});
  }
  initTabs();
  Promise.all([
    fetchJSON(ROOT+"joy-kane-model-state.json"),
    fetchJSON(ROOT+"joy-kane-dashboard.json")
  ]).then(function(rows){loadTraining(rows[0],rows[1]);}).catch(function(error){
    $("trainingUpdated").textContent="Live model state unavailable. Refresh data to retry.";
    $("joyTrainingCard").textContent="Unable to load Joy model state.";
    $("kaneTrainingCard").textContent="Unable to load Kane model state.";
    $("deploymentUpdated").textContent="Production state could not be loaded.";
    archiveStatus("live",null,"Unavailable");
  });
  loadHoldout();
  loadResearch();
  updateFreshness();
}());
