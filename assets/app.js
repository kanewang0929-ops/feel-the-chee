const tabs=[...document.querySelectorAll(".tab")];
tabs.forEach(button=>button.addEventListener("click",()=>{
  tabs.forEach(item=>item.classList.remove("active"));
  button.classList.add("active");
  document.querySelectorAll(".page").forEach(item=>item.classList.remove("active"));
  document.getElementById(button.dataset.page)?.classList.add("active");
}));

const LIVE_HISTORY_URL="https://raw.githubusercontent.com/yangxb919/lottery-data/main/data/dlt.json";
const LOCAL_HISTORY_URL="./data/draws.json";
const FORECAST_URL="./data/forecast.json";
const CHEE_FORECAST_URL="./data/chee-forecast.json";

let draws=[];
let currentPage=1;
const pageSize=10;
let editingIndex=null;
let syncMeta={};

const fallbackDraws=[
  {issue:"26085",date:"2026-07-29",front:"03 04 14 28 31",back:"05 07",status:"已同步"},
  {issue:"26084",date:"2026-07-27",front:"13 25 30 32 33",back:"04 05",status:"已同步"},
  {issue:"26083",date:"2026-07-25",front:"14 15 16 23 26",back:"07 09",status:"已同步"}
];

function normalizeDraw(record){
  const front=Array.isArray(record.front)?record.front.join(" "):String(record.front||"").trim();
  const back=Array.isArray(record.back)?record.back.join(" "):String(record.back||"").trim();
  return {
    issue:String(record.issue||"").trim(),
    date:String(record.date||"").trim(),
    front,
    back,
    status:record.status||"已同步",
    source:record.source||""
  };
}

function validDraw(record){
  const front=record.front.split(/\s+/).filter(Boolean).map(Number);
  const back=record.back.split(/\s+/).filter(Boolean).map(Number);
  return Boolean(record.issue&&/^\d{4}-\d{2}-\d{2}$/.test(record.date))&&
    front.length===5&&new Set(front).size===5&&front.every(number=>number>=1&&number<=35)&&
    back.length===2&&new Set(back).size===2&&back.every(number=>number>=1&&number<=12);
}

function applyBrowserOverrides(base){
  const edits=JSON.parse(localStorage.getItem("cheeDrawEdits")||"{}");
  const deleted=new Set(JSON.parse(localStorage.getItem("cheeDeletedDraws")||"[]"));
  return base
    .filter(item=>!deleted.has(item.issue))
    .map(item=>edits[item.issue]?{...item,...edits[item.issue]}:item);
}

