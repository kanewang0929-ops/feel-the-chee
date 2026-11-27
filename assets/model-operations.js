(function () {
  "use strict";
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
  function row(label, value) { return "<div class='ops-data-row'><span>"+esc(label)+"</span><strong>"+esc(value)+"</strong></div>"; }
  function archiveStatus(kind, value, status) {
    var node = $(kind+"ArchiveDate");
    if(node){node.textContent=value||status;node.dataset.archiveDate=value||"";node.dataset.state=status;}
    updateFreshness();
  }
  function updateFreshness() {
    var note=$("archiveFreshness"), names=["live","batch","verified"];
    if(!note)return;
    var nodes=names.map(function(name){return $(name+"ArchiveDate");});
    if(nodes.some(function(node){return !node || node.dataset.state==="loading";}))return;
    var dates=nodes.map(function(node){return node.dataset.archiveDate;});
    note.className="freshness-note";
    if(nodes.some(function(node){return node.dataset.state==="Unavailable";})){
      note.textContent="Some data could not be loaded. Refresh data to retry.";note.classList.add("attention");return;
    }
    if(dates[2] && ((dates[0] && dates[0]<dates[2]) || (dates[1] && dates[1]<dates[2]))){
      note.textContent="Newer verified draws are available. A new prediction requires the previous ticket to be scored and a complete 100-cycle batch containing that result.";
      note.classList.add("attention");
    }else if(dates.every(Boolean) && dates.every(function(value){return value===dates[0];})){
      note.textContent="The sealed prediction, latest published batch and verified archive cover the same latest draw. An unresolved prediction stays locked.";
    }else{
      note.textContent="Each date belongs to its recorded stage. A pending batch or missing prediction is shown explicitly; no substitute predictor is used.";
    }
  }
  document.addEventListener("ftc:data-updated",updateFreshness);
  function family(model) {
    var name=model.modelFamily||"";
    if(name==="quantum-circuit-born-machine")return "Quantum circuit Born machine";
    if(name==="split-step-quantum-walk")return "Split-step quantum walk";
    if(name==="legacy-adaptive-hit-model" || model.backend==="legacy_classical")return "Legacy adaptive model";
    return name||"Legacy / family not recorded";
  }
  function backend(model) {
    if(model.backend==="classical_statevector")return "Classical statevector simulation";
    if(model.backend==="legacy_classical")return "Legacy classical model";
    return model.backend||"Not recorded";
  }
  function parameterCount(value) {
    if(Array.isArray(value))return value.reduce(function(total,item){return total+parameterCount(item);},0);
    if(value && typeof value==="object")return Object.keys(value).reduce(function(total,key){return total+parameterCount(value[key]);},0);
    return typeof value==="number" && Number.isFinite(value)?1:0;
  }
  function agentCard(agent, active) {
    if(!active || agent.stateScope==="awaiting_batch")return "<p class='muted'>No current sealed prediction. Training packages are shown separately below.</p>";
    return row("Model behind sealed ticket",family(agent))+
      row("Model version",agent.modelVersion||"Not recorded")+
      row("Execution",backend(agent))+
      row("Training observations",count(agent.observations))+
      row("Trainable parameters",agent.parameters?count(parameterCount(agent.parameters)):"Not recorded")+
      row("State scope",agent.stateScope||"Published snapshot");
  }
  function loadTraining(state, dashboard) {
    if(!state.agents || !state.agents.joy || !state.agents.kane || !dashboard.nextForecast)throw new Error("Incomplete model publication");
    var agents=state.agents, gate=dashboard.predictionGate||state.predictionGate||{};
    var batch=dashboard.trainedBatch||state.trainedBatch||{status:"missing"};
    var lock=dashboard.livePredictionLock||state.livePredictionLock||{};
    var next=dashboard.nextForecast||{};
    var status=gate.status||"legacy_snapshot";
    var active=["awaiting_result","prediction_locked","legacy_snapshot"].indexOf(status)>=0 && Boolean(lock.lockedAt) && String(lock.issue)===String(next.targetIssue) && lock.date===next.targetDate;
    var batchReady=batch.status==="ready", batchAgents=batch.agents||{};
    $("trainingUpdated").textContent="Publication refreshed "+date(state.generatedAt||dashboard.generatedAt);
    $("trainModelVersion").textContent=active?(dashboard.modelVersion||state.modelVersion||"Not recorded"):"No sealed model";
    var batchObservations=[(batchAgents.joy||{}).observations,(batchAgents.kane||{}).observations];
    $("trainObservations").textContent=batchReady&&batchObservations.every(Number.isInteger)?count(Math.min.apply(null,batchObservations)):"—";
    $("trainMode").textContent=batchReady?count(batch.completedCycles)+" / 100":"WAITING";
    $("trainLastRun").textContent=batchReady?date(batch.generatedAt):"—";
    $("trainRunState").textContent=batchReady?"Completed training package · fixed cycle 100":"No eligible batch package published";
    $("joyTrainingCard").innerHTML=agentCard(agents.joy,active);
    $("kaneTrainingCard").innerHTML=agentCard(agents.kane,active);
    $("batchPackageStatus").textContent=String(batch.status||"missing").toUpperCase();
    $("batchPackageSummary").innerHTML=row("Batch ID",batch.id||"—")+row("Package ID",batch.packageId||"—")+
      row("Completed cycles",batchReady?count(batch.completedCycles):"—")+row("Selected cycle",batchReady?count(batch.selectedCycle):"—")+
      row("Selection rule",batchReady?"Fixed final cycle; no best-score selection":"—")+
      row("Archive through",(batch.archive||{}).lastDate||"—")+
      (batchReady?row("Joy batch model",family(batchAgents.joy||{}))+row("Kane batch model",family(batchAgents.kane||{})):row("Package status",batch.reason||"Awaiting a complete qualifying batch"));
    $("deployVersion").textContent=active?(dashboard.modelVersion||state.modelVersion||"Not recorded"):"No current ticket";
    $("runtimeVersion").textContent=dashboard.runtimeVersion||state.runtimeVersion||"Legacy runtime snapshot";
    $("deployIssue").textContent=active?lock.issue:"—";
    $("deployLockDate").textContent=active?"Target draw "+lock.date+" · locked "+date(lock.lockedAt):"Next ticket has not been issued";
    $("deploymentUpdated").textContent="Publication updated "+date(state.generatedAt||dashboard.generatedAt);
    $("candidateStatus").textContent=String(batch.status||"missing").toUpperCase();
    $("candidateDetail").textContent=batchReady?"Batch "+batch.id+" · cycle "+batch.selectedCycle:"No eligible complete batch";
    var labels={awaiting_result:"Awaiting actual draw",awaiting_batch:"Awaiting 100-cycle batch",prediction_locked:"Next prediction locked",blocked:"Publication blocked",legacy_snapshot:"Legacy sealed snapshot"};
    $("gateStatus").textContent=labels[status]||"Unknown publication state";
    $("gateDetail").textContent=gate.reason||"Existing sealed tickets retain their original model provenance.";
    $("lastScoredIssue").textContent=gate.lastScoredIssue||"No live result scored yet";
    archiveStatus("live",next.historyThroughDate,active?"Not recorded":"No prediction");
    archiveStatus("verified",(dashboard.dataCoverage||{}).latestDate,(dashboard.dataCoverage||{}).latestDate?"Published":"Not recorded");
  }

  function evaluationUnavailable(message) {
    $("liveEvalStatus").textContent="UNAVAILABLE";
    $("liveEvalMeta").textContent=message+" Refresh data to retry.";
    $("liveEvalOverview").textContent="";
    $("liveEvalMetrics").textContent="";
    $("liveEvalCohort").disabled=true;
    $("liveEvalRows").innerHTML="<tr><td colspan='7' class='empty-cell'>No verified evaluation available.</td></tr>";
  }
  function cohortLabel(cohort) {
    var identity=cohort.identity||{}, versions=identity.versions||{};
    return (cohort.isCurrent?"Current · ":"")+(versions.joy===versions.kane?versions.joy:versions.joy+" / "+versions.kane)+(identity.engineDigest?" · "+identity.engineDigest.slice(0,8):" · legacy");
  }
  function evalNumber(value,digits) { return typeof value==="number"&&Number.isFinite(value)?number(value,digits):"—"; }
  function evalTail(value) { return typeof value==="number"&&Number.isFinite(value)?(value<0.0001?value.toExponential(2):number(value,4)):"—"; }
  function liveTicket(ticket) {
    return ticket&&Array.isArray(ticket.front)&&Array.isArray(ticket.back)?ticket.front.join(" ")+" | "+ticket.back.join(" "):"—";
  }
  function renderLiveCohort(cohort, baseline) {
    $("liveEvalCohortDetail").textContent=cohortLabel(cohort)+" · "+count(cohort.drawCount)+" scored live draw(s)"+(cohort.drawCount===0?" · Awaiting first actual result":"");
    $("liveEvalMetrics").innerHTML=["joy","kane"].map(function(name){
      var m=cohort.agents[name], ref=m.chanceReference||{}, band=ref.meanReference95;
      var rolling=m.rolling||{};
      return "<div class='panel'><h3>"+esc(name.toUpperCase())+"</h3>"+
        row("Scored draws",count(m.drawCount))+row("Mean front hits",evalNumber(m.meanFrontHits,4)+" / "+evalNumber(baseline.meanFrontHits,4)+" chance")+
        row("Mean back hits",evalNumber(m.meanBackHits,4)+" / "+evalNumber(baseline.meanBackHits,4)+" chance")+
        row("Mean total hits",evalNumber(m.meanTotalHits,4))+row("Delta vs chance",evalNumber(m.deltaVsRandom,4))+
        row("95% chance mean range",Array.isArray(band)?evalNumber(band[0],4)+" to "+evalNumber(band[1],4):"—")+
        row("Tail P (at least observed)",evalTail(ref.oneSidedTailAtLeastObserved))+
        row("Mean NLL",evalNumber(m.meanNegativeLogLikelihood,4)+" · "+count(m.nllDrawCount)+" draw(s)")+
        row("Uniform-ticket NLL",evalNumber(baseline.negativeLogLikelihood,4))+
        row("10 / 30 / 100-draw rolling means",["10","30","100"].map(function(w){return evalNumber((rolling[w]||{}).meanTotalHits,4);}).join(" / "))+
        row("Last angular RMS change (rad)",evalNumber(m.lastParameterShiftRmsRadians,4))+
        row("Comparable snapshot pairs",count(m.parameterComparisons))+"</div>";
    }).join("");
    $("liveEvalRows").innerHTML=cohort.rows.slice().reverse().map(function(r){
      var j=r.agents.joy,k=r.agents.kane;
      function scored(a){return esc(liveTicket(a.ticket))+" · "+esc(a.frontHits+"+"+a.backHits+"="+a.totalHits);}
      return "<tr><td>"+esc(r.issue+" / "+r.date)+"</td><td>"+esc(liveTicket(r.actual))+"</td><td>"+scored(j)+"</td><td>"+scored(k)+"</td><td>"+esc(evalNumber(j.negativeLogLikelihood,4)+" / "+evalNumber(k.negativeLogLikelihood,4))+"</td><td>"+esc(date(r.sealedAt))+"</td><td>"+esc(r.batchId||"Legacy")+"</td></tr>";
    }).join("")||"<tr><td colspan='7' class='empty-cell'>No genuinely scored predictions for this model generation yet.</td></tr>";
  }
  function loadProspective(dashboard) {
    fetchJSON(ROOT+"joy-kane-live-evaluation.json").then(function(report){
      if(!report||report.schemaVersion!==1||report.scope!=="sealed_live_predictions_only"||report.status!=="available")throw new Error("No validated prospective report");
      if(report.generatedAt!==dashboard.generatedAt||(report.archive||{}).sha256!==(dashboard.dataCoverage||{}).archiveSha256||
          report.scoredDrawCount!==(dashboard.summary||{}).drawsEvaluated||report.missingDrawCount!==(dashboard.summary||{}).missingPredictions||
          (report.pending||{}).predictionId!==(dashboard.livePredictionLock||{}).predictionId)throw new Error("Evaluation and live publication do not match");
      if(!Array.isArray(report.cohorts)||!report.baseline||!Array.isArray(report.missingPredictions))throw new Error("Invalid evaluation schema");
      var current=report.cohorts.find(function(c){return c.id===report.currentCohortId&&c.isCurrent===true;});
      if(!current||!report.cohorts.every(function(c){return Array.isArray(c.rows)&&c.agents&&c.agents.joy&&c.agents.kane&&c.drawCount===c.rows.length;}))throw new Error("Invalid cohort records");
      if(report.cohorts.reduce(function(sum,c){return sum+c.drawCount;},0)!==report.scoredDrawCount)throw new Error("Inconsistent evaluation count");
      $("liveEvalStatus").textContent=current.drawCount?"VERIFIED":"AWAITING QUANTUM RESULTS";
      $("liveEvalMeta").textContent="Validated live ledger · archive through "+report.archive.lastDate+" · publication "+date(report.generatedAt)+". Historical simulation scores are separate.";
      var pending=report.pending, pendingCohort=pending&&report.cohorts.find(function(c){return c.id===pending.cohortId;});
      $("liveEvalOverview").innerHTML=row("Genuine live draws scored",count(report.scoredDrawCount))+
        row("Current quantum generation scored",count(current.drawCount))+row("Draws without a prior prediction",count(report.missingDrawCount))+
        row("Pending sealed prediction",pending?pending.issue+" · "+pending.date+(pendingCohort&&pendingCohort.isCurrent?" · current":" · earlier model"):"None")+
        row("Random expected matches",evalNumber(report.baseline.meanTotalHits,6));
      $("liveEvalMissing").textContent=report.missingPredictions.length?"No prior prediction: "+report.missingPredictions.slice(-10).map(function(r){return r.issue+" ("+r.date+")";}).join(", ")+". These draws are excluded from scoring.":"No missing predictions recorded in the live ledger.";
      var select=$("liveEvalCohort");
      select.innerHTML=report.cohorts.map(function(c){return "<option value='"+esc(c.id)+"'>"+esc(cohortLabel(c))+"</option>";}).join("");
      select.disabled=false;select.value=current.id;
      select.addEventListener("change",function(){var selected=report.cohorts.find(function(c){return c.id===select.value;});if(selected)renderLiveCohort(selected,report.baseline);});
      renderLiveCohort(current,report.baseline);
    }).catch(function(){evaluationUnavailable("Prospective evaluation is missing, unavailable or out of sync.");});
  }
  function loadHoldout() {
    var url="https://raw.githubusercontent.com/kanewang0929-ops/feel-the-chee/simulation-data/data/chronological-holdout-report.json";
    fetchJSON(url).then(function(report){
      if(!report.finalTestComparisons||!report.randomBaseline)throw new Error("Unrecognized legacy report");
      var cmp=report.finalTestComparisons, baseline=report.randomBaseline;
      var html=row("Legacy archive draws",count(report.archive&&report.archive.validDrawCount))+row("Random expected hits",number(baseline.theoreticalExpectedTotalHitsPerTicket,6));
      ["joy","kane"].forEach(function(agent){
        var c=cmp[agent]||{}, observed=c.finalTest||{};
        html+=row(agent.toUpperCase()+" legacy final-test average",number(observed.averageTotalHits,6))+row(agent.toUpperCase()+" legacy vs random mean",number(c.differenceVsRandomMean,6));
      });
      $("holdoutMetrics").innerHTML=html;
      var finalTest=(report.split||{}).finalTest||{};
      $("holdoutMeta").textContent="LEGACY MODELS ONLY · "+(report.evaluationVersion||"")+" · "+count(report.split&&report.split.counts&&report.split.counts.finalTestDraws)+" final-test draws"+(finalTest.lastDate?" · through "+finalTest.lastDate:"")+". This report does not evaluate the quantum models.";
    }).catch(function(error){
      $("holdoutMetrics").innerHTML="<p class='muted'>"+(error.status===404?"No legacy holdout report was published.":"The legacy report could not be loaded. Refresh data to retry.")+"</p>";
      $("holdoutMeta").textContent=error.status===404?"Legacy report not published":"Legacy report temporarily unavailable";
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
  Promise.all([fetchJSON(ROOT+"joy-kane-model-state.json"),fetchJSON(ROOT+"joy-kane-dashboard.json")]).then(function(rows){loadTraining(rows[0],rows[1]);loadProspective(rows[1]);}).catch(function(){
    evaluationUnavailable("Live publication is unavailable.");
    $("trainingUpdated").textContent="Model publication unavailable. Refresh data to retry.";
    $("joyTrainingCard").textContent="Unable to verify Joy model provenance.";
    $("kaneTrainingCard").textContent="Unable to verify Kane model provenance.";
    $("deploymentUpdated").textContent="Publication could not be loaded.";
    $("gateStatus").textContent="UNAVAILABLE";
    $("candidateStatus").textContent="UNKNOWN";
    $("batchPackageStatus").textContent="UNKNOWN";
    archiveStatus("live",null,"Unavailable");archiveStatus("verified",null,"Unavailable");
  });
  loadHoldout();
  updateFreshness();
}());
