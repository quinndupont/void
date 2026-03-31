(function () {
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
    return perParagraph[pid] || globalModel;
  }

  function renderLegend() {
    legend.innerHTML = "";
    const stats = data.model_stats || {};
    for (const name of data.models) {
      const color = data.model_colors[name] || "#888";
      const st = stats[name] || {};
      const pr = st.pass_rate != null ? Math.round(st.pass_rate * 1000) / 10 : null;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.dataset.model = name;
      if (name === globalModel) btn.classList.add("active");
      btn.innerHTML = `<span class="legend-dot" style="background:${color}"></span><span>${escapeHtml(
        name
      )}</span>${
        pr != null ? `<span class="legend-meta">· ${pr}% e-free paras</span>` : ""
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
    for (const name of data.models) {
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
    for (const name of data.models) {
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
      const color = data.model_colors[mname] || "#999";
      article.style.setProperty("--bar-color", color);

      const hit = document.createElement("button");
      hit.type = "button";
      hit.className = "para-bar-hit";
      hit.setAttribute("aria-label", `Choose model for ${p.id}`);
      hit.addEventListener("click", (ev) => {
        ev.stopPropagation();
        if (isMobile()) openSheet(p.id);
        else openPopoverDesktop(p.id, wrap);
      });

      const french = document.createElement("p");
      french.className = "french-line";
      french.textContent = p.french;

      const tr = p.translations[mname];
      const body = document.createElement("p");
      body.className = "para-text";
      if (tr && tr.text) {
        body.innerHTML = tr.e_count > 0 ? highlightE(tr.text) : escapeHtml(tr.text);
      } else {
        body.textContent = "—";
      }

      article.appendChild(hit);
      article.appendChild(french);
      article.appendChild(body);
      wrap.appendChild(article);
      reader.appendChild(wrap);
    }
  }

  document.addEventListener("click", () => closePopover());

  toggleFrench.addEventListener("change", () => {
    document.body.classList.toggle("show-french", toggleFrench.checked);
  });

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
      globalModel =
        json.default_model || (json.models && json.models[0]) || null;
      if (!globalModel) throw new Error("No models in data");
      renderLegend();
      renderReader();
    })
    .catch(() => {
      reader.innerHTML =
        '<p class="empty-state">Could not load data.json. Serve this folder over HTTP or run scripts/05_score.py after translations exist.</p>';
    });
})();
