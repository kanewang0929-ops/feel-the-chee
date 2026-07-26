const tabs=[...document.querySelectorAll(".tab")];
tabs.forEach(button=>button.addEventListener("click",()=>{
  tabs.forEach(item=>item.classList.remove("active"));
  button.classList.add("active");
  document.querySelectorAll(".page").forEach(item=>item.classList.remove("active"));
  document.getElementById(button.dataset.page).classList.add("active");
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
  {issue:"26083",date:"2026-07-25",front:"14 15 16 23 26",back:"07 09",status:"已同步"},
  {issue:"26082",date:"2026-07-22",front:"16 26 27 28 34",back:"02 06",status:"已同步"},
  {issue:"26081",date:"2026-07-20",front:"08 16 18 24 34",back:"09 12",status:"已同步"}
];

function normalizeDraw(record){
  const front=Array.isArray(record.front)?record.front.join(" "):String(record.front||"").trim();
  const back=Array.isArray(record.back)?record.back.join(" "):String(record.back||"").trim();
  return {issue:String(record.issue||"").trim(),date:String(record.date||"").trim(),front,back,status:record.status||"已同步",source:record.source||""};
}

function validDraw(record){
  const front=record.front.split(/\s+/).filter(Boolean).map(Number);
  const back=record.back.split(/\s+/).filter(Boolean).map(Number);
  return Boolean(record.issue&&/^\d{4}-\d{2}-\d{2}$/.test(record.date))&&front.length===5&&new Set(front).size===5&&front.every(n=>n>=1&&n<=35)&&back.length===2&&new Set(back).size===2&&back.every(n=>n>=1&&n<=12);
}

function applyBrowserOverrides(base){
  const edits=JSON.parse(localStorage.getItem("cheeDrawEdits")||"{}");
  const deleted=new Set(JSON.parse(localStorage.getItem("cheeDeletedDraws")||"[]"));
  return base.filter(item=>!deleted.has(item.issue)).map(item=>edits[item.issue]?{...item,...edits[item.issue]}:item);
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
  return {draws:normalized,meta:{total:normalized.length,latestIssue:normalized[0]?.issue,latestDate:normalized[0]?.date,earliestIssue:normalized.at(-1)?.issue,earliestDate:normalized.at(-1)?.date,source:"互联网全量历史数据 · 500.com"}};
}

async function fetchLocalHistory(){
  const payload=await fetchJson(LOCAL_HISTORY_URL);
  const raw=Array.isArray(payload)?payload:(payload.draws||[]);
  const normalized=raw.map(normalizeDraw).filter(validDraw);
  if(!normalized.length) throw new Error("本地历史数据库为空");
  return {draws:normalized,meta:Array.isArray(payload)?{total:normalized.length,source:"本地历史数据库"}:{...(payload.meta||{}),total:normalized.length}};
}

async function loadDraws(){
  document.getElementById("syncMeta").textContent="正在同步全部历史开奖记录...";
  let localResult=null;
  try{localResult=await fetchLocalHistory()}catch(error){console.warn("Local history unavailable",error)}
  try{
    const liveResult=await fetchLiveHistory();
    const selected=localResult&&localResult.draws.length>=liveResult.draws.length?localResult:liveResult;
    draws=applyBrowserOverrides(selected.draws);
    syncMeta=selected.meta;
  }catch(error){
    console.warn("Live history unavailable",error);
    if(localResult){draws=applyBrowserOverrides(localResult.draws);syncMeta={...localResult.meta,error:String(error)}}
    else{draws=applyBrowserOverrides(fallbackDraws);syncMeta={total:draws.length,source:"应急预览数据",error:String(error)}}
  }
  currentPage=1;
  renderAdmin();
}

function ball(number,back=false){return `<span class="ball${back?" back":""}">${number}</span>`}
function scoreText(value){return Number(value||0).toFixed(1)}
function hitText(values){return values?.length?values.join("、"):"无"}
function percent(value){return `${Math.round(Number(value||0)*100)}%`}

function forecastCard(result){
  return `<div class="forecast">
    <div class="forecast-top"><strong>预测结果 ${result.rank} · ${result.label}</strong><span class="score">模型匹配度 ${scoreText(result.fit)}</span></div>
    <div class="numbers">${result.front.map(n=>ball(n)).join("")}<span class="plus">+</span>${result.back.map(n=>ball(n,true)).join("")}</div>
    <div class="reason">${result.reason}</div>
  </div>`;
}

function renderAiLearning(payload){
  const learning=document.getElementById("learning");
  const firstCard=learning?.querySelector(":scope > .card:first-child");
  const logCard=learning?.querySelector(":scope > .card:nth-child(2)");
  if(!firstCard||!logCard) return;
  const intro=firstCard.querySelector(".section-head .muted");
  if(intro) intro.textContent="记录 AI 预测与 Feel the Chee 如何用预测结果和实际结果进行有边界的自适应校准。";
  const version=firstCard.querySelector(".section-head .badge");
  if(version) version.textContent=`AI模型 ${payload.modelVersion}`;
  const weights=payload.calibration?.frontWeights||{};
  const aggregate=[(weights.r10||0)+(weights.r30||0)+(weights.r100||0)+(weights.r300||0),weights.gap||0,(weights.long||0)+(weights.momentum||0),weights.transition||0];
  firstCard.querySelectorAll(".weight-grid .weight strong").forEach((node,index)=>{if(aggregate[index]!==undefined) node.textContent=percent(aggregate[index])});
  const evaluation=payload.lastEvaluation;
  const front=payload.calibration?.front||{};
  const back=payload.calibration?.back||{};
  const evaluationLog=evaluation?`<div class="log"><div class="log-time">第${evaluation.issue}期复盘</div><div><div class="log-title">AI预测与实际结果已完成对比</div><div class="log-body">实际：${evaluation.actual.front.join(" ")} + ${evaluation.actual.back.join(" ")}。三组平均前区命中 ${evaluation.summary.averageFrontHits} 个，后区命中 ${evaluation.summary.averageBackHits} 个。</div></div></div>`:"";
  logCard.querySelector("h3").textContent="AI 学习路径日志";
  logCard.querySelector(".log-list").innerHTML=`${evaluationLog}<div class="log"><div class="log-time">前区回测</div><div><div class="log-title">采用 ${front.selectedProfile||"校准"} 权重组合</div><div class="log-body">最近 ${front.tests||0} 个滚动测试中，前5名平均命中 ${front.averageMainHits??"-"} 个，前10名平均覆盖 ${front.averageWiderHits??"-"} 个。</div></div></div><div class="log"><div class="log-time">后区回测</div><div><div class="log-title">采用 ${back.selectedProfile||"校准"} 权重组合</div><div class="log-body">最近 ${back.tests||0} 个滚动测试中，前2名平均命中 ${back.averageMainHits??"-"} 个，前5名平均覆盖 ${back.averageWiderHits??"-"} 个。</div></div></div>`;
}

function renderForecast(payload){
  const card=document.querySelector("#prediction .grid > .card:first-child");
  const list=card?.querySelector(".forecast-list");
  if(list&&Array.isArray(payload.results)) list.innerHTML=payload.results.map(forecastCard).join("");
  const description=card?.querySelector(".section-head .muted");
  if(description) description.textContent=`基于 ${Number(payload.historyCount).toLocaleString("zh-CN")} 期历史数据，复盘上一期开奖后输出 3 组候选结果。`;
  const next=document.querySelector(".next");
  if(next) next.textContent=`下一期开奖：${payload.targetDate} · 第${payload.targetIssue}期`;
  renderAiLearning(payload);
}

async function loadForecast(){try{renderForecast(await fetchJson(FORECAST_URL))}catch(error){console.warn("Forecast unavailable",error)}}

function cheeCard(result){
  return `<div class="forecast"><div class="forecast-top"><strong>Chee 结果 ${result.rank} · ${result.label||"五行路径"}</strong><span class="score">Chee 值 ${scoreText(result.cheeValue)}</span></div><div class="numbers">${result.front.map(n=>ball(n)).join("")}<span class="plus">+</span>${result.back.map(n=>ball(n,true)).join("")}</div><div class="reason">${result.reason}</div></div>`;
}

function ensureCheeLearningCards(){
  const learning=document.getElementById("learning");
  let summary=document.getElementById("cheeLearningSummary");
  let logs=document.getElementById("cheeLearningLogs");
  if(!summary){
    summary=document.createElement("div");summary.id="cheeLearningSummary";summary.className="card";
    summary.innerHTML=`<div class="section-head"><div><h2>Feel the Chee 学习</h2><div class="muted">五行分布、相生路径与号码周期共同参与校准。</div></div><span class="badge gold">Chee模型</span></div><div class="weight-grid"><div class="weight"><span class="muted">当前画像</span><strong id="cheeProfile">-</strong></div><div class="weight"><span class="muted">主势</span><strong id="cheeDominant">-</strong></div><div class="weight"><span class="muted">弱势</span><strong id="cheeWeakest">-</strong></div><div class="weight"><span class="muted">五行相似度</span><strong id="cheeSimilarity">-</strong></div></div>`;
    learning.appendChild(summary);
  }
  if(!logs){logs=document.createElement("div");logs.id="cheeLearningLogs";logs.className="card";logs.innerHTML=`<h3>Feel the Chee 学习路径日志</h3><div class="log-list"></div>`;learning.appendChild(logs)}
  return {summary,logs};
}

function renderCheeLearning(payload){
  const {summary,logs}=ensureCheeLearningCards();
  summary.querySelector(".badge").textContent=`Chee模型 ${payload.modelVersion}`;
  summary.querySelector("#cheeProfile").textContent=payload.calibration?.selectedLabel||payload.calibration?.selectedProfile||"-";
  summary.querySelector("#cheeDominant").textContent=payload.analysis?.dominant||"-";
  summary.querySelector("#cheeWeakest").textContent=payload.analysis?.weakest||"-";
  const evaluation=payload.lastEvaluation;
  summary.querySelector("#cheeSimilarity").textContent=evaluation?percent(evaluation.summary.averageElementSimilarity):"待复盘";
  let evaluationRows="";
  if(evaluation) evaluationRows=evaluation.results.map(row=>`结果${row.rank}：前区命中 ${hitText(row.frontHits)}；后区命中 ${hitText(row.backHits)}；五行相似度 ${percent(row.elementSimilarity)}。`).join("<br>");
  logs.querySelector(".log-list").innerHTML=`${evaluation?`<div class="log"><div class="log-time">第${evaluation.issue}期复盘</div><div><div class="log-title">Chee结果与实际开奖已完成对照</div><div class="log-body">实际：${evaluation.actual.front.join(" ")} + ${evaluation.actual.back.join(" ")}。<br>${evaluationRows}</div></div></div>`:""}<div class="log"><div class="log-time">五行校准</div><div><div class="log-title">采用 ${payload.calibration?.selectedLabel||payload.calibration?.selectedProfile||"校准"} 路径</div><div class="log-body">主势为${payload.analysis?.dominant||"-"}，弱势为${payload.analysis?.weakest||"-"}，相生流向为${payload.analysis?.flowTarget||"-"}。最近 ${payload.calibration?.tests||0} 个滚动测试的前区平均命中 ${payload.calibration?.averageFrontHits??"-"} 个，后区平均命中 ${payload.calibration?.averageBackHits??"-"} 个。</div></div></div><div class="log"><div class="log-time">下一期生成</div><div><div class="log-title">两组Chee结果已自动更新</div><div class="log-body">号码命中和五行分布相似度会写入指数移动平均，实时反馈受到上限约束，避免单期开奖让模型大幅漂移。</div></div></div>`;
}

function renderChee(payload){
  const card=document.querySelector("#prediction .grid > .card:nth-child(2)");
  if(!card) return;
  const description=card.querySelector(".section-head .muted");
  if(description) description.textContent=`易经数字五行模型基于 ${Number(payload.historyCount).toLocaleString("zh-CN")} 期数据，复盘后输出 2 组结果。`;
  const order=["金","火","土","木","水"];
  const bars=card.querySelector(".chee-bars");
  if(bars) bars.innerHTML=order.map(name=>{const value=Number(payload.elementStrengths?.[name]||0);return `<div class="chee-row"><span>${name}</span><div class="bar"><div class="fill" style="width:${Math.max(0,Math.min(100,value))}%"></div></div><span>${Math.round(value)}</span></div>`}).join("");
  const list=card.querySelector(".forecast-list");
  if(list&&Array.isArray(payload.results)) list.innerHTML=payload.results.map(cheeCard).join("");
  renderCheeLearning(payload);
}

async function loadCheeForecast(){try{renderChee(await fetchJson(CHEE_FORECAST_URL))}catch(error){console.warn("Chee forecast unavailable",error)}}

function statusClass(status){if(status==="已同步") return "ok";if(status==="同步失败") return "fail";return "wait"}
function filteredDraws(){const query=document.getElementById("searchInput").value.trim();if(!query) return draws.map((item,index)=>({...item,_i:index}));return draws.map((item,index)=>({...item,_i:index})).filter(item=>item.issue.includes(query)||item.date.includes(query)||item.front.includes(query)||item.back.includes(query))}

function renderAdmin(){
  const list=filteredDraws();const pages=Math.max(1,Math.ceil(list.length/pageSize));if(currentPage>pages) currentPage=pages;const rows=list.slice((currentPage-1)*pageSize,currentPage*pageSize);
  document.getElementById("drawBody").innerHTML=rows.map(item=>`<tr><td>${item.issue}</td><td>${item.date}</td><td>${item.front}${item.back?` + ${item.back}`:""}</td><td><span class="status ${statusClass(item.status)}">${item.status}</span></td><td><button class="btn edit" onclick="openEdit(${item._i})">编辑</button><button class="btn del" onclick="deleteDraw(${item._i})">删除</button></td></tr>`).join("");
  const windowSize=7;const start=Math.max(1,Math.min(currentPage-Math.floor(windowSize/2),pages-windowSize+1));const end=Math.min(pages,start+windowSize-1);const buttons=[];
  if(currentPage>1) buttons.push(`<button onclick="currentPage--;renderAdmin()">‹</button>`);if(start>1) buttons.push(`<button onclick="currentPage=1;renderAdmin()">1</button><span class="muted">…</span>`);for(let page=start;page<=end;page++) buttons.push(`<button class="${page===currentPage?"active":""}" onclick="currentPage=${page};renderAdmin()">${page}</button>`);if(end<pages) buttons.push(`<span class="muted">…</span><button onclick="currentPage=${pages};renderAdmin()">${pages}</button>`);if(currentPage<pages) buttons.push(`<button onclick="currentPage++;renderAdmin()">›</button>`);document.getElementById("pager").innerHTML=buttons.join("");
  const total=syncMeta.total||draws.length;const range=syncMeta.earliestDate&&syncMeta.latestDate?`${syncMeta.earliestDate} 至 ${syncMeta.latestDate}`:"完整可用范围";document.getElementById("syncMeta").textContent=`已同步 ${total.toLocaleString("zh-CN")} 期 · ${range} · ${syncMeta.source||"历史开奖数据库"}`;
}

document.getElementById("searchInput").addEventListener("input",()=>{currentPage=1;renderAdmin()});
function openEdit(index){editingIndex=index;const item=draws[index];editIssue.value=item.issue;editDate.value=item.date;editFront.value=item.front;editBack.value=item.back;editModal.classList.add("show")}
function closeModal(){editModal.classList.remove("show")}
function saveEdit(){const originalIssue=draws[editingIndex].issue;const updated={...draws[editingIndex],issue:editIssue.value.trim(),date:editDate.value.trim(),front:editFront.value.trim(),back:editBack.value.trim(),status:"已同步"};if(!validDraw(updated)){alert("号码格式不正确。前区需要5个不重复的01至35号码，后区需要2个不重复的01至12号码。");return}draws[editingIndex]=updated;const edits=JSON.parse(localStorage.getItem("cheeDrawEdits")||"{}");delete edits[originalIssue];edits[updated.issue]=updated;localStorage.setItem("cheeDrawEdits",JSON.stringify(edits));closeModal();renderAdmin()}
function deleteDraw(index){if(confirm("确认删除这条开奖记录？")){const issue=draws[index].issue;const deleted=JSON.parse(localStorage.getItem("cheeDeletedDraws")||"[]");if(!deleted.includes(issue)) deleted.push(issue);localStorage.setItem("cheeDeletedDraws",JSON.stringify(deleted));draws.splice(index,1);renderAdmin()}}

loadDraws();
loadForecast();
loadCheeForecast();
