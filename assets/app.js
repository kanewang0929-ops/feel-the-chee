const tabs=[...document.querySelectorAll(".tab")];
tabs.forEach(btn=>btn.addEventListener("click",()=>{
  tabs.forEach(x=>x.classList.remove("active"));
  btn.classList.add("active");
  document.querySelectorAll(".page").forEach(x=>x.classList.remove("active"));
  document.getElementById(btn.dataset.page).classList.add("active");
}));

const LIVE_HISTORY_URL="https://raw.githubusercontent.com/yangxb919/lottery-data/main/data/dlt.json";
const LOCAL_HISTORY_URL="./data/draws.json";

let draws=[];
let currentPage=1;
const pageSize=10;
let editingIndex=null;
let syncMeta={};

const fallbackDraws=[
  {issue:"26082",date:"2026-07-22",front:"16 26 27 28 34",back:"02 06",status:"已同步"},
  {issue:"26081",date:"2026-07-20",front:"08 16 18 24 34",back:"09 12",status:"已同步"},
  {issue:"26080",date:"2026-07-18",front:"05 10 15 21 23",back:"07 08",status:"已同步"}
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
    front.length===5&&new Set(front).size===5&&front.every(n=>n>=1&&n<=35)&&
    back.length===2&&new Set(back).size===2&&back.every(n=>n>=1&&n<=12);
}

function applyBrowserOverrides(base){
  const edits=JSON.parse(localStorage.getItem("cheeDrawEdits")||"{}");
  const deleted=new Set(JSON.parse(localStorage.getItem("cheeDeletedDraws")||"[]"));
  return base
    .filter(d=>!deleted.has(d.issue))
    .map(d=>edits[d.issue]?{...d,...edits[d.issue]}:d);
}

async function fetchJson(url){
  const response=await fetch(url,{cache:"no-store"});
  if(!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

async function fetchLiveHistory(){
  const payload=await fetchJson(LIVE_HISTORY_URL);
  if(!Array.isArray(payload)) throw new Error("历史数据格式错误");

  const normalized=payload.map(normalizeDraw).filter(validDraw);
  if(normalized.length<1000) throw new Error(`历史数据不足：${normalized.length}`);

  normalized.sort((a,b)=>{
    const dateOrder=b.date.localeCompare(a.date);
    if(dateOrder!==0) return dateOrder;
    return Number(b.issue)-Number(a.issue);
  });

  return {
    draws:normalized,
    meta:{
      total:normalized.length,
      latestIssue:normalized[0]?.issue,
      latestDate:normalized[0]?.date,
      earliestIssue:normalized.at(-1)?.issue,
      earliestDate:normalized.at(-1)?.date,
      source:"互联网全量历史数据 · 500.com",
      sourceMode:"live"
    }
  };
}

async function fetchLocalHistory(){
  const payload=await fetchJson(LOCAL_HISTORY_URL);
  const raw=Array.isArray(payload)?payload:(payload.draws||[]);
  const normalized=raw.map(normalizeDraw).filter(validDraw);
  if(!normalized.length) throw new Error("本地历史数据库为空");
  return {
    draws:normalized,
    meta:Array.isArray(payload)?{total:normalized.length,source:"本地历史数据库"}:{...(payload.meta||{}),total:normalized.length}
  };
}

async function loadDraws(){
  document.getElementById("syncMeta").textContent="正在同步全部历史开奖记录...";
  let localResult=null;

  try{
    localResult=await fetchLocalHistory();
  }catch(error){
    console.warn("Local history unavailable",error);
  }

  try{
    const liveResult=await fetchLiveHistory();
    const selected=localResult&&localResult.draws.length>=liveResult.draws.length
      ?localResult
      :liveResult;
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

function statusClass(s){
  if(s==="已同步") return "ok";
  if(s==="同步失败") return "fail";
  return "wait";
}

function filteredDraws(){
  const q=document.getElementById("searchInput").value.trim();
  if(!q) return draws.map((d,i)=>({...d,_i:i}));
  return draws.map((d,i)=>({...d,_i:i})).filter(d=>
    d.issue.includes(q)||d.date.includes(q)||d.front.includes(q)||d.back.includes(q)
  );
}

function renderAdmin(){
  const list=filteredDraws();
  const pages=Math.max(1,Math.ceil(list.length/pageSize));
  if(currentPage>pages) currentPage=pages;
  const rows=list.slice((currentPage-1)*pageSize,currentPage*pageSize);

  document.getElementById("drawBody").innerHTML=rows.map(d=>`
    <tr>
      <td>${d.issue}</td>
      <td>${d.date}</td>
      <td>${d.front}${d.back?` + ${d.back}`:""}</td>
      <td><span class="status ${statusClass(d.status)}">${d.status}</span></td>
      <td>
        <button class="btn edit" onclick="openEdit(${d._i})">编辑</button>
        <button class="btn del" onclick="deleteDraw(${d._i})">删除</button>
      </td>
    </tr>`).join("");

  const windowSize=7;
  const start=Math.max(1,Math.min(currentPage-Math.floor(windowSize/2),pages-windowSize+1));
  const end=Math.min(pages,start+windowSize-1);
  const pageButtons=[];
  if(currentPage>1) pageButtons.push(`<button onclick="currentPage--;renderAdmin()">‹</button>`);
  if(start>1) pageButtons.push(`<button onclick="currentPage=1;renderAdmin()">1</button><span class="muted">…</span>`);
  for(let page=start;page<=end;page++){
    pageButtons.push(`<button class="${page===currentPage?"active":""}" onclick="currentPage=${page};renderAdmin()">${page}</button>`);
  }
  if(end<pages) pageButtons.push(`<span class="muted">…</span><button onclick="currentPage=${pages};renderAdmin()">${pages}</button>`);
  if(currentPage<pages) pageButtons.push(`<button onclick="currentPage++;renderAdmin()">›</button>`);
  document.getElementById("pager").innerHTML=pageButtons.join("");

  const total=syncMeta.total||draws.length;
  const range=syncMeta.earliestDate&&syncMeta.latestDate
    ?`${syncMeta.earliestDate} 至 ${syncMeta.latestDate}`
    :"完整可用范围";
  const source=syncMeta.source||"历史开奖数据库";
  document.getElementById("syncMeta").textContent=
    `已同步 ${total.toLocaleString("zh-CN")} 期 · ${range} · ${source}`;
}

document.getElementById("searchInput").addEventListener("input",()=>{currentPage=1;renderAdmin()});

function openEdit(i){
  editingIndex=i;
  const d=draws[i];
  editIssue.value=d.issue;
  editDate.value=d.date;
  editFront.value=d.front;
  editBack.value=d.back;
  editModal.classList.add("show");
}
function closeModal(){editModal.classList.remove("show")}
function saveEdit(){
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
  closeModal();renderAdmin();
}
function deleteDraw(i){
  if(confirm("确认删除这条开奖记录？")){
    const issue=draws[i].issue;
    const deleted=JSON.parse(localStorage.getItem("cheeDeletedDraws")||"[]");
    if(!deleted.includes(issue)) deleted.push(issue);
    localStorage.setItem("cheeDeletedDraws",JSON.stringify(deleted));
    draws.splice(i,1);
    renderAdmin();
  }
}

loadDraws();
