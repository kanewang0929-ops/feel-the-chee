const tabs=[...document.querySelectorAll('.tab')];
tabs.forEach(btn=>btn.addEventListener('click',()=>{
  tabs.forEach(x=>x.classList.remove('active'));
  btn.classList.add('active');
  document.querySelectorAll('.page').forEach(x=>x.classList.remove('active'));
  document.getElementById(btn.dataset.page).classList.add('active');
}));

const LIVE_HISTORY_URL='https://raw.githubusercontent.com/yangxb919/lottery-data/main/data/dlt.json';
const LOCAL_HISTORY_URL='./data/draws.json';
const FORECAST_URL='./data/forecast.json';

let draws=[];
let currentPage=1;
const pageSize=10;
let editingIndex=null;
let syncMeta={};

const fallbackDraws=[
  {issue:'26083',date:'2026-07-25',front:'14 15 16 23 26',back:'07 09',status:'已同步'},
  {issue:'26082',date:'2026-07-22',front:'16 26 27 28 34',back:'02 06',status:'已同步'},
  {issue:'26081',date:'2026-07-20',front:'08 16 18 24 34',back:'09 12',status:'已同步'}
];

function normalizeDraw(record){
  return {
    issue:String(record.issue||'').trim(),
    date:String(record.date||'').trim(),
    front:Array.isArray(record.front)?record.front.join(' '):String(record.front||'').trim(),
    back:Array.isArray(record.back)?record.back.join(' '):String(record.back||'').trim(),
    status:record.status||'已同步',
    source:record.source||''
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
  const edits=JSON.parse(localStorage.getItem('cheeDrawEdits')||'{}');
  const deleted=new Set(JSON.parse(localStorage.getItem('cheeDeletedDraws')||'[]'));
  return base.filter(d=>!deleted.has(d.issue)).map(d=>edits[d.issue]?{...d,...edits[d.issue]}:d);
}

async function fetchJson(url){
  const response=await fetch(url,{cache:'no-store'});
  if(!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

function normalizeHistory(payload,source){
  const rows=Array.isArray(payload)?payload:(payload.draws||[]);
  const normalized=rows.map(normalizeDraw).filter(validDraw);
  normalized.sort((a,b)=>b.date.localeCompare(a.date)||Number(b.issue)-Number(a.issue));
  const meta=Array.isArray(payload)?{}:(payload.meta||{});
  return {
    draws:normalized,
    meta:{
      ...meta,
      total:normalized.length,
      latestIssue:normalized[0]?.issue,
      latestDate:normalized[0]?.date,
      earliestIssue:normalized.at(-1)?.issue,
      earliestDate:normalized.at(-1)?.date,
      source:meta.source||source
    }
  };
}

async function loadDraws(){
  const metaNode=document.getElementById('syncMeta');
  if(metaNode) metaNode.textContent='正在同步全部历史开奖记录...';
  let localResult=null;
  let liveResult=null;

  try{localResult=normalizeHistory(await fetchJson(LOCAL_HISTORY_URL),'本地自动同步数据库')}catch(error){console.warn(error)}
  try{liveResult=normalizeHistory(await fetchJson(LIVE_HISTORY_URL),'互联网全量历史数据')}catch(error){console.warn(error)}

  let selected=null;
  if(localResult&&liveResult){
    const localLatest=localResult.meta.latestDate||'';
    const liveLatest=liveResult.meta.latestDate||'';
    selected=localLatest>=liveLatest?localResult:liveResult;
  }else{
    selected=localResult||liveResult;
  }

  if(!selected||!selected.draws.length){
    selected=normalizeHistory(fallbackDraws,'应急预览数据');
  }

  draws=applyBrowserOverrides(selected.draws);
  syncMeta=selected.meta;
  currentPage=1;
  renderAdmin();
}

function ball(number,back=false){
  return `<span class="ball${back?' back':''}">${number}</span>`;
}

function numberLine(front,back){
  return `${front.map(n=>ball(n)).join('')}<span class="plus">+</span>${back.map(n=>ball(n,true)).join('')}`;
}

function forecastCard(result){
  return `<div class="forecast">
    <div class="forecast-top">
      <strong>预测结果 ${result.rank} · ${result.label}</strong>
      <span class="score">模型匹配度 ${Number(result.fit).toFixed(1)}</span>
    </div>
    <div class="numbers">${numberLine(result.front,result.back)}</div>
    <div class="reason">${result.reason}</div>
  </div>`;
}

function percent(value){return `${Math.round(Number(value||0)*100)}%`}

function evaluationHtml(evaluation){
  if(!evaluation) return '';
  const actual=evaluation.actual||{front:[],back:[]};
  const rows=(evaluation.results||[]).map(row=>{
    const frontText=row.frontHits?.length?row.frontHits.join('、'):'无';
    const backText=row.backHits?.length?row.backHits.join('、'):'无';
    return `预测${row.rank}：前区命中 ${row.frontHitCount} 个（${frontText}），后区命中 ${row.backHitCount} 个（${backText}）`;
  }).join('<br>');
  return `<div class="log">
    <div class="log-time">第${evaluation.issue}期复盘</div>
    <div>
      <div class="log-title">预测结果与实际开奖完成对比</div>
      <div class="log-body">
        实际开奖：${actual.front.join(' ')} + ${actual.back.join(' ')}<br>
        ${rows}<br>
        三组平均：前区 ${evaluation.summary?.averageFrontHits??'-'} 个，后区 ${evaluation.summary?.averageBackHits??'-'} 个。
      </div>
    </div>
  </div>`;
}

function renderForecast(payload){
  const list=document.querySelector('#prediction .grid > .card:first-child .forecast-list');
  if(list&&Array.isArray(payload.results)) list.innerHTML=payload.results.map(forecastCard).join('');

  const description=document.querySelector('#prediction .grid > .card:first-child .section-head .muted');
  if(description){
    description.textContent=`基于 ${Number(payload.historyCount).toLocaleString('zh-CN')} 期历史数据，完成开奖复盘与自适应校准后输出 3 组候选结果。`;
  }

  const next=document.querySelector('.next');
  if(next) next.textContent=`下一期开奖：${payload.targetDate} · 第${payload.targetIssue}期`;

  const weights=payload.calibration?.frontWeights||{};
  const aggregate=[
    (weights.r10||0)+(weights.r30||0)+(weights.r100||0)+(weights.r300||0),
    weights.gap||0,
    (weights.long||0)+(weights.momentum||0),
    weights.transition||0
  ];
  document.querySelectorAll('#learning .weight-grid .weight strong').forEach((node,index)=>{
    if(aggregate[index]!==undefined) node.textContent=percent(aggregate[index]);
  });

  const version=document.querySelector('#learning .section-head .badge');
  if(version) version.textContent=`模型版本 ${payload.modelVersion}`;

  const front=payload.calibration?.front||{};
  const back=payload.calibration?.back||{};
  const logs=document.querySelector('#learning .log-list');
  if(logs){
    logs.innerHTML=`
      ${evaluationHtml(payload.lastEvaluation)}
      <div class="log">
        <div class="log-time">第${payload.targetIssue}期</div>
        <div>
          <div class="log-title">已生成下一期开奖预测</div>
          <div class="log-body">数据库已更新至第${payload.historyRange.latestIssue}期，共 ${Number(payload.historyCount).toLocaleString('zh-CN')} 期。系统生成三条互相分散的候选路径，并自动提交给 Render。</div>
        </div>
      </div>
      <div class="log">
        <div class="log-time">前区学习</div>
        <div>
          <div class="log-title">采用 ${front.selectedProfile||'校准'} 权重组合</div>
          <div class="log-body">${front.tests||0} 个滚动测试，前5名平均命中 ${front.averageMainHits??'-'} 个；实时反馈修正 ${Number(front.adaptiveBonus||0).toFixed(4)}。历史回测仍占主导。</div>
        </div>
      </div>
      <div class="log">
        <div class="log-time">后区学习</div>
        <div>
          <div class="log-title">采用 ${back.selectedProfile||'校准'} 权重组合</div>
          <div class="log-body">${back.tests||0} 个滚动测试，前2名平均命中 ${back.averageMainHits??'-'} 个；实时反馈修正 ${Number(back.adaptiveBonus||0).toFixed(4)}。</div>
        </div>
      </div>`;
  }
}

async function loadForecast(){
  try{renderForecast(await fetchJson(FORECAST_URL))}catch(error){console.warn('Forecast unavailable',error)}
}

function statusClass(status){
  if(status==='已同步') return 'ok';
  if(status==='同步失败') return 'fail';
  return 'wait';
}

function filteredDraws(){
  const q=document.getElementById('searchInput').value.trim();
  if(!q) return draws.map((d,i)=>({...d,_i:i}));
  return draws.map((d,i)=>({...d,_i:i})).filter(d=>d.issue.includes(q)||d.date.includes(q)||d.front.includes(q)||d.back.includes(q));
}

function renderAdmin(){
  const list=filteredDraws();
  const pages=Math.max(1,Math.ceil(list.length/pageSize));
  if(currentPage>pages) currentPage=pages;
  const rows=list.slice((currentPage-1)*pageSize,currentPage*pageSize);
  document.getElementById('drawBody').innerHTML=rows.map(d=>`
    <tr>
      <td>${d.issue}</td><td>${d.date}</td><td>${d.front} + ${d.back}</td>
      <td><span class="status ${statusClass(d.status)}">${d.status}</span></td>
      <td><button class="btn edit" onclick="openEdit(${d._i})">编辑</button><button class="btn del" onclick="deleteDraw(${d._i})">删除</button></td>
    </tr>`).join('');

  const windowSize=7;
  const start=Math.max(1,Math.min(currentPage-Math.floor(windowSize/2),pages-windowSize+1));
  const end=Math.min(pages,start+windowSize-1);
  const buttons=[];
  if(currentPage>1) buttons.push('<button onclick="currentPage--;renderAdmin()">‹</button>');
  if(start>1) buttons.push('<button onclick="currentPage=1;renderAdmin()">1</button><span class="muted">…</span>');
  for(let page=start;page<=end;page++) buttons.push(`<button class="${page===currentPage?'active':''}" onclick="currentPage=${page};renderAdmin()">${page}</button>`);
  if(end<pages) buttons.push(`<span class="muted">…</span><button onclick="currentPage=${pages};renderAdmin()">${pages}</button>`);
  if(currentPage<pages) buttons.push('<button onclick="currentPage++;renderAdmin()">›</button>');
  document.getElementById('pager').innerHTML=buttons.join('');

  const total=syncMeta.total||draws.length;
  const range=syncMeta.earliestDate&&syncMeta.latestDate?`${syncMeta.earliestDate} 至 ${syncMeta.latestDate}`:'完整可用范围';
  document.getElementById('syncMeta').textContent=`已同步 ${total.toLocaleString('zh-CN')} 期 · ${range} · ${syncMeta.source||'历史开奖数据库'}`;
}

document.getElementById('searchInput').addEventListener('input',()=>{currentPage=1;renderAdmin()});

function openEdit(index){
  editingIndex=index;
  const d=draws[index];
  editIssue.value=d.issue;editDate.value=d.date;editFront.value=d.front;editBack.value=d.back;
  editModal.classList.add('show');
}
function closeModal(){editModal.classList.remove('show')}
function saveEdit(){
  const originalIssue=draws[editingIndex].issue;
  const updated={...draws[editingIndex],issue:editIssue.value.trim(),date:editDate.value.trim(),front:editFront.value.trim(),back:editBack.value.trim(),status:'已同步'};
  if(!validDraw(updated)){
    alert('号码格式不正确。前区需要5个不重复的01至35号码，后区需要2个不重复的01至12号码。');
    return;
  }
  draws[editingIndex]=updated;
  const edits=JSON.parse(localStorage.getItem('cheeDrawEdits')||'{}');
  delete edits[originalIssue];edits[updated.issue]=updated;
  localStorage.setItem('cheeDrawEdits',JSON.stringify(edits));
  closeModal();renderAdmin();
}
function deleteDraw(index){
  if(confirm('确认删除这条开奖记录？')){
    const issue=draws[index].issue;
    const deleted=JSON.parse(localStorage.getItem('cheeDeletedDraws')||'[]');
    if(!deleted.includes(issue)) deleted.push(issue);
    localStorage.setItem('cheeDeletedDraws',JSON.stringify(deleted));
    draws.splice(index,1);renderAdmin();
  }
}

loadDraws();
loadForecast();
