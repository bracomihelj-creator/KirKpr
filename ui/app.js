/* KirKpr 5.0.01 — vmesnik WebView2 (klici HTTP API / pywebview Bridge). */
(function () {
  var state = { view: "ir", boot: null, companies: [] };
  var titles = {
    ir: "Izdani računi",
    pr: "Prejeti računi",
    ddvo: "Obrazec DDV-O",
    knjige: "Knjige IR/PR",
    api: "Minimax API",
    settings: "Nastavitve poti",
    about: "O programu"
  };

  function $(id) { return document.getElementById(id); }

  function api(path, opt) {
    return fetch(path, Object.assign({ credentials: "same-origin" }, opt || {})).then(function (r) {
      return r.json().then(function (body) {
        if (!r.ok && (!body || body.ok !== false)) {
          throw new Error((body && (body.error || body.msg)) || ("HTTP " + r.status));
        }
        return body;
      });
    });
  }

  function post(path, body) {
    return api(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {})
    });
  }

  function act(name, extra) {
    return post("/api/action", Object.assign({ name: name }, extra || {}));
  }

  function toast(msg, isError) {
    var el = $("toast");
    if (!el || !msg) return;
    el.textContent = msg;
    el.classList.toggle("error", !!isError);
    el.classList.remove("hidden");
    clearTimeout(toast._t);
    toast._t = setTimeout(function () { el.classList.add("hidden"); }, 4200);
  }

  function bridge() { return window.pywebview && window.pywebview.api; }

  function pickFile() {
    var b = bridge();
    var kinds = ["KIR/KPR (*.zip;*.json;*.xml;*.csv)", "Vse (*.*)"];
    if (b && b.pick_file) return b.pick_file(kinds).then(function (p) { return p || ""; });
    return Promise.resolve("");
  }

  function applyState(s) {
    if (!s) return;
    state.boot = s;
    $("brandVer").textContent = s.version || "5.0.01";
    var company = s.company;
    $("companyLabel").textContent = company ? ((company.zst ? company.zst + " · " : "") + (company.name || company.key)) : "Ni izbrano";
    $("periodLabel").textContent = s.period_label || (s.period_from ? (s.period_from + " – " + s.period_to) : "—");
    $("periodFrom").value = s.period_from || "";
    $("periodTo").value = s.period_to || "";
    var sum = s.summary || {};
    $("kpiIr").textContent = sum.ir_count != null ? sum.ir_count : "0";
    $("kpiPr").textContent = sum.pr_count != null ? sum.pr_count : "0";
    $("kpiIrMoney").textContent = (sum.ir_net || "0,00") + " + DDV " + (sum.ir_vat || "0,00");
    $("kpiPrMoney").textContent = (sum.pr_net || "0,00") + " + DDV " + (sum.pr_vat || "0,00");
    $("kpiIrVat").textContent = sum.ir_vat || "0,00";
    $("kpiPrVat").textContent = sum.pr_vat || "0,00";
    $("navCntIr").textContent = sum.ir_count || "";
    $("navCntPr").textContent = sum.pr_count || "";
    var crumb = [];
    if (company) crumb.push(company.name || company.key);
    if (s.period_label || s.period_from) crumb.push(s.period_label || (s.period_from + " – " + s.period_to));
    if (sum.source_name) crumb.push(sum.source_name);
    $("crumbs").textContent = crumb.join(" · ") || "Izberi podjetje in odpri KIR/KPR datoteko.";
    $("statusLine").textContent = s.msg || (s.has_data ? "Podatki so naloženi." : "Ni naloženih podatkov.");
    if (s.msg) toast(s.msg, s.ok === false);
  }

  function renderCompanies(rows) {
    state.companies = rows || [];
    var box = $("companyList");
    box.innerHTML = "";
    if (!state.companies.length) {
      box.innerHTML = "<div class=\"empty\">Seznam podjetij je prazen. Preveri pot do EvidenceFirm.</div>";
      return;
    }
    state.companies.forEach(function (c) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "companyItem" + (state.boot && state.boot.company && state.boot.company.key === c.key ? " active" : "");
      btn.innerHTML = "<span class=\"zst\">" + (c.zst || "") + "</span><span>" + (c.name || c.key) + "<br><small>" + (c.tax || "") + "</small></span>";
      btn.addEventListener("click", function () {
        post("/api/company/select", { key: c.key }).then(function (s) {
          applyState(s);
          $("companyPop").classList.add("hidden");
          reloadView();
        }).catch(function (e) { toast(e.message, true); });
      });
      box.appendChild(btn);
    });
  }

  function renderTable(table, columns, rows, moneyCols) {
    moneyCols = moneyCols || {};
    var html = "<thead><tr>";
    columns.forEach(function (col) {
      html += "<th" + (moneyCols[col.key] ? " class=\"num\"" : "") + ">" + col.label + "</th>";
    });
    html += "</tr></thead><tbody>";
    if (!rows || !rows.length) {
      html += "<tr><td class=\"empty\" colspan=\"" + columns.length + "\">Ni vrstic za prikaz.</td></tr>";
    } else {
      rows.forEach(function (row) {
        var cls = row.tag === "tax_only" || row.tag === "vat_not_deducted" ? " class=\"warnRow\"" : "";
        html += "<tr" + cls + ">";
        columns.forEach(function (col) {
          var val = row[col.key] == null ? "" : String(row[col.key]);
          html += "<td" + (moneyCols[col.key] ? " class=\"num\"" : "") + ">" + escapeHtml(val) + "</td>";
        });
        html += "</tr>";
      });
    }
    html += "</tbody>";
    table.innerHTML = html;
  }

  function escapeHtml(text) {
    return text.replace(/[&<>\"']/g, function (ch) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" })[ch];
    });
  }

  var IR_COLS = [
    { key: "zapst", label: "Zap. št." }, { key: "date", label: "Datum" },
    { key: "invoice", label: "Listina" }, { key: "party", label: "Kupec" },
    { key: "tax_id", label: "ID za DDV" }, { key: "net", label: "Neto" },
    { key: "vat_22", label: "DDV 22%" }, { key: "vat_95", label: "DDV 9,5%" },
    { key: "vat", label: "DDV" }, { key: "gross", label: "Skupaj" },
    { key: "account", label: "Konto" }, { key: "status", label: "Obravnava" }
  ];
  var PR_COLS = [
    { key: "zapst", label: "Zap. št." }, { key: "date", label: "Datum" },
    { key: "invoice", label: "Listina" }, { key: "party", label: "Dobavitelj" },
    { key: "tax_id", label: "ID za DDV" }, { key: "net", label: "Osnova" },
    { key: "vat_22", label: "DDV 22%" }, { key: "vat_95", label: "DDV 9,5%" },
    { key: "vat", label: "Odbitni DDV" }, { key: "gross", label: "Obveznost" },
    { key: "account", label: "Konto" }, { key: "self_tax", label: "Samoobd." },
    { key: "vat_deductible", label: "DDV se odbija" }, { key: "status", label: "Vrsta" }
  ];
  var MONEY = { net: 1, vat_22: 1, vat_95: 1, vat: 1, gross: 1, exact: 1, value: 1, difference: 1 };
  var DDVO_COLS = [
    { key: "code", label: "Polje" }, { key: "label", label: "Opis" },
    { key: "section", label: "Razdelek" }, { key: "exact", label: "Točno" },
    { key: "value", label: "Zaokroženo" }, { key: "status", label: "Status" }
  ];

  function reloadView() {
    var q = $("searchBox").value || "";
    var view = state.view;
    if (view === "ir") {
      return api("/api/ir?q=" + encodeURIComponent(q)).then(function (data) {
        renderTable($("tblIr"), IR_COLS, data.rows || [], MONEY);
        $("statusLine").textContent = data.has_data ? ("Prikazanih IR: " + data.visible + " / " + data.count) : "Ni naloženih podatkov.";
      });
    }
    if (view === "pr") {
      return api("/api/pr?q=" + encodeURIComponent(q)).then(function (data) {
        renderTable($("tblPr"), PR_COLS, data.rows || [], MONEY);
        $("statusLine").textContent = data.has_data ? ("Prikazanih PR: " + data.visible + " / " + data.count) : "Ni naloženih podatkov.";
      });
    }
    if (view === "ddvo") {
      return api("/api/ddvo?q=" + encodeURIComponent(q)).then(function (data) {
        var meta = "Ni naloženih podatkov.";
        if (data.has_data) {
          meta = "Zavezanec " + (data.taxpayer || "—") + " · " + (data.period_from || "") + " – " + (data.period_to || "") +
            " · Obveznost " + (data.obligation || "0,00") + " · Presežek " + (data.excess || "0,00") +
            " · Kontrola " + (data.control_ok ? "OK" : ("razlika " + data.control_difference));
        }
        $("ddvoMeta").textContent = meta;
        renderTable($("tblDdvo"), DDVO_COLS, data.fields || [], MONEY);
        $("statusLine").textContent = data.has_data ? ("Polj: " + (data.fields || []).length) : "Ni naloženih podatkov.";
      });
    }
    if (view === "settings") {
      return api("/api/paths").then(function (data) {
        $("setRegistry").value = data.company_registry_path || "";
        $("setTrops").value = data.trops_root || "";
        $("setMinimax").value = data.minimax_settings_path || "";
      });
    }
    return Promise.resolve();
  }

  function setView(name) {
    state.view = name;
    $("pageTitle").textContent = titles[name] || name;
    document.querySelectorAll(".navItem[data-view]").forEach(function (btn) {
      btn.classList.toggle("active", btn.getAttribute("data-view") === name);
    });
    document.querySelectorAll(".page").forEach(function (page) {
      page.classList.toggle("hidden", page.getAttribute("data-page") !== name);
    });
    $("toolbar").classList.toggle("hidden", name === "settings" || name === "about" || name === "knjige" || name === "api");
    reloadView().catch(function (e) { toast(e.message, true); });
  }

  function pollJob(jobId) {
    return api("/api/job?id=" + encodeURIComponent(jobId)).then(function (job) {
      if (job.state === "running") {
        $("statusLine").textContent = job.label || "Delo v teku…";
        return new Promise(function (resolve, reject) {
          setTimeout(function () { pollJob(jobId).then(resolve, reject); }, 250);
        });
      }
      if (job.state === "error" || job.ok === false) {
        throw new Error(job.error || job.msg || "Naloga ni uspela.");
      }
      return job.result || job;
    });
  }

  function openSource(path) {
    if (!path) return Promise.resolve();
    $("statusLine").textContent = "Nalagam…";
    return act("load_source", { path: path }).then(function (res) {
      if (res.job || res.id && res.state === "running") {
        return pollJob(res.job || res.id);
      }
      return res;
    }).then(function (s) {
      applyState(s);
      reloadView();
    }).catch(function (e) { toast(e.message, true); });
  }

  function boot() {
    return api("/api/boot").then(function (s) {
      applyState(s);
      renderCompanies(s.companies || []);
      return reloadView();
    });
  }

  document.getElementById("nav").addEventListener("click", function (ev) {
    var btn = ev.target.closest("[data-view]");
    if (btn) setView(btn.getAttribute("data-view"));
  });
  $("companyBtn").addEventListener("click", function () {
    $("companyPop").classList.toggle("hidden");
    $("periodPop").classList.add("hidden");
    if (!$("companyPop").classList.contains("hidden")) $("companySearch").focus();
  });
  $("periodBtn").addEventListener("click", function () {
    $("periodPop").classList.toggle("hidden");
    $("companyPop").classList.add("hidden");
  });
  $("companySearch").addEventListener("input", function () {
    var q = $("companySearch").value;
    api("/api/companies?q=" + encodeURIComponent(q)).then(function (data) {
      renderCompanies(data.rows || []);
    });
  });
  $("periodPrev").addEventListener("click", function () {
    act("shift_period", { delta: -1 }).then(function (s) { applyState(s); reloadView(); });
  });
  $("periodNext").addEventListener("click", function () {
    act("shift_period", { delta: 1 }).then(function (s) { applyState(s); reloadView(); });
  });
  $("periodApply").addEventListener("click", function () {
    post("/api/period", { from: $("periodFrom").value, to: $("periodTo").value }).then(function (s) {
      applyState(s);
      $("periodPop").classList.add("hidden");
      reloadView();
    });
  });
  $("periodReset").addEventListener("click", function () {
    act("reset_period").then(function (s) {
      applyState(s);
      $("periodPop").classList.add("hidden");
      reloadView();
    });
  });
  $("openFileBtn").addEventListener("click", function () {
    pickFile().then(openSource);
  });
  $("searchBox").addEventListener("input", function () {
    clearTimeout($("searchBox")._t);
    $("searchBox")._t = setTimeout(function () { reloadView(); }, 200);
  });
  $("savePathsBtn").addEventListener("click", function () {
    post("/api/paths/save", {
      company_registry_path: $("setRegistry").value,
      trops_root: $("setTrops").value,
      minimax_settings_path: $("setMinimax").value
    }).then(function (s) {
      applyState(s);
      toast(s.msg || "Shranjeno.");
    }).catch(function (e) { toast(e.message, true); });
  });
  $("themeBtn").addEventListener("click", function () {
    var next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
  });
  document.addEventListener("click", function (ev) {
    if (!ev.target.closest("#companyPicker") && !ev.target.closest("#companyPop")) {
      $("companyPop").classList.add("hidden");
    }
    if (!ev.target.closest("#periodBtn") && !ev.target.closest("#periodPop") && !ev.target.closest("#periodPrev") && !ev.target.closest("#periodNext")) {
      $("periodPop").classList.add("hidden");
    }
  });

  boot().catch(function (e) { toast(e.message || "Zagon ni uspel.", true); });
})();