async function fetchJson(url){
  const response=await fetch(`${url}?v=${Date.now()}`,{cache:"no-store"});
  if(!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

async function fetchLiveHistory(){
  const payload=await fetchJson(LIVE_HISTORY_URL);
  if(!Array.isArray(payload)) throw new Error("历史数据格式错误");
  const normalized=payload.map(normalizeDraw).filter(validDraw);
  if(normalized.length<1000) throw new Error(`历史数据不足：${normalized.length}`);
  normalized.sort((a,b)=>b.date.localeCompare(a.date)||Number(b.issue)-Number(a.issue));
  return {
    draws:normalized,
    meta:{
      total:normalized.length,
      latestIssue:normalized[0]?.issue,
      latestDate:normalized[0]?.date,
      earliestIssue:normalized.at(-1)?.issue,
      earliestDate:normalized.at(-1)?.date,
      source:"互联网全量历史数据 · 500.com"
    }
  };
}

async function fetchLocalHistory(){
  const payload=await fetchJson(LOCAL_HISTORY_URL);
  const raw=Array.isArray(payload)?payload:(payload.draws||[]);
  const normalized=raw.map(normalizeDraw).filter(validDraw);
  if(!normalized.length) throw new Error("本地历史数据库为空");
  normalized.sort((a,b)=>b.date.localeCompare(a.date)||Number(b.issue)-Number(a.issue));
  return {
    draws:normalized,
    meta:Array.isArray(payload)
      ?{total:normalized.length,source:"本地历史数据库"}
      :{...(payload.meta||{}),total:normalized.length}
  };
}

async function loadDraws(){
  const metaNode=document.getElementById("syncMeta");
  if(metaNode) metaNode.textContent="正在同步全部历史开奖记录...";
  let localResult=null;
  try{
    localResult=await fetchLocalHistory();
  }catch(error){
    console.warn("Local history unavailable",error);
  }

  try{
    const liveResult=await fetchLiveHistory();
    const selected=localResult&&localResult.draws.length>=liveResult.draws.length?localResult:liveResult;
    draws=applyBrowserOverrides(selected.draws);
    syncMeta=selected.meta;
  }catch(error){
    console.warn("Live history unavailable",error);
    if(localResult){
      draws=applyBrowserOverrides(localResult.draws);
      syncMeta={...localResult.meta,error:String(error)};
    }else{
      draws=applyBrowserOverrides(fallbackDraws);
      syncMeta={total:draws.length,source:"应急预览数据",error:String(error)};
    }
  }

  currentPage=1;
  renderAdmin();
}

function ball(number,back=false){
  return `<span class="ball${back?" back":""}">${number}</span>`;
}

function scoreText(value){
  return Number(value||0).toFixed(1);
}

function forecastCard(result){
  return `<div class="forecast">
    <div class="forecast-top">
      <strong>预测结果 ${result.rank} · ${result.label}</strong>
      <span class="score">曲线吻合度 ${scoreText(result.fit)}</span>
    </div>
    <div class="numbers">
      ${(result.front||[]).map(number=>ball(number)).join("")}
      <span class="plus">+</span>
      ${(result.back||[]).map(number=>ball(number,true)).join("")}
    </div>
    <div class="reason">${result.reason||""}</div>
  </div>`;
}

function cheeCard(result){
  return `<div class="forecast">
    <div class="forecast-top">
      <strong>Chee 结果 ${result.rank} · ${result.label||"五行路径"}</strong>
      <span class="score">Chee 值 ${scoreText(result.cheeValue)}</span>
    </div>
    <div class="numbers">
      ${(result.front||[]).map(number=>ball(number)).join("")}
      <span class="plus">+</span>
      ${(result.back||[]).map(number=>ball(number,true)).join("")}
    </div>
    <div class="reason">${result.reason||""}</div>
  </div>`;
}

function renderAiLearning(payload){
  const summary=document.getElementById("aiLearningSummary");
  const logs=document.getElementById("aiLearningLogs");
  if(!summary||!logs) return;

  const calibration=payload.calibration||{};
  summary.querySelector(".section-head .muted").textContent=
    "AI学习五个前区排序位置和两个后区排序位置的运行曲线，并从预测中心与不确定带中生成3组不同路径。";
  summary.querySelector(".section-head .badge").textContent=`AI模型 ${payload.modelVersion||"-"}`;
  summary.querySelector(".weight-grid").innerHTML=`
    <div class="weight"><span class="muted">曲线画像</span><strong>${calibration.selectedLabel||calibration.selectedProfile||"-"}</strong></div>
    <div class="weight"><span class="muted">前区曲线损失</span><strong>${Number(calibration.frontCurveLoss||0).toFixed(3)}</strong></div>
    <div class="weight"><span class="muted">后区曲线损失</span><strong>${Number(calibration.backCurveLoss||0).toFixed(3)}</strong></div>
    <div class="weight"><span class="muted">采样温度</span><strong>${Number(calibration.temperature||0).toFixed(2)}</strong></div>`;

  const evaluation=payload.lastEvaluation;
  const centers=payload.curveForecast?.front?.centers||[];
  const sigmas=payload.curveForecast?.front?.sigmas||[];
  const review=evaluation?`<div class="log">
    <div class="log-time">第${evaluation.issue}期复盘</div>
    <div>
      <div class="log-title">预测曲线与实际结果已对照</div>
      <div class="log-body">实际：${evaluation.actual?.front?.join(" ")} + ${evaluation.actual?.back?.join(" ")}。平均前区命中 ${evaluation.summary?.averageFrontHits??"-"} 个，后区命中 ${evaluation.summary?.averageBackHits??"-"} 个。</div>
    </div>
  </div>`:"";

  logs.querySelector("h3").textContent="AI 曲线学习日志";
  logs.querySelector(".log-list").innerHTML=`${review}
    <div class="log">
      <div class="log-time">滚动回测</div>
      <div>
        <div class="log-title">选择 ${calibration.selectedLabel||calibration.selectedProfile||"曲线画像"}</div>
        <div class="log-body">最近 ${calibration.tests||0} 个走步测试中，前区曲线损失 ${Number(calibration.frontCurveLoss||0).toFixed(4)}，后区曲线损失 ${Number(calibration.backCurveLoss||0).toFixed(4)}。</div>
      </div>
    </div>
    <div class="log">
      <div class="log-time">下一期曲线</div>
      <div>
        <div class="log-title">从预测中心与波动带生成候选</div>
        <div class="log-body">前区中心：${centers.join(" / ")}；标准差：${sigmas.join(" / ")}。页面固定显示3组AI结果。</div>
      </div>
    </div>`;
}

function renderForecast(payload){
  const card=document.getElementById("aiPredictionCard");
  if(!card) return;
  const results=Array.isArray(payload.results)?payload.results.slice(0,3):[];
  card.querySelector(".forecast-list").innerHTML=results.length
    ?results.map(forecastCard).join("")
    :`<div class="forecast"><div class="muted">AI结果暂不可用。</div></div>`;
  card.querySelector(".section-head .muted").textContent=
    `基于 ${Number(payload.historyCount||0).toLocaleString("zh-CN")} 期数据学习开奖排序曲线，从下一期波动带中输出3组候选。`;
  card.querySelector(".section-head .badge").textContent=`${results.length}组结果`;
  const next=document.querySelector(".next");
  if(next) next.textContent=`下一期开奖：${payload.targetDate} · 第${payload.targetIssue}期`;
  renderAiLearning(payload);
}

function renderCheeFormula(payload){
  const learning=document.getElementById("learning");
  if(!learning) return;
  let card=document.getElementById("cheeFormulaCard");
  if(!card){
    card=document.createElement("div");
    card.id="cheeFormulaCard";
    card.className="card";
    learning.appendChild(card);
  }

  const calculation=payload.calculation||{};
  card.innerHTML=`<div class="section-head">
    <div>
      <h2>Feel the Chee 公式计算</h2>
      <div class="muted">每日执行全历史审计并保存日志，但不使用历史开奖结果训练公式。</div>
    </div>
    <span class="badge gold">${payload.modelVersion||"公式模型"}</span>
  </div>
  <div class="weight-grid">
    <div class="weight"><span class="muted">天数</span><strong>${calculation.heavenNumber??"-"}</strong></div>
    <div class="weight"><span class="muted">地数</span><strong>${calculation.earthNumber??"-"}</strong></div>
    <div class="weight"><span class="muted">人数</span><strong>${calculation.humanNumber??"-"}</strong></div>
    <div class="weight"><span class="muted">动爻</span><strong>${calculation.movingLine??"-"}</strong></div>
  </div>
  <div class="log-list">
    <div class="log">
      <div class="log-time">五行路径</div>
      <div>
        <div class="log-title">${calculation.primaryElement||"-"} → ${calculation.supportElement||"-"} → ${calculation.balanceElement||"-"}</div>
        <div class="log-body">目标第${payload.targetIssue}期，日期${payload.targetDate}。公式只读取期号、日期和河图洛书映射。</div>
      </div>
    </div>
  </div>`;
}

function renderChee(payload){
  const card=document.getElementById("cheePredictionCard");
  if(!card) return;
  const results=Array.isArray(payload.results)?payload.results.slice(0,2):[];
  card.querySelector(".section-head .muted").textContent=
    "仅按河图洛书、目标期号和开奖日期计算2组结果，不使用历史开奖学习。";
  card.querySelector(".section-head .badge").textContent=`${results.length}组结果 · 公式计算`;

  const order=["金","火","土","木","水"];
  const bars=card.querySelector(".chee-bars");
  if(bars){
    bars.innerHTML=order.map(name=>{
      const value=Number(payload.elementStrengths?.[name]||0);
      return `<div class="chee-row">
        <span>${name}</span>
        <div class="bar"><div class="fill" style="width:${Math.max(0,Math.min(100,value))}%"></div></div>
        <span>${Math.round(value)}</span>
      </div>`;
    }).join("");
  }

  card.querySelector(".forecast-list").innerHTML=results.length
    ?results.map(cheeCard).join("")
    :`<div class="forecast"><div class="muted">风水公式结果暂不可用。</div></div>`;
  renderCheeFormula(payload);
}

async function loadForecast(){
  try{
    renderForecast(await fetchJson(FORECAST_URL));
  }catch(error){
    console.warn("Forecast unavailable",error);
    const list=document.querySelector("#aiPredictionCard .forecast-list");
    if(list) list.innerHTML=`<div class="forecast"><div class="muted">AI结果加载失败，请稍后刷新。</div></div>`;
  }
}

async function loadCheeForecast(){
  try{
    renderChee(await fetchJson(CHEE_FORECAST_URL));
  }catch(error){
    console.warn("Chee forecast unavailable",error);
    const list=document.querySelector("#cheePredictionCard .forecast-list");
    if(list) list.innerHTML=`<div class="forecast"><div class="muted">风水公式加载失败，请稍后刷新。</div></div>`;
  }
}

function statusClass(status){
  if(status==="已同步") return "ok";
  if(status==="同步失败") return "fail";
  return "wait";
}

function filteredDraws(){
  const query=document.getElementById("searchInput")?.value.trim()||"";
  const indexed=draws.map((item,index)=>({...item,_i:index}));
  if(!query) return indexed;
  return indexed.filter(item=>
    item.issue.includes(query)||
    item.date.includes(query)||
    item.front.includes(query)||
    item.back.includes(query)
  );
}

function renderAdmin(){
  const body=document.getElementById("drawBody");
  const pager=document.getElementById("pager");
  const metaNode=document.getElementById("syncMeta");
  if(!body||!pager||!metaNode) return;

  const list=filteredDraws();
  const pages=Math.max(1,Math.ceil(list.length/pageSize));
  if(currentPage>pages) currentPage=pages;
  const rows=list.slice((currentPage-1)*pageSize,currentPage*pageSize);

  body.innerHTML=rows.map(item=>`<tr>
    <td>${item.issue}</td>
    <td>${item.date}</td>
    <td>${item.front}${item.back?` + ${item.back}`:""}</td>
    <td><span class="status ${statusClass(item.status)}">${item.status}</span></td>
    <td>
      <button class="btn edit" onclick="openEdit(${item._i})">编辑</button>
      <button class="btn del" onclick="deleteDraw(${item._i})">删除</button>
    </td>
  </tr>`).join("");

  const windowSize=7;
  const start=Math.max(1,Math.min(currentPage-Math.floor(windowSize/2),pages-windowSize+1));
  const end=Math.min(pages,start+windowSize-1);
  const buttons=[];
  if(currentPage>1) buttons.push(`<button onclick="currentPage--;renderAdmin()">‹</button>`);
  if(start>1) buttons.push(`<button onclick="currentPage=1;renderAdmin()">1</button><span class="muted">…</span>`);
  for(let page=start;page<=end;page++){
    buttons.push(`<button class="${page===currentPage?"active":""}" onclick="currentPage=${page};renderAdmin()">${page}</button>`);
  }
  if(end<pages) buttons.push(`<span class="muted">…</span><button onclick="currentPage=${pages};renderAdmin()">${pages}</button>`);
  if(currentPage<pages) buttons.push(`<button onclick="currentPage++;renderAdmin()">›</button>`);
  pager.innerHTML=buttons.join("");

  const total=syncMeta.total||draws.length;
  const range=syncMeta.earliestDate&&syncMeta.latestDate
    ?`${syncMeta.earliestDate} 至 ${syncMeta.latestDate}`
    :"完整可用范围";
  metaNode.textContent=`已同步 ${Number(total).toLocaleString("zh-CN")} 期 · ${range} · ${syncMeta.source||"历史开奖数据库"}`;
}

document.getElementById("searchInput")?.addEventListener("input",()=>{
  currentPage=1;
  renderAdmin();
});

function openEdit(index){
  editingIndex=index;
  const item=draws[index];
  if(!item) return;
  editIssue.value=item.issue;
  editDate.value=item.date;
  editFront.value=item.front;
  editBack.value=item.back;
  editModal.classList.add("show");
}

function closeModal(){
  editModal.classList.remove("show");
}

function saveEdit(){
  if(editingIndex===null||!draws[editingIndex]) return;
  const originalIssue=draws[editingIndex].issue;
  const updated={
    ...draws[editingIndex],
    issue:editIssue.value.trim(),
    date:editDate.value.trim(),
    front:editFront.value.trim(),
    back:editBack.value.trim(),
    status:"已同步"
  };

  if(!validDraw(updated)){
    alert("号码格式不正确。前区需要5个不重复的01至35号码，后区需要2个不重复的01至12号码。");
    return;
  }

  draws[editingIndex]=updated;
  const edits=JSON.parse(localStorage.getItem("cheeDrawEdits")||"{}");
  delete edits[originalIssue];
  edits[updated.issue]=updated;
  localStorage.setItem("cheeDrawEdits",JSON.stringify(edits));
  closeModal();
  renderAdmin();
}

function deleteDraw(index){
  if(!draws[index]||!confirm("确认删除这条开奖记录？")) return;
  const issue=draws[index].issue;
  const deleted=JSON.parse(localStorage.getItem("cheeDeletedDraws")||"[]");
  if(!deleted.includes(issue)) deleted.push(issue);
  localStorage.setItem("cheeDeletedDraws",JSON.stringify(deleted));
  draws.splice(index,1);
  renderAdmin();
}

loadDraws();
loadForecast();
loadCheeForecast();
