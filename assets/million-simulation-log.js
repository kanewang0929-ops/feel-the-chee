/* Million-simulation training history for the model-learning page. */
(() => {
  const LOCAL="./data/million-simulation-log.json";
  const RAW="https://raw.githubusercontent.com/kanewang0929-ops/feel-the-chee/main/data/million-simulation-log.json";

  const number=(value,d=4)=>{
    const n=Number(value);
    return Number.isFinite(n)?n.toFixed(d):"-";
  };
  const time=value=>{
    if(!value)return "-";
    const d=new Date(value);
    return Number.isNaN(d.getTime())?String(value):d.toLocaleString("zh-CN",{hour12:false});
  };
  async function fetchJson(url){
    const r=await fetch(`${url}?v=${Date.now()}`,{cache:"no-store"});
    if(!r.ok)throw new Error(`${r.status} ${r.statusText}`);
    return r.json();
  }
  async function loadData(){
    for(const url of [LOCAL,RAW]){
      try{return await fetchJson(url)}catch(error){}
    }
    throw new Error("million-simulation-log.json unavailable");
  }
  function ensure(){
    const learning=document.getElementById("learning");
    if(!learning)return null;
    let card=document.getElementById("millionSimulationTrainingCard");
    if(!card){
      card=document.createElement("div");
      card.id="millionSimulationTrainingCard";
      card.className="card";
      learning.insertBefore(card,learning.firstChild);
    }
    return card;
  }
  function render(rows){
    const card=ensure();if(!card)return;
    if(!Array.isArray(rows)||!rows.length){
      card.innerHTML='<h2>百万模拟训练</h2><div class="muted">首次百万模拟尚未完成。</div>';
      return;
    }
    const latest=rows.at(-1);
    const ai=latest.ai||{}, chee=latest.chee||{}, agent=latest.agent||{};
    const total=rows.reduce((s,row)=>s+Number(row.totalIterations||0),0);
    const recent=[...rows].reverse().slice(0,10).map(row=>`<tr>
      <td>${time(row.generatedAt)}</td>
      <td>${Number(row.iterationsPerModel||0).toLocaleString("zh-CN")}</td>
      <td>${number(row.ai?.validationScoreAfter,2)}</td>
      <td>${row.ai?.accepted?"✓":"保持"}</td>
      <td>${number(row.chee?.auditScore,2)}</td>
      <td>${number(row.agent?.validationScoreAfter,2)}</td>
      <td>${row.agent?.accepted?"✓":"保持"}</td>
    </tr>`).join("");
    card.innerHTML=`<div class="section-head">
      <div><h2>每日百万模拟训练</h2><div class="muted">AI与Agent只接受通过时间顺序留出验证的改进；风水执行同规模审计，但公式永不因历史开奖结果改变。</div></div>
      <span class="badge gold">${Number(latest.iterationsPerModel||0).toLocaleString("zh-CN")} 次 / 模型</span>
    </div>
    <div class="weight-grid">
      <div class="weight"><span class="muted">本轮总模拟</span><strong>${Number(latest.totalIterations||0).toLocaleString("zh-CN")}</strong></div>
      <div class="weight"><span class="muted">累计百万层模拟</span><strong>${total.toLocaleString("zh-CN")}</strong></div>
      <div class="weight"><span class="muted">AI验证分</span><strong>${number(ai.validationScoreBefore,2)} → ${number(ai.validationScoreAfter,2)}</strong></div>
      <div class="weight"><span class="muted">Agent验证分</span><strong>${number(agent.validationScoreBefore,2)} → ${number(agent.validationScoreAfter,2)}</strong></div>
    </div>
    <div class="log-list">
      <div class="log"><div class="log-time">AI</div><div><div class="log-title">${ai.accepted?"新策略通过验证并写回":"挑战者未超过当前策略，保持原模型"}</div><div class="log-body">均值锚定 ${number(ai.anchorBefore,3)} → ${number(ai.anchorAfter,3)}；温度修正 ${number(ai.temperatureBefore,4)} → ${number(ai.temperatureAfter,4)}。</div></div></div>
      <div class="log"><div class="log-time">风水</div><div><div class="log-title">公式锁定 · 仅审计</div><div class="log-body">1,000,000次历史抽样审计分 ${number(chee.auditScore,2)}；公式参数没有改变。</div></div></div>
      <div class="log"><div class="log-time">Agent</div><div><div class="log-title">${agent.accepted?"新三源权重通过验证并写回":"新权重未超过当前策略，保持原权重"}</div><div class="log-body">验证分 ${number(agent.validationScoreBefore,2)} → ${number(agent.validationScoreAfter,2)}。</div></div></div>
    </div>
    <h3 style="margin-top:20px">最近百万模拟运行</h3>
    <div style="overflow:auto"><table><thead><tr><th>运行时间</th><th>每模型次数</th><th>AI分数</th><th>AI更新</th><th>风水审计</th><th>Agent分数</th><th>Agent更新</th></tr></thead><tbody>${recent}</tbody></table></div>
    <div class="notice" style="margin-top:14px">验证分用于比较历史样本外表现，不是下一期开奖的中奖概率。</div>`;
  }
  async function load(){
    const card=ensure();if(card)card.innerHTML='<h2>百万模拟训练</h2><div class="muted">正在读取每日百万模拟日志...</div>';
    try{render(await loadData())}catch(error){
      if(card)card.innerHTML='<h2>百万模拟训练</h2><div class="muted">首次百万模拟尚未落库，完成下一次每日训练后这里会自动显示。</div>';
    }
  }
  document.querySelectorAll('.tab[data-page="learning"]').forEach(button=>button.addEventListener("click",load));
  load();
})();