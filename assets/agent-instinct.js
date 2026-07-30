/* Three-source Agent display: AI + 风水 + Agent Instinct. */
const AGENT_FORECAST_URL="./data/hybrid-forecast.json";
const AGENT_BACKTEST_URL="./data/hybrid-backtest.json";
const AGENT_SIMULATION_LOG_URL="./data/hybrid-simulation-log.json";

let agentForecastLoaded=false;
let agentBacktestLoaded=false;
let agentSimulationLoaded=false;

function agentFetch(url){
  return fetch(`${url}?v=${Date.now()}`,{cache:"no-store"}).then(response=>{
    if(!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  });
}

function agentBall(number,back=false){
  return `<span class="ball${back?" back":""}">${number}</span>`;
}

function agentNumber(value,digits=3){
  const number=Number(value);
  return Number.isFinite(number)?number.toFixed(digits):"-";
}

function agentPercent(value){
  const number=Number(value);
  return Number.isFinite(number)?`${(number*100).toFixed(1)}%`:"-";
}

function sourceLabel(sources=[]){
  const key=[...sources].sort().join("+");
  const labels={
    "ai":"AI",
    "chee":"风水",
    "instinct":"直觉",
    "ai+chee":"AI+风水",
    "ai+instinct":"AI+直觉",
    "chee+instinct":"风水+直觉",
    "ai+chee+instinct":"三方共振"
  };
  return labels[key]||"Agent";
}

function sourceTags(result,area){
  const map=result.numberSources?.[area]||{};
  return Object.entries(map)
    .map(([number,sources])=>`<span class="badge ${sources.includes("instinct")?"gold":"blue"}">${number} ${sourceLabel(sources)}</span>`)
    .join(" ");
}

function instinctCount(result,area){
  const map=result.numberSources?.[area]||{};
  return Object.values(map).filter(sources=>sources.includes("instinct")).length;
}

function agentResultCard(result){
  const instinctFront=instinctCount(result,"front");
  const instinctBack=instinctCount(result,"back");
  return `<div class="forecast">
    <div class="forecast-top">
      <strong>Agent结果 ${result.rank} · ${result.label}</strong>
      <span class="score">融合分 ${Number(result.agentScore||0).toFixed(1)}</span>
    </div>
    <div class="numbers">
      ${(result.front||[]).map(number=>agentBall(number)).join("")}
      <span class="plus">+</span>
      ${(result.back||[]).map(number=>agentBall(number,true)).join("")}
    </div>
    <div class="reason">Agent直觉参与：前区 ${instinctFront} 个，后区 ${instinctBack} 个。</div>
    <div class="reason">${result.instinctStatement||"Agent 直觉落子，不展开推理。"}</div>
    <div class="reason">${sourceTags(result,"front")} ${sourceTags(result,"back")}</div>
  </div>`;
}

function ensureAgentCard(){
  const grid=document.querySelector("#prediction .grid");
  if(!grid) return null;
  let card=document.getElementById("hybridAgentCard");
  if(!card){
    card=document.createElement("div");
    card.id="hybridAgentCard";
    card.className="card";
    grid.insertBefore(card,grid.firstChild);
  }
  return card;
}

function ensureAgentLearning(){
  const learning=document.getElementById("learning");
  if(!learning) return {};
  let state=document.getElementById("hybridAgentLearning");
  let logs=document.getElementById("hybridAgentLogs");

  if(!state){
    state=document.createElement("div");
    state.id="hybridAgentLearning";
    state.className="card";
    learning.insertBefore(state,learning.firstChild);
  }

  if(!logs){
    logs=document.createElement("div");
    logs.id="hybridAgentLogs";
    logs.className="card";
    learning.insertBefore(logs,state.nextSibling);
  }
  return {state,logs};
}

function renderAgentForecast(payload){
  const card=ensureAgentCard();
  const results=Array.isArray(payload.results)?payload.results.slice(0,2):[];

  if(card){
    card.innerHTML=`<div class="section-head">
      <div>
        <h2>融合 Agent · 下期精选</h2>
        <div class="muted">第${payload.targetIssue}期 · AI、风水与Agent直觉三源权重共同生成2组结果。</div>
      </div>
      <span class="badge gold">2组结果 · Agent Instinct</span>
    </div>
    <div class="forecast-list">${
      results.length
        ?results.map(agentResultCard).join("")
        :`<div class="forecast"><div class="muted">Agent结果暂不可用。</div></div>`
    }</div>`;
  }

  const {state,logs}=ensureAgentLearning();
  const front=payload.sourceWeights?.front||{};
  const back=payload.sourceWeights?.back||{};

  if(state){
    state.innerHTML=`<div class="section-head">
      <div>
        <h2>融合 Agent 学习</h2>
        <div class="muted">Agent直觉是独立探索源。AI、风水、直觉均保留有边界的影响力。</div>
      </div>
      <span class="badge gold">${payload.modelVersion||"Agent Instinct"}</span>
    </div>
    <div class="weight-grid">
      <div class="weight"><span class="muted">前区 AI / 风水 / 直觉</span><strong>${agentPercent(front.ai)} / ${agentPercent(front.chee)} / ${agentPercent(front.instinct)}</strong></div>
      <div class="weight"><span class="muted">后区 AI / 风水 / 直觉</span><strong>${agentPercent(back.ai)} / ${agentPercent(back.chee)} / ${agentPercent(back.instinct)}</strong></div>
      <div class="weight"><span class="muted">历史复盘</span><strong>${Number(payload.observations||0).toLocaleString("zh-CN")}</strong></div>
      <div class="weight"><span class="muted">目标期次</span><strong>${payload.targetIssue||"-"}</strong></div>
    </div>`;
  }

  if(logs){
    const evaluation=payload.lastEvaluation;
    const evaluationHtml=evaluation?`<div class="log">
      <div class="log-time">第${evaluation.issue}期复盘</div>
      <div>
        <div class="log-title">Agent结果已与实际开奖比较</div>
        <div class="log-body">实际：${evaluation.actual?.front?.join(" ")} + ${evaluation.actual?.back?.join(" ")}。两组平均前区命中 ${agentNumber(evaluation.summary?.averageFrontHits)}，后区命中 ${agentNumber(evaluation.summary?.averageBackHits)}。三源权重已更新。</div>
      </div>
    </div>`:`<div class="log">
      <div class="log-time">等待开奖</div>
      <div>
        <div class="log-title">当前Agent结果尚未复盘</div>
        <div class="log-body">开奖后将保存每个直觉号码、命中情况及三源权重变化。</div>
      </div>
    </div>`;

    logs.innerHTML=`<h3>Agent Instinct 后台日志</h3>
      <div class="log-list">
        ${evaluationHtml}
        <div class="log">
          <div class="log-time">直觉策略</div>
          <div>
            <div class="log-title">选择保留，推理不展开</div>
            <div class="log-body">系统记录随机种子版本、号码来源、历史表现和权重变化，但不生成伪装成直觉的长篇解释。</div>
          </div>
        </div>
      </div>`;
  }
}

function ensureAgentSimulationCard(){
  const learning=document.getElementById("learning");
  if(!learning) return null;
  let card=document.getElementById("agentDailySimulationLog");
  if(!card){
    card=document.createElement("div");
    card.id="agentDailySimulationLog";
    card.className="card";
    const logs=document.getElementById("hybridAgentLogs");
    if(logs?.nextSibling) learning.insertBefore(card,logs.nextSibling);
    else learning.appendChild(card);
  }
  return card;
}

function latestInstinctSimulation(rows){
  if(!Array.isArray(rows)) return null;
  return [...rows].reverse().find(row=>
    row?.eventType==="agent-instinct-simulation-learning"||
    String(row?.modelVersion||"").includes("intuitive")
  )||null;
}

function renderAgentSimulationLog(rows){
  const card=ensureAgentSimulationCard();
  if(!card) return;
  const latest=latestInstinctSimulation(rows);

  if(!latest){
    card.innerHTML=`<h3>Agent Instinct 每日模拟日志</h3>
      <div class="log-list">
        <div class="log">
          <div class="log-time">等待运行</div>
          <div>
            <div class="log-title">尚未找到Agent每日模拟记录</div>
            <div class="log-body">计划任务完成后，这里会显示回测期数、票数、命中均值及三源权重变化。</div>
          </div>
        </div>
      </div>`;
    return;
  }

  const after=latest.weightsAfter||latest.weightsAfter?.source||{};
  const sourceAfter=after.source||after;
  const front=sourceAfter.front||{};
  const back=sourceAfter.back||{};
  const generatedAt=latest.generatedAt?new Date(latest.generatedAt).toLocaleString("zh-CN",{hour12:false}):"-";

  card.innerHTML=`<div class="section-head">
    <div>
      <h2>Agent Instinct 每日模拟日志</h2>
      <div class="muted">每天随AI回测与风水审计一起运行，并把模拟结果与权重变化写入后端数据库。</div>
    </div>
    <span class="badge gold">最近运行 ${generatedAt}</span>
  </div>
  <div class="weight-grid">
    <div class="weight"><span class="muted">模拟期数</span><strong>${Number(latest.drawsEvaluated||0).toLocaleString("zh-CN")}</strong></div>
    <div class="weight"><span class="muted">Agent票数</span><strong>${Number(latest.ticketsEvaluated||0).toLocaleString("zh-CN")}</strong></div>
    <div class="weight"><span class="muted">平均前区命中</span><strong>${agentNumber(latest.averageFrontHits)}</strong></div>
    <div class="weight"><span class="muted">平均后区命中</span><strong>${agentNumber(latest.averageBackHits)}</strong></div>
  </div>
  <div class="log-list">
    <div class="log">
      <div class="log-time">权重写回</div>
      <div>
        <div class="log-title">AI / 风水 / 直觉</div>
        <div class="log-body">前区：${agentPercent(front.ai)} / ${agentPercent(front.chee)} / ${agentPercent(front.instinct)}；后区：${agentPercent(back.ai)} / ${agentPercent(back.chee)} / ${agentPercent(back.instinct)}。</div>
      </div>
    </div>
    <div class="log">
      <div class="log-time">后端存储</div>
      <div>
        <div class="log-title">hybrid-simulation-log.json</div>
        <div class="log-body">保留每次Agent模拟的运行时间、模型版本、回测规模、命中均值、更新前后权重与策略权重。</div>
      </div>
    </div>
  </div>`;
}

function renderAgentBacktest(payload){
  const learning=document.getElementById("learning");
  if(!learning) return;

  document.getElementById("hybridBacktestLoading")?.remove();
  document.getElementById("hybridBacktestSummary")?.remove();

  const summary=payload.summary||{};
  const observed=summary.observed||{};
  const baseline=summary.theoreticalFixedTicketBaseline||{};
  const sources=summary.comparison?.sourcePerformance||{};
  const latest=summary.learningCurve?.at(-1)||{};

  const card=document.createElement("div");
  card.id="hybridBacktestSummary";
  card.className="card";
  card.innerHTML=`<div class="section-head">
    <div>
      <h2>Agent Instinct 历史学习回测</h2>
      <div class="muted">逐期先生成AI、风水和独立直觉号码，再揭示实际开奖并更新三源权重。</div>
    </div>
    <span class="badge gold">${payload.backtestVersion||"直觉回测"}</span>
  </div>
  <div class="weight-grid">
    <div class="weight"><span class="muted">回测期数</span><strong>${Number(summary.drawsEvaluated||0).toLocaleString("zh-CN")}</strong></div>
    <div class="weight"><span class="muted">Agent票数</span><strong>${Number(summary.ticketsEvaluated||0).toLocaleString("zh-CN")}</strong></div>
    <div class="weight"><span class="muted">平均前区命中</span><strong>${agentNumber(observed.averageFrontHitsPerTicket)}</strong></div>
    <div class="weight"><span class="muted">平均后区命中</span><strong>${agentNumber(observed.averageBackHitsPerTicket)}</strong></div>
  </div>
  <div class="log-list">
    <div class="log">
      <div class="log-time">三源对比</div>
      <div>
        <div class="log-title">AI · 风水 · Agent直觉</div>
        <div class="log-body">AI：${agentNumber(sources.ai?.averageFrontHits)} + ${agentNumber(sources.ai?.averageBackHits)}；风水：${agentNumber(sources.chee?.averageFrontHits)} + ${agentNumber(sources.chee?.averageBackHits)}；直觉：${agentNumber(sources.instinct?.averageFrontHits)} + ${agentNumber(sources.instinct?.averageBackHits)}。</div>
      </div>
    </div>
    <div class="log">
      <div class="log-time">公平基准</div>
      <div>
        <div class="log-title">随机固定单票：${agentNumber(baseline.averageFrontHitsPerTicket)} + ${agentNumber(baseline.averageBackHitsPerTicket)}</div>
        <div class="log-body">历史回测只衡量过去表现，不将Agent直觉包装成未来中奖概率。</div>
      </div>
    </div>
    <div class="log">
      <div class="log-time">最新权重</div>
      <div>
        <div class="log-title">第${latest.issue||"-"}期学习快照</div>
        <div class="log-body">前区直觉 ${agentPercent(latest.sourceWeights?.front?.instinct)}；后区直觉 ${agentPercent(latest.sourceWeights?.back?.instinct)}。</div>
      </div>
    </div>
  </div>`;
  learning.appendChild(card);
}

async function loadAgentForecast(){
  if(agentForecastLoaded) return;
  agentForecastLoaded=true;
  try{
    renderAgentForecast(await agentFetch(AGENT_FORECAST_URL));
  }catch(error){
    console.warn("Agent forecast unavailable",error);
    const list=document.querySelector("#hybridAgentCard .forecast-list");
    if(list) list.innerHTML=`<div class="forecast"><div class="muted">Agent结果加载失败，请稍后刷新。</div></div>`;
  }
}

async function loadAgentSimulationLog(){
  if(agentSimulationLoaded) return;
  agentSimulationLoaded=true;
  try{
    renderAgentSimulationLog(await agentFetch(AGENT_SIMULATION_LOG_URL));
  }catch(error){
    console.warn("Agent simulation log unavailable",error);
    renderAgentSimulationLog([]);
  }
}

async function loadAgentBacktest(){
  if(agentBacktestLoaded) return;
  agentBacktestLoaded=true;
  const learning=document.getElementById("learning");
  if(!learning) return;

  const loading=document.createElement("div");
  loading.id="hybridBacktestLoading";
  loading.className="card";
  loading.innerHTML=`<h2>Agent Instinct 历史学习回测</h2><div class="muted">正在读取三源逐期模拟...</div>`;
  learning.appendChild(loading);

  try{
    renderAgentBacktest(await agentFetch(AGENT_BACKTEST_URL));
  }catch(error){
    console.warn("Agent backtest unavailable",error);
    loading.innerHTML=`<h2>Agent Instinct 历史学习回测</h2><div class="muted">三源模拟结果暂不可用。</div>`;
  }
}

document.querySelectorAll(".tab").forEach(button=>{
  if(button.dataset.page==="learning"){
    button.addEventListener("click",()=>{
      loadAgentSimulationLog();
      loadAgentBacktest();
    });
  }
});

loadAgentForecast();
loadAgentSimulationLog();
