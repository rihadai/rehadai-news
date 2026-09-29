/* =====================================================================
   リハダイNEWS → リハダイジェスト(アプリ)へ案内する部品
   使い方: index.html の </body> の直前に次の1行を足すだけ
     <script src="rehadai-app-link.js" defer></script>
   できること
     1. 画面の下に「アプリで開く」帯を表示(×で閉じると7日間出ない)
     2. 記事ごとに「アプリで見る」案内を自動で付ける
        - PubMedの論文の記事 → その論文のAI要約をアプリで開く
        - それ以外の記事     → アプリのニュースでその記事を開く
     3. アドレスの #article-番号 で、その記事まで自動で移動する
   ===================================================================== */
(function () {
  "use strict";
  var APP = "https://rehab-digest.pages.dev/";
  var DATA = "data/articles.json";
  var TEXT = {
    barLead: "毎朝の新着論文を、日本語のAI要約で。",
    barName: "リハダイジェスト(無料)",
    barBtn: "アプリで開く",
    close: "閉じる",
    ctaPaper: "この論文のAI要約をアプリで見る",
    ctaNews: "アプリで読む・毎朝の論文を受け取る",
  };

  function link(params) {
    var q = Object.keys(params).map(function (k) { return k + "=" + encodeURIComponent(params[k]); }).join("&");
    return APP + "?" + q + (q ? "&" : "") + "from=news";
  }
  function pmidOf(url) { var m = String(url || "").match(/pubmed\.ncbi\.nlm\.nih\.gov\/(\d{1,9})/); return m ? m[1] : ""; }
  function store(k, v) { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } }

  // ---- 見た目(ほかのデザインとぶつからないよう rda- で始まる名前だけ使う) ----
  var css = document.createElement("style");
  css.textContent =
    ".rda-bar{position:fixed;left:0;right:0;bottom:0;z-index:9999;display:flex;align-items:center;gap:10px;" +
    "padding:10px 12px calc(10px + env(safe-area-inset-bottom,0px));background:#0b7a75;color:#fff;" +
    "box-shadow:0 -4px 16px rgba(0,0,0,.18);font-family:inherit;animation:rda-up .35s ease-out}" +
    ".rda-bar img{width:36px;height:36px;border-radius:9px;flex:none}" +
    ".rda-txt{flex:1;min-width:0;font-size:12.5px;line-height:1.35}.rda-txt b{display:block;font-size:14px}" +
    ".rda-go{flex:none;background:#fff;color:#0b7a75;font-weight:800;font-size:14px;border-radius:999px;padding:9px 14px;text-decoration:none;white-space:nowrap}" +
    ".rda-x{flex:none;background:none;border:0;color:#fff;opacity:.8;font-size:20px;line-height:1;padding:6px;cursor:pointer}" +
    ".rda-cta{display:flex;align-items:center;justify-content:space-between;gap:8px;margin:12px 0 4px;padding:10px 12px;" +
    "border-radius:10px;background:#e3f3f1;color:#0b5e5a;font-weight:700;font-size:14px;text-decoration:none;border:1px solid #b6e0db}" +
    ".rda-cta:after{content:'→';font-weight:800}" +
    ".rda-cta img{width:22px;height:22px;border-radius:6px;flex:none}" +
    ".rda-cta span{flex:1}" +
    ".rda-flash{animation:rda-flash 1.6s ease-out}" +
    "@keyframes rda-up{from{transform:translateY(100%)}to{transform:none}}" +
    "@keyframes rda-flash{0%{box-shadow:0 0 0 4px #0b7a75}100%{box-shadow:0 0 0 0 transparent}}" +
    "@media (prefers-reduced-motion:reduce){.rda-bar,.rda-flash{animation:none}}" +
    "@media (prefers-color-scheme:dark){.rda-cta{background:#12403f;color:#bff0ea;border-color:#1f5d5a}}" +
    "body.rda-pad{padding-bottom:76px}";
  document.head.appendChild(css);
  var ICON = APP + "icon-192.png";

  // ---- 1. 下の帯 ----
  function showBar() {
    var closed = +(store("rda_bar_closed") || 0);
    if (Date.now() - closed < 7 * 86400000) return;
    var bar = document.createElement("div");
    bar.className = "rda-bar";
    bar.setAttribute("role", "region");
    bar.setAttribute("aria-label", TEXT.barName);
    bar.innerHTML = '<img src="' + ICON + '" alt="">' +
      '<div class="rda-txt"><b>' + TEXT.barName + "</b>" + TEXT.barLead + "</div>" +
      '<a class="rda-go" href="' + link({}) + '">' + TEXT.barBtn + "</a>" +
      '<button type="button" class="rda-x" aria-label="' + TEXT.close + '">×</button>';
    bar.querySelector(".rda-x").addEventListener("click", function () {
      store("rda_bar_closed", String(Date.now()));
      bar.remove(); document.body.classList.remove("rda-pad");
    });
    document.body.appendChild(bar);
    document.body.classList.add("rda-pad");
  }

  // ---- 2. 記事ごとの案内 ----
  var byTitle = {}, byId = {};
  function norm(s) { return String(s || "").replace(/\s+/g, "").trim(); }
  function ctaFor(a) {
    var pm = pmidOf(a.url);
    var el = document.createElement("a");
    el.className = "rda-cta";
    el.href = pm ? link({ pmid: pm }) : link({ tab: "news", article: a.id });
    el.innerHTML = '<img src="' + ICON + '" alt=""><span></span>';
    el.querySelector("span").textContent = pm ? TEXT.ctaPaper : TEXT.ctaNews;
    return el;
  }
  function decorate(root) {
    var heads = (root || document).querySelectorAll("h1,h2,h3,h4,.title,[class*=title]");
    for (var i = 0; i < heads.length; i++) {
      var h = heads[i];
      if (h.closest(".rda-bar,.rda-cta") || h.getAttribute("data-rda")) continue;
      var a = byTitle[norm(h.textContent)];
      if (!a) continue;
      h.setAttribute("data-rda", "1");
      var box = h.closest("article,.card,.article,li,section") || h.parentElement;
      if (!box || box.querySelector(".rda-cta")) continue;
      if (!box.id) box.id = "article-" + a.id;
      box.appendChild(ctaFor(a));
    }
  }

  // ---- 3. #article-番号 で記事へ移動 ----
  function jump() {
    var m = location.hash.match(/^#article-(\d+)$/);
    if (!m) return;
    var box = document.getElementById("article-" + m[1]);
    if (!box) return;
    box.scrollIntoView({ behavior: "smooth", block: "start" });
    box.classList.add("rda-flash");
    setTimeout(function () { box.classList.remove("rda-flash"); }, 1700);
    jumped = true;
  }
  var jumped = false;

  function start() {
    showBar();
    fetch(DATA, { cache: "no-cache" }).then(function (r) { return r.ok ? r.json() : []; }).then(function (list) {
      (Array.isArray(list) ? list : []).forEach(function (a) { if (a && a.title) { byTitle[norm(a.title)] = a; byId[a.id] = a; } });
      decorate(document);
      jump();
      // 記事があとから表示される作りでも付くように見張る
      new MutationObserver(function () {
        decorate(document);
        if (!jumped) jump();
      }).observe(document.body, { childList: true, subtree: true });
    }).catch(function () { /* 読めなくても帯だけは出す */ });
    window.addEventListener("hashchange", function () { jumped = false; jump(); });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
