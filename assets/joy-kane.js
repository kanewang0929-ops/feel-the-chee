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
  const card=document.getElementById("kanePredictionCard");
  if(!card) return;
  const forecast=payload.nextForecast?.kane||{};
  const picks=(forecast.results||[]).filter(validTicket).slice(0,1);
  card.querySelector(".section-head .muted").textContent=
    "使用独立信号与权重，与 Joy 在同一期次比较实际命中。";
  card.querySelector(".forecast-meta").textContent=`第 ${payload.nextForecast?.targetIssue||"—"} 期 · 目标开奖 ${payload.nextForecast?.targetDate||"未记录"}`;
  card.querySelector(".forecast-meta").classList.toggle("is-stale",isPastTarget(payload.nextForecast?.targetDate));
  card.querySelector(".section-head .badge").textContent=`Kane · ${picks.length}组挑战预测`;
  card.querySelector(".forecast-list").innerHTML=picks.length
    ?picks.map(ticket=>jkTicketCard(ticket,"Kane",payload.nextForecast?.targetDate)).join("")
    :`<div class="forecast"><div class="muted">Kane 的预测暂不可用。</div></div>`;
}

function signalWeightHtml(weights){
  return Object.entries(weights||{}).map(([name,value])=>
    `<span class="signal-weight">${name} ${(Number(value)*100).toFixed(1)}%</span>`
  ).join("");
}

function agentLearningHtml(name,state={},stats){
  const title=name==="joy"?"Joy":"Kane";
  const avg=stats||{};
  const wins=state.duel||{};
  return `<div class="card duel-agent-learning">
    <div class="section-head">
      <div>
        <h3>${title} · 独立模型状态</h3>
        <div class="muted">${escapeText(state.modelVersion||"-")} · 已逐期学习 ${Number(state.observations||0).toLocaleString("zh-CN")} 期</div>
      </div>
      <span class="badge ${name==="joy"?"blue":"gold"}">${title}</span>
    </div>
    <div class="weight-grid">
      <div class="weight"><span class="muted">历史单票平均命中</span><strong>${jkNumber(avg.averageBestTotalHits)}</strong></div>
      <div class="weight"><span class="muted">对决胜 / 负 / 平</span><strong>${wins.wins||0} / ${wins.losses||0} / ${wins.ties||0}</strong></div>
      <div class="weight"><span class="muted">探索强度</span><strong>${jkNumber(state.exploration)}</strong></div>
      <div class="weight"><span class="muted">最近回放更新 · 北京时间</span><strong>${escapeText(formatBeijing(state.updatedAt))}</strong></div>
    </div>
    <div class="log-list">
      <div class="log">
        <div class="log-time">前区信号权重</div>
        <div class="signal-weights">${signalWeightHtml(state.weights?.front)}</div>
      </div>
      <div class="log">
        <div class="log-time">后区信号权重</div>
        <div class="signal-weights">${signalWeightHtml(state.weights?.back)}</div>
      </div>
      <div class="log">
        <div class="log-time">自我学习</div>
        <div class="log-body">按时间顺序回放历史开奖：先封存一组预测，再揭示真实结果、计算命中并更新模型状态。百万次参数搜索已移除。</div>
      </div>
    </div>
  </div>`;
}

function renderJoyKaneLearning(payload){
  const root=document.getElementById("joyKaneLearning");
  if(!root) return;
  const summary=payload.summary||{};
  const states=payload.agentStates||{};
  const wins=summary.duelWins||{};
  root.innerHTML=`<div class="section-head">
    <div>
      <h2>Joy & Kane · 双智能体学习中心</h2>
      <div class="muted">这里展示已发布的模型状态。100-simulation 指完整回放历史开奖记录 100 轮；每轮按时间顺序推进，每期先封存双方各一组预测，再揭示结果、评分并分别学习。</div>
    </div>
    <span class="badge gold">${payload.modelVersion||"Joy vs Kane"}</span>
  </div>
  <div class="weight-grid duel-overview">
    <div class="weight"><span class="muted">逐期样本</span><strong>${Number(summary.drawsEvaluated||0).toLocaleString("zh-CN")}</strong></div>
    <div class="weight"><span class="muted">Joy 获胜</span><strong>${Number(wins.joy||0).toLocaleString("zh-CN")}</strong></div>
    <div class="weight"><span class="muted">Kane 获胜</span><strong>${Number(wins.kane||0).toLocaleString("zh-CN")}</strong></div>
    <div class="weight"><span class="muted">平局</span><strong>${Number(wins.tie||0).toLocaleString("zh-CN")}</strong></div>
  </div>
  <div class="duel-agent-grid">
    ${agentLearningHtml("joy",states.joy,summary.joy)}
    ${agentLearningHtml("kane",states.kane,summary.kane)}
  </div>
  <div class="log-list">
    <div class="log">
      <div class="log-time">下期预测已封存</div>
      <div class="log-body">第${payload.livePredictionLock?.issue||payload.nextForecast?.targetIssue||"-"}期 · ${payload.livePredictionLock?.date||payload.nextForecast?.targetDate||"-"} · 封存时间 ${payload.livePredictionLock?.lockedAt||"-"}。开奖结果公布前不会改写这组号码。</div>
    </div>
    <div class="log">
      <div class="log-time">唯一评分标准</div>
      <div class="log-body">每期比较 Joy 与 Kane 各自提前封存的唯一一组号码。前区精确命中数 + 后区精确命中数 = 本期得分。没有曲线拟合分、和值奖励、冷热号奖励或平衡奖励。</div>
    </div>
    <div class="log">
      <div class="log-time">Kane 的方法</div>
      <div class="log-body">Kane 使用近200期频率、出现间隔、理论频率偏差、分布均匀度和 OVERDUE NUMBERS 指标。平衡结构只用于生成候选组合，不计入开奖得分。</div>
    </div>
    <div class="log">
      <div class="log-time">双方协同</div>
      <div class="log-body">每次历史结果揭示后，双方都会看到对手的命中结果，并据此调整自己的探索强度。Joy 与 Kane 的模型权重和训练状态始终分开保存。</div>
    </div>
    <div class="log">
      <div class="log-time">防止未来信息泄漏</div>
      <div class="log-body">每条历史预测均保存训练截止期、SHA-256 历史摘要和封存时间。预测账本与开奖结果账本分开保存，目标期开奖号码只在预测封存后用于评分。</div>
    </div>
    <div class="log">
      <div class="log-time">OVERDUE NUMBERS 注意事项</div>
      <div class="log-body">${payload.method?.overdueCaveat||"遗漏期数描述历史间隔，并不意味着下一期概率提高。公平独立开奖中，遗漏号码不会因为等待更久而变得更容易出现。"}</div>
    </div>
    <div class="log">
      <div class="log-time">历史记录</div>
      <div class="log-body">旧优化日志仅保留为历史记录。当前学习记录以逐期封存预测、真实结果与命中比较为准。</div>
    </div>
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
