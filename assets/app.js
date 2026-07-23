const tabs=[...document.querySelectorAll(".tab")];
tabs.forEach(btn=>btn.addEventListener("click",()=>{
  tabs.forEach(x=>x.classList.remove("active"));
  btn.classList.add("active");
  document.querySelectorAll(".page").forEach(x=>x.classList.remove("active"));
  document.getElementById(btn.dataset.page).classList.add("active");
}));

let draws=[];
let currentPage=1;
const pageSize=10;
let editingIndex=null;
let syncMeta={};

const fallbackDraws=[
  {issue:"26082",date:"2026-07-22",front:"16 26 27 28 34",back:"02 06",status:"已同步"},
  {issue:"26081",date:"2026-07-20",front:"08 16 18 24 34",back:"09 12",status:"已同步"},
  {issue:"26080",date:"2026-07-18",front:"05 10 15 21 23",back:"07 08",status:"已同步"},
  {issue:"26079",date:"2026-07-15",front:"06 08 23 26 27",back:"05 12",status:"已同步"},
  {issue:"26078",date:"2026-07-13",front:"02 13 20 25 32",back:"08 11",status:"已同步"},
  {issue:"26077",date:"2026-07-11",front:"04 14 19 24 27",back:"06 07",status:"已同步"},
  {issue:"26076",date:"2026-07-08",front:"15 20 27 28 35",back:"02 11",status:"已同步"},
  {issue:"26075",date:"2026-07-06",front:"01 06 16 18 26",back:"04 10",status:"已同步"},
  {issue:"26074",date:"2026-07-04",front:"01 04 10 23 25",back:"01 12",status:"已同步"},
  {issue:"26073",date:"2026-07-01",front:"04 10 22 23 33",back:"02 12",status:"已同步"},
  {issue:"26072",date:"2026-06-29",front:"01 13 26 29 30",back:"09 11",status:"已同步"}
];

function loadOverrides(base){
  const edits=JSON.parse(localStorage.getItem("cheeDrawEdits")||"{}");
  const deleted=new Set(JSON.parse(localStorage.getItem("cheeDeletedDraws")||"[]"));
  return base
    .filter(d=>!deleted.has(d.issue))
    .map(d=>edits[d.issue]?{...d,...edits[d.issue]}:d);
}

async function loadDraws(){
  try{
    const response=await fetch("./data/draws.json",{cache:"no-store"});
    if(!response.ok) throw new Error("HTTP "+response.status);
    const payload=await response.json();
    const base=Array.isArray(payload)?payload:(payload.draws||[]);
    syncMeta=Array.isArray(payload)?{}:(payload.meta||{});
    if(!base.length) throw new Error("empty data");
    draws=loadOverrides(base);
  }catch(error){
    draws=loadOverrides(fallbackDraws);
    syncMeta={total:draws.length,source:"本地预览数据",error:String(error)};
  }
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
    String(d.issue).includes(q)||
    String(d.date).includes(q)||
    String(d.front).includes(q)||
    String(d.back).includes(q)
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

  document.getElementById("pager").innerHTML=Array.from({length:pages},(_,i)=>`
    <button class="${i+1===currentPage?"active":""}" onclick="currentPage=${i+1};renderAdmin()">${i+1}</button>
  `).join("");

  const syncedAt=syncMeta.syncedAt?new Date(syncMeta.syncedAt).toLocaleString("zh-CN",{hour12:false}):"预览数据";
  const total=syncMeta.total||draws.length;
  document.getElementById("syncMeta").textContent=
    `历史开奖 ${total} 期 · 当前显示 ${list.length} 期 · 最近同步 ${syncedAt}`;
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
