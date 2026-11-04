/* Dedicated million-iteration history panels for AI and Agent Instinct. */
(() => {
  const LOCAL = "./data/full-history-cycle-log.json";
  const RAW = "https://raw.githubusercontent.com/kanewang0929-ops/feel-the-chee/main/data/full-history-cycle-log.json";
  const PAGE_SIZE = 10;

  const fmt = (value, digits = 2) => {
    const n = Number(value);
    return Number.isFinite(n) ? n.toFixed(digits) : "-";
  };
  const pct = (value) => {
    const n = Number(value);
    return Number.isFinite(n) ? (n * 100).toFixed(1) + "%" : "-";
  };
  const count = (value) => Number(value || 0).toLocaleString("zh-CN");
  const time = (value) => {
    if (!value) return "-";
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleString("zh-CN", { hour12: false });
  };

  async function fetchJson(url) {
    const response = await fetch(`${url}?v=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    return response.json();
  }

  async function loadRows() {
    for (const url of [LOCAL, RAW]) {
      try {
        const rows = await fetchJson(url);
        if (Array.isArray(rows)) return rows;
      } catch (_) {}
    }
    return [];
  }

  function latestAccepted(rows, field) {
    const reversed = [...rows].reverse();
    return reversed.find(row => row?.[field]?.accepted) || null;
  }

  function makePager(total, current, onPage) {
    const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
    const wrap = document.createElement("div");
    wrap.className = "pager";
    for (let page = 1; page <= pages; page++) {
      const button = document.createElement("button");
      button.textContent = page;
      if (page === current) button.className = "active";
      button.addEventListener("click", () => onPage(page));
      wrap.appendChild(button);
    }
    return wrap;
  }

  function insertAfter(reference, node) {
    if (reference?.parentNode) reference.parentNode.insertBefore(node, reference.nextSibling);
  }

  function renderAI(rows) {
    const learning = document.getElementById("learning");
    if (!learning || !rows.length) return;

    let card = document.getElementById("aiMillionSimulationHistory");
    if (!card) {
      card = document.createElement("div");
      card.id = "aiMillionSimulationHistory";
      card.className = "card";
      insertAfter(document.getElementById("aiBacktestSummary") || document.getElementById("aiLearningLogs"), card);
    }

    let page = 1;
    const renderPage = () => {
      const latest = rows.at(-1);
      const ai = latest.ai || {};
      const accepted = latestAccepted(rows, "ai");
      const total = rows.reduce((sum, row) => sum + Number(row?.ai?.cycles || 0), 0);
      const recent = [...rows].reverse().slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

      card.innerHTML = `
        <div class="section-head">
          <div>
            <h2>AI 每日100万次完整历史循环</h2>
            <div class="muted">历史回测负责验证真实性；这一层每天额外进行1,000,000次完整历史预测循环，并只接受留出验证集更好的挑战者。</div>
          </div>
          <span class="badge blue">每日 1,000,000 次</span>
        </div>
        <div class="weight-grid">
          <div class="weight"><span class="muted">今日完整循环</span><strong>${count(ai.cycles)}</strong></div>
          <div class="weight"><span class="muted">累计完整循环</span><strong>${count(total)}</strong></div>
          <div class="weight"><span class="muted">当前验证分</span><strong>${fmt(ai.validationScoreAfter)}</strong></div>\n          <div class="weight"><span class="muted">每循环档案遍历</span><strong>${count(ai.archiveDrawsTraversed || ai.drawsPerCycle)}</strong></div>\n          <div class="weight"><span class="muted">每循环可评分期数</span><strong>${count(ai.drawsPerCycle)}</strong></div>\n          <div class="weight"><span class="muted">有效逐期比较</span><strong>${count(ai.effectiveDrawComparisons)}</strong></div>
          <div class="weight"><span class="muted">本轮策略</span><strong>${ai.accepted ? "已升级" : "保持原策略"}</strong></div>
        </div>
        <div class="log-list">
          <div class="log">
            <div class="log-time">验证门</div>
            <div>
              <div class="log-title">${fmt(ai.validationScoreBefore)} → ${fmt(ai.validationScoreAfter)}</div>
              <div class="log-body">只有时间顺序留出验证分提高，才把新参数写回AI。否则本轮100万次搜索只留下日志，不污染线上模型。</div>
            </div>
          </div>
          <div class="log">
            <div class="log-time">参数</div>
            <div>
              <div class="log-title">均值锚 ${fmt(ai.anchorBefore, 3)} → ${fmt(ai.anchorAfter, 3)}</div>
              <div class="log-body">完整历史损失 ${fmt(ai.fullHistoryLossBefore, 6)} → ${fmt(ai.fullHistoryLossAfter, 6)}。最近一次真正通过验证的训练：${accepted ? time(accepted.generatedAt) : "尚无"}。</div>
            </div>
          </div>
        </div>
        <h3 style="margin-top:20px">AI 完整历史循环逐次运行记录</h3>
        <div style="overflow:auto">
          <table>
            <thead><tr><th>运行时间</th><th>完整循环次数</th><th>验证分前</th><th>验证分后</th><th>验证损失</th><th>均值锚</th><th>结果</th></tr></thead>
            <tbody>
              ${recent.map(row => {
                const x = row.ai || {};
                return `<tr>
                  <td>${time(row.generatedAt)}</td>
                  <td>${count(x.cycles)}</td>
                  <td>${fmt(x.validationScoreBefore)}</td>
                  <td>${fmt(x.validationScoreAfter)}</td>
                  <td>${fmt(x.validationLossAfter, 6)}</td>
                  <td>${fmt(x.anchorAfter, 3)}</td>
                  <td>${x.accepted ? "接受新策略" : "保持原策略"}</td>
                </tr>`;
              }).join("")}
            </tbody>
          </table>
        </div>
      `;
      card.appendChild(makePager(rows.length, page, newPage => {
        page = newPage;
        renderPage();
      }));
    };
    renderPage();
  }

  function renderAgent(rows) {
    const learning = document.getElementById("learning");
    if (!learning || !rows.length) return;

    let card = document.getElementById("agentMillionSimulationHistory");
    if (!card) {
      card = document.createElement("div");
      card.id = "agentMillionSimulationHistory";
      card.className = "card";
      insertAfter(document.getElementById("agentSimulationHistoryCard") || document.getElementById("hybridBacktestSummary"), card);
    }

    let page = 1;
    const renderPage = () => {
      const latest = rows.at(-1);
      const agent = latest.agent || {};
      const total = rows.reduce((sum, row) => sum + Number(row?.agent?.cycles || 0), 0);
      const source = agent.sourceWeightsAfter || {};
      const recent = [...rows].reverse().slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

      card.innerHTML = `
        <div class="section-head">
          <div>
            <h2>Agent Instinct 每日100万次完整历史循环</h2>
            <div class="muted">每个cycle都从第一期可预测历史一路比较到最新一期，再搜索AI、风水、Agent直觉三源权重与组合策略。</div>
          </div>
          <span class="badge gold">每日 1,000,000 次</span>
        </div>
        <div class="weight-grid">
          <div class="weight"><span class="muted">今日完整循环</span><strong>${count(agent.cycles)}</strong></div>
          <div class="weight"><span class="muted">累计完整循环</span><strong>${count(total)}</strong></div>
          <div class="weight"><span class="muted">当前验证分</span><strong>${fmt(agent.validationScoreAfter)}</strong></div>\n          <div class="weight"><span class="muted">每循环档案遍历</span><strong>${count(agent.archiveDrawsTraversed || agent.drawsPerCycle)}</strong></div>\n          <div class="weight"><span class="muted">每循环可评分期数</span><strong>${count(agent.drawsPerCycle)}</strong></div>\n          <div class="weight"><span class="muted">有效逐期比较</span><strong>${count(agent.effectiveDrawComparisons)}</strong></div>
          <div class="weight"><span class="muted">本轮策略</span><strong>${agent.accepted ? "已升级" : "保持原策略"}</strong></div>
        </div>
        <div class="log-list">
          <div class="log">
            <div class="log-time">验证门</div>
            <div>
              <div class="log-title">${fmt(agent.validationScoreBefore)} → ${fmt(agent.validationScoreAfter)}</div>
              <div class="log-body">100万次完整历史循环产生的新三源权重只有在留出数据上真正更好才会写回。没有进步就保留当前冠军策略。</div>
            </div>
          </div>
          <div class="log">
            <div class="log-time">当前权重</div>
            <div>
              <div class="log-title">前区 AI / 风水 / 直觉：${pct(source.front?.ai)} / ${pct(source.front?.chee)} / ${pct(source.front?.instinct)}</div>
              <div class="log-body">后区 AI / 风水 / 直觉：${pct(source.back?.ai)} / ${pct(source.back?.chee)} / ${pct(source.back?.instinct)}。</div>
            </div>
          </div>
        </div>
        <h3 style="margin-top:20px">Agent 完整历史循环逐次运行记录</h3>
        <div style="overflow:auto">
          <table>
            <thead><tr><th>运行时间</th><th>完整循环次数</th><th>验证分前</th><th>验证分后</th><th>前区权重 AI / 风水 / 直觉</th><th>后区权重 AI / 风水 / 直觉</th><th>结果</th></tr></thead>
            <tbody>
              ${recent.map(row => {
                const x = row.agent || {};
                const w = x.sourceWeightsAfter || {};
                return `<tr>
                  <td>${time(row.generatedAt)}</td>
                  <td>${count(x.cycles)}</td>
                  <td>${fmt(x.validationScoreBefore)}</td>
                  <td>${fmt(x.validationScoreAfter)}</td>
                  <td>${pct(w.front?.ai)} / ${pct(w.front?.chee)} / ${pct(w.front?.instinct)}</td>
                  <td>${pct(w.back?.ai)} / ${pct(w.back?.chee)} / ${pct(w.back?.instinct)}</td>
                  <td>${x.accepted ? "接受新策略" : "保持原策略"}</td>
                </tr>`;
              }).join("")}
            </tbody>
          </table>
        </div>
      `;
      card.appendChild(makePager(rows.length, page, newPage => {
        page = newPage;
        renderPage();
      }));
    };
    renderPage();
  }

  async function load() {
    const rows = (await loadRows()).filter(row =>
      Number(row?.ai?.cycles || 0) >= 1000000 &&
      Number(row?.agent?.cycles || 0) >= 1000000
    );
    renderAI(rows);
    renderAgent(rows);
  }

  document.querySelectorAll('.tab[data-page="learning"]').forEach(button => {
    button.addEventListener("click", load);
  });
  load();
})();