/* Adaptive AI + Feel the Chee fusion-agent display. */
const HYBRID_FORECAST_URL="./data/hybrid-forecast.json";
const HYBRID_BACKTEST_URL="./data/hybrid-backtest.json";
let hybridForecastLoaded=false;
let hybridBacktestLoaded=false;

function hybridFetch(url){
  return fetch(`${url}?v=${Date.now()}`,{cache:"no-store"}).then(response=>{
    if(!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  });
}

function hybridBall(number,back=false){
  return `<span class="ball${back?" back":""}">${number}</span>`;
}

function hybridPercent(value){
  const number=Number(value);
  return Number.isFinite(number)?`${(number*100).toFixed(1)}%`:"-";
}

function hybridNumber(value,digits=3){
  const number=Number(value);
  return Number.isFinite(number)?number.toFixed(digits):"-";
}

function mixText(mix={}){
  return `AI独有${mix.aiOnly||0} · 风水独有${mix.cheeOnly||0} · 共识${mix.both||0}`;
}

function sourceTags(result,area){
  const map=result.numberSources?.[area]||{};
  return Object.entries(map).map(([number,sources])=>{
    const label=sources.length===2?"AI+风水":sources[0]==="ai"?"AI":"风水";
    return `<span class="badge ${sources.length===2?"gold":"blue"}">${number} ${label}</span>`;
  }).join(" ");
}

function hybridResultCard(result){
  return `<div class="forecast">
    <div class="forecast-top"><strong>Agent结果 ${result.rank} · ${result.label}</strong><span class="score">融合分 ${Number(result.agentScore||0).toFixed(1)}</span></div>
    <div class="numbers">${result.front.map(number=>hybridBall(number)).join("")}<span class="plus">+</span>${result.back.map(number=>hybridBall(number,true)).join("")}</div>
    <div class="reason">前区：${mixText(result.sourceMix?.front)}；后区：${mixText(result.sourceMix?.back)}。</div>
    <div class="reason">${result.reason||""}</div>
    <div class="reason">${sourceTags(result,"front")} ${sourceTags(result,"back")}</div>
  </div>`;
}

function ensureHybridPredictionCard(){
  const grid=document.querySelector("#prediction .grid");
  if(!grid) return null;
  let card=document.getElementById("hybridAgentCard");
  if(!card){
    card=document.createElement("div");
    card.id="hybridAgentCard";
    card.className="card";
    card.innerHTML=`<div class="section-head"><div><h2>融合 Agent</h2><div class="muted">读取AI与风水候选，按学习后的来源权重自由组合2组结果。</div></div><span class="badge blue">2组结果</span></div><div class="forecast-list"><div class="forecast"><div class="muted">正在运行融合代理...</div></div></div>`;
    grid.appendChild(card);
  }
  return card;
}

function ensureHybridLearningCards(){
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

function renderHybridForecast(payload){
  const card=ensureHybridPredictionCard();
  if(card){
    const description=card.querySelector(".section-head .muted");
    if(description) description.textContent=`第${payload.targetIssue}期 · 来源权重由历史回测和 ${payload.observations||0} 次上线复盘共同决定。`;
    const list=card.querySelector(".forecast-list");
    if(list) list.innerHTML=(payload.results||[]).map(hybridResultCard).join("");
  }

  const {state,logs}=ensureHybridLearningCards();
  const front=payload.sourceWeights?.front||{};
  const back=payload.sourceWeights?.back||{};
  if(state){
    state.innerHTML=`<div class="section-head"><div><h2>融合 Agent 学习</h2><div class="muted">代理可以为每个号码选择AI、风水或双方共识来源，但任何单一来源权重不会低于25%。</div></div><span class="badge blue">${payload.modelVersion||"Fusion Agent"}</span></div>
      <div class="weight-grid">
        <div class="weight"><span class="muted">前区 AI / 风水</span><strong>${hybridPercent(front.ai)} / ${hybridPercent(front.chee)}</strong></div>
        <div class="weight"><span class="muted">后区 AI / 风水</span><strong>${hybridPercent(back.ai)} / ${hybridPercent(back.chee)}</strong></div>
        <div class="weight"><span class="muted">上线复盘次数</span><strong>${Number(payload.observations||0).toLocaleString("zh-CN")}</strong></div>
        <div class="weight"><span class="muted">目标期次</span><strong>${payload.targetIssue||"-"}</strong></div>
      </div>`;
  }
  if(logs){
    const evaluation=payload.lastEvaluation;
    const evaluationHtml=evaluation?`<div class="log"><div class="log-time">第${evaluation.issue}期复盘</div><div><div class="log-title">融合结果与实际开奖已完成比较</div><div class="log-body">实际：${evaluation.actual?.front?.join(" ")} + ${evaluation.actual?.back?.join(" ")}。两组平均前区命中 ${hybridNumber(evaluation.summary?.averageFrontHits)}，后区命中 ${hybridNumber(evaluation.summary?.averageBackHits)}。来源权重已更新。</div></div></div>`:`<div class="log"><div class="log-time">等待开奖</div><div><div class="log-title">首轮上线结果尚未复盘</div><div class="log-body">开奖同步后，代理会保存实际结果、每个号码来源、命中情况、更新前后权重与学习规则。</div></div></div>`;
    logs.innerHTML=`<h3>融合 Agent 后台学习日志</h3><div class="log-list">${evaluationHtml}<div class="log"><div class="log-time">数据存储</div><div><div class="log-title">预测、历史、状态与学习日志分开保存</div><div class="log-body">hybrid-forecast.json · hybrid-history.json · hybrid-model-state.json · hybrid-learning-log.json · hybrid-backtest.json</div></div></div></div>`;
  }
}

function renderHybridBacktest(payload){
  const learning=document.getElementById("learning");
  if(!learning) return;
  document.getElementById("hybridBacktestLoading")?.remove();
  document.getElementById("hybridBacktestSummary")?.remove();
  document.getElementById("hybridBacktestExamples")?.remove();
  const summary=payload.summary||{};
  const observed=summary.observed||{};
  const baseline=summary.theoreticalFixedTicketBaseline||{};
  const source=summary.comparison?.versusSourceModels||{};
  const latest=summary.learningCurve?.at(-1)||{};

  const card=document.createElement("div");
  card.id="hybridBacktestSummary";
  card.className="card";
  card.innerHTML=`<div class="section-head"><div><h2>融合 Agent 历史学习回测</h2><div class="muted">逐期读取当时的AI回测候选和风水公式候选，先生成2组融合结果，再揭示实际开奖并更新权重。</div></div><span class="badge blue">${payload.backtestVersion||"融合回测"}</span></div>
    <div class="weight-grid">
      <div class="weight"><span class="muted">回测期数</span><strong>${Number(summary.drawsEvaluated||0).toLocaleString("zh-CN")}</strong></div>
      <div class="weight"><span class="muted">融合票数</span><strong>${Number(summary.ticketsEvaluated||0).toLocaleString("zh-CN")}</strong></div>
      <div class="weight"><span class="muted">平均前区命中</span><strong>${hybridNumber(observed.averageFrontHitsPerTicket)}</strong></div>
      <div class="weight"><span class="muted">平均后区命中</span><strong>${hybridNumber(observed.averageBackHitsPerTicket)}</strong></div>
    </div>
    <div class="log-list">
      <div class="log"><div class="log-time">公平基准</div><div><div class="log-title">随机单票：前区 ${hybridNumber(baseline.averageFrontHitsPerTicket)}，后区 ${hybridNumber(baseline.averageBackHitsPerTicket)}</div><div class="log-body">融合Agent：前区 ${hybridNumber(observed.averageFrontHitsPerTicket)}，后区 ${hybridNumber(observed.averageBackHitsPerTicket)}。结果只描述历史行为，不代表未来中奖概率。</div></div></div>
      <div class="log"><div class="log-time">来源对比</div><div><div class="log-title">AI、风水与融合结果并列审计</div><div class="log-body">AI：${hybridNumber(source.ai?.averageFrontHits)} + ${hybridNumber(source.ai?.averageBackHits)}；风水：${hybridNumber(source.chee?.averageFrontHits)} + ${hybridNumber(source.chee?.averageBackHits)}；融合：${hybridNumber(observed.averageFrontHitsPerTicket)} + ${hybridNumber(observed.averageBackHitsPerTicket)}。</div></div></div>
      <div class="log"><div class="log-time">学习曲线</div><div><div class="log-title">最近快照：第${latest.issue||"-"}期</div><div class="log-body">前区 AI / 风水：${hybridPercent(latest.sourceWeights?.front?.ai)} / ${hybridPercent(latest.sourceWeights?.front?.chee)}；后区 AI / 风水：${hybridPercent(latest.sourceWeights?.back?.ai)} / ${hybridPercent(latest.sourceWeights?.back?.chee)}。</div></div></div>
    </div>`;
  learning.appendChild(card);

  const examples=(summary.bestExamples||[]).slice(0,10);
  const exampleCard=document.createElement("div");
  exampleCard.id="hybridBacktestExamples";
  exampleCard.className="card";
  exampleCard.innerHTML=`<h3>融合 Agent 历史最佳案例</h3><div style="overflow:auto"><table><thead><tr><th>期次</th><th>日期</th><th>实际号码</th><th>最佳融合结果</th><th>命中</th><th>来源组合</th></tr></thead><tbody>${examples.map(example=>{
    const tickets=example.evaluation?.results||[];
    const best=tickets.slice().sort((a,b)=>(b.frontHitCount+b.backHitCount)-(a.frontHitCount+a.backHitCount))[0]||{};
    const mix=best.sourceMix?.front||{};
    return `<tr><td>${example.issue}</td><td>${example.date}</td><td>${example.actual?.front?.join(" ")} + ${example.actual?.back?.join(" ")}</td><td>${best.front?.join(" ")} + ${best.back?.join(" ")}</td><td>${best.frontHitCount||0}+${best.backHitCount||0}</td><td>${mixText(mix)}</td></tr>`;
  }).join("")}</tbody></table></div>`;
  learning.appendChild(exampleCard);
}

async function loadHybridForecast(){
  if(hybridForecastLoaded) return;
  hybridForecastLoaded=true;
  ensureHybridPredictionCard();
  try{renderHybridForecast(await hybridFetch(HYBRID_FORECAST_URL))}
  catch(error){console.warn("Hybrid forecast unavailable",error)}
}

async function loadHybridBacktest(){
  if(hybridBacktestLoaded) return;
  hybridBacktestLoaded=true;
  const learning=document.getElementById("learning");
  if(!learning) return;
  const loading=document.createElement("div");
  loading.id="hybridBacktestLoading";
  loading.className="card";
  loading.innerHTML=`<h2>融合 Agent 历史学习回测</h2><div class="muted">正在读取逐期融合、命中比较和学习曲线...</div>`;
  learning.appendChild(loading);
  try{renderHybridBacktest(await hybridFetch(HYBRID_BACKTEST_URL))}
  catch(error){
    console.warn("Hybrid backtest unavailable",error);
    loading.innerHTML=`<h2>融合 Agent 历史学习回测</h2><div class="muted">首次全历史模拟正在生成。完成后这里会显示融合Agent与AI、风水及公平随机基准的对比。</div>`;
  }
}

document.querySelectorAll(".tab").forEach(button=>{
  if(button.dataset.page==="learning") button.addEventListener("click",loadHybridBacktest);
});

loadHybridForecast();
