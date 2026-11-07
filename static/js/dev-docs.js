/* Developer docs (/developers). */
(function () {
  var side = document.getElementById("side");
  var backdrop = document.getElementById("sideBackdrop");
  var menuBtn = document.getElementById("menuBtn");

  function closeSide() {
    side.classList.remove("open");
    backdrop.classList.remove("open");
  }
  function toggleSide() {
    side.classList.toggle("open");
    backdrop.classList.toggle("open");
  }
  if (menuBtn) menuBtn.addEventListener("click", toggleSide);
  if (backdrop) backdrop.addEventListener("click", closeSide);
  side.querySelectorAll("a").forEach(function (a) {
    a.addEventListener("click", function () {
      if (window.innerWidth <= 768) closeSide();
    });
  });
})();

function copyBase() {
  var t = document.getElementById("baseUrl").textContent.trim();
  navigator.clipboard.writeText(t).then(function () {
    alert("Base URL copied");
  }).catch(function () {
    prompt("Copy base URL:", t);
  });
}

function showResult(id, data) {
  var box = document.getElementById(id);
  if (!box) return;
  box.style.display = "block";
  var pre = box.querySelector("pre");
  if (pre) pre.textContent = typeof data === "string" ? data : JSON.stringify(data, null, 2);
}

function request(path, keyInputId, resultId) {
  var key = document.getElementById(keyInputId).value.trim();
  if (!key) {
    alert("Paste your API key first.");
    return;
  }
  fetch(path, {
    headers: { "Authorization": "Bearer " + key }
  })
  .then(function (r) {
    return r.json().then(function (d) {
      return { status: r.status, body: d };
    });
  })
  .then(function (res) {
    showResult(resultId, res);
  })
  .catch(function (err) {
    showResult(resultId, { error: String(err) });
  });
}

function song() {
  var id = document.getElementById("songId").value || "1";
  var key = document.getElementById("songKey").value.trim();
  if (!key) { alert("Paste your API key first."); return; }
  fetch("/api/music/" + encodeURIComponent(id), {
    headers: { "Authorization": "Bearer " + key }
  })
  .then(function (r) { return r.json().then(function (d) { return { status: r.status, body: d }; }); })
  .then(function (res) { showResult("songResult", res); })
  .catch(function (err) { showResult("songResult", { error: String(err) }); });
}

function oneQuote() {
  var id = document.getElementById("quoteId").value || "1";
  var key = document.getElementById("quoteOneKey").value.trim();
  if (!key) { alert("Paste your API key first."); return; }
  fetch("/api/quotes/" + encodeURIComponent(id), {
    headers: { "Authorization": "Bearer " + key }
  })
  .then(function (r) { return r.json().then(function (d) { return { status: r.status, body: d }; }); })
  .then(function (res) { showResult("quoteOneResult", res); })
  .catch(function (err) { showResult("quoteOneResult", { error: String(err) }); });
}

(function () {
  var steps = document.querySelectorAll("#steps .step");

  /* Hatua moja wazi kwa wakati (accordion). Zinafungwa papo hapo wakati wa kubofya,
     ili kusiwe na mweko wa hatua mbili kuwa wazi pamoja. */
  function closeOthers(d) {
    steps.forEach(function (o) { if (o !== d) o.open = false; });
  }
  steps.forEach(function (d) {
    d.querySelector("summary").addEventListener("click", function () { if (!d.open) closeOthers(d); });
    d.addEventListener("toggle", function () { if (d.open) closeOthers(d); });
  });

  function openStep(n, scroll) {
    var el = document.getElementById("step-" + n);
    if (!el) return;
    closeOthers(el);
    el.open = true;
    if (scroll) setTimeout(function () { el.scrollIntoView({ behavior: "smooth", block: "start" }); }, 30);
  }

  /* Kiungo cha moja kwa moja: /developers#step-2 */
  function fromHash() {
    var m = /^#step-([123])$/.exec(location.hash);
    if (m) openStep(m[1], true);
  }
  window.addEventListener("hashchange", fromHash);
  fromHash();

  /* Vitufe vya "Next" */
  document.addEventListener("click", function (e) {
    var a = e.target.closest("[data-open-step]");
    if (!a) return;
    e.preventDefault();
    openStep(a.getAttribute("data-open-step"), true);
  });

  /* Weka jina la column kwenye kila seli (linatumika na mpangilio wa kadi kwenye simu ndogo) */
  document.querySelectorAll(".step-body table.ref").forEach(function (t) {
    var heads = Array.prototype.map.call(t.querySelectorAll("thead th"), function (th) { return th.textContent.trim(); });
    t.querySelectorAll("tbody tr").forEach(function (tr) {
      Array.prototype.forEach.call(tr.children, function (td, i) { if (heads[i]) td.setAttribute("data-label", heads[i]); });
    });
  });

  /* Tabs za lugha (cURL / JavaScript / Python) */
  document.querySelectorAll(".lang-box").forEach(function (box) {
    box.addEventListener("click", function (e) {
      var b = e.target.closest("button[data-lang]");
      if (!b) return;
      var lang = b.getAttribute("data-lang");
      box.querySelectorAll(".lang-tabs button").forEach(function (x) { x.classList.toggle("on", x === b); });
      box.querySelectorAll(".lang-panel").forEach(function (p) { p.classList.toggle("on", p.getAttribute("data-lang") === lang); });
    });
  });
})();
