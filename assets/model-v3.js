/* v3 display layer: curve-sampled AI + formula-only Feel the Chee. */
function forecastCard(result){
  return `<div class="forecast"><div class="forecast-top"><strong>预测结果 ${result.rank} · ${result.label}</strong><span class="score">曲线吻合度 ${scoreText(result.fit)}</span></div><div class="numbers">${result.front.map(n=>ball(n)).join("")}<span class="plus">+</span>${result.back.map(n=>ball(n,true)).join("")}</div><div class="reason">${result.reason}</div></div>`;
}
function renderAiLearning(payload){
  const learning=document.getElementById("learning");
  const summary=learning?.querySelector(":scope > .card:first-child");
  const logs=learning?.querySelector(":scope > .card:nth-child(2)");
  if(!summary||!logs) return;
  summary.querySelector(".section-head .muted").textContent="AI模型不再固定追逐热号，而是学习每个排序位置的运行曲线，再从下一期的不确定波动带中抽取3组不同路径。";
  summary.querySelector(".section-head .badge").textContent=`AI模型 ${payload.modelVersion}`;
  const c=payload.calibration||{};
  summary.querySelector(".weight-grid").innerHTML=`
    <div class="weight"><span class="muted">曲线画像</span><strong>${c.selectedLabel||c.selectedProfile||"-"}</strong></div>
    <div class="weight"><span class="muted">前区曲线损失</span><strong>${Number(c.frontCurveLoss||0).toFixed(3)}</strong></div>
    <div class="weight"><span class="muted">后区曲线损失</span><strong>${Number(c.backCurveLoss||0).toFixed(3)}</strong></div>
    <div class="weight"><span class="muted">采样温度</span><strong>${Number(c.temperature||0).toFixed(2)}</strong></div>`;
  const e=payload.lastEvaluation;
  const centers=payload.curveForecast?.front?.centers||[];
  const sigmas=payload.curveForecast?.front?.sigmas||[];
  const review=e?`<div class="log"><div class="log-time">第${e.issue}期复盘</div><div><div class="log-title">预测曲线与实际结果已对照</div><div class="log-body">实际：${e.actual.front.join(" ")} + ${e.actual.back.join(" ")}。平均前区命中 ${e.summary.averageFrontHits} 个，后区命中 ${e.summary.averageBackHits} 个；最佳曲线距离 ${Number(e.summary.bestCurveDistance).toFixed(3)}。该误差只调整下一期采样带宽，不会把刚开出的号码变成固定热门。</div></div></div>`:"";
  logs.querySelector("h3").textContent="AI 曲线学习日志";
  logs.querySelector(".log-list").innerHTML=`${review}
    <div class="log"><div class="log-time">滚动回测</div><div><div class="log-title">选择 ${c.selectedLabel||c.selectedProfile||"曲线画像"}</div><div class="log-body">最近 ${c.tests||0} 个走步测试中，前区曲线损失 ${Number(c.frontCurveLoss||0).toFixed(4)}，后区曲线损失 ${Number(c.backCurveLoss||0).toFixed(4)}。评分对象是整条排序曲线，不是单个号码热度。</div></div></div>
    <div class="log"><div class="log-time">下一期曲线</div><div><div class="log-title">从预测中心与波动带生成候选</div><div class="log-body">前区中心：${centers.join(" / ")}；标准差：${sigmas.join(" / ")}。三组之间前区最多重合2个，且与上一期预测最多重合3个。</div></div></div>`;
}
function renderForecast(payload){
  const card=document.querySelector("#prediction .grid > .card:first-child");
  const list=card?.querySelector(".forecast-list");
  if(list&&Array.isArray(payload.results)) list.innerHTML=payload.results.map(forecastCard).join("");
  const description=card?.querySelector(".section-head .muted");
  if(description) description.textContent=`基于 ${Number(payload.historyCount).toLocaleString("zh-CN")} 期数据学习开奖排序曲线，从下一期波动带中抽取3组不同候选。`;
  const next=document.querySelector(".next");
  if(next) next.textContent=`下一期开奖：${payload.targetDate} · 第${payload.targetIssue}期`;
  renderAiLearning(payload);
}
function cheeCard(result){
  return `<div class="forecast"><div class="forecast-top"><strong>Chee 结果 ${result.rank} · ${result.label}</strong><span class="score">Chee 值 ${scoreText(result.cheeValue)}</span></div><div class="numbers">${result.front.map(n=>ball(n)).join("")}<span class="plus">+</span>${result.back.map(n=>ball(n,true)).join("")}</div><div class="reason">${result.reason}</div></div>`;
}
function renderCheeFormula(payload){
  document.getElementById("cheeLearningSummary")?.remove();
  document.getElementById("cheeLearningLogs")?.remove();
  const learning=document.getElementById("learning");
  let card=document.getElementById("cheeFormulaCard");
  if(!card){card=document.createElement("div");card.id="cheeFormulaCard";card.className="card";learning.appendChild(card)}
  const x=payload.calculation||{};
  card.innerHTML=`<div class="section-head"><div><h2>Feel the Chee 公式计算</h2><div class="muted">该模块不读取历史开奖号码，也不进行机器学习。每期只使用目标期号、开奖日期与河图洛书数字五行公式。</div></div><span class="badge gold">${payload.modelVersion}</span></div>
  <div class="weight-grid"><div class="weight"><span class="muted">天数</span><strong>${x.heavenNumber??"-"}</strong></div><div class="weight"><span class="muted">地数</span><strong>${x.earthNumber??"-"}</strong></div><div class="weight"><span class="muted">人数</span><strong>${x.humanNumber??"-"}</strong></div><div class="weight"><span class="muted">动爻</span><strong>${x.movingLine??"-"}</strong></div></div>
  <div class="log-list"><div class="log"><div class="log-time">五行路径</div><div><div class="log-title">${x.primaryElement||"-"} → ${x.supportElement||"-"} → ${x.balanceElement||"-"}</div><div class="log-body">河图洛书映射：1/6水、2/7火、3/8木、4/9金、0/5土。目标为第${payload.targetIssue}期，日期${payload.targetDate}，阴阳取${x.yinYang||"-"}，卦数${x.guaNumber??"-"}。结果完全由公式确定。</div></div></div></div>`;
}
function renderChee(payload){
  const card=document.querySelector("#prediction .grid > .card:nth-child(2)");
  if(!card) return;
  card.querySelector(".section-head .muted").textContent="仅按河图洛书、目标期号和开奖日期计算2组结果，不使用历史开奖学习。";
  const order=["金","火","土","木","水"];
  const bars=card.querySelector(".chee-bars");
  if(bars) bars.innerHTML=order.map(name=>{const value=Number(payload.elementStrengths?.[name]||0);return `<div class="chee-row"><span>${name}</span><div class="bar"><div class="fill" style="width:${Math.max(0,Math.min(100,value))}%"></div></div><span>${Math.round(value)}</span></div>`}).join("");
  const list=card.querySelector(".forecast-list");
  if(list&&Array.isArray(payload.results)) list.innerHTML=payload.results.map(cheeCard).join("");
  renderCheeFormula(payload);
}
loadForecast();
loadCheeForecast();
