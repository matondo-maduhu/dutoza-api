/* App shell ya Mercfy: mode ya giza, PWA, mini-player na notifications
   kwa kurasa zote. Inapakiwa kwa `defer` mwishoni mwa kila ukurasa. */
(function () {
  "use strict";

  var root = document.documentElement;

  /* ====================== MODE YA GIZA ====================== */
  var KEY = "mercfy_theme";                       // auto | light | dark

  function stored() {
    try { return localStorage.getItem(KEY) || "auto"; } catch (e) { return "auto"; }
  }
  function systemDark() {
    return !!(window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
  }
  function effective(mode) {
    return mode === "dark" || (mode === "auto" && systemDark()) ? "dark" : "light";
  }
  function applyTheme(mode) {
    var eff = effective(mode);
    root.setAttribute("data-theme", eff);

    var meta = document.getElementById("metaTheme");
    if (meta) meta.setAttribute("content", eff === "dark" ? "#0e111a" : "#ffffff");

    document.querySelectorAll("[data-theme-icon]").forEach(function (el) {
      el.className = eff === "dark" ? "fa-solid fa-sun" : "fa-solid fa-moon";
    });
    document.querySelectorAll("[data-theme-choice]").forEach(function (b) {
      var on = b.getAttribute("data-theme-choice") === mode;
      b.classList.toggle("on", on);
      b.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }
  function setMode(mode) {
    try { localStorage.setItem(KEY, mode); } catch (e) { /* hifadhi imezimwa */ }
    applyTheme(mode);
  }

  window.MercfyTheme = { get: stored, set: setMode, effective: function () { return effective(stored()); } };
  applyTheme(stored());

  if (window.matchMedia) {
    var mq = window.matchMedia("(prefers-color-scheme: dark)");
    var onSystem = function () { if (stored() === "auto") applyTheme("auto"); };
    if (mq.addEventListener) mq.addEventListener("change", onSystem);
    else if (mq.addListener) mq.addListener(onSystem);
  }

  document.addEventListener("click", function (e) {
    var toggle = e.target.closest("#themeToggle");
    if (toggle) { setMode(effective(stored()) === "dark" ? "light" : "dark"); return; }

    var choice = e.target.closest("[data-theme-choice]");
    if (choice) setMode(choice.getAttribute("data-theme-choice"));
  });

  /* ====================== PWA ====================== */
  var secure = location.protocol === "https:" || location.hostname === "localhost" || location.hostname === "127.0.0.1";

  if ("serviceWorker" in navigator && secure) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/sw.js").catch(function () { /* si lazima */ });
    });
  }

  var deferredInstall = null;

  function showInstall(show) {
    document.querySelectorAll("[data-install]").forEach(function (el) { el.hidden = !show; });
  }
  window.addEventListener("beforeinstallprompt", function (e) {
    e.preventDefault();
    deferredInstall = e;
    showInstall(true);
  });
  window.addEventListener("appinstalled", function () { deferredInstall = null; showInstall(false); });
  document.addEventListener("click", function (e) {
    if (!e.target.closest("[data-install-btn]") || !deferredInstall) return;
    deferredInstall.prompt();
    deferredInstall.userChoice.then(function () { deferredInstall = null; showInstall(false); });
  });

  /* ====================== MINI-PLAYER ====================== */
  var mini = document.getElementById("miniPlayer");

  if (mini) {
    var mpCover = mini.querySelector(".mp-cover");
    var mpTitle = mini.querySelector(".mp-title");
    var mpArtist = mini.querySelector(".mp-artist");
    var mpToggle = mini.querySelector("[data-mp-toggle]");
    var mpClose = mini.querySelector("[data-mp-close]");
    var mpFill = mini.querySelector(".mp-fill");
    var current = null, currentCard = null, cardVisible = true, observer = null;

    var isTrack = function (el) { return el && el.tagName === "AUDIO" && el.classList.contains("mf-audio-el"); };

    var textOf = function (el) { return el ? el.textContent.replace(/\s+/g, " ").trim() : ""; };

    function fillInfo(audio) {
      var card = audio.closest(".feed-card") || audio.parentElement;
      currentCard = card;

      var title = textOf(card && card.querySelector(".mf-chip-title")) || "Wimbo";
      var artist = textOf(card && card.querySelector(".mf-artist-line"));
      var img = card && card.querySelector("img.mf-cover-img");

      mpTitle.textContent = title;
      mpArtist.textContent = artist;
      mpCover.textContent = "";

      if (img && img.getAttribute("src")) {
        var copy = document.createElement("img");
        copy.src = img.getAttribute("src");
        copy.alt = "";
        mpCover.appendChild(copy);
      } else {
        var icon = document.createElement("i");
        icon.className = "fa-solid fa-music";
        mpCover.appendChild(icon);
      }
    }

    function watchCard() {
      if (observer) observer.disconnect();
      if (!currentCard || !("IntersectionObserver" in window)) { cardVisible = false; refresh(); return; }

      observer = new IntersectionObserver(function (entries) {
        cardVisible = entries[0].isIntersecting;
        refresh();
      }, { threshold: 0.12 });
      observer.observe(currentCard);
    }

    function icon() {
      var i = mpToggle.querySelector("i");
      if (i) i.className = current && !current.paused ? "fa-solid fa-pause" : "fa-solid fa-play";
    }

    function refresh() {
      var detached = current && !document.contains(current);
      var show = current && !detached && !current.ended && !cardVisible;

      icon();

      if (detached) { current = null; currentCard = null; }

      if (show) {
        mini.hidden = false;
        requestAnimationFrame(function () { mini.classList.add("show"); });
        document.body.classList.add("has-mini");
      } else {
        mini.classList.remove("show");
        document.body.classList.remove("has-mini");
        setTimeout(function () { if (!mini.classList.contains("show")) mini.hidden = true; }, 260);
      }
    }

    /* Matukio ya audio hayapandi juu (bubble), kwa hiyo tunayakamata kwa capture */
    document.addEventListener("play", function (e) {
      if (!isTrack(e.target)) return;
      current = e.target;
      fillInfo(current);
      cardVisible = true;                   // kadi inaonekana wakati wa kuanza kucheza
      watchCard();
      refresh();
    }, true);

    ["pause", "ended"].forEach(function (name) {
      document.addEventListener(name, function (e) { if (e.target === current) refresh(); }, true);
    });

    document.addEventListener("timeupdate", function (e) {
      if (e.target !== current || !current.duration) return;
      mpFill.style.width = Math.min(100, (current.currentTime / current.duration) * 100) + "%";
    }, true);

    mpToggle.addEventListener("click", function () {
      if (!current) return;
      if (current.paused) current.play(); else current.pause();
    });

    mpClose.addEventListener("click", function () {
      if (current) current.pause();
      current = null;
      currentCard = null;
      if (observer) observer.disconnect();
      refresh();
    });

    mini.querySelector(".mp-info").addEventListener("click", function () {
      if (currentCard) currentCard.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  }

  /* ====================== NOTIFICATIONS (kurasa zote) ======================
     Feed ina code yake ya notifications na inaweka window.__notificationsWired.
     Kurasa nyingine (profile, search, settings, n.k.) zinatumia hii. */
  var panel = document.getElementById("notificationPanel");

  if (panel && !window.__notificationsWired) {
    var btn = document.getElementById("notificationButton");
    var badge = document.getElementById("notificationBadge");
    var list = document.getElementById("notificationList");
    var closeBtn = document.getElementById("notificationClose");
    var markAll = document.getElementById("markAllButton");
    var urls = panel.dataset;

    var esc = function (value) {
      return String(value == null ? "" : value)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;").replace(/'/g, "&#039;");
    };

    var fmtDate = function (value) {
      var d = new Date(value);
      if (isNaN(d.getTime())) return "";
      return d.toLocaleString("sw-TZ", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
    };

    var setBadge = function (count) {
      var n = Number.isFinite(Number(count)) ? Math.max(0, Number(count)) : 0;
      if (n <= 0) { badge.classList.add("hidden"); badge.textContent = "0"; return; }
      badge.classList.remove("hidden");
      badge.textContent = n > 99 ? "99+" : String(n);
    };

    var getJson = function (url, options) {
      return fetch(url, Object.assign({ headers: { "Accept": "application/json" }, credentials: "same-origin" }, options || {}))
        .then(function (r) { if (!r.ok) throw new Error("request failed"); return r.json(); });
    };

    var loadCount = function () {
      return getJson(urls.countUrl).then(function (d) { setBadge(d.unread_count); }).catch(function () { /* kimya */ });
    };

    var renderItem = function (n) {
      var actor = n.actor || {};
      var name = esc(actor.full_name || "Mercfy User");
      var message = esc(n.message || (name + " amekufanyia action."));
      var avatar = actor.profile_image_url
        ? '<img src="' + esc(actor.profile_image_url) + '" alt="Profile">'
        : esc((actor.full_name || "M").trim().charAt(0).toUpperCase());

      return '<button type="button" class="notification-item ' + (n.is_read ? "" : "unread") + '"' +
        ' data-notification-id="' + esc(n.id) + '" data-read="' + (n.is_read ? "1" : "0") + '">' +
        '<div class="notification-avatar">' + avatar + "</div>" +
        '<div class="notification-body"><div class="notification-message">' + message + "</div>" +
        '<div class="notification-time">' + fmtDate(n.created_at) + "</div></div>" +
        (n.is_read ? "" : '<span class="unread-dot" aria-label="Unread"></span>') + "</button>";
    };

    var loadList = function () {
      list.innerHTML = '<div class="notification-loading">Inapakia notifications...</div>';

      return getJson(urls.listUrl).then(function (d) {
        list.innerHTML = d.notifications && d.notifications.length
          ? d.notifications.map(renderItem).join("")
          : '<div class="notification-empty">Hakuna notifications kwa sasa.</div>';
      }).catch(function () {
        list.innerHTML = '<div class="notification-error">Imeshindikana kupakia notifications.</div>';
      });
    };

    var setOpen = function (open) {
      panel.classList.toggle("open", open);
      btn.setAttribute("aria-expanded", open ? "true" : "false");
    };

    btn.addEventListener("click", function (e) {
      e.stopPropagation();
      if (panel.classList.contains("open")) { setOpen(false); return; }
      setOpen(true);
      loadList();
    });
    closeBtn.addEventListener("click", function () { setOpen(false); });
    document.addEventListener("click", function (e) {
      if (!panel.contains(e.target) && !btn.contains(e.target)) setOpen(false);
    });

    list.addEventListener("click", function (e) {
      var item = e.target.closest(".notification-item");
      if (!item || !item.dataset.notificationId || item.dataset.read === "1") return;

      getJson(urls.readUrl.replace("__ID__", encodeURIComponent(item.dataset.notificationId)), { method: "POST" })
        .then(function () {
          item.classList.remove("unread");
          item.dataset.read = "1";
          var dot = item.querySelector(".unread-dot");
          if (dot) dot.remove();
          return loadCount();
        }).catch(function () { /* kimya */ });
    });

    markAll.addEventListener("click", function (e) {
      e.stopPropagation();
      markAll.disabled = true;

      getJson(urls.readAllUrl, { method: "POST" })
        .then(function () {
          list.querySelectorAll(".notification-item").forEach(function (item) {
            item.classList.remove("unread");
            item.dataset.read = "1";
            var dot = item.querySelector(".unread-dot");
            if (dot) dot.remove();
          });
          setBadge(0);
        })
        .catch(function () { /* kimya */ })
        .then(function () { markAll.disabled = false; });
    });

    loadCount();
    setInterval(function () { if (!document.hidden) loadCount(); }, 30000);
  }
})();
