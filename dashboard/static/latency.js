/* The Speed section: p50 / p95 / p99 of every step the agent already times. Built with DOM calls and textContent only (nothing from the data is parsed as HTML).
   Uses el(), clear(), get(), state and openCall() from the page's own script. */
(function () {
  var STAGES = ["prep", "lid", "asr", "intent", "reply", "tts", "send"];
  var COLOR = { prep: "#898781", lid: "#378add", asr: "#eb6834", intent: "#1baf7a", reply: "#eda100", tts: "#7f77dd", send: "#b4b2a9" };
  var SHORT = { prep: "Clean-up", lid: "Language ID", asr: "Recognition (after LID)", intent: "Understanding", reply: "Lookups + wording", tts: "Speech synthesis", send: "Hand to line", total: "First audio (total)" };
  var TIER = { cache: "Intent cache", fast_path: "Fast path", rule: "Answered by rule", model: "The model decided", other: "Other (booking flow, early routes, guards)" };
  var NS = "http://www.w3.org/2000/svg";
  var sp = { tier: "" };

  function fmt(ms) {
    if (ms === null || ms === undefined) return "-";
    return ms >= 1000 ? (Math.round(ms / 10) / 100).toFixed(2) + " s" : Math.round(ms) + " ms";
  }
  function pc(x) { return x === null || x === undefined ? "-" : (Math.round(x * 1000) / 10) + "%"; }
  function level(ms, th) { return ms === null || ms === undefined ? "" : ms > th.slow_ms ? "p-bad" : ms > th.slow_ms * 0.66 ? "p-warn" : "p-ok"; }
  function div(cls, text) { return el("div", cls, text); }
  function svg(tag, attrs) {
    var n = document.createElementNS(NS, tag);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    return n;
  }
  function section(host, title, note) {
    var s = div("sp-block");
    s.appendChild(el("h3", "sp-h", title));
    if (note) s.appendChild(div("note", note));
    host.appendChild(s);
    return s;
  }
  function table(host, head, rows, onclick) {
    var t = el("table"), h = el("tr");
    head.forEach(function (c, i) { h.appendChild(el("th", i > 0 && c.num ? "num" : "", c.text !== undefined ? c.text : c)); });
    t.appendChild(h);
    rows.forEach(function (r) {
      var tr = el("tr", r.cls || "");
      r.cells.forEach(function (c, i) {
        var td = el("td", head[i] && head[i].num ? "num" : "");
        if (c && c.node) td.appendChild(c.node); else td.textContent = c === null || c === undefined ? "-" : String(c);
        tr.appendChild(td);
      });
      if (r.onclick) { tr.className = (r.cls || "") + " call"; tr.onclick = r.onclick; }
      t.appendChild(tr);
    });
    host.appendChild(t);
    return t;
  }
  function spark(points, color) {
    var w = 90, h = 22, s = svg("svg", { width: w, height: h, viewBox: "0 0 " + w + " " + h });
    var vals = points.filter(function (v) { return v !== null && v !== undefined; });
    if (vals.length < 2) return s;
    var mx = Math.max.apply(null, vals), mn = Math.min.apply(null, vals), span = Math.max(mx - mn, 1);
    var d = vals.map(function (v, i) { return (i * (w - 2) / (vals.length - 1) + 1).toFixed(1) + "," + (h - 3 - (v - mn) / span * (h - 6)).toFixed(1); }).join(" ");
    s.appendChild(svg("polyline", { points: d, fill: "none", stroke: color || "#378add", "stroke-width": "1.6", "stroke-linejoin": "round" }));
    return s;
  }
  function trendOf(r, name) { return ((r.trend || {})[name] || []).map(function (x) { return x.p95; }); }

  function tiles(host, r) {
    var th = r.thresholds, by = {};
    r.stages.forEach(function (s) { by[s.stage] = s; });
    var tot = by.total || {};
    var stageP95 = STAGES.filter(function (s) { return by[s] && by[s].n; }).sort(function (a, b) { return by[b].p95 - by[a].p95; });
    var eng = (r.asr_engines || []).filter(function (e) { return e.n; }).sort(function (a, b) { return b.p95 - a.p95; })[0];
    var gen = (r.ollama || []).filter(function (o) { return o.route === "generate" && o.n; })[0];
    var live = r.live && r.live.latest ? r.live.latest : {};
    var lag = null;
    Object.keys(live).forEach(function (src) { if (live[src].loop_lag_p95_ms) lag = live[src].loop_lag_p95_ms.value; });
    var row = div("sp-tiles");
    function tile(big, label, cls) { var t = div("sp-tile"); var b = el("b", cls || "", big); t.appendChild(b); t.appendChild(el("span", "", label)); row.appendChild(t); }
    tile(tot.n ? fmt(tot.p95) : "-", "first audio p95" + (tot.n ? " (p50 " + fmt(tot.p50) + ", " + tot.n + " turns)" : ""), "pill " + level(tot.p95, th));
    tile(pc(r.slow_share), "of turns slower than " + fmt(th.slow_ms));
    tile(pc(r.over_target_share), "of turns over the " + fmt(th.target_ms) + " target");
    tile(stageP95.length ? SHORT[stageP95[0]] : "-", "step with the largest p95" + (stageP95.length ? " (" + fmt(by[stageP95[0]].p95) + ")" : ""));
    tile(eng ? fmt(eng.p95) : "-", "slowest recogniser p95" + (eng ? " (" + eng.engine + ")" : ""));
    tile(gen ? fmt(gen.p95) : "-", "intent model p95 (Ollama)");
    tile(by.tts && by.tts.n ? fmt(by.tts.p95) : "-", "speech synthesis p95");
    tile(by.api_ms && by.api_ms.n ? fmt(by.api_ms.p95) : "-", "clinic API per turn p95");
    tile(lag === null ? "-" : fmt(lag), "event-loop lag p95 (live)");
    host.appendChild(row);
  }

  function timeChart(host, r) {
    var th = r.thresholds, by = {};
    r.stages.forEach(function (s) { by[s.stage] = s; });
    var tot = by.total;
    if (!tot || !tot.n) { host.appendChild(div("empty", "No turn timings in this period.")); return; }
    var scale = Math.max(th.slow_ms * 1.1, tot.p99 || tot.p95);
    var order = STAGES.concat(["total"]);
    var chart = div("sp-chart");
    order.forEach(function (name) {
      var s = by[name]; if (!s || !s.n) return;
      var row = div("sp-row" + (name === "total" ? " sp-total" : ""));
      row.appendChild(div("sp-lab", SHORT[name]));
      var track = div("sp-track");
      [th.target_ms, th.slow_ms].forEach(function (m, i) { var mk = div("sp-mark" + (i ? " slow" : "")); mk.style.left = (m / scale * 100) + "%"; track.appendChild(mk); });
      var b95 = div("sp-b95"); b95.style.width = Math.min(100, s.p95 / scale * 100) + "%"; b95.style.background = COLOR[name] || "#2a78d6";
      var b50 = div("sp-b50"); b50.style.width = Math.min(100, s.p50 / scale * 100) + "%"; b50.style.background = COLOR[name] || "#2a78d6";
      track.appendChild(b95); track.appendChild(b50);
      row.appendChild(track);
      row.appendChild(div("sp-val", "p50 " + fmt(s.p50) + "  p95 " + fmt(s.p95)));
      chart.appendChild(row);
    });
    host.appendChild(chart);
    host.appendChild(div("note", "Solid bar = p50, pale bar = p95. Dotted lines: " + fmt(th.target_ms) + " (the owner's target) and " + fmt(th.slow_ms) + " (a reply the call score counts as slow). The stage p95s do not add up to the total's p95: they are slices of one path, and the slowest turn is rarely slow in every stage."));
  }

  function allSteps(host, r) {
    var th = r.thresholds, rows = [];
    function add(label, source, s, trend, color) {
      var d = s || {};
      rows.push({ cells: [label, source, d.n || 0, d.n ? fmt(d.p50) : "-", d.n ? { node: pill(fmt(d.p95), label === "First audio (total)" ? level(d.p95, th) : "") } : "-", d.n ? fmt(d.p99) : "-", d.n ? fmt(d.max) : "-", trend && trend.length > 1 ? { node: spark(trend, color) } : ""], cls: label === "First audio (total)" ? "sp-total-row" : "" });
    }
    function grp(t) { rows.push({ cells: [t, "", "", "", "", "", "", ""], cls: "sp-grp" }); }
    var by = {};
    r.stages.forEach(function (s) { by[s.stage] = s; });
    grp("Each turn, start to first audio (the agent's own timing line)");
    STAGES.forEach(function (n) { add(SHORT[n], "turn timing", by[n], trendOf(r, n), COLOR[n]); });
    add(SHORT.total, "turn timing", by.total, trendOf(r, "total"), "#2a78d6");
    grp("Recognisers, whole time per clip (they start together with language ID)");
    (r.asr_engines || []).forEach(function (e) { add("Recogniser " + e.engine, "ASR timings", e, null); });
    grp("Model server (Ollama), per request");
    (r.ollama || []).forEach(function (o) { add(o.route === "generate" ? "Intent model (generate)" : o.route === "embed" ? "Cache embedding (embed)" : "Other requests", "Ollama log" + (o.errors ? ", " + o.errors + " errors" : ""), o, null); });
    grp("Data");
    add("Clinic API, total per turn", "turn timing", by.api_ms, trendOf(r, "api_ms"), "#eda100");
    grp("Per call (from the call journal)");
    var cm = r.call_medians || {};
    add("Median first audio of a call", "journal, " + (cm.turns || 0) + " turns, " + (cm.slow_replies || 0) + " slow", cm, null);
    host.appendChild(div("note", "n counts turns (or requests, or calls); a step that did not run in a turn is not counted in that step."));
    table(host, ["Step", "Source", { text: "n", num: true }, { text: "p50", num: true }, { text: "p95", num: true }, { text: "p99", num: true }, { text: "max", num: true }, "p95 by day"], rows);
  }
  function pill(text, cls) { return el("span", cls ? "pill " + cls : "", text); }

  function breakdown(host, r) {
    var th = r.thresholds, rows = [];
    Object.keys(r.by_language || {}).forEach(function (lg) {
      var d = r.by_language[lg];
      rows.push({ cells: [lg, d.total ? d.total.n : 0, d.total ? fmt(d.total.p50) : "-", { node: pill(d.total ? fmt(d.total.p95) : "-", d.total ? level(d.total.p95, th) : "") }].concat(["lid", "asr", "intent", "reply", "tts"].map(function (s) { return d[s] ? fmt(d[s].p95) : "-"; })) });
    });
    var h1 = section(host, "By language heard", "The language the recogniser picked for the turn, not the language of the reply.");
    var N = function (t) { return { text: t, num: true }; };
    if (rows.length) table(h1, ["Language", N("turns"), N("total p50"), N("total p95"), N("lid p95"), N("asr p95"), N("intent p95"), N("reply p95"), N("tts p95")], rows); else h1.appendChild(div("empty", "None."));
    var trows = [];
    Object.keys(r.by_tier || {}).forEach(function (t) {
      var d = r.by_tier[t];
      trows.push({ cells: [TIER[t] || t, d.total ? d.total.n : 0, d.total ? fmt(d.total.p50) : "-", { node: pill(d.total ? fmt(d.total.p95) : "-", d.total ? level(d.total.p95, th) : "") }, d.intent ? fmt(d.intent.p95) : "-", d.reply ? fmt(d.reply.p95) : "-", d.tts ? fmt(d.tts.p95) : "-"] });
    });
    var h2 = section(host, "By how the turn was understood", "From the log lines that say which tier answered. \"Other\" is every turn with no such line: booking flow, early routes, guards.");
    if (trows.length) table(h2, ["Tier", N("turns"), N("total p50"), N("total p95"), N("intent p95"), N("reply p95"), N("tts p95")], trows); else h2.appendChild(div("empty", "None."));
  }

  function trendChart(host, r) {
    var t = (r.trend || {}).total || [];
    var b = section(host, "First audio, day by day");
    if (t.length < 2) { b.appendChild(div("empty", "Needs at least two days of timings.")); return; }
    var W = 640, H = 170, L = 44, R = 10, T = 10, B = 24, th = r.thresholds;
    var mx = Math.max(th.slow_ms * 1.1, Math.max.apply(null, t.map(function (x) { return x.p95; })) * 1.05);
    var s = svg("svg", { viewBox: "0 0 " + W + " " + H, width: "100%", role: "img", "aria-label": "p50 and p95 of first audio by day" });
    function X(i) { return L + i * (W - L - R) / (t.length - 1); }
    function Y(v) { return T + (1 - v / mx) * (H - T - B); }
    [th.target_ms, th.slow_ms].forEach(function (m) {
      s.appendChild(svg("line", { x1: L, x2: W - R, y1: Y(m), y2: Y(m), stroke: "#999", "stroke-dasharray": "3 3", "stroke-width": "1" }));
      var lb = svg("text", { x: 2, y: Y(m) + 4, "font-size": "11", fill: "#888" }); lb.textContent = fmt(m); s.appendChild(lb);
    });
    [["p95", "#e24b4a"], ["p50", "#378add"]].forEach(function (k) {
      s.appendChild(svg("polyline", { points: t.map(function (x, i) { return X(i).toFixed(1) + "," + Y(x[k[0]]).toFixed(1); }).join(" "), fill: "none", stroke: k[1], "stroke-width": "2" }));
    });
    t.forEach(function (x, i) {
      if (t.length > 8 && i % Math.ceil(t.length / 8) !== 0 && i !== t.length - 1) return;
      var lb = svg("text", { x: X(i), y: H - 6, "font-size": "10", "text-anchor": "middle", fill: "#888" }); lb.textContent = x.day.slice(5); s.appendChild(lb);
    });
    b.appendChild(s);
    b.appendChild(div("note", "Red = p95, blue = p50, per day (the day in the agent's log)."));
  }

  function slowTable(host, turns) {
    var b = section(host, "Slowest turns", "Click one to open its call. The bar shows where its time went.");
    if (!turns.length) { b.appendChild(div("empty", "None.")); return; }
    var rows = turns.map(function (t) {
      var bar = div("sp-stack");
      STAGES.forEach(function (s) { if (t.stages[s]) { var seg = div(""); seg.style.width = (t.stages[s] / t.total * 100) + "%"; seg.style.background = COLOR[s]; seg.title = SHORT[s] + " " + fmt(t.stages[s]); bar.appendChild(seg); } });
      return { cells: [t.log_day + " " + t.time, t.call_id, t.lang || "-", TIER[t.tier] || t.tier || "-", { node: pill(fmt(t.total), t.total > 1500 ? "p-bad" : "p-warn") }, { node: bar }, SHORT[t.slowest_stage] || "-"], onclick: t.call_day ? function () { if (window.openCall) { window.openCall(t.call_day, t.call_id); var d = document.getElementById("detail"); if (d && d.scrollIntoView) d.scrollIntoView(); } } : null };
    });
    table(b, ["When", "Call", "Lang", "Tier", { text: "Total", num: true }, "Where the time went", "Longest step"], rows);
    var lg = div("legend sp-legend");
    STAGES.forEach(function (s) { var sp_ = el("span"); var sw = el("s"); sw.style.background = COLOR[s]; sp_.appendChild(sw); sp_.appendChild(document.createTextNode(SHORT[s])); lg.appendChild(sp_); });
    b.appendChild(lg);
  }

  function liveBlock(host, r) {
    var b = section(host, "Right now, from the running agent", "Read from the agent's own /api/stats and /api/health every few seconds; its window is its last 200 turns and it restarts at zero.");
    var latest = (r.live || {}).latest || {}, series = (r.live || {}).series || {}, srcs = Object.keys(latest);
    if (!srcs.length) { b.appendChild(div("empty", "The agent has not answered yet (DASHBOARD_AGENT_URLS) or nothing was read in the last 3 hours.")); return; }
    srcs.forEach(function (src) {
      var d = latest[src], rows = [];
      Object.keys(d).sort().forEach(function (name) {
        var v = d[name].value, shown, key = src + " " + name;
        if (/_s(\.|$)/.test(name) || /\.p95_s$/.test(name)) shown = fmt(v * 1000);
        else if (/_ms$/.test(name)) shown = fmt(v);
        else if (/_rate$/.test(name)) shown = pc(v);
        else shown = String(Math.round(v * 100) / 100);
        var pts = (series[key] || []).map(function (x) { return x.v; });
        rows.push({ cells: [name, shown, pts.length > 1 ? { node: spark(pts, "#378add") } : ""] });
      });
      b.appendChild(el("h4", "sp-src", src));
      table(b, ["Reading", { text: "Now", num: true }, "Last 3 hours"], rows);
    });
  }

  function waits(host, r) {
    var b = section(host, "Waits built into turn-taking (configuration, not measured)", "These happen before a turn starts, so they are not in the timings above, but the caller waits through them. They are the defaults in the code; the pod's environment may set others.");
    table(b, ["What", { text: "Seconds", num: true }, "Setting"], (r.configured_waits || []).map(function (w) { return { cells: [w.what, w.seconds, w.setting] }; }));
  }

  function notMeasured(host) {
    var b = section(host, "What this cannot measure");
    var ul = el("ul", "note");
    ["The wait before a turn starts (end-of-speech detection): it is not logged, only configured (above).",
     "The time on the phone line and in the caller's speaker, and Twilio's own delay.",
     "Speech synthesis queueing versus synthesis itself: the agent logs one number for the whole synthesis step.",
     "The model's time inside one particular turn: the Ollama log has no call id, so the intent model is shown per request, and per turn only as the \"Understanding\" slice.",
     "Each clinic API call separately: the agent logs the number of calls and their total time per turn.",
     "The voice-activity and echo-cancelling work: only its effect shows, as event-loop lag and audio backlog in the live block."
    ].forEach(function (t) { ul.appendChild(el("li", "", t)); });
    b.appendChild(ul);
  }

  function qs() { return "days=" + state.days + "&lang=" + encodeURIComponent(state.lang) + "&tier=" + encodeURIComponent(sp.tier); }
  function draw(r, slow) {
    var host = document.getElementById("speed");
    clear(host);
    var bar = div("sp-bar");
    bar.appendChild(el("label", "", "Tier "));
    var sel = el("select");
    [["", "All"], ["fast_path", "Fast path"], ["cache", "Intent cache"], ["rule", "Answered by rule"], ["model", "The model decided"], ["other", "Other"]].forEach(function (o) {
      var op = el("option", "", o[1]); op.value = o[0]; if (o[0] === sp.tier) op.selected = true; sel.appendChild(op);
    });
    sel.onchange = function () { sp.tier = sel.value; window.loadSpeed(); };
    bar.appendChild(sel);
    bar.appendChild(el("span", "note", " " + r.from + (r.from === r.to ? "" : " to " + r.to) + (state.lang ? ", language heard " + state.lang : "") + ". Uses the Period and Language selectors above."));
    host.appendChild(bar);
    tiles(host, r);
    var a = section(host, "Where the time goes");
    timeChart(a, r);
    var t = section(host, "Every step");
    allSteps(t, r);
    breakdown(host, r);
    trendChart(host, r);
    slowTable(host, slow);
    liveBlock(host, r);
    waits(host, r);
    notMeasured(host);
  }
  window.loadSpeed = function () {
    var host = document.getElementById("speed");
    if (!host) return;
    Promise.all([get("api/latency?" + qs()), get("api/latency/slow?" + qs() + "&limit=15")])
      .then(function (v) { draw(v[0], v[1].turns || []); })
      .catch(function () { clear(host); host.appendChild(div("empty", "Could not load the speed figures.")); });
  };
  window.loadSpeed();
})();
