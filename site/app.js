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

  const isMobile = () => window.matchMedia("(max-width: 639px)").matches;
  const allModels = () => [FRENCH_MODEL, ...(data?.models || [])];

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
    return perParagraph[pid] || null;
  }

  function renderLegend() {
    legend.innerHTML = "";
    const stats = data.model_stats || {};
    const totalParas =
      (data.metadata && Number(data.metadata.total_paragraphs)) ||
      (Array.isArray(data.paragraphs) ? data.paragraphs.length : 0);
    for (const name of allModels()) {
      const color = name === FRENCH_MODEL ? "#444" : data.model_colors[name] || "#888";
      const st = stats[name] || {};
      const pr = st.pass_rate != null ? Math.round(st.pass_rate * 1000) / 10 : null;
      const processed =
        name === FRENCH_MODEL
          ? totalParas
          : Array.isArray(data.paragraphs)
            ? data.paragraphs.reduce(
                (acc, p) => acc + (p.translations && p.translations[name] ? 1 : 0),
                0
              )
            : 0;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.dataset.model = name;
      if (name === globalModel) btn.classList.add("active");
      btn.innerHTML = `<span class="legend-dot" style="background:${color}"></span><span>${escapeHtml(
        name === FRENCH_MODEL ? "french" : name
      )}</span><span class="legend-meta">· ${processed}/${totalParas} paras</span>${
        name === FRENCH_MODEL
          ? `<span class="legend-meta"> · 100% e-free</span>`
          : pr != null
            ? `<span class="legend-meta"> · ${pr}% e-free</span>`
            : ""
      }`;
      btn.addEventListener("click", () => {
        globalModel = name;
        Object.keys(perParagraph).forEach((k) => delete perParagraph[k]);
        renderLegend();
        renderReader();
      });
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
    for (const name of allModels()) {
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
    for (const name of allModels()) {
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
    let lastChapter = null;
    for (const p of data.paragraphs) {
      if (lastChapter !== null && p.chapter !== lastChapter) {
        const div = document.createElement("div");
        div.className = "chapter-break";
        div.textContent = `· ${p.chapter} ·`;
        reader.appendChild(div);
      }
      lastChapter = p.chapter;

      const wrap = document.createElement("div");
      wrap.className = "para-wrap";

      const article = document.createElement("article");
      article.className = "para";
      const mname = modelForParagraph(p.id);
      article.style.setProperty("--band-count", String(allModels().length || 1));

      const bands = document.createElement("div");
      bands.className = "para-bands";
      for (const name of allModels()) {
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

      article.appendChild(bands);
      article.appendChild(body);
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
