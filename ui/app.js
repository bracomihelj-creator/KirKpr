/* KirKpr 5.0.04 — vmesnik WebView2 (klici HTTP API / pywebview Bridge). */
(function () {
  var state = { view: "ir", boot: null, companies: [], selected: {}, editor: null, dataEditor: null, dataField: "", lastExportDir: "", lastExportPath: "" };
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

  function selectedIds() {
    return Object.keys(state.selected[state.view] || {});
  }

  function setSelected(view, id, on) {
    if (!state.selected[view]) state.selected[view] = {};
    if (on) state.selected[view][id] = true;
    else delete state.selected[view][id];
  }

  function applyState(s) {
    if (!s) return;
    if (s.ok === false) {
      toast(s.msg || s.error || "Napaka.", true);
      return;
    }
    state.boot = s;
    $("brandVer").textContent = s.version || "5.0.04";
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
    var dirty = s.working_dirty ? "Neshranjeni popravki. " : "";
    $("statusLine").textContent = dirty + (s.msg || (s.has_data ? "Podatki so naloženi." : "Ni naloženih podatkov."));
    if (s.msg) toast(s.msg, s.ok === false);
    var about = $("aboutBox");
    if (about) {
      about.innerHTML = "<p><b>KIR/KPR → Minimax Studio " + (s.version || "") + "</b> — vmesnik WebView2 po zgledu Trops Studio 5.</p>" +
        "<p>Tk vmesnik 4.0.3 ostane v mapi (KirKpr_V4.0.3.pyw), dokler 5.x ne pokrije vseh zaslonov.</p>" +
        "<p>Izračuni DDV, XML in oddaja v Minimax se v tej različici ne spreminjajo.</p>";
    }
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

  function renderTable(table, columns, rows, moneyCols, selectable) {
    moneyCols = moneyCols || {};
    var html = "<thead><tr>";
    if (selectable) html += "<th class=\"selCell\"></th>";
    columns.forEach(function (col) {
      html += "<th" + (moneyCols[col.key] ? " class=\"num\"" : "") + ">" + col.label + "</th>";
    });
    html += "</tr></thead><tbody>";
    if (!rows || !rows.length) {
      html += "<tr><td class=\"empty\" colspan=\"" + (columns.length + (selectable ? 1 : 0)) + "\">Ni vrstic za prikaz.</td></tr>";
    } else {
      rows.forEach(function (row) {
        var id = row.id || "";
        var chosen = !!(state.selected[state.view] && state.selected[state.view][id]);
        var cls = [];
        if (row.tag === "tax_only" || row.tag === "vat_not_deducted") cls.push("warnRow");
        if (chosen) cls.push("selected");
        html += "<tr data-id=\"" + escapeHtml(id) + "\"" + (cls.length ? " class=\"" + cls.join(" ") + "\"" : "") + ">";
        if (selectable) {
          html += "<td class=\"selCell\"><input type=\"checkbox\" class=\"rowChk\"" + (chosen ? " checked" : "") + "></td>";
        }
        columns.forEach(function (col) {
          var val = row[col.key] == null ? "" : String(row[col.key]);
          html += "<td" + (moneyCols[col.key] ? " class=\"num\"" : "") + ">" + escapeHtml(val) + "</td>";
        });
        html += "</tr>";
      });
    }
    html += "</tbody>";
    table.innerHTML = html;
    if (selectable) bindTableSelection(table);
  }

  function bindTableSelection(table) {
    table.querySelectorAll("tbody tr[data-id]").forEach(function (tr) {
      var id = tr.getAttribute("data-id");
      var chk = tr.querySelector(".rowChk");
      tr.addEventListener("click", function (ev) {
        if (ev.target.classList.contains("rowChk")) return;
        var on = !(state.selected[state.view] && state.selected[state.view][id]);
        if (!ev.ctrlKey && !ev.metaKey && ev.target.tagName !== "INPUT") {
          if (!ev.shiftKey) {
            /* toggle only this row when clicking the row */
          }
        }
        setSelected(state.view, id, on);
        tr.classList.toggle("selected", on);
        if (chk) chk.checked = on;
      });
      tr.addEventListener("dblclick", function () { openEditor(id); });
      if (chk) {
        chk.addEventListener("click", function (ev) {
          ev.stopPropagation();
          setSelected(state.view, id, chk.checked);
          tr.classList.toggle("selected", chk.checked);
        });
      }
    });
  }

  function escapeHtml(text) {
    return String(text).replace(/[&<>\"']/g, function (ch) {
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

  function syncBookTools() {
    var book = state.view === "ir" || state.view === "pr";
    $("bookTools").classList.toggle("hidden", !book);
    $("vatOnBtn").classList.toggle("hidden", state.view !== "pr");
    $("vatOffBtn").classList.toggle("hidden", state.view !== "pr");
    if (book) loadAccounts();
  }

  function loadAccounts() {
    api("/api/accounts").then(function (data) {
      var list = $("accountList");
      list.innerHTML = "";
      (data.rows || []).forEach(function (label) {
        var opt = document.createElement("option");
        opt.value = label;
        list.appendChild(opt);
      });
    }).catch(function () {});
  }

  function reloadView() {
    var q = $("searchBox").value || "";
    var view = state.view;
    syncBookTools();
    if (view === "ir") {
      return api("/api/ir?q=" + encodeURIComponent(q)).then(function (data) {
        renderTable($("tblIr"), IR_COLS, data.rows || [], MONEY, true);
        $("statusLine").textContent = data.has_data ? ("Prikazanih IR: " + data.visible + " / " + data.count) : "Ni naloženih podatkov.";
      });
    }
    if (view === "pr") {
      return api("/api/pr?q=" + encodeURIComponent(q)).then(function (data) {
        renderTable($("tblPr"), PR_COLS, data.rows || [], MONEY, true);
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
        renderTable($("tblDdvo"), DDVO_COLS, data.fields || [], MONEY, false);
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



  var DATA_COLS = [
    { key: "name", label: "Polje" }, { key: "label", label: "Pomen" },
    { key: "evidence", label: "KIR/KPR" }, { key: "ddvo", label: "DDV-O" },
    { key: "original", label: "Izvorna vrednost (samo branje)" },
    { key: "working", label: "Delovna vrednost za Minimax" }
  ];

  function closeDataEditor() {
    $("dataModal").classList.add("hidden");
    state.dataEditor = null;
    state.dataField = "";
  }

  function renderDataFields(editor) {
    state.dataEditor = editor;
    var rows = (editor.fields || []).map(function (f) {
      return Object.assign({}, f, { tag: f.changed ? "tax_only" : "" });
    });
    renderTable($("tblData"), DATA_COLS, rows, {}, false);
    $("tblData").querySelectorAll("tbody tr").forEach(function (tr, idx) {
      var field = (editor.fields || [])[idx];
      if (!field) return;
      tr.setAttribute("data-field", field.name);
      if (state.dataField === field.name) tr.classList.add("selected");
      tr.addEventListener("click", function () { selectDataField(field.name); });
    });
    if (state.dataField) selectDataField(state.dataField);
  }

  function selectDataField(name) {
    if (!state.dataEditor) return;
    var field = (state.dataEditor.fields || []).find(function (f) { return f.name === name; });
    if (!field) return;
    state.dataField = name;
    $("dataFieldLabel").textContent = field.name + " — " + field.label;
    $("dataValue").value = field.working || "";
    $("tblData").querySelectorAll("tbody tr").forEach(function (tr) {
      tr.classList.toggle("selected", tr.getAttribute("data-field") === name);
    });
    $("dataValue").focus();
    $("dataValue").select();
  }

  function openDataEditor() {
    var ids = selectedIds();
    if (ids.length !== 1) { toast("Za urejanje podatkov izberite natanko en račun.", true); return; }
    api("/api/data-editor?id=" + encodeURIComponent(ids[0])).then(function (data) {
      if (data.ok === false) throw new Error(data.msg || data.error || "Urejevalnika ni mogoče odpreti.");
      $("dataTitle").textContent = "Delovna kopija " + data.book + " — " + (data.invoice || "brez številke");
      $("dataSub").textContent = (data.party || "") + " · Izvorna vrednost ostane nespremenjena. KIR/KPR pokaže mesto v evidenci, DDV-O pa neposredno polje obrazca; za XML/API se uporabi delovna vrednost.";
      state.dataField = (data.fields && data.fields[0] && data.fields[0].name) || "";
      renderDataFields(data);
      $("dataModal").classList.remove("hidden");
    }).catch(function (e) { toast(e.message, true); });
  }

  function applyDataField() {
    if (!state.dataEditor || !state.dataField) { toast("Najprej izberite vrstico s poljem.", true); return Promise.resolve(); }
    return post("/api/data-editor/apply", {
      id: state.dataEditor.id,
      field: state.dataField,
      value: $("dataValue").value
    }).then(function (s) {
      if (s.ok === false) throw new Error(s.msg || s.error);
      applyState(s);
      if (s.editor) renderDataFields(s.editor);
      reloadView();
    }).catch(function (e) { toast(e.message, true); });
  }

  function closeEditor() {
    $("editorModal").classList.add("hidden");
    state.editor = null;
  }

  function openEditor(id) {
    api("/api/row?id=" + encodeURIComponent(id)).then(function (data) {
      if (data.ok === false) throw new Error(data.msg || data.error || "Urejevalnika ni mogoče odpreti.");
      state.editor = data;
      $("editorTitle").textContent = (data.book === "IR" ? "Izdani račun" : "Prejeti račun") + " " + (data.invoice || "");
      $("editorSub").textContent = (data.party || "") + " · Spremembe veljajo za delovno kopijo; izvor ostane nespremenjen.";
      var html = "<div class=\"editorMeta\">";
      html += "<label class=\"fld\">Konto<input id=\"edAccount\" list=\"accountList\" value=\"" + escapeHtml(data.account_label || data.account || "") + "\"></label>";
      html += "<label class=\"fld\">Opis knjižbe<input id=\"edDesc\" value=\"" + escapeHtml(data.description || "") + "\"></label>";
      html += "</div>";
      html += "<label class=\"chk\"><input type=\"checkbox\" id=\"edRemember\"" + (data.remember_rule ? " checked" : "") + "> Zapomni si za partnerja</label>";
      if (data.book === "PR") {
        html += "<div class=\"popRow\">";
        html += "<label class=\"chk\"><input type=\"checkbox\" id=\"edSelf\"" + (data.self_assessment ? " checked" : "") + "> Samoobdavčitev</label>";
        html += "<label class=\"chk\"><input type=\"checkbox\" id=\"edVat\"" + (data.vat_deductible ? " checked" : "") + "> DDV se odbija</label>";
        html += "</div>";
      }
      html += "<div class=\"editorGrid\">";
      (data.fields || []).forEach(function (field) {
        var extra = field.vat_base ? " vatBase" : "";
        var ddvo = field.ddvo && field.ddvo.length ? " · DDV-O " + field.ddvo.join(", ") : "";
        html += "<label class=\"fld" + extra + "\" data-field=\"" + escapeHtml(field.name) + "\">" +
          escapeHtml(field.name + " — " + field.label + ddvo) +
          "<input" + (field.money ? " class=\"num\"" : "") + (field.vat_base ? " data-vat-base=\"1\"" : "") +
          " data-name=\"" + escapeHtml(field.name) + "\" value=\"" + escapeHtml(field.value || "") + "\"></label>";
      });
      html += "</div>";
      $("editorBody").innerHTML = html;
      $("editorModal").classList.remove("hidden");
      $("editorBody").querySelectorAll("input[data-vat-base]").forEach(function (inp) {
        inp.title = "Dvojni klik: izračuna osnovo (DDV ÷ stopnja) in jo kopira v odložišče.";
        inp.addEventListener("dblclick", function () {
          post("/api/vat-base", { field: inp.getAttribute("data-name"), value: inp.value }).then(function (res) {
            if (res.ok === false) throw new Error(res.msg || res.error);
            var text = res.base || "";
            if (navigator.clipboard && navigator.clipboard.writeText) {
              navigator.clipboard.writeText(text).catch(function () {});
            }
            toast((res.msg || "") + "  V odložišču: " + text);
          }).catch(function (e) { toast(e.message, true); });
        });
      });
    }).catch(function (e) { toast(e.message, true); });
  }

  function saveEditor() {
    if (!state.editor) return;
    var fields = {};
    $("editorBody").querySelectorAll("input[data-name]").forEach(function (inp) {
      fields[inp.getAttribute("data-name")] = inp.value;
    });
    var payload = {
      id: state.editor.id,
      account: $("edAccount").value,
      description: $("edDesc").value,
      remember_rule: $("edRemember").checked,
      fields: fields
    };
    if (state.editor.book === "PR") {
      payload.self_assessment = $("edSelf").checked;
      payload.vat_deductible = $("edVat").checked;
    }
    post("/api/row/save", payload).then(function (s) {
      if (s.ok === false) throw new Error(s.msg || s.error);
      applyState(s);
      closeEditor();
      reloadView();
    }).catch(function (e) { toast(e.message, true); });
  }


  function rememberExport(s) {
    var paths = (s && (s.export_paths || s.virman)) || {};
    var first = paths.pdf || paths.xml || paths.report || paths.virman || (s.virman && (s.virman.pdf || s.virman.virman)) || "";
    if (first) {
      state.lastExportPath = first;
      state.lastExportDir = first.replace(/[\\\/][^\\\/]+$/, "");
    }
  }

  function runAction(name, extra, openWhenDone) {
    $("statusLine").textContent = "Delo v teku…";
    return act(name, extra || {}).then(function (res) {
      if (res.job || (res.id && res.state === "running")) return pollJob(res.job || res.id);
      return res;
    }).then(function (s) {
      if (s && s.ok === false) throw new Error(s.msg || s.error || "Naloga ni uspela.");
      if (s && (s.version || s.has_data !== undefined)) applyState(s);
      else if (s && s.msg) toast(s.msg);
      rememberExport(s);
      if (openWhenDone && state.lastExportPath) {
        return act("open_export_path", { path: state.lastExportPath }).then(function () { return s; });
      }
      return s;
    });
  }

  function exportDdvo(kind) {
    return runAction("export_ddvo", { kind: kind }).then(function () { reloadView(); }).catch(function (e) { toast(e.message, true); });
  }

  function refreshVirmanQuote() {
    var k = $("konto62") ? $("konto62").value : "0";
    return api("/api/ddvo/quote?konto62=" + encodeURIComponent(k)).then(function (data) {
      if (data.ok === false) throw new Error(data.msg || data.error);
      if ($("virmanFormula")) $("virmanFormula").textContent = data.formula || data.msg || "";
      if ($("virmanPayment")) $("virmanPayment").value = data.payment || "";
      return data;
    });
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
    state.selected = {};
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
  $("applyAccountBtn").addEventListener("click", function () {
    var ids = selectedIds();
    if (!ids.length) { toast("Najprej izberite enega ali več računov.", true); return; }
    act("apply_accounts", {
      book: state.view === "pr" ? "PR" : "IR",
      ids: ids,
      account: $("accountBox").value,
      remember_rule: $("rememberRule").checked
    }).then(function (s) {
      if (s.ok === false) throw new Error(s.msg || s.error);
      applyState(s);
      reloadView();
    }).catch(function (e) { toast(e.message, true); });
  });
  $("vatOnBtn").addEventListener("click", function () {
    var ids = selectedIds();
    if (!ids.length) { toast("Najprej izberite enega ali več prejetih računov.", true); return; }
    act("set_vat_deductible", { ids: ids, enabled: true }).then(function (s) {
      if (s.ok === false) throw new Error(s.msg || s.error);
      applyState(s);
      reloadView();
    }).catch(function (e) { toast(e.message, true); });
  });
  $("vatOffBtn").addEventListener("click", function () {
    var ids = selectedIds();
    if (!ids.length) { toast("Najprej izberite enega ali več prejetih računov.", true); return; }
    act("set_vat_deductible", { ids: ids, enabled: false }).then(function (s) {
      if (s.ok === false) throw new Error(s.msg || s.error);
      applyState(s);
      reloadView();
    }).catch(function (e) { toast(e.message, true); });
  });
  $("saveWorkingBtn").addEventListener("click", function () {
    act("save_working_copy").then(function (s) {
      if (s.ok === false) throw new Error(s.msg || s.error);
      applyState(s);
    }).catch(function (e) { toast(e.message, true); });
  });
  $("editorClose").addEventListener("click", closeEditor);
  $("editorCancel").addEventListener("click", closeEditor);
  $("editorSave").addEventListener("click", saveEditor);
  $("editorModal").addEventListener("click", function (ev) {
    if (ev.target === $("editorModal")) closeEditor();
  });
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape" && !$("dataModal").classList.contains("hidden")) { closeDataEditor(); return; }
    if (ev.key === "Escape" && !$("editorModal").classList.contains("hidden")) closeEditor();
    if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "a" && (state.view === "ir" || state.view === "pr")) {
      var table = state.view === "ir" ? $("tblIr") : $("tblPr");
      if (!table || ($("editorModal") && !$("editorModal").classList.contains("hidden")) || ($("dataModal") && !$("dataModal").classList.contains("hidden"))) return;
      ev.preventDefault();
      table.querySelectorAll("tbody tr[data-id]").forEach(function (tr) {
        var id = tr.getAttribute("data-id");
        setSelected(state.view, id, true);
        tr.classList.add("selected");
        var chk = tr.querySelector(".rowChk");
        if (chk) chk.checked = true;
      });
    }
    if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "s" && state.editor) {
      ev.preventDefault();
      saveEditor();
    }
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



  $("dataEditorBtn").addEventListener("click", openDataEditor);
  $("dataClose").addEventListener("click", closeDataEditor);
  $("dataCancel").addEventListener("click", closeDataEditor);
  $("dataApplyBtn").addEventListener("click", function () { applyDataField(); });
  $("dataSaveBtn").addEventListener("click", function () {
    var current = state.dataEditor && state.dataField && (state.dataEditor.fields || []).find(function (f) { return f.name === state.dataField; });
    var pending = current && $("dataValue").value !== (current.working || "");
    var proceed = pending ? applyDataField() : Promise.resolve();
    proceed.then(function () {
      return act("save_working_copy").then(function (s) {
        if (s && s.ok === false) throw new Error(s.msg || s.error);
        if (s) applyState(s);
      });
    }).catch(function (e) { toast(e.message, true); });
  });
  $("dataValue").addEventListener("keydown", function (ev) {
    if (ev.key === "Enter") { ev.preventDefault(); applyDataField(); }
  });
  $("dataModal").addEventListener("click", function (ev) {
    if (ev.target === $("dataModal")) closeDataEditor();
  });


  document.querySelectorAll("#ddvoTools [data-ddvo]").forEach(function (btn) {
    btn.addEventListener("click", function () { exportDdvo(btn.getAttribute("data-ddvo")); });
  });
  $("ddvoPreviewBtn").addEventListener("click", function () {
    runAction("preview_ddvo", { open_file: true }).catch(function (e) { toast(e.message, true); });
  });
  $("ddvoOpenBtn").addEventListener("click", function () {
    var path = state.lastExportDir || state.lastExportPath;
    if (!path) { toast("Najprej izvozite DDV-O.", true); return; }
    act("open_export_path", { path: path }).then(function (s) {
      if (s && s.ok === false) throw new Error(s.msg || s.error);
      toast((s && s.msg) || "Mapa je odprta.");
    }).catch(function (e) { toast(e.message, true); });
  });
  $("virmanQuoteBtn").addEventListener("click", function () {
    refreshVirmanQuote().catch(function (e) { toast(e.message, true); });
  });
  $("konto62").addEventListener("change", function () {
    refreshVirmanQuote().catch(function () {});
  });
  $("virmanCreateBtn").addEventListener("click", function () {
    runAction("create_virman_package", {
      konto62: $("konto62").value,
      payer_iban: $("payerIban").value,
      execution_date: $("virmanDate").value
    }).then(function () { reloadView(); }).catch(function (e) { toast(e.message, true); });
  });

  boot().catch(function (e) { toast(e.message || "Zagon ni uspel.", true); });
})();
