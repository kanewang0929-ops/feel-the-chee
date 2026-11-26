const tabs=[...document.querySelectorAll("button.tab[data-page]")];
function selectPage(page,updateUrl=false){
  if(!tabs.some(button=>button.dataset.page===page)) page="prediction";
  tabs.forEach(button=>{
    const selected=button.dataset.page===page;
    button.classList.toggle("active",selected);
    button.setAttribute("aria-selected",String(selected));
    button.tabIndex=selected?0:-1;
  });
  document.querySelectorAll(".page").forEach(panel=>{
    const selected=panel.id===page;
    panel.classList.toggle("active",selected);
    panel.hidden=!selected;
  });
  if(updateUrl) history.replaceState(null,"",`#${page}`);
}
tabs.forEach((button,index)=>{
  button.addEventListener("click",()=>selectPage(button.dataset.page,true));
  button.addEventListener("keydown",event=>{
    let next;
    if(event.key==="ArrowRight") next=(index+1)%tabs.length;
    if(event.key==="ArrowLeft") next=(index-1+tabs.length)%tabs.length;
    if(event.key==="Home") next=0;
    if(event.key==="End") next=tabs.length-1;
    if(next===undefined) return;
    event.preventDefault();
    selectPage(tabs[next].dataset.page,true);
    tabs[next].focus();
  });
});
window.addEventListener("hashchange",()=>selectPage(location.hash.slice(1)));
selectPage(location.hash.slice(1));

function escapeText(value){
  return String(value??"").replace(/[&<>"']/g,char=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
}

function formatBeijing(value){
  const date=new Date(value);
  if(!value||Number.isNaN(date.getTime())) return "未记录";
  return new Intl.DateTimeFormat("zh-CN",{timeZone:"Asia/Shanghai",year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false}).format(date);
}

function beijingDate(now=new Date()){
  const parts=new Intl.DateTimeFormat("en",{timeZone:"Asia/Shanghai",year:"numeric",month:"2-digit",day:"2-digit"}).formatToParts(now);
  const part=type=>parts.find(item=>item.type===type).value;
  return `${part("year")}-${part("month")}-${part("day")}`;
}

function isPastTarget(targetDate,now=new Date()){
  return /^\d{4}-\d{2}-\d{2}$/.test(String(targetDate||""))&&targetDate<beijingDate(now);
}

function validTicket(ticket){
  return [[ticket?.front,5,35],[ticket?.back,2,12]].every(([values,count,max])=>
    Array.isArray(values)&&values.length===count&&new Set(values.map(Number)).size===count&&
    values.every(value=>Number.isInteger(Number(value))&&Number(value)>=1&&Number(value)<=max));
}

const LIVE_HISTORY_URL="https://raw.githubusercontent.com/yangxb919/lottery-data/main/data/dlt.json";
const LOCAL_HISTORY_URL="./data/draws.json";
const DUEL_DASHBOARD_URL="./data/joy-kane-dashboard.json";
let duelPayloadPromise=null;
function loadDuelPayload(){
  if(!duelPayloadPromise) duelPayloadPromise=fetchJson(DUEL_DASHBOARD_URL);
  return duelPayloadPromise;
}

let draws=[];
let originalDraws=[];
let currentPage=1;
const pageSize=10;
let editingIndex=null;
let editingSourceIssue=null;
let syncMeta={};

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
  return Boolean(/^\d+$/.test(record.issue)&&/^\d{4}-\d{2}-\d{2}$/.test(record.date))&&
    front.length===5&&new Set(front).size===5&&front.every(number=>Number.isInteger(number)&&number>=1&&number<=35)&&
    back.length===2&&new Set(back).size===2&&back.every(number=>Number.isInteger(number)&&number>=1&&number<=12);
}

function readLocalValue(key,fallback){
  try{
    const value=JSON.parse(localStorage.getItem(key)||"null");
    if(Array.isArray(fallback)) return Array.isArray(value)?value:fallback;
    return value&&typeof value==="object"&&!Array.isArray(value)?value:fallback;
  }catch(error){return fallback;}
}

function applyBrowserOverrides(base){
  const edits=readLocalValue("cheeDrawEdits",{});
  const deleted=new Set(readLocalValue("cheeDeletedDraws",[]));
  return base
    .filter(item=>!deleted.has(item.issue))
    .map(item=>{
      const edited=edits[item.issue]?normalizeDraw({...item,...edits[item.issue]}):null;
      return {...(edited&&validDraw(edited)?{...edited,status:"本地修改"}:item),_sourceIssue:item.issue};
    });
}

async function fetchJson(url){
  const controller=new AbortController();
  const timeout=setTimeout(()=>controller.abort(),12000);
  try{
    const response=await fetch(`${url}?v=${Date.now()}`,{cache:"no-store",signal:controller.signal});
    if(!response.ok) throw new Error(`HTTP ${response.status}`);
    return await response.json();
  }finally{clearTimeout(timeout);}
}

async function fetchLiveHistory(){
  const payload=await fetchJson(LIVE_HISTORY_URL);
  if(!Array.isArray(payload)) throw new Error("历史数据格式错误");
  const today=beijingDate();
  const normalized=payload.map(normalizeDraw).filter(record=>validDraw(record)&&record.date<=today);
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
    meta:{
      ...(!Array.isArray(payload)?payload.meta||{}:{}),
      source:(!Array.isArray(payload)&&payload.meta?.source)||"已发布历史数据库",
      total:normalized.length,
      latestIssue:normalized[0]?.issue,
      latestDate:normalized[0]?.date,
      earliestIssue:normalized.at(-1)?.issue,
      earliestDate:normalized.at(-1)?.date
    }
  };
}

