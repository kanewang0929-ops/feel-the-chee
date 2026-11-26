/* Render Chee once, with its own draw identity and a check against the live forecast. */
(() => {
  "use strict";

  const CARD_ID = "cheePredictionCard";
  const DATA_SOURCES = [
    "./data/chee-forecast.json",
    "https://raw.githubusercontent.com/kanewang0929-ops/feel-the-chee/main/data/chee-forecast.json"
  ];

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>'"]/g, character => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      "'": "&#39;",
      '"': "&quot;"
    })[character]);
  }

  function ball(number, isBack = false) {
    return `<span class="ball${isBack ? " back" : ""}">${escapeHtml(number)}</span>`;
  }

  function resultCard(result) {
    const front = Array.isArray(result?.front) ? result.front.slice(0, 5) : [];
    const back = Array.isArray(result?.back) ? result.back.slice(0, 2) : [];
    return `<div class="forecast">
      <div class="forecast-top">
        <strong>Chee 结果 ${escapeHtml(result?.rank)} · ${escapeHtml(result?.label || "五行路径")}</strong>
        <span class="score">公式值 ${result?.cheeValue == null ? "未记录" : Number(result.cheeValue).toFixed(1)}</span>
      </div>
      <div class="numbers">
        ${front.map(number => ball(number)).join("")}
        <span class="plus">+</span>
        ${back.map(number => ball(number, true)).join("")}
      </div>
      <div class="reason">${escapeHtml(result?.reason || "")}</div>
    </div>`;
  }

  function validatePayload(payload) {
    return Boolean(
      payload &&
      /^\d+$/.test(String(payload.targetIssue || "")) &&
      /^\d{4}-\d{2}-\d{2}$/.test(String(payload.targetDate || "")) &&
      Array.isArray(payload.results) &&
      payload.results.length >= 2 &&
      payload.results.slice(0, 2).every(result => [[result.front, 5, 35], [result.back, 2, 12]].every(([values, count, maximum]) =>
        Array.isArray(values) && values.length === count && new Set(values.map(Number)).size === count &&
        values.every(value => Number.isInteger(Number(value)) && Number(value) >= 1 && Number(value) <= maximum))) &&
      payload.elementStrengths &&
      typeof payload.elementStrengths === "object"
    );
  }

  async function fetchPayload() {
    const errors = [];
    for (const source of DATA_SOURCES) {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 12000);
      try {
        const separator = source.includes("?") ? "&" : "?";
        const response = await fetch(`${source}${separator}v=${Date.now()}`, { cache: "no-store", signal: controller.signal });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json();
        if (!validatePayload(payload)) throw new Error("invalid Chee payload");
        return { payload, source };
      } catch (error) {
        errors.push(`${source}: ${error.message || error}`);
      } finally {
        clearTimeout(timeout);
      }
    }
    throw new Error(errors.join(" | "));
  }

  function render(payload, source, target) {
    const card = document.getElementById(CARD_ID);
    if (!card) throw new Error(`#${CARD_ID} not found`);

    const results = payload.results.slice(0, 2);
    const strengths = payload.elementStrengths || {};
    const order = ["金", "火", "土", "木", "水"];
    const verified = Boolean(target?.targetIssue && target?.targetDate);
    const matchesTarget = verified && String(payload.targetIssue) === String(target.targetIssue) && payload.targetDate === target.targetDate;
    const past = typeof isPastTarget === "function" && isPastTarget(payload.targetDate);
    const stale = (verified && !matchesTarget) || past;

    const description = card.querySelector(".section-head .muted");
    if (description) {
      description.textContent = "只按河图洛书、目标期号和开奖日期计算，不使用历史开奖学习。";
    }

    const badge = card.querySelector(".section-head .badge");
    if (badge) badge.textContent = stale ? "历史结果 · 待更新" : matchesTarget ? "2组结果 · 本期期次一致" : "2组结果 · 期次未核验";
    const status = document.getElementById("cheeStatus");
    if (status) {
      status.classList.toggle("is-stale", stale || !verified);
      status.textContent = verified && !matchesTarget
        ? `公式仍为第 ${payload.targetIssue} 期（${payload.targetDate}）；当前预测目标是第 ${target.targetIssue} 期（${target.targetDate}）。本期公式结果尚未发布。`
        : past ? `最近发布的是第 ${payload.targetIssue} 期（${payload.targetDate}）的历史公式结果，目标开奖日期已过。`
        : `第 ${payload.targetIssue} 期 · 目标开奖 ${payload.targetDate}${verified ? " · 与 Joy / Kane 期次一致" : " · 无法读取 Joy / Kane 期次，尚未核验是否为本期"}`;
    }

    const bars = card.querySelector(".chee-bars");
    if (bars) {
      bars.hidden = stale;
      bars.innerHTML = order.map(name => {
        const value = Math.max(0, Math.min(100, Number(strengths[name] || 0)));
        return `<div class="chee-row">
          <span>${name}</span>
          <div class="bar"><div class="fill" style="width:${value}%"></div></div>
          <span>${Math.round(value)}</span>
        </div>`;
      }).join("");
    }

    const list = card.querySelector(".forecast-list");
    if (list) list.innerHTML = stale
      ? `<details class="archived-formula"><summary>查看第 ${escapeHtml(payload.targetIssue)} 期的历史公式结果</summary><div class="archived-results">${results.map(resultCard).join("")}</div></details>`
      : results.map(resultCard).join("");

    card.dataset.cheeLoaded = "true";
    card.dataset.cheeSource = source;
    card.dataset.cheeCurrent = String(matchesTarget && !past);
    window.dispatchEvent(new CustomEvent("chee:rendered", { detail: { issue: payload.targetIssue, source } }));
  }

  function renderFailure(error) {
    const card = document.getElementById(CARD_ID);
    if (!card) return;
    const list = card.querySelector(".forecast-list");
    if (list) {
      list.innerHTML = `<div class="forecast">
        <div class="forecast-top"><strong>公式结果暂不可用</strong></div>
        <div class="reason">数据源尚未返回有效结果，请稍后刷新页面。</div>
      </div>`;
    }
    card.dataset.cheeLoaded = "false";
    card.querySelector(".chee-bars").hidden = true;
    card.querySelector(".section-head .badge").textContent = "数据暂不可用";
    const status = document.getElementById("cheeStatus");
    if (status) status.textContent = "尚未读取到可核验的公式结果。";
  }

  async function boot() {
    try {
      const [formula, live] = await Promise.allSettled([
        fetchPayload(),
        typeof loadDuelPayload === "function" ? loadDuelPayload() : Promise.reject(new Error("live forecast unavailable"))
      ]);
      if (formula.status === "rejected") throw formula.reason;
      const { payload, source } = formula.value;
      render(payload, source, live.status === "fulfilled" ? live.value.nextForecast : null);
    } catch (error) {
      console.error("Standalone Chee runtime failed", error);
      renderFailure(error);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
