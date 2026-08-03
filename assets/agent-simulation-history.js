/* Full Agent Instinct simulation history for the model-learning page. */
(() => {
  const LOCAL_URL = "./data/hybrid-simulation-log.json";
  const RAW_URL = "https://raw.githubusercontent.com/kanewang0929-ops/feel-the-chee/main/data/hybrid-simulation-log.json";
  const PAGE_SIZE = 10;

  let historyRows = [];
  let currentPage = 1;
  let loaded = false;

  function numberText(value, digits = 3) {
    const number = Number(value);
    return Number.isFinite(number) ? number.toFixed(digits) : "-";
  }

  function percentText(value) {
    const number = Number(value);
    return Number.isFinite(number) ? `${(number * 100).toFixed(1)}%` : "-";
  }

  function timeText(value) {
    if (!value) return "-";
    const date = new Date(value);
    return Number.isNaN(date.getTime())
      ? String(value)
      : date.toLocaleString("zh-CN", { hour12: false });
  }

  async function fetchJson(url) {
    const response = await fetch(`${url}${url.includes("?") ? "&" : "?"}v=${Date.now()}`, {
      cache: "no-store",
    });
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    return response.json();
  }

  async function fetchHistory() {
    const errors = [];
    for (const url of [LOCAL_URL, RAW_URL]) {
      try {
        return await fetchJson(url);
      } catch (error) {
        errors.push(`${url}: ${error.message}`);
      }
    }
    throw new Error(errors.join(" | "));
  }

  function sourceWeights(row) {
    const after = row?.weightsAfter || {};
    const source = after.source || after;
    return {
      front: source.front || {},
      back: source.back || {},
    };
  }

  function normalizeRows(payload) {
    if (!Array.isArray(payload)) return [];

    const instinctEvents = payload.filter(row =>
      row?.eventType === "agent-instinct-simulation-learning"
    );

    const source = instinctEvents.length
      ? instinctEvents
      : payload.filter(row => String(row?.modelVersion || "").includes("intuitive"));

    const seen = new Set();
    return source
      .filter(row => row?.generatedAt)
      .sort((a, b) => Date.parse(a.generatedAt) - Date.parse(b.generatedAt))
      .filter(row => {
        const key = `${row.generatedAt}|${row.simulationRuns || ""}|${row.drawsEvaluated || ""}`;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      });
  }

  function ensureCard() {
    const learning = document.getElementById("learning");
    if (!learning) return null;

    let card = document.getElementById("agentSimulationHistoryCard");
    if (!card) {
      card = document.createElement("div");
      card.id = "agentSimulationHistoryCard";
      card.className = "card";

      const backtest = document.getElementById("hybridBacktestSummary");
      const daily = document.getElementById("agentDailySimulationLog");
      const anchor = backtest || daily;
      if (anchor?.nextSibling) learning.insertBefore(card, anchor.nextSibling);
      else learning.appendChild(card);
    }
    return card;
  }

  function weightDelta(first, latest, area, source) {
    const start = sourceWeights(first)[area]?.[source];
    const end = sourceWeights(latest)[area]?.[source];
    if (!Number.isFinite(Number(start)) || !Number.isFinite(Number(end))) return "-";
    const delta = (Number(end) - Number(start)) * 100;
    const sign = delta > 0 ? "+" : "";
    return `${percentText(start)} → ${percentText(end)} (${sign}${delta.toFixed(1)}pp)`;
  }

  function renderTable() {
    const body = document.getElementById("agentSimulationHistoryBody");
    const pager = document.getElementById("agentSimulationHistoryPager");
    if (!body || !pager) return;

    const newestFirst = [...historyRows].reverse();
    const pageCount = Math.max(1, Math.ceil(newestFirst.length / PAGE_SIZE));
    currentPage = Math.min(Math.max(1, currentPage), pageCount);
    const pageRows = newestFirst.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

    body.innerHTML = pageRows.map((row, index) => {
      const weights = sourceWeights(row);
      const runNumber = row.simulationRuns || (newestFirst.length - ((currentPage - 1) * PAGE_SIZE + index));
      return `<tr>
        <td>${runNumber}</td>
        <td>${timeText(row.generatedAt)}</td>
        <td>${Number(row.drawsEvaluated || 0).toLocaleString("zh-CN")}</td>
        <td>${Number(row.ticketsEvaluated || 0).toLocaleString("zh-CN")}</td>
        <td>${numberText(row.averageFrontHits)}</td>
        <td>${numberText(row.averageBackHits)}</td>
        <td>${percentText(weights.front.ai)} / ${percentText(weights.front.chee)} / ${percentText(weights.front.instinct)}</td>
        <td>${percentText(weights.back.ai)} / ${percentText(weights.back.chee)} / ${percentText(weights.back.instinct)}</td>
      </tr>`;
    }).join("") || '<tr><td colspan="8">暂无Agent Instinct模拟历史</td></tr>';

    const buttons = [];
    if (currentPage > 1) buttons.push(`<button data-page="${currentPage - 1}">‹</button>`);
    for (let page = 1; page <= pageCount; page += 1) {
      if (page === 1 || page === pageCount || Math.abs(page - currentPage) <= 2) {
        buttons.push(`<button data-page="${page}" class="${page === currentPage ? "active" : ""}">${page}</button>`);
      } else if (buttons.at(-1) !== '<span class="muted">…</span>') {
        buttons.push('<span class="muted">…</span>');
      }
    }
    if (currentPage < pageCount) buttons.push(`<button data-page="${currentPage + 1}">›</button>`);
    pager.innerHTML = buttons.join("");
    pager.querySelectorAll("button[data-page]").forEach(button => {
      button.addEventListener("click", () => {
        currentPage = Number(button.dataset.page) || 1;
        renderTable();
      });
    });
  }

  function renderHistory() {
    const card = ensureCard();
    if (!card) return;

    if (!historyRows.length) {
      card.innerHTML = `<h2>Agent Instinct 模拟历史</h2><div class="muted">尚未找到可显示的逐次模拟记录。</div>`;
      return;
    }

    const first = historyRows[0];
    const latest = historyRows.at(-1);
    const firstTime = timeText(first.generatedAt);
    const latestTime = timeText(latest.generatedAt);

    card.innerHTML = `<div class="section-head">
      <div>
        <h2>Agent Instinct 模拟历史</h2>
        <div class="muted">显示后端保存的每次完整Agent Instinct模拟，而不只显示最新汇总。每页10条，最新运行排在最前。</div>
      </div>
      <span class="badge gold">${historyRows.length} 次已保存运行</span>
    </div>

    <div class="weight-grid">
      <div class="weight"><span class="muted">首次保存</span><strong>${firstTime}</strong></div>
      <div class="weight"><span class="muted">最近保存</span><strong>${latestTime}</strong></div>
      <div class="weight"><span class="muted">最新回测期数</span><strong>${Number(latest.drawsEvaluated || 0).toLocaleString("zh-CN")}</strong></div>
      <div class="weight"><span class="muted">最新Agent票数</span><strong>${Number(latest.ticketsEvaluated || 0).toLocaleString("zh-CN")}</strong></div>
    </div>

    <div class="log-list">
      <div class="log">
        <div class="log-time">前区直觉权重</div>
        <div><div class="log-title">${weightDelta(first, latest, "front", "instinct")}</div><div class="log-body">每次模拟结束后写回三源权重，并保留旧快照。</div></div>
      </div>
      <div class="log">
        <div class="log-time">后区直觉权重</div>
        <div><div class="log-title">${weightDelta(first, latest, "back", "instinct")}</div><div class="log-body">表格同时展示AI、风水与Agent直觉的完整权重轨迹。</div></div>
      </div>
    </div>

    <h3 style="margin-top:20px">逐次模拟运行记录</h3>
    <div style="overflow:auto">
      <table>
        <thead>
          <tr>
            <th>运行</th><th>运行时间</th><th>回测期数</th><th>Agent票数</th>
            <th>前区均值</th><th>后区均值</th><th>前区 AI / 风水 / 直觉</th><th>后区 AI / 风水 / 直觉</th>
          </tr>
        </thead>
        <tbody id="agentSimulationHistoryBody"></tbody>
      </table>
    </div>
    <div id="agentSimulationHistoryPager" class="pager"></div>`;

    renderTable();
  }

  function renderError(error) {
    const card = ensureCard();
    if (!card) return;
    card.innerHTML = `<div class="section-head"><div><h2>Agent Instinct 模拟历史</h2><div class="muted">历史记录读取失败。</div></div><span class="status fail">读取失败</span></div><div class="notice">${String(error.message || error)}</div>`;
  }

  async function loadHistory(force = false) {
    if (loaded && !force) return;
    const card = ensureCard();
    if (card) card.innerHTML = `<h2>Agent Instinct 模拟历史</h2><div class="muted">正在读取全部逐次模拟记录...</div>`;
    try {
      historyRows = normalizeRows(await fetchHistory());
      currentPage = 1;
      loaded = true;
      renderHistory();
    } catch (error) {
      console.error("Agent simulation history unavailable", error);
      renderError(error);
    }
  }

  document.querySelectorAll('.tab[data-page="learning"]').forEach(button => {
    button.addEventListener("click", () => loadHistory(true));
  });

  loadHistory();
})();