function newerArchive(candidate,current){
  if(!candidate?.draws?.length) return false;
  if(candidate.draws[0].date>beijingDate()) return false;
  if(!current?.draws?.length) return true;
  if(candidate.draws.length<current.draws.length) return false;
  const latest=candidate.draws[0],previous=current.draws[0];
  return latest.date>previous.date||(latest.date===previous.date&&Number(latest.issue)>Number(previous.issue));
}

async function loadDraws(){
  const metaNode=document.getElementById("syncMeta");
  if(metaNode) metaNode.textContent="正在同步全部历史开奖记录...";
  let localResult=null;
  try{
    localResult=await fetchLocalHistory();
    originalDraws=localResult.draws;
    draws=applyBrowserOverrides(originalDraws);
    syncMeta={...localResult.meta,refreshing:true};
    renderAdmin();
  }catch(error){
    console.warn("Local history unavailable",error);
  }

  try{
    const liveResult=await fetchLiveHistory();
    if(newerArchive(liveResult,localResult)){
      originalDraws=liveResult.draws;
      // Re-read local overrides in case the user edited a record while the fetch was pending.
      draws=applyBrowserOverrides(originalDraws);
      syncMeta=liveResult.meta;
    }else{
      syncMeta={...syncMeta,refreshing:false};
    }
  }catch(error){
    console.warn("Live history unavailable",error);
    if(localResult){
      syncMeta={...localResult.meta,error:String(error)};
    }else{
      originalDraws=[];
      draws=[];
      syncMeta={unavailable:true,error:String(error)};
    }
  }

  // Keep the reader's search and current page when a background refresh completes.
  renderAdmin();
}

function ball(number,back=false){
  return `<span class="ball${back?" back":""}">${escapeText(String(number).padStart(2,"0"))}</span>`;
}

function scoreText(value){
  return Number(value||0).toFixed(1);
}

function forecastCard(result,targetDate){
  return `<div class="forecast">
    <div class="forecast-top">
      <strong>${isPastTarget(targetDate)?"历史号码":"目标号码"} · ${escapeText(result.label||"Joy Main")}</strong>
      <span class="score">5 个前区 + 2 个后区</span>
    </div>
    <div class="numbers">
      ${(result.front||[]).map(number=>ball(number)).join("")}
      <span class="plus">+</span>
      ${(result.back||[]).map(number=>ball(number,true)).join("")}
    </div>
    ${result.reason?`<div class="reason">${escapeText(result.reason)}</div>`:""}
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
    "AI信号严格按历史期次逐期生成，每一期只读取目标期之前的开奖数据。";
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
        <div class="log-title">从过去的开奖曲线与波动带生成候选</div>
        <div class="log-body">前区中心：${centers.join(" / ")}；标准差：${sigmas.join(" / ")}。页面固定显示3组AI结果。</div>
      </div>
    </div>`;
}

function renderForecast(payload){
  const card=document.getElementById("aiPredictionCard");
  if(!card) return;
  const results=Array.isArray(payload.results)?payload.results.filter(validTicket).slice(0,1):[];
  card.querySelector(".forecast-list").innerHTML=results.length
    ?results.map(result=>forecastCard(result,payload.targetDate)).join("")
    :`<div class="forecast"><div class="muted">AI结果暂不可用。</div></div>`;
  card.querySelector(".section-head .muted").textContent=
    "按历史信号生成一组号码，开奖后按实际命中数评分。";
  card.querySelector(".section-head .badge").textContent=`Joy · ${results.length}组预测`;
  card.querySelector(".forecast-meta").textContent=`第 ${payload.targetIssue||"—"} 期 · 目标开奖 ${payload.targetDate||"未记录"}`;
  card.querySelector(".forecast-meta").classList.toggle("is-stale",isPastTarget(payload.targetDate));
  const next=document.querySelector(".next");
  if(next) next.textContent=`${isPastTarget(payload.targetDate)?"最近发布目标":"目标开奖"}：${payload.targetDate||"未记录"} · 第 ${payload.targetIssue||"—"} 期`;
}

