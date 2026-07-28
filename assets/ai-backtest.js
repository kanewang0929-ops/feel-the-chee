/* Walk-forward AI curve backtest display. */
const AI_BACKTEST_URL="./data/ai-backtest.json";
let aiBacktestLoaded=false;

function aiAuditNumber(value,digits=3){
  const number=Number(value);
  return Number.isFinite(number)?number.toFixed(digits):"-";
}

function aiAuditDelta(observed,baseline){
  const difference=Number(observed)-Number(baseline);
  const sign=difference>0?"+":"";
  return `${sign}${difference.toFixed(4)}`;
}

function aiAuditBestTicket(example){
  return example.tickets?.find(
    ticket=>ticket.rank===example.bestTicket?.rank
  )||example.tickets?.[0];
}

function aiAuditLossChange(model,baseline){
  const modelValue=Number(model);
  const baselineValue=Number(baseline);
  if(!Number.isFinite(modelValue)||!Number.isFinite(baselineValue)||baselineValue===0) return "-";
  const improvement=(baselineValue-modelValue)/baselineValue;
  const sign=improvement>0?"+":"";
  return `${sign}${(improvement*100).toFixed(1)}%`;
}

function renderAiBacktest(payload){
  const learning=document.getElementById("learning");
  if(!learning) return;

  document.getElementById("aiBacktestLoading")?.remove();
  document.getElementById("aiBacktestSummary")?.remove();
  document.getElementById("aiBacktestCurve")?.remove();
  document.getElementById("aiBacktestDistribution")?.remove();
  document.getElementById("aiBacktestProfiles")?.remove();
  document.getElementById("aiBacktestExamples")?.remove();

  const summary=payload.summary||{};
  const observed=summary.observed||{};
  const baseline=summary.theoreticalFixedTicketBaseline||{};
  const curve=summary.curveBenchmark||{};

  const summaryCard=document.createElement("div");
  summaryCard.id="aiBacktestSummary";
  summaryCard.className="card";
  summaryCard.innerHTML=`
    <div class="section-head">
      <div>
        <h2>AI 曲线模型全历史步进回测</h2>
        <div class="muted">每一期都只使用此前已公布的开奖记录重新选择曲线画像、拟合位置轨迹、生成3组候选，再揭示当期实际结果。前 ${Number(summary.warmupDraws||0).toLocaleString("zh-CN")} 期只用于模型预热。</div>
      </div>
      <span class="badge blue">${payload.backtestVersion||"步进回测"}</span>
    </div>
    <div class="weight-grid">
      <div class="weight"><span class="muted">样本外期数</span><strong>${Number(summary.drawsEvaluated||0).toLocaleString("zh-CN")}</strong></div>
      <div class="weight"><span class="muted">AI候选票数</span><strong>${Number(summary.ticketsEvaluated||0).toLocaleString("zh-CN")}</strong></div>
      <div class="weight"><span class="muted">平均前区命中</span><strong>${aiAuditNumber(observed.averageFrontHitsPerTicket)}</strong></div>
      <div class="weight"><span class="muted">平均后区命中</span><strong>${aiAuditNumber(observed.averageBackHitsPerTicket)}</strong></div>
    </div>
    <div class="log-list">
      <div class="log"><div class="log-time">防止偷看未来</div><div><div class="log-title">严格 walk-forward，无未来数据泄漏</div><div class="log-body">第N期预测只允许读取第N期之前的数据。实际号码只在三组候选生成后用于评分和下一期的有界温度更新。</div></div></div>
      <div class="log"><div class="log-time">公平基准</div><div><div class="log-title">每张AI候选与任意固定单票比较</div><div class="log-body">理论前区均值 ${aiAuditNumber(baseline.averageFrontHitsPerTicket)}，后区 ${aiAuditNumber(baseline.averageBackHitsPerTicket)}。AI相对基准：前区 ${aiAuditDelta(observed.averageFrontHitsPerTicket,baseline.averageFrontHitsPerTicket)}，后区 ${aiAuditDelta(observed.averageBackHitsPerTicket,baseline.averageBackHitsPerTicket)}。</div></div></div>
      <div class="log"><div class="log-time">完整命中</div><div><div class="log-title">5+2 次数：${Number(observed.exactFivePlusTwo||0)}</div><div class="log-body">命中统计按每张候选票计算。三组候选存在多样性约束，因此最佳三选一结果不直接套用独立随机票公式。</div></div></div>
    </div>`;
  learning.appendChild(summaryCard);

  const curveCard=document.createElement("div");
  curveCard.id="aiBacktestCurve";
  curveCard.className="card";
  curveCard.innerHTML=`
    <div class="section-head">
      <div>
        <h3>曲线预测能力</h3>
        <div class="muted">损失越低越好。除了号码命中，还检验模型对七个排序位置、和值和跨度轨迹的预测。</div>
      </div>
      <span class="badge blue">${payload.modelVersion||"AI模型"}</span>
    </div>
    <div class="weight-grid">
      <div class="weight"><span class="muted">AI曲线损失</span><strong>${aiAuditNumber(curve.modelAverageLoss,4)}</strong></div>
      <div class="weight"><span class="muted">沿用上一期</span><strong>${aiAuditNumber(curve.persistenceAverageLoss,4)}</strong></div>
      <div class="weight"><span class="muted">过去60期均值</span><strong>${aiAuditNumber(curve.trailingMean60AverageLoss,4)}</strong></div>
      <div class="weight"><span class="muted">对60期均值改善</span><strong>${aiAuditLossChange(curve.modelAverageLoss,curve.trailingMean60AverageLoss)}</strong></div>
    </div>
    <div class="log-list">
      <div class="log"><div class="log-time">上一期基准</div><div><div class="log-title">相对“下一期复制上一期曲线”</div><div class="log-body">AI损失变化 ${aiAuditLossChange(curve.modelAverageLoss,curve.persistenceAverageLoss)}。正数代表AI曲线误差更低，负数代表简单沿用上一期更好。</div></div></div>
      <div class="log"><div class="log-time">均值基准</div><div><div class="log-title">相对过去60期排序位置均值</div><div class="log-body">AI损失变化 ${aiAuditLossChange(curve.modelAverageLoss,curve.trailingMean60AverageLoss)}。该比较衡量曲线模型是否真正优于一个安静但顽固的平均值。</div></div></div>
    </div>`;
  learning.appendChild(curveCard);

  const frontObserved=observed.frontHitDistribution||{};
  const frontExpected=baseline.expectedFrontHitCounts||{};
  const backObserved=observed.backHitDistribution||{};
  const backExpected=baseline.expectedBackHitCounts||{};
  const distributionCard=document.createElement("div");
  distributionCard.id="aiBacktestDistribution";
  distributionCard.className="card";
  distributionCard.innerHTML=`
    <h3>AI实际命中分布 vs 公平随机基准</h3>
    <div style="overflow:auto">
      <table>
        <thead><tr><th>区域</th><th>命中数</th><th>AI实际次数</th><th>理论期望次数</th><th>差值</th></tr></thead>
        <tbody>
          ${[0,1,2,3,4,5].map(hits=>`<tr><td>前区</td><td>${hits}</td><td>${Number(frontObserved[hits]||0).toLocaleString("zh-CN")}</td><td>${Number(frontExpected[hits]||0).toFixed(1)}</td><td>${(Number(frontObserved[hits]||0)-Number(frontExpected[hits]||0)).toFixed(1)}</td></tr>`).join("")}
          ${[0,1,2].map(hits=>`<tr><td>后区</td><td>${hits}</td><td>${Number(backObserved[hits]||0).toLocaleString("zh-CN")}</td><td>${Number(backExpected[hits]||0).toFixed(1)}</td><td>${(Number(backObserved[hits]||0)-Number(backExpected[hits]||0)).toFixed(1)}</td></tr>`).join("")}
        </tbody>
      </table>
    </div>`;
  learning.appendChild(distributionCard);

  const profiles=Object.entries(summary.byProfile||{});
  const profileCard=document.createElement("div");
  profileCard.id="aiBacktestProfiles";
  profileCard.className="card";
  profileCard.innerHTML=`
    <h3>曲线画像表现</h3>
    <div style="overflow:auto">
      <table>
        <thead><tr><th>画像</th><th>采用期数</th><th>平均前区命中</th><th>平均后区命中</th><th>平均曲线损失</th></tr></thead>
        <tbody>${profiles.map(([label,row])=>`<tr><td>${label}</td><td>${Number(row.draws||0).toLocaleString("zh-CN")}</td><td>${aiAuditNumber(row.averageFrontHits)}</td><td>${aiAuditNumber(row.averageBackHits)}</td><td>${aiAuditNumber(row.averageModelCurveLoss,4)}</td></tr>`).join("")}</tbody>
      </table>
    </div>`;
  learning.appendChild(profileCard);

  const examples=(summary.bestExamples||[]).slice(0,10);
  const examplesCard=document.createElement("div");
  examplesCard.id="aiBacktestExamples";
  examplesCard.className="card";
  examplesCard.innerHTML=`
    <h3>历史最佳AI对齐案例</h3>
    <div style="overflow:auto">
      <table>
        <thead><tr><th>期次</th><th>日期</th><th>实际号码</th><th>最佳AI结果</th><th>命中</th><th>曲线距离</th></tr></thead>
        <tbody>${examples.map(example=>{
          const ticket=aiAuditBestTicket(example)||{};
          return `<tr><td>${example.issue}</td><td>${example.date}</td><td>${example.actual?.front?.join(" ")} + ${example.actual?.back?.join(" ")}</td><td>${ticket.front?.join(" ")} + ${ticket.back?.join(" ")}</td><td>${ticket.frontHitCount||0}+${ticket.backHitCount||0}</td><td>${aiAuditNumber(ticket.curveDistance,4)}</td></tr>`;
        }).join("")}</tbody>
      </table>
    </div>
    <div class="muted" style="margin-top:12px">回测范围：${summary.dateRange?.earliest||"-"} 至 ${summary.dateRange?.latest||"-"}。历史最佳案例是事后审计，不代表下一期开奖会复制。</div>`;
  learning.appendChild(examplesCard);
}

async function loadAiBacktest(){
  if(aiBacktestLoaded) return;
  aiBacktestLoaded=true;
  const learning=document.getElementById("learning");
  if(!learning) return;

  const loading=document.createElement("div");
  loading.id="aiBacktestLoading";
  loading.className="card";
  loading.innerHTML=`<h2>AI 曲线模型全历史步进回测</h2><div class="muted">正在读取逐期重新训练、预测和评分的完整报告...</div>`;
  learning.appendChild(loading);

  try{
    const response=await fetch(`${AI_BACKTEST_URL}?v=${Date.now()}`,{cache:"no-store"});
    if(!response.ok) throw new Error(`HTTP ${response.status}`);
    renderAiBacktest(await response.json());
  }catch(error){
    console.warn("AI backtest unavailable",error);
    loading.innerHTML=`<h2>AI 曲线模型全历史步进回测</h2><div class="muted">首次完整步进回测正在运行。它会依次完成预热后的每一期训练、预测和对照，报告生成后这里会自动显示结果。</div>`;
  }
}

document.querySelectorAll(".tab").forEach(button=>{
  if(button.dataset.page==="learning"){
    button.addEventListener("click",loadAiBacktest);
  }
});
