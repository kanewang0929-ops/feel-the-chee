/* Full-archive formula-only Feel the Chee backtest display. */
const CHEE_BACKTEST_URL="./data/chee-backtest.json";
let cheeBacktestLoaded=false;

function backtestNumber(value,digits=3){
  const number=Number(value);
  return Number.isFinite(number)?number.toFixed(digits):"-";
}

function backtestPercent(value){
  const number=Number(value);
  return Number.isFinite(number)?`${(number*100).toFixed(1)}%`:"-";
}

function metricDelta(observed,baseline){
  const difference=Number(observed)-Number(baseline);
  const sign=difference>0?"+":"";
  return `${sign}${difference.toFixed(4)}`;
}

function ticketForBestExample(example){
  return example.tickets?.find(ticket=>ticket.rank===example.bestTicket?.rank)||example.tickets?.[0];
}

function renderCheeBacktest(payload){
  const learning=document.getElementById("learning");
  if(!learning) return;
  document.getElementById("cheeBacktestLoading")?.remove();
  document.getElementById("cheeBacktestSummary")?.remove();
  document.getElementById("cheeBacktestDistribution")?.remove();
  document.getElementById("cheeBacktestExamples")?.remove();

  const summary=payload.summary||{};
  const observed=summary.observed||{};
  const baseline=summary.theoreticalFixedTicketBaseline||{};
  const comparison=summary.comparison||{};

  const summaryCard=document.createElement("div");
  summaryCard.id="cheeBacktestSummary";
  summaryCard.className="card";
  summaryCard.innerHTML=`
    <div class="section-head">
      <div>
        <h2>Feel the Chee 全历史公式回测</h2>
        <div class="muted">对数据库中每一期分别使用当期“期号 + 开奖日期”运行同一套河图洛书公式，之后才与实际号码比较。历史开奖结果没有参与预测计算。</div>
      </div>
      <span class="badge gold">${payload.backtestVersion||"公式回测"}</span>
    </div>
    <div class="weight-grid">
      <div class="weight"><span class="muted">回测期数</span><strong>${Number(summary.drawsEvaluated||0).toLocaleString("zh-CN")}</strong></div>
      <div class="weight"><span class="muted">公式票数</span><strong>${Number(summary.ticketsEvaluated||0).toLocaleString("zh-CN")}</strong></div>
      <div class="weight"><span class="muted">平均前区命中</span><strong>${backtestNumber(observed.averageFrontHitsPerTicket)}</strong></div>
      <div class="weight"><span class="muted">平均后区命中</span><strong>${backtestNumber(observed.averageBackHitsPerTicket)}</strong></div>
    </div>
    <div class="log-list">
      <div class="log"><div class="log-time">公平基准</div><div><div class="log-title">任意固定单票的理论均值</div><div class="log-body">前区 ${backtestNumber(baseline.averageFrontHitsPerTicket)}，后区 ${backtestNumber(baseline.averageBackHitsPerTicket)}。公式相对基准：前区 ${metricDelta(observed.averageFrontHitsPerTicket,baseline.averageFrontHitsPerTicket)}，后区 ${metricDelta(observed.averageBackHitsPerTicket,baseline.averageBackHitsPerTicket)}。</div></div></div>
      <div class="log"><div class="log-time">五行结构</div><div><div class="log-title">平均五行相似度 ${backtestPercent(observed.averageElementSimilarity)}</div><div class="log-body">此指标只比较预测七个号码与实际七个号码的五行数量分布，不等同于号码命中，也不是中奖概率。</div></div></div>
      <div class="log"><div class="log-time">完整命中</div><div><div class="log-title">5+2 次数：${Number(observed.exactFivePlusTwo||0)}</div><div class="log-body">公式结果完全由当期日期和期号决定。回测只做审计，不反向学习或调整风水公式。</div></div></div>
    </div>`;
  learning.appendChild(summaryCard);

  const distributionCard=document.createElement("div");
  distributionCard.id="cheeBacktestDistribution";
  distributionCard.className="card";
  const frontObserved=observed.frontHitDistribution||{};
  const frontExpected=baseline.expectedFrontHitCounts||{};
  const backObserved=observed.backHitDistribution||{};
  const backExpected=baseline.expectedBackHitCounts||{};
  distributionCard.innerHTML=`
    <h3>实际命中分布 vs 公平随机基准</h3>
    <div style="overflow:auto">
      <table>
        <thead><tr><th>区域</th><th>命中数</th><th>公式实际次数</th><th>理论期望次数</th><th>差值</th></tr></thead>
        <tbody>
          ${[0,1,2,3,4,5].map(hits=>`<tr><td>前区</td><td>${hits}</td><td>${Number(frontObserved[hits]||0).toLocaleString("zh-CN")}</td><td>${Number(frontExpected[hits]||0).toFixed(1)}</td><td>${(Number(frontObserved[hits]||0)-Number(frontExpected[hits]||0)).toFixed(1)}</td></tr>`).join("")}
          ${[0,1,2].map(hits=>`<tr><td>后区</td><td>${hits}</td><td>${Number(backObserved[hits]||0).toLocaleString("zh-CN")}</td><td>${Number(backExpected[hits]||0).toFixed(1)}</td><td>${(Number(backObserved[hits]||0)-Number(backExpected[hits]||0)).toFixed(1)}</td></tr>`).join("")}
        </tbody>
      </table>
    </div>`;
  learning.appendChild(distributionCard);

  const examples=(summary.bestExamples||[]).slice(0,10);
  const examplesCard=document.createElement("div");
  examplesCard.id="cheeBacktestExamples";
  examplesCard.className="card";
  examplesCard.innerHTML=`
    <h3>历史最佳对齐案例</h3>
    <div style="overflow:auto">
      <table>
        <thead><tr><th>期次</th><th>日期</th><th>实际号码</th><th>最佳公式结果</th><th>命中</th><th>五行相似度</th></tr></thead>
        <tbody>${examples.map(example=>{
          const ticket=ticketForBestExample(example)||{};
          return `<tr><td>${example.issue}</td><td>${example.date}</td><td>${example.actual?.front?.join(" ")} + ${example.actual?.back?.join(" ")}</td><td>${ticket.front?.join(" ")} + ${ticket.back?.join(" ")}</td><td>${ticket.frontHitCount||0}+${ticket.backHitCount||0}</td><td>${backtestPercent(ticket.elementSimilarity)}</td></tr>`;
        }).join("")}</tbody>
      </table>
    </div>
    <div class="muted" style="margin-top:12px">日期范围：${summary.dateRange?.earliest||"-"} 至 ${summary.dateRange?.latest||"-"}。最佳案例属于事后回测展示，不代表下一期会重复。</div>`;
  learning.appendChild(examplesCard);
}

async function loadCheeBacktest(){
  if(cheeBacktestLoaded) return;
  cheeBacktestLoaded=true;
  const learning=document.getElementById("learning");
  if(!learning) return;
  const loading=document.createElement("div");
  loading.id="cheeBacktestLoading";
  loading.className="card";
  loading.innerHTML=`<h2>Feel the Chee 全历史公式回测</h2><div class="muted">正在读取全部历史公式计算与实际开奖结果的对比报告...</div>`;
  learning.appendChild(loading);
  try{
    const response=await fetch(`${CHEE_BACKTEST_URL}?v=${Date.now()}`,{cache:"no-store"});
    if(!response.ok) throw new Error(`HTTP ${response.status}`);
    renderCheeBacktest(await response.json());
  }catch(error){
    console.warn("Chee backtest unavailable",error);
    loading.innerHTML=`<h2>Feel the Chee 全历史公式回测</h2><div class="muted">回测报告正在生成。GitHub Actions 完成后，这里会自动显示全部历史对比结果。</div>`;
  }
}

document.querySelectorAll('.tab').forEach(button=>{
  if(button.dataset.page==='learning') button.addEventListener('click',loadCheeBacktest);
});
