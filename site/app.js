(function () {
  const FRENCH_MODEL = "__french__";
  const reader = document.getElementById("reader");
  const legend = document.getElementById("modelLegend");
  const toggleFrench = document.getElementById("toggleFrench");
  const sheet = document.getElementById("sheet");
  const sheetBackdrop = document.getElementById("sheetBackdrop");
  const sheetList = document.getElementById("sheetList");
  const sheetTitle = document.getElementById("sheetTitle");

  let data = null;
  /** @type {string|null} */
  let globalModel = null;
  /** @type {Record<string, string>} */
  const perParagraph = {};
  let openPopover = null;
  let sheetParaId = null;
  /** @type {string|null} */
  let failureViewerModel = null;

  const isMobile = () => window.matchMedia("(max-width: 639px)").matches;
  const allModels = () => [FRENCH_MODEL, ...(data?.models || [])];

  function orderedModels() {
    const stats = data?.model_stats || {};
    return (data?.models || []).slice().sort((a, b) => {
      const sa = stats[a] || {};
      const sb = stats[b] || {};
      const rfa = Number(sa.failure_rate ?? 1);
      const rfb = Number(sb.failure_rate ?? 1);
      if (rfa !== rfb) return rfa - rfb;
      const cfa = Number(sa.failures ?? 999999);
      const cfb = Number(sb.failures ?? 999999);
      if (cfa !== cfb) return cfa - cfb;
      const tea = Number.isFinite(sa.total_e_count) ? Number(sa.total_e_count) : 999999999;
      const teb = Number.isFinite(sb.total_e_count) ? Number(sb.total_e_count) : 999999999;
      if (tea !== teb) return tea - teb;
      const pra = Number(sa.pass_rate || 0);
      const prb = Number(sb.pass_rate || 0);
      if (prb !== pra) return prb - pra;
      return a.localeCompare(b);
    });
  }

  function uiModels() {
    return [...orderedModels(), FRENCH_MODEL];
  }

  function escapeHtml(s) {
    return s
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function highlightE(text) {
    let out = "";
    for (const ch of text) {
      if (ch === "e" || ch === "E") {
        out += `<span class="e-bad">${escapeHtml(ch)}</span>`;
      } else {
        out += escapeHtml(ch);
      }
    }
    return out;
  }

  function modelForParagraph(pid) {
    return perParagraph[pid] || globalModel || FRENCH_MODEL;
  }

  function isFailureForModel(paragraph, modelName) {
    if (!modelName || modelName === FRENCH_MODEL) return false;
    const tr = paragraph?.translations?.[modelName];
    return tr?.is_failure === true;
  }

  function renderLegend() {
    legend.innerHTML = "";
    const stats = data.model_stats || {};
    const totalParas =
      (data.metadata && Number(data.metadata.total_paragraphs)) ||
      (Array.isArray(data.paragraphs) ? data.paragraphs.length : 0);
    const ordered = uiModels();
    const rankByModel = Object.fromEntries(orderedModels().map((name, idx) => [name, idx + 1]));

    for (const [idx, name] of ordered.entries()) {
      const color = name === FRENCH_MODEL ? "#444" : data.model_colors[name] || "#888";
      const st = stats[name] || {};
      const pr = st.pass_rate != null ? Math.round(st.pass_rate * 1000) / 10 : null;
      const failureCount = Number.isFinite(st.failures) ? st.failures : null;
      const totalE = Number.isFinite(st.total_e_count) ? st.total_e_count : null;
      const processed =
        name === FRENCH_MODEL
          ? totalParas
          : Array.isArray(data.paragraphs)
            ? data.paragraphs.reduce(
                (acc, p) => acc + (p.translations && p.translations[name] ? 1 : 0),
                0
              )
            : 0;
      const qualityTooltip =
        "Failures count outputs that were not detected as English " +
        "(including French). Higher values indicate lower constraint-compliant translation reliability.";
      const escapedTooltip = escapeHtml(qualityTooltip);
      const failureRate = failureCount != null && processed > 0 ? failureCount / processed : null;
      const riskLabel =
        name === FRENCH_MODEL
          ? "Georges Perec"
          : failureRate == null
            ? "unknown"
            : failureCount === 0
              ? "clean"
              : failureRate >= 0.15
                ? "high failure rate"
                : "some failures";
      const btn = document.createElement("button");
      btn.type = "button";
      btn.dataset.model = name;
      btn.classList.add("legend-card");
      if (name === globalModel) btn.classList.add("active");
      if (name !== FRENCH_MODEL && failureViewerModel === name) btn.classList.add("failure-mode");
      const displayName = name === FRENCH_MODEL ? "french original" : name;
      btn.innerHTML = `
        <span class="legend-card-top">
          <span class="legend-dot" style="background:${color}"></span>
          <span class="legend-name">${escapeHtml(displayName)}</span>
          <span class="legend-rank">${name === FRENCH_MODEL ? "source" : `#${rankByModel[name]}`}</span>
        </span>
        ${
          name === FRENCH_MODEL
            ? `<span class="legend-chip neutral" aria-hidden="true" style="visibility:hidden;">placeholder</span>`
            : `<span class="legend-chip ${
                riskLabel === "clean" ? "good" : riskLabel === "unknown" ? "neutral" : "warn"
              }">${escapeHtml(riskLabel)}</span>`
        }
        <span class="legend-row"><span class="legend-k">e-free</span><span class="legend-v">${
          name === FRENCH_MODEL ? "100%" : pr != null ? `${pr}%` : "n/a"
        }</span></span>
        <span class="legend-row"><span class="legend-k">Failures</span><span class="legend-v legend-failures-v">${
          name === FRENCH_MODEL ? "n/a" : failureCount != null ? failureCount : "n/a"
        }${
          name !== FRENCH_MODEL && failureCount != null
            ? ` <span class="legend-tip" tabindex="0" role="note" aria-label="${escapedTooltip}" data-tooltip="${escapedTooltip}">ⓘ</span>`
            : ""
        }</span></span>
        <span class="legend-row"><span class="legend-k">total e</span><span class="legend-v">${
          name === FRENCH_MODEL ? "0" : totalE != null ? totalE : "n/a"
        }</span></span>
      `;
      btn.addEventListener("click", () => {
        globalModel = name;
        failureViewerModel = null;
        Object.keys(perParagraph).forEach((k) => delete perParagraph[k]);
        renderLegend();
        renderReader();
      });
      if (name !== FRENCH_MODEL) {
        const failuresValue = btn.querySelector(".legend-failures-v");
        if (failuresValue) {
          failuresValue.addEventListener("click", (ev) => {
            ev.stopPropagation();
            globalModel = name;
            Object.keys(perParagraph).forEach((k) => delete perParagraph[k]);
            failureViewerModel = failureViewerModel === name ? null : name;
            renderLegend();
            renderReader();
          });
        }
      }
      legend.appendChild(btn);
    }
  }

  function closePopover() {
    if (openPopover) {
      openPopover.remove();
      openPopover = null;
    }
  }

  function openSheet(pid) {
    sheetParaId = pid;
    sheetTitle.textContent = `Model for ${pid}`;
    sheetList.innerHTML = "";
    const fr = data.paragraphs.find((p) => p.id === pid);
    if (!fr) return;
    for (const name of orderedModels()) {
      if (name === FRENCH_MODEL) continue;
      const tr = fr.translations[name];
      if (!tr) continue;
      const li = document.createElement("li");
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = `${name} (e: ${tr.e_count})`;
      b.addEventListener("click", () => {
        perParagraph[pid] = name;
        sheet.hidden = true;
        sheetParaId = null;
        renderLegend();
        renderReader();
      });
      li.appendChild(b);
      sheetList.appendChild(li);
    }
    sheet.hidden = false;
  }

  function openPopoverDesktop(pid, anchor) {
    closePopover();
    const fr = data.paragraphs.find((p) => p.id === pid);
    if (!fr) return;
    const ul = document.createElement("ul");
    ul.className = "popover";
    for (const name of orderedModels()) {
      if (name === FRENCH_MODEL) continue;
      const tr = fr.translations[name];
      if (!tr) continue;
      const li = document.createElement("li");
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = `${name} (e: ${tr.e_count})`;
      b.addEventListener("click", (ev) => {
        ev.stopPropagation();
        perParagraph[pid] = name;
        closePopover();
        renderLegend();
        renderReader();
      });
      li.appendChild(b);
      ul.appendChild(li);
    }
    anchor.appendChild(ul);
    openPopover = ul;
  }

  function renderReader() {
    reader.innerHTML = "";
    if (!data.paragraphs.length) {
      reader.innerHTML =
        '<p class="empty-state">No paragraphs in data.json. Run the pipeline and scripts/05_score.py.</p>';
      return;
    }
    const orderedParagraphs = [...data.paragraphs].sort((a, b) => {
      if (a.id === "p0001_pre" && b.id === "p0001_main") return -1;
      if (a.id === "p0001_main" && b.id === "p0001_pre") return 1;
      return a.id.localeCompare(b.id);
    });
    let lastChapter = null;
    for (const p of orderedParagraphs) {
      if (p.id === "p0001_pre") {
        const div = document.createElement("div");
        div.className = "chapter-break";
        div.textContent = "";
        reader.appendChild(div);
      } else if (p.id === "p0001_main") {
        const div = document.createElement("div");
        div.className = "chapter-break";
        div.textContent = "";
        reader.appendChild(div);
      }

      if (lastChapter !== null && p.chapter !== lastChapter) {
        const div = document.createElement("div");
        div.className = "chapter-break";
        div.textContent = "";
        reader.appendChild(div);
      }
      lastChapter = p.chapter;

      const wrap = document.createElement("div");
      wrap.className = "para-wrap";

      const article = document.createElement("article");
      article.className = "para";
      const mname = modelForParagraph(p.id);
      const inFailureMode = failureViewerModel && failureViewerModel !== FRENCH_MODEL;
      const isFailurePara = inFailureMode ? isFailureForModel(p, failureViewerModel) : false;
      article.style.setProperty("--band-count", String(uiModels().length || 1));

      const bands = document.createElement("div");
      bands.className = "para-bands";
      for (const name of uiModels()) {
        const band = document.createElement("button");
        band.type = "button";
        band.className = "para-band-btn";
        if (name === mname) band.classList.add("active");
        if (name !== FRENCH_MODEL && !(p.translations && p.translations[name])) band.classList.add("missing");
        band.style.setProperty(
          "--band-color",
          name === FRENCH_MODEL ? "#444" : data.model_colors[name] || "#999"
        );
        if (name === FRENCH_MODEL) {
          band.title = "french (original)";
          band.setAttribute("aria-label", `Use french original for ${p.id}`);
        } else {
          const trBand = p.translations && p.translations[name];
          const ec = trBand ? trBand.e_count : "n/a";
          band.title = `${name} (e: ${ec})`;
          band.setAttribute("aria-label", `Use ${name} for ${p.id}`);
        }
        band.addEventListener("click", (ev) => {
          ev.stopPropagation();
          perParagraph[p.id] = name;
          renderLegend();
          renderReader();
        });
        bands.appendChild(band);
      }

      const tr = p.translations[mname];
      const body = document.createElement("p");
      body.className = "para-text";
      if (mname && mname !== FRENCH_MODEL && tr && tr.text) {
        body.innerHTML = tr.e_count > 0 ? highlightE(tr.text) : escapeHtml(tr.text);
      } else {
        body.textContent = p.french;
      }

      if (!inFailureMode || isFailurePara) {
        article.appendChild(bands);
      }
      article.appendChild(body);
      if (isFailurePara) {
        article.classList.add("failure-highlight");
      }
      wrap.appendChild(article);
      reader.appendChild(wrap);
    }
  }

  document.addEventListener("click", () => closePopover());

  toggleFrench.addEventListener("change", () => {
    document.body.classList.toggle("show-french", toggleFrench.checked);
  });
  document.body.classList.toggle("show-french", toggleFrench.checked);

  sheetBackdrop.addEventListener("click", () => {
    sheet.hidden = true;
    sheetParaId = null;
  });

  fetch("data.json")
    .then((r) => {
      if (!r.ok) throw new Error(r.statusText);
      return r.json();
    })
    .then((json) => {
      data = json;
      globalModel = FRENCH_MODEL;
      if (!globalModel) throw new Error("No models in data");
      renderLegend();
      renderReader();
    })
    .catch(() => {
      reader.innerHTML =
        '<p class="empty-state">Could not load data.json. Serve this folder over HTTP or run scripts/05_score.py after translations exist.</p>';
    });
})();
