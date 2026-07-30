/* Standalone Feel the Chee runtime. It deliberately does not depend on app.js. */
(() => {
  "use strict";

  const CARD_ID = "cheePredictionCard";
  const DATA_SOURCES = [
    "./data/chee-forecast.json",
    "/data/chee-forecast.json",
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
        <span class="score">Chee 值 ${Number(result?.cheeValue || 0).toFixed(1)}</span>
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
      Array.isArray(payload.results) &&
      payload.results.length >= 2 &&
      payload.elementStrengths &&
      typeof payload.elementStrengths === "object"
    );
  }

  async function fetchPayload() {
    const errors = [];
    for (const source of DATA_SOURCES) {
      try {
        const separator = source.includes("?") ? "&" : "?";
        const response = await fetch(`${source}${separator}v=${Date.now()}`, { cache: "no-store" });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json();
        if (!validatePayload(payload)) throw new Error("invalid Chee payload");
        return { payload, source };
      } catch (error) {
        errors.push(`${source}: ${error.message || error}`);
      }
    }
    throw new Error(errors.join(" | "));
  }

  function render(payload, source) {
    const card = document.getElementById(CARD_ID);
    if (!card) throw new Error(`#${CARD_ID} not found`);

    const results = payload.results.slice(0, 2);
    const strengths = payload.elementStrengths || {};
    const order = ["金", "火", "土", "木", "水"];

    const description = card.querySelector(".section-head .muted");
    if (description) {
      description.textContent = `第${payload.targetIssue || "-"}期 · 只按河图洛书、目标期号和开奖日期计算2组结果，不使用历史开奖学习。`;
    }

    const badge = card.querySelector(".section-head .badge");
    if (badge) badge.textContent = "2组结果 · 公式计算";

    const bars = card.querySelector(".chee-bars");
    if (bars) {
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
    if (list) list.innerHTML = results.map(resultCard).join("");

    card.dataset.cheeLoaded = "true";
    card.dataset.cheeSource = source;
    window.dispatchEvent(new CustomEvent("chee:rendered", { detail: { issue: payload.targetIssue, source } }));
  }

  function renderFailure(error) {
    const card = document.getElementById(CARD_ID);
    if (!card) return;
    const list = card.querySelector(".forecast-list");
    if (list) {
      list.innerHTML = `<div class="forecast">
        <div class="forecast-top"><strong>风水公式加载失败</strong><span class="score">需要刷新</span></div>
        <div class="reason">${escapeHtml(error.message || error)}</div>
      </div>`;
    }
    card.dataset.cheeLoaded = "false";
  }

  async function boot() {
    try {
      const { payload, source } = await fetchPayload();
      render(payload, source);
    } catch (error) {
      console.error("Standalone Chee runtime failed", error);
      renderFailure(error);
      setTimeout(boot, 5000);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
