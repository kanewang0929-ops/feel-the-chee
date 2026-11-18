/* Three-source Agent display: AI + 风水 + Agent Instinct. */
const AGENT_FORECAST_URL="./data/walk-forward-agent.json";
const AGENT_BACKTEST_URL="./data/walk-forward-agent.json";
const AGENT_SIMULATION_LOG_URL="./data/walk-forward-agent.json";

let agentForecastLoaded=false;
let agentBacktestLoaded=false;
let agentSimulationLoaded=false;

function agentFetch(url){
  return fetch(`${url}?v=${Date.now()}`,{cache:"no-store"}).then(response=>{
    if(!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  });
}

function walkForwardAgentView(payload){
  const next=payload.nextForecast||{};
  const forecast=next.agent||{};
  const state=next.agentState||payload.finalState?.agentLiveState||{};
  const latest=payload.draws?.at(-1)||null;
  const evaluation=latest?.evaluation?.agent||null;
  return {
    ...forecast,
    targetIssue:next.targetIssue||forecast.targetIssue,
    targetDate:next.targetDate||forecast.targetDate,
    sourceWeights:forecast.sourceWeights||state.sourceWeights||{},
    strategyWeights:forecast.strategyWeights||state.strategyWeights||{},
    observations:state.observations||payload.summary?.drawsEvaluated||0,
    lastEvaluation:forecast.lastEvaluation||(latest?{
      issue:latest.issue,
      actual:latest.actual,
      summary:{
        averageFrontHits:evaluation?.averageFrontHitsPerTicket,
        averageBackHits:evaluation?.averageBackHitsPerTicket
      }
    }:null),
    modelVersion:payload.modelVersion||forecast.modelVersion,
    results:forecast.results||[]
  };
}

function walkForwardSimulationView(payload){
  const summary=payload.summary||{};
  const state=payload.nextForecast?.agentState||payload.finalState?.agentLiveState||{};
  return {
    eventType:"agent-instinct-simulation-learning",
    generatedAt:payload.generatedAt,
    drawsEvaluated:summary.drawsEvaluated||0,
    ticketsEvaluated:summary.agent?.ticketsEvaluated||summary.ticketsEvaluated||0,
    averageFrontHits:summary.agent?.averageFrontHitsPerTicket||0,
    averageBackHits:summary.agent?.averageBackHitsPerTicket||0,
    weightsAfter:{source:state.sourceWeights||{},strategy:state.strategyWeights||{}}
  };
}

function walkForwardBacktestView(payload){
  const summary=payload.summary||{};
  return {
    backtestVersion:payload.modelVersion,
    predictionLocks:summary.predictionLocks||0,
    futureLeakage:payload.futureLeakage===false,
    summary:{
      drawsEvaluated:summary.drawsEvaluated||0,
      ticketsEvaluated:summary.ticketsEvaluated||0,
      observed:summary.observed||{},
      theoreticalFixedTicketBaseline:summary.theoreticalFixedTicketBaseline||{},
      comparison:summary.comparison||{}
    },
    learningCurve:payload.learningCurve||[],
    method:payload.method||{}
  };
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
        <h2>Walk-forward Agent · 下期精选</h2>
        <div class="muted">第${payload.targetIssue}期 · 逐期模拟后更新模型，先锁定预测再揭示开奖。</div>
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
      <h2>Walk-forward Agent 逐期模拟日志</h2>
      <div class="muted">按历史期次逐期回放。每期预测先写入独立账本，开奖结果随后才进入评分与学习。</div>
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
        <div class="log-title">walk-forward-agent-predictions.jsonl</div>
        <div class="log-body">只保存开奖揭示前的预测、历史数据截止期与SHA-256摘要；评分和学习结果另存于模拟记录。</div>
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
      <h2>Agent 严格逐期历史模拟</h2>
      <div class="muted">每期只使用此前开奖结果生成预测。预测写入账本后，才揭示当期结果并更新后续模型。</div>
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
      <div class="log-time">无未来信息泄漏</div>
      <div>
        <div class="log-title">已锁定 ${Number(payload.predictionLocks||summary.drawsEvaluated||0).toLocaleString("zh-CN")} 条历史预测</div>
        <div class="log-body">每条记录都保存训练数据截止期与历史数据摘要。目标期开奖号码只在预测写入账本后用于评分。</div>
      </div>
    </div>
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
    const payload=await agentFetch(AGENT_FORECAST_URL);
    renderAgentForecast(walkForwardAgentView(payload));
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
    const payload=await agentFetch(AGENT_SIMULATION_LOG_URL);
    renderAgentSimulationLog([walkForwardSimulationView(payload)]);
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
  loading.innerHTML=`<h2>Agent 严格逐期历史模拟</h2><div class="muted">正在读取预测封存账本与逐期评分...</div>`;
  learning.appendChild(loading);

  try{
    const payload=await agentFetch(AGENT_BACKTEST_URL);
    renderAgentBacktest(walkForwardBacktestView(payload));
  }catch(error){
    console.warn("Agent backtest unavailable",error);
    loading.innerHTML=`<h2>Agent 严格逐期历史模拟</h2><div class="muted">模拟结果暂不可用，请检查最新运行记录。</div>`;
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
