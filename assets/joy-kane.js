/* Joy and Kane front-end: independent forecasts, learning states, and draw audit. */
const JOY_KANE_DASHBOARD_URL="./data/joy-kane-dashboard.json";
const JOY_KANE_AUDIT_URL="./data/joy-kane-audit.json";
let joyKaneDashboard=null;
let joyKaneAuditRows=[];
let joyKaneAuditPage=1;
const joyKaneAuditPageSize=20;

async function joyKaneFetch(url){
  const response=await fetch(`${url}?v=${Date.now()}`,{cache:"no-store"});
  if(!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

function jkNumber(value,digits=3){
  const number=Number(value);
  return Number.isFinite(number)?number.toFixed(digits):"-";
}

function jkBall(value,back=false){
  return `<span class="ball${back?" back":""}">${escapeText(String(value).padStart(2,"0"))}</span>`;
}

function jkTicketCard(ticket,agentName,targetDate){
  return `<div class="forecast">
    <div class="forecast-top">
      <strong>${isPastTarget(targetDate)?"历史号码":"目标号码"} · ${escapeText(ticket.label||agentName+" Main")}</strong>
      <span class="score">5 个前区 + 2 个后区</span>
    </div>
    <div class="numbers">
      ${(ticket.front||[]).map(n=>jkBall(n)).join("")}
      <span class="plus">+</span>
      ${(ticket.back||[]).map(n=>jkBall(n,true)).join("")}
    </div>
  </div>`;
}

function renderKaneForecast(payload){
  renderAgentForecast(payload,"kane");
}

function agentLearningHtml(name,state={}){
  const title=name==="joy"?"Joy":"Kane";
  const label=modelDescriptor(state);
  const observations=Number.isInteger(state.observations)?state.observations.toLocaleString("zh-CN"):"未记录";
  return `<div class="card duel-agent-learning">
    <div class="section-head"><div><h3>${title} · 当前封存模型</h3><div class="muted">${escapeText(label)} · ${escapeText(state.modelVersion||"未记录")}</div></div></div>
    <div class="weight-grid">
      <div class="weight"><span class="muted">训练观察数</span><strong>${observations}</strong></div>
      <div class="weight"><span class="muted">执行方式</span><strong>${escapeText(state.backend==="classical_statevector"?"经典计算机模拟":state.backend==="legacy_classical"?"既有经典模型":"未记录")}</strong></div>
    </div>
  </div>`;
}

function renderJoyKaneLearning(payload){
  const root=document.getElementById("joyKaneLearning");
  if(!root) return;
  const states=payload.agentStates||{}, batch=payload.trainedBatch||{};
  root.innerHTML=`<div class="section-head"><div>
    <h2>Joy & Kane · 100 轮历史学习</h2>
    <div class="muted">100-simulation 指完整回放历史开奖记录 100 轮。每轮从独立初始状态开始，先预测、封存，再揭示结果、评分和更新。固定使用第 100 轮的最终状态生成后续预测。</div>
  </div></div>
  <div class="duel-agent-grid">${agentLearningHtml("joy",states.joy)}${agentLearningHtml("kane",states.kane)}</div>
  <div class="log-list">
    <div class="log"><div class="log-time">训练批次</div><div class="log-body">${escapeText(batch.status==="ready"?`${batch.id} · 已完成 ${batch.completedCycles} 轮 · 使用第 ${batch.selectedCycle} 轮`:"尚无符合条件的完整训练批次")}</div></div>
    <div class="log"><div class="log-time">训练目标与评分</div><div class="log-body">只在仿真中揭示实际结果后，按无序整票的负对数似然更新参数。公开预测得分仍为前区命中数加后区命中数。</div></div>
    <div class="log"><div class="log-time">发布顺序</div><div class="log-body">核对当前封存预测与实际结果，记录比较，再等待包含该结果的完整 100 轮训练，最后生成并封存下一期号码。等待时不会生成替代号码。</div></div>
  </div>`;
}

function auditTicketHtml(ticket,agent){
  const front=(ticket.front||[]).map(n=>jkBall(n)).join("");
  const back=(ticket.back||[]).map(n=>jkBall(n,true)).join("");
  return `<div class="audit-ticket">
    <div class="audit-ticket-head">${agent} ${ticket.rank||""}</div>
    <div class="numbers">${front}<span class="plus">+</span>${back}</div>
    <div class="audit-hit">前区 ${ticket.frontHitCount||0} 命中 · 后区 ${ticket.backHitCount||0} 命中 · <strong>合计 ${ticket.totalHitCount||0}</strong></div>
  </div>`;
}

function auditAgentCell(metrics,agent){
  return `<div class="audit-agent-cell">
    ${(metrics?.tickets||[]).map(ticket=>auditTicketHtml(ticket,agent)).join("")}
    <div class="audit-best">本期得分：${metrics?.bestFrontHits||0}+${metrics?.bestBackHits||0} = ${metrics?.bestTotalHits||0}</div>
  </div>`;
}

function renderJoyKaneAudit(){
  const root=document.getElementById("joyKaneAudit");
  if(!root) return;
  const query=(document.getElementById("joyKaneAuditSearch")?.value||"").trim().toLowerCase();
  const rows=[...joyKaneAuditRows].reverse().filter(row=>
    !query||String(row.issue).toLowerCase().includes(query)||String(row.date).includes(query)
  );
  const pages=Math.max(1,Math.ceil(rows.length/joyKaneAuditPageSize));
  joyKaneAuditPage=Math.min(joyKaneAuditPage,pages);
  const pageRows=rows.slice((joyKaneAuditPage-1)*joyKaneAuditPageSize,joyKaneAuditPage*joyKaneAuditPageSize);
  root.innerHTML=`<div class="section-head">
    <div>
      <h2>Draw-by-draw audit · 逐期开奖封存审计</h2>
      <div class="muted">每行展示开奖前封存的 Joy 与 Kane 各一组预测、实际号码、命中数及本期胜者。最新期次在最上方。</div>
    </div>
    <span class="badge blue">${rows.length.toLocaleString("zh-CN")} 条记录</span>
  </div>
  <div class="toolbar">
    <input id="joyKaneAuditSearch" class="search" placeholder="搜索期次或日期" value="${query.replace(/"/g,"&quot;")}">
    <div class="muted">每页 ${joyKaneAuditPageSize} 期 · 预测封存后才揭晓</div>
  </div>
  <div class="audit-wrap">
    <table class="audit-table">
      <thead><tr><th>期次 / 日期</th><th>实际开奖号码</th><th>Joy · 1组预测及命中</th><th>Kane · 1组预测及命中</th><th>本期胜者</th></tr></thead>
      <tbody>${pageRows.map(row=>`<tr>
        <td><strong>${row.issue}</strong><div class="muted">${row.date}</div><div class="audit-cutoff">训练截止 ${row.trainingThroughIssue||"-"}</div><div class="audit-cutoff">${row.usedLivePredictionLock?"真实预测封存":"历史逐期回放"}</div></td>
        <td><div class="numbers">${(row.actual?.front||[]).map(n=>jkBall(n)).join("")}<span class="plus">+</span>${(row.actual?.back||[]).map(n=>jkBall(n,true)).join("")}</div></td>
        <td>${auditAgentCell(row.joy,"Joy")}</td>
        <td>${auditAgentCell(row.kane,"Kane")}</td>
        <td><span class="badge ${row.winner==="joy"?"blue":row.winner==="kane"?"gold":""}">${row.winner==="joy"?"Joy":row.winner==="kane"?"Kane":"平局"}</span></td>
      </tr>`).join("")||`<tr><td colspan="5">没有找到匹配的审计记录。</td></tr>`}</tbody>
    </table>
  </div>
  <div class="pager">
    <button id="joyKaneAuditPrev" ${joyKaneAuditPage<=1?"disabled":""}>‹</button>
    <span class="muted">第 ${joyKaneAuditPage} / ${pages} 页</span>
    <button id="joyKaneAuditNext" ${joyKaneAuditPage>=pages?"disabled":""}>›</button>
  </div>`;
  root.querySelector("#joyKaneAuditSearch")?.addEventListener("input",()=>{
    joyKaneAuditPage=1;
    renderJoyKaneAudit();
    const input=document.getElementById("joyKaneAuditSearch");
    input?.focus();
    if(input) input.setSelectionRange(input.value.length,input.value.length);
  });
  root.querySelector("#joyKaneAuditPrev")?.addEventListener("click",()=>{
    joyKaneAuditPage=Math.max(1,joyKaneAuditPage-1);
    renderJoyKaneAudit();
  });
  root.querySelector("#joyKaneAuditNext")?.addEventListener("click",()=>{
    joyKaneAuditPage=Math.min(pages,joyKaneAuditPage+1);
    renderJoyKaneAudit();
  });
}

async function loadJoyKane(){
  try{
    joyKaneDashboard=await loadDuelPayload();
    renderKaneForecast(joyKaneDashboard);
    renderJoyKaneLearning(joyKaneDashboard);
  }catch(error){
    console.warn("Joy/Kane dashboard unavailable",error);
    const card=document.getElementById("kanePredictionCard");
    if(card) card.querySelector(".forecast-list").innerHTML=`<div class="forecast"><div class="muted">Kane 的预测暂不可用，请检查后台运行记录。</div></div>`;
    if(card) card.querySelector(".forecast-meta").textContent="目标期次暂不可用";
  }

  // The public homepage has no audit table. Avoid downloading its full ledger.
  if(!document.getElementById("joyKaneAudit")) return;
  try{
    const audit=await joyKaneFetch(JOY_KANE_AUDIT_URL);
    joyKaneAuditRows=Array.isArray(audit.rows)?audit.rows:[];
    renderJoyKaneAudit();
  }catch(error){
    console.warn("Joy/Kane audit unavailable",error);
    const root=document.getElementById("joyKaneAudit");
    if(root) root.innerHTML=`<h2>逐期开奖封存审计</h2><div class="muted">审计数据暂不可用，请检查后台账本。</div>`;
  }
}

loadJoyKane();