function renderHomeSummary(payload){
  const forecast=payload.nextForecast||{};
  const lock=payload.livePredictionLock||{};
  const sealed=Boolean(lock.lockedAt&&String(lock.issue)===String(forecast.targetIssue)&&lock.date===forecast.targetDate);
  const past=isPastTarget(forecast.targetDate);
  document.getElementById("homeLockStatus").textContent=past?"显示最近发布的历史预测":sealed?"Joy / Kane 预测已封存":"封存状态未验证";
  document.getElementById("homeLockStatus").classList.toggle("is-stale",past);
  document.getElementById("homeLockDetail").textContent=past?"目标开奖日期已过，请核对模型更新记录":sealed?`${formatBeijing(lock.lockedAt)} · 北京时间`:"请在模型运行中心核对当前记录";
  document.getElementById("homeUpdatedAt").textContent=formatBeijing(payload.generatedAt);
  document.getElementById("homeVersion").textContent=payload.modelVersion||"版本未记录";
  document.getElementById("homeArchiveCount").textContent=Number.isInteger(forecast.historyCount)?`${forecast.historyCount.toLocaleString("zh-CN")} 期历史开奖`:"样本数未记录";
  document.getElementById("homeArchiveThrough").textContent=`数据截止 ${payload.summary?.dateRange?.latest||"未记录"}`;
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
    const payload=await loadDuelPayload();
    renderHomeSummary(payload);
    const joy=payload.nextForecast?.joy||{};
    renderForecast({...joy,targetIssue:payload.nextForecast?.targetIssue,targetDate:payload.nextForecast?.targetDate,historyCount:payload.nextForecast?.historyCount});
  }catch(error){
    console.warn("Forecast unavailable",error);
    const list=document.querySelector("#aiPredictionCard .forecast-list");
    if(list) list.innerHTML=`<div class="forecast"><div class="muted">AI结果加载失败，请稍后刷新。</div></div>`;
    document.querySelector(".next").textContent="预测数据暂不可用";
    document.getElementById("homeLockStatus").textContent="无法读取封存状态";
    document.getElementById("homeLockDetail").textContent="请稍后刷新页面";
    document.getElementById("homeVersion").textContent="模型数据暂不可用";
    document.getElementById("homeArchiveThrough").textContent="模型数据暂不可用";
    document.querySelector("#aiPredictionCard .forecast-meta").textContent="目标期次暂不可用";
  }
}

