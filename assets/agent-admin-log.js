/* Admin database view for Agent Instinct simulation and live learning logs. */
(() => {
  const LOCAL_SIMULATION_URL = "./data/hybrid-simulation-log.json";
  const LOCAL_LEARNING_URL = "./data/hybrid-learning-log.json";
  const RAW_ROOT = "https://raw.githubusercontent.com/kanewang0929-ops/feel-the-chee/main/data";

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function formatNumber(value, digits = 3) {
    const number = Number(value);
    return Number.isFinite(number) ? number.toFixed(digits) : "-";
  }

  function formatPercent(value) {
    const number = Number(value);
    return Number.isFinite(number) ? `${(number * 100).toFixed(1)}%` : "-";
  }

  function formatDate(value) {
    if (!value) return "-";
    const date = new Date(value);
    return Number.isNaN(date.getTime())
      ? escapeHtml(value)
      : date.toLocaleString("zh-CN", { hour12: false });
  }

  async function fetchJson(url) {
    const response = await fetch(`${url}${url.includes("?") ? "&" : "?"}v=${Date.now()}`, {
      cache: "no-store",
    });
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    return response.json();
  }

  async function fetchFirst(urls) {
    const errors = [];
    for (const url of urls) {
      try {
        return await fetchJson(url);
      } catch (error) {
        errors.push(`${url}: ${error.message}`);
      }
    }
    throw new Error(errors.join(" | "));
  }

  function ensureCard() {
    const admin = document.getElementById("admin");
    if (!admin) return null;
    let card = document.getElementById("agentInstinctAdminLog");
    if (!card) {
      card = document.createElement("div");
      card.id = "agentInstinctAdminLog";
      card.className = "card";
      admin.appendChild(card);
    }
    return card;
  }

  function isInstinctSimulation(row) {
    return row?.eventType === "agent-instinct-simulation-learning" ||
      String(row?.modelVersion || "").includes("intuitive");
  }

  function simulationTimestamp(row) {
    return Date.parse(row?.generatedAt || "") || 0;
  }

  function extractSourceWeights(row) {
    const after = row?.weightsAfter || {};
    const source = after.source || after;
    return {
      front: source.front || {},
      back: source.back || {},
    };
  }

  function resultLine(result) {
    const front = Array.isArray(result?.front) ? result.front.join(" ") : "-";
    const back = Array.isArray(result?.back) ? result.back.join(" ") : "-";
    const frontHits = Array.isArray(result?.frontHits) && result.frontHits.length
      ? result.frontHits.join("、")
      : "无";
    const backHits = Array.isArray(result?.backHits) && result.backHits.length
      ? result.backHits.join("、")
      : "无";
    return `结果${escapeHtml(result?.rank || "-")}：${escapeHtml(front)} + ${escapeHtml(back)}；前区命中 ${escapeHtml(frontHits)}，后区命中 ${escapeHtml(backHits)}`;
  }

  function render(simulationRows, learningRows) {
    const card = ensureCard();
    if (!card) return;

    const simulations = (Array.isArray(simulationRows) ? simulationRows : [])
      .filter(isInstinctSimulation)
      .sort((a, b) => simulationTimestamp(b) - simulationTimestamp(a));
    const evaluations = (Array.isArray(learningRows) ? learningRows : [])
      .filter(row => row && (row.modelVersion || row.issue))
      .sort((a, b) => (Date.parse(b.evaluatedAt || "") || 0) - (Date.parse(a.evaluatedAt || "") || 0));

    const latestSimulation = simulations[0] || null;
    const latestEvaluation = evaluations[0] || null;
    const weights = extractSourceWeights(latestSimulation);
    const latestResults = Array.isArray(latestEvaluation?.results) ? latestEvaluation.results : [];
    const actualFront = latestEvaluation?.actual?.front?.join(" ") || "-";
    const actualBack = latestEvaluation?.actual?.back?.join(" ") || "-";

    const recentRows = simulations.slice(0, 6).map(row => `
      <tr>
        <td>${formatDate(row.generatedAt)}</td>
        <td>${escapeHtml(row.modelVersion || "-")}</td>
        <td>${Number(row.drawsEvaluated || 0).toLocaleString("zh-CN")}</td>
        <td>${Number(row.ticketsEvaluated || 0).toLocaleString("zh-CN")}</td>
        <td>${formatNumber(row.averageFrontHits)}</td>
        <td>${formatNumber(row.averageBackHits)}</td>
      </tr>`).join("");

    card.innerHTML = `
      <div class="section-head">
        <div>
          <h2>Agent Instinct 日志数据库</h2>
          <div class="muted">直接读取后端的每日模拟日志与开奖后学习日志。每次运行均保留，不覆盖旧记录。</div>
        </div>
        <span class="badge gold">${simulations.length} 次模拟 · ${evaluations.length} 次开奖复盘</span>
      </div>

      <div class="weight-grid">
        <div class="weight"><span class="muted">最近模拟</span><strong>${formatDate(latestSimulation?.generatedAt)}</strong></div>
        <div class="weight"><span class="muted">模拟期数</span><strong>${Number(latestSimulation?.drawsEvaluated || 0).toLocaleString("zh-CN")}</strong></div>
        <div class="weight"><span class="muted">Agent票数</span><strong>${Number(latestSimulation?.ticketsEvaluated || 0).toLocaleString("zh-CN")}</strong></div>
        <div class="weight"><span class="muted">最近复盘期次</span><strong>${escapeHtml(latestEvaluation?.issue || "-")}</strong></div>
      </div>

      <div class="log-list">
        <div class="log">
          <div class="log-time">每日模拟</div>
          <div>
            <div class="log-title">平均命中与三源权重</div>
            <div class="log-body">前区平均命中 ${formatNumber(latestSimulation?.averageFrontHits)}，后区平均命中 ${formatNumber(latestSimulation?.averageBackHits)}。<br>前区 AI / 风水 / 直觉：${formatPercent(weights.front.ai)} / ${formatPercent(weights.front.chee)} / ${formatPercent(weights.front.instinct)}。<br>后区 AI / 风水 / 直觉：${formatPercent(weights.back.ai)} / ${formatPercent(weights.back.chee)} / ${formatPercent(weights.back.instinct)}。</div>
          </div>
        </div>
        <div class="log">
          <div class="log-time">第${escapeHtml(latestEvaluation?.issue || "-")}期</div>
          <div>
            <div class="log-title">Agent预测与实际开奖复盘</div>
            <div class="log-body">实际：${escapeHtml(actualFront)} + ${escapeHtml(actualBack)}。<br>${latestResults.map(resultLine).join("<br>") || "尚无开奖复盘记录。"}<br>两组平均前区命中 ${formatNumber(latestEvaluation?.summary?.averageFrontHits)}，后区命中 ${formatNumber(latestEvaluation?.summary?.averageBackHits)}。</div>
          </div>
        </div>
      </div>

      <h3 style="margin-top:20px">最近 Agent Instinct 模拟运行</h3>
      <div style="overflow:auto">
        <table>
          <thead>
            <tr><th>运行时间</th><th>模型版本</th><th>回测期数</th><th>票数</th><th>前区均值</th><th>后区均值</th></tr>
          </thead>
          <tbody>${recentRows || '<tr><td colspan="6">暂无日志</td></tr>'}</tbody>
        </table>
      </div>`;
  }

  function renderError(error) {
    const card = ensureCard();
    if (!card) return;
    card.innerHTML = `
      <div class="section-head">
        <div><h2>Agent Instinct 日志数据库</h2><div class="muted">日志加载失败。</div></div>
        <span class="status fail">读取失败</span>
      </div>
      <div class="notice">${escapeHtml(error.message)}</div>`;
  }

  async function load() {
    const card = ensureCard();
    if (card) card.innerHTML = '<h2>Agent Instinct 日志数据库</h2><div class="muted">正在读取每日模拟与开奖复盘记录...</div>';
    try {
      const [simulations, evaluations] = await Promise.all([
        fetchFirst([LOCAL_SIMULATION_URL, `${RAW_ROOT}/hybrid-simulation-log.json`]),
        fetchFirst([LOCAL_LEARNING_URL, `${RAW_ROOT}/hybrid-learning-log.json`]),
      ]);
      render(simulations, evaluations);
    } catch (error) {
      console.error("Agent admin log unavailable", error);
      renderError(error);
    }
  }

  document.querySelectorAll('.tab[data-page="admin"]').forEach(button => {
    button.addEventListener("click", load);
  });

  load();
})();
