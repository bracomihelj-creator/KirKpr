/* KirKpr 5.0.08 — vmesnik WebView2 (klici HTTP API / pywebview Bridge). */
(function () {
  var state = { view: "ir", boot: null, companies: [], selected: {}, editor: null, dataEditor: null, dataField: "", lastExportDir: "", lastExportPath: "", knjigaBook: "IR", knjigaMode: "json", apiFilter: "ALL" };
  var titles = {
    ir: "Izdani računi",
    pr: "Prejeti računi",
    ddvo: "Obrazec DDV-O",
    knjige: "Knjige IR/PR",
    api: "Minimax API",
    email: "E-pošta DDV",
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
    $("brandVer").textContent = s.version || "5.0.08";
    if (s.theme) document.documentElement.setAttribute("data-theme", s.theme);
    if ($("autoReopenChk")) $("autoReopenChk").checked = !!s.auto_reopen;
    if (s.sessions) renderSessions(s.sessions, s.selected_session_id);
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


  function renderSessions(rows, selectedId) {
    var sel = $("sessionSelect");
    if (!sel) return;
    var current = selectedId || sel.value;
    sel.innerHTML = "";
    var empty = document.createElement("option");
    empty.value = "";
    empty.textContent = rows && rows.length ? "Izberi sejo…" : "Ni shranjene seje";
    sel.appendChild(empty);
    (rows || []).forEach(function (row) {
      var opt = document.createElement("option");
      opt.value = String(row.id);
      opt.textContent = row.label || row.title || ("Seja " + row.id);
      if (String(row.id) === String(current)) opt.selected = true;
      sel.appendChild(opt);
    });
    var label = $("sessionLabel");
    var chosen = (rows || []).find(function (r) { return String(r.id) === String(sel.value); });
    if (label) label.textContent = chosen ? (chosen.label || chosen.title) : (rows && rows.length ? "Izberi sejo" : "Ni shranjene seje");
  }

  function loadSessions() {
    return api("/api/sessions").then(function (data) {
      renderSessions(data.rows || [], data.selected_id);
      return data;
    });
  }

  function closeMenus() {
    document.querySelectorAll(".menu").forEach(function (m) { m.classList.remove("open"); });
    document.querySelectorAll(".menuList").forEach(function (m) { m.classList.add("hidden"); });
  }

  function showHelp(topic) {
    return api("/api/help?topic=" + encodeURIComponent(topic)).then(function (data) {
      $("helpTitle").textContent = data.title || "Pomoč";
      $("helpBody").textContent = data.body || "";
      $("helpModal").classList.remove("hidden");
    }).catch(function (e) { toast(e.message, true); });
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
        if (row.tag === "match_ok" || row.tag === "api_ok") cls.push("matchOk");
        if (row.tag === "api_ok") cls.push("apiOk");
        if (row.tag === "api_error") cls.push("apiError");
        if (row.tag === "api_sent" || row.tag === "api_exists") cls.push("apiSent");
        if (row.tag === "match_api_only") cls.push("matchApi");
        if (row.tag === "match_local_only") cls.push("matchLocal");
        if (row.totals || row.zapst === "Σ") cls.push("totalsRow");
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


  function syncKnjigaButtons() {
    var jsonBtn = $("knjigaModeJson");
    var apiBtn = $("knjigaModeApi");
    if (jsonBtn) jsonBtn.classList.toggle("ghost", state.knjigaMode !== "json");
    if (apiBtn) apiBtn.classList.toggle("ghost", state.knjigaMode !== "api");
    var irBtn = $("knjigaBookIr");
    var prBtn = $("knjigaBookPr");
    if (irBtn) irBtn.classList.toggle("ghost", state.knjigaBook !== "IR");
    if (prBtn) prBtn.classList.toggle("ghost", state.knjigaBook !== "PR");
  }

  function renderKnjiga(data) {
    var cols = (data.columns || []).map(function (c) { return { key: c.key, label: c.label }; });
    var money = {};
    (data.columns || []).forEach(function (c) { if (c.money) money[c.key] = 1; });
    var rows = data.rows || [];
    if (data.totals && cols.length) {
      var totalRow = { zapst: "Σ", obdobje: "SKUPAJ", match: "SKUPAJ", totals: true };
      cols.forEach(function (c) {
        if (c.key !== "zapst" && data.totals[c.key] != null) totalRow[c.key] = data.totals[c.key];
      });
      rows = rows.concat([totalRow]);
    }
    renderTable($("tblKnjiga"), cols, rows, money, false);
    $("knjigaSummary").textContent = data.summary || "";
    var box = $("knjigaTotals");
    box.innerHTML = "";
    (data.columns || []).forEach(function (c) {
      if (!c.money) return;
      var amount = (data.totals || {})[c.key];
      if (!amount || amount === "0,00") return;
      var card = document.createElement("div");
      card.className = "card";
      card.innerHTML = "<small>" + escapeHtml(c.label) + "</small><b>" + escapeHtml(amount) + "</b>";
      box.appendChild(card);
    });
    $("statusLine").textContent = data.has_data
      ? ("Prikazanih " + data.book + ": " + data.visible + (data.count != null ? " / " + data.count : ""))
      : "Ni naloženih podatkov.";
  }

  function reloadKnjige() {
    syncKnjigaButtons();
    var q = $("searchBox").value || "";
    var hide = $("knjigaHideZero") && $("knjigaHideZero").checked ? "1" : "";
    return api("/api/knjige?book=" + encodeURIComponent(state.knjigaBook)
      + "&mode=" + encodeURIComponent(state.knjigaMode)
      + "&q=" + encodeURIComponent(q)
      + (hide ? "&hide_zero=1" : "")).then(function (data) {
      if (data.ok === false) throw new Error(data.msg || data.error);
      renderKnjiga(data);
    });
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
    if (view === "knjige") {
      return reloadKnjige();
    }
    if (view === "api") {
      return reloadApi();
    }
    if (view === "email") {
      return reloadEmail();
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
    $("toolbar").classList.toggle("hidden", name === "settings" || name === "about" || name === "api" || name === "email");
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
      return loadSessions().then(function () { return reloadView(); });
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
    act("set_theme", { theme: next }).catch(function () {});
  });
  document.addEventListener("click", function (ev) {
    if (!ev.target.closest(".menu")) closeMenus();
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


  document.querySelectorAll("[data-knjiga-mode]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      state.knjigaMode = btn.getAttribute("data-knjiga-mode") || "json";
      act("set_knjiga_mode", { mode: state.knjigaMode }).then(function (s) {
        if (s) applyState(s);
        reloadView();
      }).catch(function (e) { toast(e.message, true); });
    });
  });
  document.querySelectorAll("[data-knjiga-book]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      state.knjigaBook = btn.getAttribute("data-knjiga-book") || "IR";
      reloadView().catch(function (e) { toast(e.message, true); });
    });
  });
  $("knjigaHideZero").addEventListener("change", function () {
    reloadView().catch(function (e) { toast(e.message, true); });
  });
  $("knjigaRefreshBtn").addEventListener("click", function () {
    runAction("refresh_knjige_from_api", {}).then(function (s) {
      state.knjigaMode = "api";
      if (s) applyState(s);
      reloadView();
    }).catch(function (e) { toast(e.message, true); });
  });


  document.querySelectorAll(".menuBtn").forEach(function (btn) {
    btn.addEventListener("click", function (ev) {
      ev.stopPropagation();
      var menu = btn.parentElement;
      var open = menu.classList.contains("open");
      closeMenus();
      if (!open) {
        menu.classList.add("open");
        var list = menu.querySelector(".menuList");
        if (list) list.classList.remove("hidden");
      }
    });
  });
  document.querySelectorAll("[data-file]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      closeMenus();
      var name = btn.getAttribute("data-file");
      if (name === "open") pickFile().then(openSource);
      else if (name === "last") runAction("open_last_source", {}).then(function (s) { if (s) { applyState(s); reloadView(); } }).catch(function (e) { toast(e.message, true); });
      else if (name === "save-accounts") runAction("save_accounts", {}).then(function (s) { if (s) applyState(s); }).catch(function (e) { toast(e.message, true); });
      else if (name === "save-working") act("save_working_copy").then(function (s) { if (s.ok === false) throw new Error(s.msg || s.error); applyState(s); }).catch(function (e) { toast(e.message, true); });
      else if (name === "knjige") setView("knjige");
      else if (name === "api") setView("api");
      else if (name === "settings") setView("settings");
      else if (name === "email") setView("email");
      else if (name === "export-dir") {
        var path = state.lastExportDir || (state.boot && state.boot.paths && state.boot.paths.last_source) || "";
        if (!path) { toast("Ni shranjene izhodne mape.", true); return; }
        act("open_export_path", { path: path }).catch(function (e) { toast(e.message, true); });
      }
      else if (name === "log") {
        api("/api/log").then(function (data) {
          if (!data.path) throw new Error("Dnevnik ni na voljo.");
          return act("open_export_path", { path: data.path });
        }).catch(function (e) { toast(e.message, true); });
      }
      else if (name === "exit") {
        var b = bridge();
        if (b && b.close_window) b.close_window();
        else window.close();
      }
    });
  });
  $("autoReopenChk").addEventListener("change", function () {
    act("set_auto_reopen", { enabled: $("autoReopenChk").checked }).then(function (s) { applyState(s); }).catch(function (e) { toast(e.message, true); });
  });
  document.querySelectorAll("[data-theme]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      closeMenus();
      var theme = btn.getAttribute("data-theme") || "light";
      document.documentElement.setAttribute("data-theme", theme);
      act("set_theme", { theme: theme }).then(function (s) { if (s) applyState(s); }).catch(function (e) { toast(e.message, true); });
    });
  });
  document.querySelectorAll("[data-help]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      closeMenus();
      showHelp(btn.getAttribute("data-help") || "about");
    });
  });
  $("helpClose").addEventListener("click", function () { $("helpModal").classList.add("hidden"); });
  $("helpOk").addEventListener("click", function () { $("helpModal").classList.add("hidden"); });
  $("helpModal").addEventListener("click", function (ev) { if (ev.target === $("helpModal")) $("helpModal").classList.add("hidden"); });
  $("sessionOpenBtn").addEventListener("click", function () {
    var id = $("sessionSelect").value;
    if (!id) { toast("Ni izbrane seje.", true); return; }
    runAction("open_session", { id: Number(id) }).then(function (s) {
      if (s) applyState(s);
      loadSessions();
      reloadView();
    }).catch(function (e) { toast(e.message, true); });
  });
  $("sessionSaveBtn").addEventListener("click", function () {
    var title = window.prompt("Ime seje (predlagano — lahko spremeniš ali pustiš):", $("sessionLabel").textContent || "");
    if (title === null) return;
    act("save_session", { title: title }).then(function (s) {
      if (s.ok === false) throw new Error(s.msg || s.error);
      applyState(s);
      loadSessions();
    }).catch(function (e) { toast(e.message, true); });
  });
  $("sessionDeleteBtn").addEventListener("click", function () {
    var id = $("sessionSelect").value;
    if (!id) { toast("Ni izbrane seje.", true); return; }
    var label = $("sessionSelect").selectedOptions[0] ? $("sessionSelect").selectedOptions[0].textContent : id;
    if (!window.confirm("Res zbrišem sejo\\n\\n" + label + "\\n\\nDatoteka s podatki ostane, zbriše se samo zapis seje.")) return;
    act("delete_session", { id: Number(id) }).then(function (s) {
      if (s.ok === false) throw new Error(s.msg || s.error);
      applyState(s);
      loadSessions();
    }).catch(function (e) { toast(e.message, true); });
  });


  var API_COLS = [
    { key: "book", label: "Knjiga" },
    { key: "invoice", label: "Listina" },
    { key: "date", label: "Datum / partner" },
    { key: "party", label: "Partner" },
    { key: "tax_id", label: "ID za DDV" },
    { key: "gross", label: "Znesek z DDV" },
    { key: "account", label: "Konto" },
    { key: "invoice_status", label: "Stanje v Minimaxu" },
    { key: "api_status", label: "API" },
    { key: "detail", label: "Rezultat / napaka" }
  ];

  function pickFolder() {
    var b = bridge();
    if (b && b.pick_folder) return b.pick_folder().then(function (p) { return p || ""; });
    return Promise.resolve("");
  }

  function pickFiles() {
    var b = bridge();
    if (b && b.pick_files) {
      return b.pick_files(["Vse (*.*)"]).then(function (p) {
        if (!p) return [];
        if (Array.isArray(p)) return p.filter(Boolean);
        return [p];
      });
    }
    if (b && b.pick_file) return b.pick_file(["Vse (*.*)"]).then(function (p) { return p ? [p] : []; });
    return Promise.resolve([]);
  }

  function fillSelect(id, rows, value, valueKey, labelKey, emptyLabel) {
    var el = $(id);
    if (!el) return;
    var current = value || el.value || "";
    var html = emptyLabel ? "<option value=\"\">" + emptyLabel + "</option>" : "";
    (rows || []).forEach(function (row) {
      var val = row[valueKey] != null ? String(row[valueKey]) : "";
      if (!val) return;
      var label = row[labelKey] || val;
      html += "<option value=\"" + escapeHtml(val) + "\">" + escapeHtml(String(label)) + "</option>";
    });
    el.innerHTML = html;
    if (current) el.value = current;
  }

  function applyApiForm(api) {
    api = api || {};
    if ($("apiMode")) $("apiMode").value = api.mode || "journal";
    if ($("apiJournalStatus")) $("apiJournalStatus").value = api.journal_status || "O";
    if ($("apiDueDays")) $("apiDueDays").value = api.due_days || "8";
    if ($("apiPrCompanion")) $("apiPrCompanion").checked = !!api.pr_companion_journal;
    var catalogs = api.catalogs || {};
    fillSelect("apiIrNumbering", catalogs.ir_numberings, api.numbering_ir_id, "id", "label", "—");
    fillSelect("apiPrNumbering", catalogs.pr_numberings, api.numbering_pr_id, "id", "label", "—");
    fillSelect("apiIrItem", catalogs.items, api.item_ir_id, "id", "label", "—");
    fillSelect("apiVatIr", catalogs.vat_types, api.vat_type_ir, "code", "label", "—");
    fillSelect("apiVatPr", catalogs.vat_types, api.vat_type_pr, "code", "label", "— običajni PR");
    var conn = $("apiConnLabel");
    if (conn) {
      conn.textContent = api.connected
        ? ("Povezano: " + (api.org_label || api.org_id || ""))
        : (api.message || "Minimax API ni povezan.");
    }
  }

  function apiOptionsPayload() {
    return {
      mode: $("apiMode").value,
      journal_status: $("apiJournalStatus").value,
      due_days: $("apiDueDays").value,
      pr_companion_journal: $("apiPrCompanion").checked,
      numbering_ir_id: $("apiIrNumbering").value,
      numbering_pr_id: $("apiPrNumbering").value,
      item_ir_id: $("apiIrItem").value,
      vat_type_ir: $("apiVatIr").value,
      vat_type_pr: $("apiVatPr").value
    };
  }

  function singleApiId() {
    var ids = selectedIds();
    if (ids.length !== 1) {
      toast("Najprej označite natanko en PR.", true);
      return "";
    }
    return ids[0];
  }

  function reloadApi() {
    var q = ($("apiSearch") && $("apiSearch").value) || "";
    document.querySelectorAll("[data-api-filter]").forEach(function (btn) {
      btn.classList.toggle("ghost", btn.getAttribute("data-api-filter") !== state.apiFilter);
    });
    return api("/api/minimax?book=" + encodeURIComponent(state.apiFilter) + "&q=" + encodeURIComponent(q)).then(function (data) {
      applyApiForm(data.api || (state.boot && state.boot.api) || {});
      renderTable($("tblApi"), API_COLS, data.rows || [], { gross: true }, true);
      var summary = data.has_data ? ("Prikazanih: " + data.visible + " / " + data.count) : "Ni naloženih podatkov.";
      if (data.api && data.api.message) summary += "  •  " + data.api.message;
      $("apiSummary").textContent = summary;
      $("statusLine").textContent = summary;
    });
  }

  $("apiConnectBtn").addEventListener("click", function () {
    runAction("connect_minimax_api", {}).then(function (s) {
      if (s) applyState(s);
      reloadApi();
    }).catch(function (e) { toast(e.message, true); });
  });
  $("apiSaveOptsBtn").addEventListener("click", function () {
    act("set_api_options", apiOptionsPayload()).then(function (s) {
      if (s.ok === false) throw new Error(s.msg || s.error);
      applyState(s);
      if (s.api) applyApiForm(s.api);
    }).catch(function (e) { toast(e.message, true); });
  });
  document.querySelectorAll("[data-api-filter]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      state.apiFilter = btn.getAttribute("data-api-filter") || "ALL";
      reloadApi().catch(function (e) { toast(e.message, true); });
    });
  });
  $("apiSearch").addEventListener("input", function () {
    clearTimeout(reloadApi._t);
    reloadApi._t = setTimeout(function () {
      reloadApi().catch(function (e) { toast(e.message, true); });
    }, 200);
  });
  $("apiValidateBtn").addEventListener("click", function () {
    var ids = selectedIds();
    if (!ids.length) { toast("Izberite enega ali več še neoddanih računov.", true); return; }
    runAction("validate_api_selection", { ids: ids }).then(function (s) {
      if (s) applyState(s);
      reloadApi();
    }).catch(function (e) { toast(e.message, true); });
  });
  $("apiSendBtn").addEventListener("click", function () {
    var ids = selectedIds();
    if (!ids.length) { toast("Izberite račune za oddajo.", true); return; }
    act("preview_api_send", { ids: ids }).then(function (data) {
      if (data.ok === false) throw new Error(data.msg || data.error || "Predogled oddaje ni uspel.");
      if (!window.confirm(data.prompt)) return null;
      return runAction("send_api_selection", { ids: ids, confirm: true });
    }).then(function (s) {
      if (!s) return;
      applyState(s);
      reloadApi();
    }).catch(function (e) { toast(e.message, true); });
  });
  $("apiRetryBtn").addEventListener("click", function () {
    runAction("retry_failed_api_rows", {}).then(function (s) {
      if (s) applyState(s);
      reloadApi();
    }).catch(function (e) { toast(e.message, true); });
  });
  $("apiAttachBtn").addEventListener("click", function () {
    var id = singleApiId();
    if (!id) return;
    pickFolder().then(function (dir) {
      if (!dir) return null;
      return runAction("download_invoice_attachments", { id: id, out_dir: dir });
    }).then(function (s) {
      if (s) { applyState(s); reloadApi(); }
    }).catch(function (e) { toast(e.message, true); });
  });
  $("apiImportAttBtn").addEventListener("click", function () {
    var id = singleApiId();
    if (!id) return;
    pickFiles().then(function (paths) {
      if (!paths || !paths.length) return null;
      return runAction("import_attachment_from_folder", { id: id, sources: paths });
    }).then(function (s) {
      if (s) { applyState(s); reloadApi(); }
    }).catch(function (e) { toast(e.message, true); });
  });
  $("apiSupplierAttBtn").addEventListener("click", function () {
    var id = singleApiId();
    if (!id) return;
    runAction("download_supplier_issued_attachment", { id: id }).then(function (s) {
      if (s) { applyState(s); reloadApi(); }
    }).catch(function (e) { toast(e.message, true); });
  });



  var emailExtraAttachments = [];

  function emailPayload(extra) {
    var data = {
      template_id: $("emailTemplate").value,
      title: $("emailTitle").value,
      subject: $("emailSubject").value,
      body: $("emailBody").value,
      to: $("emailTo").value,
      cc: $("emailCc").value,
      bcc: $("emailBcc").value,
      from_smtp: $("emailFrom").value,
      channel: $("emailChannel").value,
      postscript: $("emailPs").value,
      konto62: $("emailKonto62").value,
      vracilo: $("emailVracilo").checked,
      attach_pdf: $("emailAttachPdf").checked,
      attach_virman: $("emailAttachVirman").checked,
      attachments: emailExtraAttachments.slice()
    };
    return Object.assign(data, extra || {});
  }

  function fillEmailForm(data) {
    if (!data) return;
    var sel = $("emailTemplate");
    var current = data.template_id || sel.value;
    var html = "";
    (data.templates || []).forEach(function (row) {
      html += "<option value=\"" + escapeHtml(row.id) + "\">" + escapeHtml(row.title || row.id) + "</option>";
    });
    sel.innerHTML = html;
    if (current) sel.value = current;
    $("emailTitle").value = data.title || "";
    $("emailTo").value = data.to || "";
    $("emailCc").value = data.cc || "";
    $("emailBcc").value = data.bcc || "";
    $("emailFrom").value = data.from_smtp || "";
    $("emailChannel").value = data.channel || "smtp";
    $("emailSubject").value = data.rendered_subject || data.subject || "";
    $("emailBody").value = data.rendered_body || data.body || "";
    $("emailPs").value = data.postscript || "";
    $("emailKonto62").value = data.konto62 || "";
    $("emailVracilo").checked = !!data.vracilo;
    $("emailAttachPdf").checked = data.attach_pdf !== false;
    $("emailAttachVirman").checked = !!data.attach_virman;
    $("emailLines").textContent = [data.line1, data.line2].filter(Boolean).join("\n");
    var files = (data.attachments || []).concat(emailExtraAttachments);
    $("emailAttachments").textContent = files.length ? ("Priponke:\n" + files.join("\n")) : "Ni samodejnih priponk (najprej izvozite DDV-O / virman).";
    $("emailMeta").textContent = data.has_data
      ? ((data.company && data.company.name) || "Stranka") + " · " + (data.period_label || "") + " · obveznost " + (data.obligation || "0,00") + " · plačilo " + (data.payment || "0,00")
      : "Najprej odprite podatke.";
  }

  function reloadEmail() {
    var tid = $("emailTemplate") ? $("emailTemplate").value : "";
    var konto = $("emailKonto62") ? $("emailKonto62").value : "";
    var q = "/api/email?template_id=" + encodeURIComponent(tid || "") + "&konto62=" + encodeURIComponent(konto || "");
    return api(q).then(function (data) {
      fillEmailForm(data);
      $("statusLine").textContent = data.has_data ? ("Predloga e-pošte: " + (data.title || data.template_id || "")) : "Ni naloženih podatkov.";
    });
  }

  function confirmAndSend(test) {
    var payload = emailPayload({ test: !!test });
    act("preview_email_send", payload).then(function (data) {
      if (data.ok === false) throw new Error(data.msg || data.error || "Predogled ni uspel.");
      if (!window.confirm(data.prompt)) return null;
      return runAction("send_email", Object.assign({}, payload, { confirm: true }));
    }).then(function (s) {
      if (!s) return;
      applyState(s);
    }).catch(function (e) { toast(e.message, true); });
  }

  $("emailTemplate").addEventListener("change", function () {
    reloadEmail().catch(function (e) { toast(e.message, true); });
  });
  $("emailKonto62").addEventListener("change", function () {
    reloadEmail().catch(function (e) { toast(e.message, true); });
  });
  $("emailVracilo").addEventListener("change", function () {
    /* samo za naslednji predogled / shranjevanje; ne pošilja */
  });
  $("emailSaveBtn").addEventListener("click", function () {
    act("save_email_template", emailPayload()).then(function (s) {
      if (s.ok === false) throw new Error(s.msg || s.error);
      applyState(s);
      fillEmailForm(s);
    }).catch(function (e) { toast(e.message, true); });
  });
  $("emailSendBtn").addEventListener("click", function () { confirmAndSend(false); });
  $("emailTestBtn").addEventListener("click", function () { confirmAndSend(true); });
  $("emailAddAttBtn").addEventListener("click", function () {
    pickFiles().then(function (paths) {
      (paths || []).forEach(function (p) {
        if (p && emailExtraAttachments.indexOf(p) < 0) emailExtraAttachments.push(p);
      });
      var el = $("emailAttachments");
      var shown = el.textContent || "";
      if (paths && paths.length) el.textContent = (shown ? shown + "\n" : "") + paths.join("\n");
    });
  });


  boot().catch(function (e) { toast(e.message || "Zagon ni uspel.", true); });
})();