async function loadCheeForecast(){
  try{
    const payload=await fetchJson("./data/chee-forecast.json");
    renderChee(payload);
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
    <td>${escapeText(item.issue)}</td>
    <td>${escapeText(item.date)}</td>
    <td class="archive-numbers">${escapeText(item.front)}${item.back?` + ${escapeText(item.back)}`:""}</td>
    <td><span class="status ${statusClass(item.status)}">${escapeText(item.status)}</span></td>
    <td>
      <button class="btn edit" aria-label="本地编辑第 ${escapeText(item.issue)} 期" onclick="openEdit(${item._i})">本地编辑</button>
      <button class="btn secondary" aria-label="在此浏览器隐藏第 ${escapeText(item.issue)} 期" onclick="deleteDraw(${item._i})">隐藏</button>
    </td>
  </tr>`).join("")||`<tr><td colspan="5" class="empty-state">${syncMeta.unavailable?"开奖记录暂不可用，请稍后刷新。":"没有找到匹配的记录，请尝试其他期次、日期或号码。"}</td></tr>`;

  const windowSize=7;
  const start=Math.max(1,Math.min(currentPage-Math.floor(windowSize/2),pages-windowSize+1));
  const end=Math.min(pages,start+windowSize-1);
  const buttons=[];
  if(currentPage>1) buttons.push(`<button aria-label="上一页" onclick="currentPage--;renderAdmin()">‹</button>`);
  if(start>1) buttons.push(`<button onclick="currentPage=1;renderAdmin()">1</button><span class="muted">…</span>`);
  for(let page=start;page<=end;page++){
    buttons.push(`<button class="${page===currentPage?"active":""}" ${page===currentPage?'aria-current="page"':""} aria-label="第 ${page} 页" onclick="currentPage=${page};renderAdmin()">${page}</button>`);
  }
  if(end<pages) buttons.push(`<span class="muted">…</span><button onclick="currentPage=${pages};renderAdmin()">${pages}</button>`);
  if(currentPage<pages) buttons.push(`<button aria-label="下一页" onclick="currentPage++;renderAdmin()">›</button>`);
  pager.innerHTML=list.length?buttons.join(""):"";

  const total=syncMeta.total||draws.length;
  const range=syncMeta.earliestDate&&syncMeta.latestDate
    ?`${syncMeta.earliestDate} 至 ${syncMeta.latestDate}`
    :"完整可用范围";
  const sourceState=syncMeta.refreshing?"已显示快照，正在检查在线更新":syncMeta.error?"在线源暂不可用，显示已发布快照":"已读取";
  metaNode.textContent=syncMeta.unavailable?"本地与在线数据均未能读取，页面未填充示例记录。":`${sourceState} ${Number(total).toLocaleString("zh-CN")} 期 · ${range} · ${syncMeta.source||"历史开奖数据库"}`;
  document.getElementById("archiveResultCount").textContent=list.length?`共 ${list.length.toLocaleString("zh-CN")} 条匹配记录 · 第 ${currentPage} / ${pages} 页`:"0 条匹配记录";
}

document.getElementById("searchInput")?.addEventListener("input",()=>{
  currentPage=1;
  renderAdmin();
});

let modalReturnFocus=null;
function openEdit(index){
  editingIndex=index;
  const item=draws[index];
  if(!item) return;
  editingSourceIssue=item._sourceIssue||item.issue;
  editIssue.value=item.issue;
  editDate.value=item.date;
  editFront.value=item.front;
  editBack.value=item.back;
  modalReturnFocus=document.activeElement;
  editModal.classList.add("show");
  editIssue.focus();
}

function closeModal(){
  editModal.classList.remove("show");
  if(modalReturnFocus?.isConnected) modalReturnFocus.focus();
  else document.getElementById("searchInput")?.focus();
}

document.getElementById("editModal")?.addEventListener("keydown",event=>{
  if(event.key==="Escape") {event.preventDefault();closeModal();return;}
  if(event.key!=="Tab") return;
  const controls=[...editModal.querySelectorAll("input,button")];
  const first=controls[0],last=controls.at(-1);
  if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}
  if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
});

function saveEdit(){
  // Incoming online records may change row indexes while this dialog is open.
  if(editingSourceIssue!==null) editingIndex=draws.findIndex(item=>(item._sourceIssue||item.issue)===editingSourceIssue);
  if(editingIndex===null||!draws[editingIndex]) return;
  const originalIssue=draws[editingIndex]._sourceIssue||draws[editingIndex].issue;
  const updated={
    ...draws[editingIndex],
    issue:editIssue.value.trim(),
    date:editDate.value.trim(),
    front:editFront.value.trim(),
    back:editBack.value.trim(),
    status:"本地修改"
  };

  if(!validDraw(updated)){
    alert("号码格式不正确。前区需要5个不重复的01至35号码，后区需要2个不重复的01至12号码。");
    return;
  }

  const edits=readLocalValue("cheeDrawEdits",{});
  edits[originalIssue]=updated;
  try{localStorage.setItem("cheeDrawEdits",JSON.stringify(edits));}
  catch(error){alert("浏览器未允许保存本地记录，请检查存储设置后重试。");return;}
  draws[editingIndex]=updated;
  closeModal();
  renderAdmin();
}

function deleteDraw(index){
  if(!draws[index]||!confirm("仅在此浏览器隐藏这条开奖记录？可通过“恢复原始记录”撤销。线上数据库不会改变。")) return;
  const issue=draws[index]._sourceIssue||draws[index].issue;
  const deleted=readLocalValue("cheeDeletedDraws",[]);
  if(!deleted.includes(issue)) deleted.push(issue);
  try{localStorage.setItem("cheeDeletedDraws",JSON.stringify(deleted));}
  catch(error){alert("浏览器未允许保存本地记录，请检查存储设置后重试。");return;}
  draws.splice(index,1);
  renderAdmin();
}

document.getElementById("resetLocalChanges")?.addEventListener("click",()=>{
  if(!confirm("清除此浏览器的编辑和隐藏记录，恢复原始公开数据？")) return;
  try{localStorage.removeItem("cheeDrawEdits");localStorage.removeItem("cheeDeletedDraws");}
  catch(error){alert("无法清除本地记录，请检查浏览器存储设置。");return;}
  draws=applyBrowserOverrides(originalDraws);
  currentPage=1;
  renderAdmin();
});

loadDraws();
loadForecast();
// Chee is rendered only by chee-runtime.js, which verifies its target draw.
