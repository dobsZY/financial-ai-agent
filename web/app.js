/* Financial Command Center — web paneli
   Ayni origin'den servis edilir, API cagrilari goreli yol kullanir (CORS yok). */

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const state = {
  view: "signals",
  filters: new Set(),
  segment: "all",
  signals: [], symbols: [], news: [], jobs: [], health: null,
  patterns: {},          // pattern -> PatternInfo
  selected: null,
  auto: true, theme: "dark", busy: false,
  live: { ticker: "", interval: "1h", every: 10, quote: null, timer: null, error: null, tick: 0 },
};

/* ------------------------------------------------------------------ API */

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: opts.body ? { "Content-Type": "application/json" } : {},
    ...opts,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail ?? detail; } catch {}
    throw new Error(`${res.status} · ${detail}`);
  }
  return res.status === 204 ? null : res.json();
}

/* ------------------------------------------------------- bicimlendirme */

const patternLabel = (p) => state.patterns[p]?.label ?? String(p).replace(/_/g, " ");

function scoreColor(s) {
  if (s == null) return "var(--fg-mute)";
  return s >= 0.7 ? "var(--long)" : s >= 0.6 ? "var(--warn)" : "var(--fg-dim)";
}

function relTime(iso) {
  if (!iso) return "–";
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
  const min = Math.floor((Date.now() - d.getTime()) / 60000);
  if (min < 1) return "az önce";
  if (min < 60) return `${min} dk önce`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h} sa önce`;
  return `${Math.floor(h / 24)} gün önce`;
}

function fmtTime(iso) {
  if (!iso) return "–";
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
  return d.toLocaleString("tr-TR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

const chartUrl = (t, o = {}) =>
  `/charts/${encodeURIComponent(t)}?interval=${o.interval || "1h"}&candles=${o.candles || 120}` +
  `&width=${o.w || 1000}&height=${o.h || 460}&volume=${o.volume ?? true}&theme=${state.theme}`;

function toast(msg, kind = "") {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = msg;
  $("#toasts").append(el);
  setTimeout(() => el.remove(), 4200);
}

/* ------------------------------------------------------------ veri yukle */

async function loadAll({ silent = false } = {}) {
  if (!silent) $("#main").innerHTML = '<div class="skeleton"></div>'.repeat(5);
  try {
    const [signals, symbols, news, jobs, health] = await Promise.all([
      api("/signals?limit=60"), api("/symbols"), api("/news?limit=40"),
      api("/jobs?limit=20"), api("/health"),
    ]);
    Object.assign(state, { signals, symbols, news, jobs, health });
    $("#live-dot").className = "dot";
    $("#st-updated").textContent = `güncellendi ${new Date().toLocaleTimeString("tr-TR")}`;
  } catch (err) {
    $("#live-dot").className = "dot dead";
    $("#st-updated").textContent = "API'ye ulaşılamıyor";
    if (!silent) {
      $("#main").innerHTML = emptyState("⚡", `API'ye bağlanılamadı — ${esc(err.message)}`,
        "Sunucunun çalıştığından emin ol: python main.py");
      return;
    }
  }
  render();
}

async function loadPatterns() {
  try {
    for (const info of await api("/patterns")) state.patterns[info.pattern] = info;
  } catch { /* sozluk yoksa ham ad gosterilir */ }
}

/* ------------------------------------------------------------- gorunumler */

const emptyState = (icon, title, hint = "") =>
  `<div class="empty"><div class="big">${icon}</div><p>${esc(title)}</p>
   ${hint ? `<p style="font-size:12px;opacity:.75">${esc(hint)}</p>` : ""}</div>`;

function visibleSignals() {
  const f = state.filters;
  return state.signals.filter((s) => {
    if (state.segment === "notified" && !s.notified_at) return false;
    if (state.segment === "pending" && s.notified_at) return false;
    if (f.has("high") && (s.final_score ?? 0) < 0.7) return false;
    if (f.has("long") && s.direction !== "LONG") return false;
    if (f.has("short") && s.direction !== "SHORT") return false;
    if (f.has("notified") && !s.notified_at) return false;
    if (f.has("bist") && !s.ticker.endsWith(".IS")) return false;
    if (f.has("nasdaq") && s.ticker.endsWith(".IS")) return false;
    return true;
  });
}

function renderSignals() {
  const rows = visibleSignals();
  $("#title").textContent = "Sinyaller";
  $("#subtitle").textContent = rows.length
    ? `${rows.length} sinyal${state.filters.size ? " (filtreli)" : ""}`
    : "eşleşen sinyal yok";
  $("#seg").innerHTML = ["all:Tümü", "notified:Bildirilen", "pending:Eşik altı"]
    .map((o) => { const [k, l] = o.split(":");
      return `<button data-seg="${k}" class="${state.segment === k ? "act" : ""}">${l}</button>`; })
    .join("");

  if (!rows.length) {
    $("#main").innerHTML = emptyState("◈", "Gösterilecek sinyal yok",
      state.filters.size ? "Filtreleri temizlemeyi dene." : "Bir tarama başlat.");
    return;
  }

  $("#main").innerHTML = rows.map((s) => `
    <div class="row ${state.selected === s.id ? "sel" : ""}" data-id="${s.id}">
      <div><span class="tk">${esc(s.ticker)}<small>${s.ticker.endsWith(".IS") ? "BIST" : "NASDAQ"} · 1h</small></span></div>
      <div class="pat"><span>${esc(patternLabel(s.pattern))}</span>
        <button class="help" data-help="${esc(s.pattern)}" title="Bu ne demek?">?</button>
        <small></small></div>
      <div class="c-spark"><img class="spark" loading="lazy" alt=""
        src="${chartUrl(s.ticker, { w: 320, h: 100, candles: 40, volume: false })}"
        onerror="this.style.visibility='hidden'"></div>
      <div><span class="dirchip ${s.direction === "LONG" ? "l" : "s"}">
        ${s.direction === "LONG" ? "▲" : "▼"} ${s.direction}</span></div>
      <div class="scorecell"><b style="color:${scoreColor(s.final_score)}">${(s.final_score ?? 0).toFixed(2)}</b>
        <span>güven %${Math.round((s.confidence ?? 0) * 100)}</span></div>
      <div class="c-bell"><span class="bell ${s.notified_at ? "on" : ""}"
        title="${s.notified_at ? "bildirildi" : "bildirim gönderilmedi"}">${s.notified_at ? "◉" : "○"}</span></div>
    </div>`).join("");
}

function renderWatchlist() {
  $("#title").textContent = "İzleme Listesi";
  $("#subtitle").textContent = `${state.symbols.length} sembol`;
  $("#seg").innerHTML = "";

  const form = `
    <div class="card">
      <div class="crow">
        <input id="new-ticker" class="chip" style="padding:9px 12px;flex:1;background:var(--bg);border:1px solid var(--line);border-radius:9px;color:var(--fg)"
               placeholder="Sembol ekle — THYAO.IS veya AAPL">
        <select id="new-interval" class="chip" style="padding:9px 10px;background:var(--bg);border:1px solid var(--line);border-radius:9px;color:var(--fg)">
          ${["5m", "15m", "30m", "1h", "1d"].map((i) => `<option ${i === "1h" ? "selected" : ""}>${i}</option>`).join("")}
        </select>
        <button class="primary" id="add-symbol">Ekle</button>
      </div>
      <p style="margin:9px 0 0;font-size:11.5px;color:var(--fg-mute)">
        BIST sembolleri <b>.IS</b> ile biter (THYAO.IS). Soneki olmayanlar NASDAQ sayılır.</p>
    </div>`;

  const list = state.symbols.length ? state.symbols.map((s) => `
    <div class="card">
      <div class="crow">
        <span class="tk" style="width:120px">${esc(s.ticker)}</span>
        <span class="chip">${esc(s.market)}</span>
        <span class="chip">${esc(s.interval)}</span>
        <span class="grow"></span>
        <span class="chip">${s.is_active ? "taranıyor" : "duraklatıldı"}</span>
        <button class="swi ${s.is_active ? "on" : ""}" data-toggle="${esc(s.ticker)}"
                title="Taramaya dahil et / çıkar"></button>
        <button class="iconbtn" data-scan-one="${esc(s.ticker)}" title="Yalnız bunu tara">▶</button>
        <button class="iconbtn danger" data-del="${esc(s.ticker)}" title="Listeden çıkar">✕</button>
      </div>
    </div>`).join("") : emptyState("☰", "İzleme listesi boş", "Yukarıdan sembol ekle.");

  $("#main").innerHTML = form + list;
}

function renderNews() {
  $("#title").textContent = "Haberler";
  const pending = state.news.filter((n) => n.sentiment == null).length;
  $("#subtitle").textContent = `${state.news.length} bildirim${pending ? ` · ${pending} özetsiz` : ""}`;
  $("#seg").innerHTML = pending
    ? `<button data-action="summarize">${pending} özeti tamamla</button>` : "";

  if (!state.news.length) {
    $("#main").innerHTML = emptyState("✉", "Kayıtlı haber yok", "KAP/SEC yoklaması başlat.");
    return;
  }

  $("#main").innerHTML = state.news.map((n) => {
    const s = n.sentiment;
    const cls = s == null ? "" : s > 0.15 ? "long" : s < -0.15 ? "short" : "";
    const label = s == null ? "özet yok" : `${s > 0.15 ? "olumlu" : s < -0.15 ? "olumsuz" : "nötr"} ${s > 0 ? "+" : ""}${s.toFixed(2)}`;
    return `<div class="card">
      <div class="crow">
        <span class="chip brand">${esc(n.source)}</span>
        <span class="tk" style="font-size:13.5px">${esc(n.ticker || "–")}</span>
        <span class="chip ${cls}">${esc(label)}</span>
        ${n.risk_level ? `<span class="chip warn">${esc(n.risk_level)} risk</span>` : ""}
        <span class="grow"></span>
        <span class="chip">${esc(fmtTime(n.published_at || n.created_at))}</span>
      </div>
      <p class="news-title">${esc(n.title)}</p>
      ${n.bullets?.length ? `<ul class="news-bullets">${n.bullets.map((b) => `<li>${esc(b)}</li>`).join("")}</ul>` : ""}
      ${n.url ? `<a class="news-link" href="${esc(n.url)}" target="_blank" rel="noopener">Kaynağı aç ↗</a>` : ""}
    </div>`;
  }).join("");
}

function renderSystem() {
  const h = state.health || {};
  const int = h.integrations || {};
  $("#title").textContent = "Sistem";
  $("#subtitle").textContent = "sağlık ve iş geçmişi";
  $("#seg").innerHTML = `<button data-action="scan">Tara</button><button data-action="poll">Haber yokla</button>`;

  const stat = (k, v, s, color) =>
    `<div class="stat"><div class="k">${k}</div><div class="v" style="color:${color || "var(--fg)"}">${v}</div><div class="s">${s}</div></div>`;

  const cards = [
    stat("Scheduler", h.scheduler_running ? "Çalışıyor" : "Durdu",
      `${h.jobs ?? 0} iş kayıtlı`, h.scheduler_running ? "var(--long)" : "var(--short)"),
    stat("İzleme listesi", h.watchlist_size ?? "–", "sembol"),
    stat("Bildirim", int.telegram ? "Telegram" : "Kapalı",
      int.pushover ? "Pushover yedek" : "yedek kanal yok", int.telegram ? "var(--long)" : "var(--warn)"),
    stat("Gemini", int.gemini ? "Bağlı" : "Anahtar yok", h.env ?? "", int.gemini ? "var(--long)" : "var(--warn)"),
  ].join("");

  const rows = state.jobs.map((j) => {
    const dur = j.started_at && j.finished_at
      ? ((new Date(j.finished_at) - new Date(j.started_at)) / 1000).toFixed(1) + " sn" : "–";
    const c = { success: "long", partial: "warn", error: "short", running: "brand" }[j.status] || "";
    return `<tr><td>${esc(j.job_name)}</td><td><span class="chip ${c}">${esc(j.status)}</span></td>
      <td>${esc(relTime(j.started_at))}</td><td>${dur}</td><td>${j.items_processed}</td>
      <td style="color:var(--short)">${esc((j.error_text || "").slice(0, 60) || "–")}</td></tr>`;
  }).join("");

  $("#main").innerHTML = `<div class="stats">${cards}</div>
    <div class="card" style="padding:6px 8px">
      <table><thead><tr><th>İş</th><th>Durum</th><th>Başlangıç</th><th>Süre</th><th>İşlenen</th><th>Hata</th></tr></thead>
      <tbody>${rows || `<tr><td colspan="6" style="color:var(--fg-mute);padding:18px">Henüz iş kaydı yok.</td></tr>`}</tbody></table>
    </div>`;
}


/* ------------------------------------------------------------ canlı takip */

function renderLive() {
  const L = state.live;
  $("#title").textContent = "Canlı Takip";
  $("#subtitle").textContent = L.ticker
    ? `${L.ticker} · ${L.interval} · her ${L.every} sn · ${L.timer ? "canlı" : "durduruldu"}`
    : "bir sembol seç, fiyat ve grafik canlı akmaya başlasın";
  $("#seg").innerHTML = "";

  const options = [...new Set([...state.symbols.map((s) => s.ticker), L.ticker].filter(Boolean))];
  const bar = `
    <div class="live-bar">
      <input id="live-ticker" list="live-symbols" value="${esc(L.ticker)}"
             placeholder="Sembol — THYAO.IS, AAPL…" autocomplete="off">
      <datalist id="live-symbols">${options.map((o) => `<option value="${esc(o)}">`).join("")}</datalist>
      <select id="live-interval">${["5m", "15m", "30m", "1h", "1d"]
        .map((i) => `<option ${i === L.interval ? "selected" : ""}>${i}</option>`).join("")}</select>
      <select id="live-every">${[3, 5, 10, 15, 30, 60]
        .map((s) => `<option value="${s}" ${s === L.every ? "selected" : ""}>${s} sn</option>`).join("")}</select>
      <button class="primary" id="live-start">${L.timer ? "Durdur" : "Takibi başlat"}</button>
    </div>`;

  if (!L.ticker) {
    $("#main").innerHTML = bar + emptyState("◎", "Canlı takip için sembol gir",
      "İzleme listendeki semboller otomatik önerilir.");
    return;
  }

  if (L.error) {
    $("#main").innerHTML = bar + emptyState("⚡", L.error, "Sembol kodunu kontrol et.");
    return;
  }

  const q = L.quote;
  if (!q) { $("#main").innerHTML = bar + '<div class="skeleton" style="height:150px"></div>'; return; }

  const up = q.change >= 0;
  const col = up ? "var(--long)" : "var(--short)";
  const ind = q.indicators || {};
  const indCard = (k, v, fmt = 2) =>
    `<div class="stat"><div class="k">${k}</div><div class="v">${v == null ? "–" : Number(v).toFixed(fmt)}</div></div>`;

  $("#main").innerHTML = bar + `
    <div class="quote">
      <div>
        <div class="sym"><span class="pulse" style="background:${col}"></span>${esc(q.ticker)} · ${esc(q.market)} · ${esc(q.interval)}</div>
        <div class="px" style="color:${col}">${q.price.toFixed(2)}</div>
      </div>
      <div class="delta" style="color:${col};background:${up ? "var(--long-bg)" : "var(--short-bg)"}">
        ${up ? "▲" : "▼"} ${q.change.toFixed(2)} (${up ? "+" : ""}${q.change_pct.toFixed(2)}%)</div>
      <div class="meta">
        <div><div class="k">Yüksek</div><div class="v">${q.high.toFixed(2)}</div></div>
        <div><div class="k">Düşük</div><div class="v">${q.low.toFixed(2)}</div></div>
        <div><div class="k">Önceki</div><div class="v">${q.previous_close.toFixed(2)}</div></div>
        <div><div class="k">Hacim</div><div class="v">${Intl.NumberFormat("tr-TR", { notation: "compact" }).format(q.volume)}</div></div>
        <div><div class="k">Son mum</div><div class="v">${esc(fmtTime(q.last_candle_ts))}</div></div>
      </div>
      ${q.is_stale ? '<div class="stale">⚠ Veri bayat görünüyor — piyasa kapalı olabilir.</div>' : ""}
    </div>

    <img class="livechart" alt="${esc(q.ticker)} canlı grafik"
         src="${chartUrl(q.ticker, { interval: L.interval, w: 1400, h: 560, candles: 150 })}&live=true&t=${L.tick}">

    <div class="ind">
      ${indCard("RSI(14)", ind.rsi, 1)}
      ${indCard("EMA 20", ind.ema_20)}
      ${indCard("EMA 50", ind.ema_50)}
      ${indCard("EMA 200", ind.ema_200)}
      ${indCard("MACD hist", ind.macd_hist, 3)}
      ${indCard("Hacim oranı", ind.volume_ratio, 2)}
    </div>`;
}

async function refreshQuote() {
  const L = state.live;
  if (!L.ticker) return;
  try {
    L.quote = await api(`/quote/${encodeURIComponent(L.ticker)}?interval=${L.interval}`);
    L.error = null;
    L.tick += 1;
  } catch (err) {
    L.error = `${L.ticker} için fiyat alınamadı — ${err.message}`;
  }
  if (state.view === "live") renderLive();
}

function stopLive() {
  if (state.live.timer) { clearInterval(state.live.timer); state.live.timer = null; }
}

async function startLive(ticker, interval, every) {
  const L = state.live;
  stopLive();
  Object.assign(L, { ticker: ticker.trim().toUpperCase(), interval, every, quote: null, error: null });
  go("live");
  await refreshQuote();
  L.timer = setInterval(refreshQuote, every * 1000);
  renderLive();
  toast(`${L.ticker} canlı takipte — ${every} sn`, "ok");
}

/* ---------------------------------------------------------- detay bolmesi */

async function renderDetail() {
  const el = $("#detail");
  const s = state.signals.find((x) => x.id === state.selected);
  document.querySelector(".app").classList.toggle("no-detail", state.view !== "signals");
  if (state.view !== "signals") return;

  if (!s) {
    el.innerHTML = emptyState("◈", "Sinyal seç", "Soldaki listeden bir satıra tıkla.");
    return;
  }

  const info = state.patterns[s.pattern];
  el.innerHTML = `
    <div class="dhead"><div class="r1">
      <div><h2>${esc(s.ticker)}</h2>
        <p>${esc(patternLabel(s.pattern))} · ${s.direction} · ${esc(relTime(s.created_at))}</p></div>
      <div class="dscore"><b style="color:${scoreColor(s.final_score)}">${(s.final_score ?? 0).toFixed(2)}</b>
        <span>final skor</span></div>
    </div></div>

    <div class="sec"><h4>Fiyat grafiği</h4>
      <img class="chart" src="${chartUrl(s.ticker, { w: 1000, h: 460 })}"
           alt="${esc(s.ticker)} grafiği" onerror="this.replaceWith(Object.assign(document.createElement('p'),{textContent:'Grafik için yeterli veri yok.',style:'font-size:12.5px;color:var(--fg-mute)'}))"></div>

    <div class="sec"><h4>Skor</h4>
      <div class="bdrow"><span>Formasyon güveni</span>
        <div class="trk"><i style="width:${(s.confidence ?? 0) * 100}%;background:var(--brand)"></i></div>
        <b>${(s.confidence ?? 0).toFixed(2)}</b></div>
      <div class="bdrow"><span>Final skor</span>
        <div class="trk"><i style="width:${(s.final_score ?? 0) * 100}%;background:${scoreColor(s.final_score)}"></i></div>
        <b>${(s.final_score ?? 0).toFixed(2)}</b></div>
      <p style="margin:4px 0 0;font-size:11.5px;color:var(--fg-mute)">
        Final skor; formasyon güveni, indikatör teyidi ve haber duyarlılığının ağırlıklı toplamıdır.</p>
    </div>

    <div class="sec"><h4>Künye</h4>
      <div class="bdrow" style="grid-template-columns:1fr auto"><span>Fiyat</span><b>${s.price_at_signal?.toFixed(2) ?? "–"}</b></div>
      <div class="bdrow" style="grid-template-columns:1fr auto"><span>Mum</span><b>${esc(fmtTime(s.bucket_ts))}</b></div>
      <div class="bdrow" style="grid-template-columns:1fr auto"><span>Bildirim</span>
        <b style="color:${s.notified_at ? "var(--long)" : "var(--fg-mute)"}">${s.notified_at ? fmtTime(s.notified_at) : "gönderilmedi"}</b></div>
    </div>

    ${info ? `<div class="sec"><h4>${esc(info.label)} ne demek</h4>
      <p style="margin:0;font-size:13px;line-height:1.6;color:var(--fg-dim)">${esc(info.summary)}</p>
      <button class="ghost" style="margin-top:11px;width:100%" data-help="${esc(s.pattern)}">Ayrıntılı açıklama</button></div>` : ""}

    <div class="sec" id="d-news"><h4>${esc(s.ticker)} haberleri</h4>
      <p style="margin:0;font-size:12.5px;color:var(--fg-mute)">yükleniyor…</p></div>

    <div class="acts">
      <button class="ghost" data-live="${esc(s.ticker)}">◎ Canlı izle</button>
      <button class="ghost" data-scan-one="${esc(s.ticker)}">Yeniden tara</button>
      <a class="ghost" style="display:grid;place-items:center;text-decoration:none"
         href="${chartUrl(s.ticker, { w: 1600, h: 900, candles: 200 })}" target="_blank" rel="noopener">Grafiği büyüt</a>
    </div>`;

  try {
    const items = await api(`/news?ticker=${encodeURIComponent(s.ticker)}&limit=4`);
    $("#d-news").innerHTML = `<h4>${esc(s.ticker)} haberleri</h4>` + (items.length
      ? items.map((n) => `<div style="padding:9px 0;border-top:1px solid var(--line-soft)">
          <div class="crow" style="gap:7px"><span class="chip brand">${esc(n.source)}</span>
            <span class="chip">${n.sentiment == null ? "özet yok" : (n.sentiment > 0 ? "+" : "") + n.sentiment.toFixed(2)}</span></div>
          <p style="margin:6px 0 0;font-size:12.5px">${esc(n.title)}</p></div>`).join("")
      : `<p style="margin:0;font-size:12.5px;color:var(--fg-mute)">Son 24 saatte bu sembol için bildirim yok.</p>`);
  } catch { /* detay haberleri opsiyonel */ }
}

/* ----------------------------------------------------- formasyon aciklamasi */

async function openPattern(pattern) {
  let info = state.patterns[pattern];
  if (!info) { try { info = await api(`/patterns/${pattern}`); } catch { toast("Açıklama bulunamadı", "err"); return; } }
  let notes = {};
  try { notes = await api("/patterns/notes"); } catch {}

  const sec = (icon, title, text, color) => `<div class="msec">
    <h5 style="color:${color}">${icon} ${title}</h5><p>${esc(text)}</p></div>`;

  $("#modal").innerHTML = `
    <div class="mhead">
      <h3>${info.direction === "LONG" ? "▲" : "▼"} ${esc(info.label)}
        <span class="chip ${info.direction === "LONG" ? "long" : "short"}">
          beklenen yön: ${info.direction === "LONG" ? "yukarı" : "aşağı"}</span>
        <span class="chip">${info.family === "dönüş" ? "trend dönüşü" : "trend devamı"}</span></h3>
      <p class="sum">${esc(info.summary)}</p>
    </div>
    <div class="mbody">
      ${sec("◷", "Nasıl oluşur", info.forms, "var(--brand)")}
      ${sec("◉", "Ne anlama gelir", info.implication, "var(--brand)")}
      ${sec("✓", "Teyit koşulu", info.confirmation, "var(--long)")}
      ${sec("✕", "Nerede geçersiz olur", info.invalidation, "var(--short)")}
      ${sec("⌖", "Hedef hesabı", info.target, "var(--brand)")}
      ${sec("⚠", "Sık yapılan hata", info.pitfalls, "var(--warn)")}
      ${notes.detection_caveat ? `<div class="note">ⓘ <span>${esc(notes.detection_caveat)}</span></div>` : ""}
      ${notes.disclaimer ? `<div class="note">§ <span>${esc(notes.disclaimer)}</span></div>` : ""}
    </div>
    <div class="mfoot"><button class="ghost" style="padding:0 18px" data-close-modal>Kapat</button></div>`;
  $("#modal-ov").classList.add("open");
}

/* ------------------------------------------------------------ komut paleti */

const COMMANDS = [
  { icon: "◈", label: "Sinyaller", tail: "sayfa", run: () => go("signals") },
  { icon: "☰", label: "İzleme listesi", tail: "sayfa", run: () => go("watchlist") },
  { icon: "✉", label: "Haberler", tail: "sayfa", run: () => go("news") },
  { icon: "◔", label: "Sistem", tail: "sayfa", run: () => go("system") },
  { icon: "⟳", label: "Taramayı başlat", tail: "komut", run: () => triggerScan() },
  { icon: "✉", label: "Haber yoklaması", tail: "komut", run: () => triggerPoll() },
  { icon: "★", label: "Özetsiz haberleri tamamla", tail: "komut", run: () => triggerSummarize() },
  { icon: "◐", label: "Temayı değiştir", tail: "komut", run: () => toggleTheme() },
  { icon: "◎", label: "Canlı takip", tail: "sayfa", run: () => go("live") },
];

function paintPalette(q = "") {
  const s = q.toLowerCase().trim();
  const groups = [];

  const sig = state.signals.filter((x) =>
    (x.ticker + patternLabel(x.pattern)).toLowerCase().includes(s)).slice(0, 6);
  if (sig.length) groups.push(["Sinyaller", sig.map((x) => ({
    icon: x.direction === "LONG" ? "▲" : "▼",
    label: `${x.ticker} — ${patternLabel(x.pattern)}`,
    tail: (x.final_score ?? 0).toFixed(2),
    run: () => { go("signals"); select(x.id); },
  }))]);
  if (s && sig.length) groups.push(["Canlı takip", sig.slice(0, 3).map((x) => ({
    icon: "◎", label: `${x.ticker} canlı izle`, tail: "canlı",
    run: () => startLive(x.ticker, state.live.interval, state.live.every),
  }))]);

  const pat = Object.values(state.patterns)
    .filter((p) => (p.label + p.summary).toLowerCase().includes(s)).slice(0, 5);
  if (s && pat.length) groups.push(["Formasyonlar", pat.map((p) => ({
    icon: "?", label: p.label, tail: "açıklama", run: () => openPattern(p.pattern),
  }))]);

  const cmd = COMMANDS.filter((c) => c.label.toLowerCase().includes(s));
  if (cmd.length) groups.push(["Komutlar", cmd]);

  $("#pres").innerHTML = groups.length
    ? groups.map(([name, items], gi) => `<div class="pgroup">${name}</div>` +
        items.map((it, i) => `<button class="pitem ${gi === 0 && i === 0 ? "hi" : ""}"
          data-g="${gi}" data-i="${i}"><b>${it.icon}</b>${esc(it.label)}
          <span class="tail">${esc(it.tail)}</span></button>`).join("")).join("")
    : `<div class="empty" style="padding:26px"><p>"${esc(q)}" için sonuç yok</p></div>`;
  window.__paletteGroups = groups.map(([, items]) => items);
}

function openPalette() { $("#ov").classList.add("open"); $("#pq").value = ""; paintPalette(); $("#pq").focus(); }
function closePalette() { $("#ov").classList.remove("open"); $("#q").blur(); }

function runHighlighted() {
  const hi = $(".pitem.hi", $("#pres"));
  if (!hi) return;
  const entry = window.__paletteGroups[+hi.dataset.g][+hi.dataset.i];
  closePalette();
  entry.run();
}

function moveHighlight(delta) {
  const items = $$(".pitem", $("#pres"));
  if (!items.length) return;
  const idx = Math.max(0, items.findIndex((el) => el.classList.contains("hi")));
  items[idx]?.classList.remove("hi");
  items[(idx + delta + items.length) % items.length].classList.add("hi");
}

/* ------------------------------------------------------------- eylemler */

async function withBusy(fn, label) {
  if (state.busy) return;
  state.busy = true;
  $("#scan").disabled = true;
  $("#auto").classList.add("spin");
  try { await fn(); } catch (err) { toast(`${label} başarısız: ${err.message}`, "err"); }
  finally { state.busy = false; $("#scan").disabled = false; $("#auto").classList.remove("spin"); }
}

const triggerScan = (tickers) => withBusy(async () => {
  const body = { background: false, send_notification: true };
  if (tickers) body.tickers = tickers;
  const r = await api("/scan", { method: "POST", body: JSON.stringify(body) });
  toast(`Tarama bitti — ${r.saved} yeni sinyal, ${r.notified} bildirim`, "ok");
  await loadAll({ silent: true });
}, "Tarama");

const triggerPoll = () => withBusy(async () => {
  const r = await api("/news/poll?background=false", { method: "POST" });
  toast(`Yoklama bitti — ${r.new} yeni haber, ${r.summarized} özet`, "ok");
  await loadAll({ silent: true });
}, "Yoklama");

const triggerSummarize = () => withBusy(async () => {
  const r = await api("/news/summarize?limit=20", { method: "POST" });
  toast(`${r.summarized} haber özetlendi${r.failed ? `, ${r.failed} başarısız` : ""}`, r.failed ? "" : "ok");
  await loadAll({ silent: true });
}, "Özetleme");

/* ---------------------------------------------------------------- yonlendirme */

function go(view) {
  if (view !== "live") stopLive();
  state.view = view;
  location.hash = `#/${view}`;
  $$(".nav[data-view]").forEach((b) => b.classList.toggle("act", b.dataset.view === view));
  render();
}

function select(id) { state.selected = id; render(); }

function render() {
  $("#c-signals").textContent = state.signals.length;
  $("#c-symbols").textContent = state.symbols.length;
  $("#c-news").textContent = state.news.length;

  const h = state.health || {};
  $("#markets").innerHTML = Object.entries(h.markets || {})
    .map(([m, open]) => `<span class="mkt"><s class="${open ? "open" : ""}"></s>${m} ${open ? "açık" : "kapalı"}</span>`).join("");
  $("#st-scheduler").innerHTML = `Scheduler <b>${h.scheduler_running ? "çalışıyor" : "durdu"}</b>`;
  const last = state.jobs[0];
  $("#st-jobs").innerHTML = last ? `Son iş <b>${esc(last.job_name)} · ${esc(last.status)}</b>` : "Son iş <b>–</b>";
  const int = h.integrations || {};
  $("#st-integrations").innerHTML =
    `Telegram <b>${int.telegram ? "bağlı" : "kapalı"}</b> · Gemini <b>${int.gemini ? "bağlı" : "kapalı"}</b>`;

  ({ signals: renderSignals, watchlist: renderWatchlist, live: renderLive, news: renderNews, system: renderSystem }[state.view])();
  renderDetail();
}

/* -------------------------------------------------------------------- tema */

function applyTheme(t) {
  state.theme = t;
  document.documentElement.dataset.theme = t;
  localStorage.setItem("theme", t);
  $("#theme").textContent = t === "dark" ? "◐" : "◑";
}
const toggleTheme = () => { applyTheme(state.theme === "dark" ? "light" : "dark"); render(); };

/* ------------------------------------------------------------------- olaylar */

document.addEventListener("click", async (e) => {
  const t = e.target;

  const help = t.closest("[data-help]");
  if (help) { e.stopPropagation(); openPattern(help.dataset.help); return; }
  if (t.closest("[data-close-modal]") || t.id === "modal-ov") { $("#modal-ov").classList.remove("open"); return; }

  const nav = t.closest(".nav[data-view]");
  if (nav) return go(nav.dataset.view);

  const filter = t.closest(".nav[data-filter]");
  if (filter) {
    const f = filter.dataset.filter;
    state.filters.has(f) ? state.filters.delete(f) : state.filters.add(f);
    filter.classList.toggle("act", state.filters.has(f));
    if (state.view !== "signals") go("signals"); else render();
    return;
  }

  const seg = t.closest("[data-seg]");
  if (seg) { state.segment = seg.dataset.seg; return render(); }

  const row = t.closest(".row");
  if (row) return select(+row.dataset.id);

  const action = t.closest("[data-action]")?.dataset.action;
  if (action === "scan") return triggerScan();
  if (action === "poll") return triggerPoll();
  if (action === "summarize") return triggerSummarize();

  const scanOne = t.closest("[data-scan-one]");
  if (scanOne) return triggerScan([scanOne.dataset.scanOne]);

  const toggle = t.closest("[data-toggle]");
  if (toggle) {
    const ticker = toggle.dataset.toggle;
    const sym = state.symbols.find((s) => s.ticker === ticker);
    return withBusy(async () => {
      await api(`/symbols/${encodeURIComponent(ticker)}`,
        { method: "PATCH", body: JSON.stringify({ is_active: !sym.is_active }) });
      await loadAll({ silent: true });
    }, "Güncelleme");
  }

  const del = t.closest("[data-del]");
  if (del) {
    const ticker = del.dataset.del;
    if (!confirm(`${ticker} izleme listesinden çıkarılsın mı?\nBu sembole ait mumlar ve sinyaller de silinir.`)) return;
    return withBusy(async () => {
      await api(`/symbols/${encodeURIComponent(ticker)}`, { method: "DELETE" });
      toast(`${ticker} silindi`, "ok");
      await loadAll({ silent: true });
    }, "Silme");
  }

  if (t.id === "live-start") {
    if (state.live.timer) { stopLive(); renderLive(); return toast("Canlı takip durduruldu"); }
    const ticker = $("#live-ticker").value.trim();
    if (!ticker) return toast("Önce sembol gir", "err");
    return startLive(ticker, $("#live-interval").value, +$("#live-every").value);
  }

  const liveOne = t.closest("[data-live]");
  if (liveOne) return startLive(liveOne.dataset.live, state.live.interval, state.live.every);

  if (t.id === "add-symbol") {
    const ticker = $("#new-ticker").value.trim();
    if (!ticker) return toast("Önce sembol kodu gir", "err");
    return withBusy(async () => {
      await api("/symbols", { method: "POST", body: JSON.stringify({ ticker, interval: $("#new-interval").value }) });
      toast(`${ticker.toUpperCase()} eklendi`, "ok");
      await loadAll({ silent: true });
    }, "Ekleme");
  }

  const pitem = t.closest(".pitem");
  if (pitem) {
    const entry = window.__paletteGroups[+pitem.dataset.g][+pitem.dataset.i];
    closePalette();
    return entry.run();
  }
  if (t.id === "ov") return closePalette();
  if (t.id === "scan") return triggerScan();
  if (t.id === "theme") return toggleTheme();
  if (t.id === "auto") {
    state.auto = !state.auto;
    $("#auto").classList.toggle("on", state.auto);
    toast(state.auto ? "Otomatik yenileme açık (30 sn)" : "Otomatik yenileme kapalı");
  }
});

$("#q").addEventListener("focus", openPalette);
$("#pq").addEventListener("input", (e) => paintPalette(e.target.value));

document.addEventListener("keydown", (e) => {
  const paletteOpen = $("#ov").classList.contains("open");
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); return openPalette(); }
  if (e.key === "Escape") { closePalette(); $("#modal-ov").classList.remove("open"); return; }
  if (paletteOpen) {
    if (e.key === "ArrowDown") { e.preventDefault(); moveHighlight(1); }
    if (e.key === "ArrowUp") { e.preventDefault(); moveHighlight(-1); }
    if (e.key === "Enter") { e.preventDefault(); runHighlighted(); }
    return;
  }
  if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
  if (state.view === "signals" && (e.key === "j" || e.key === "k")) {
    const rows = visibleSignals();
    if (!rows.length) return;
    const idx = rows.findIndex((r) => r.id === state.selected);
    select(rows[Math.min(rows.length - 1, Math.max(0, idx + (e.key === "j" ? 1 : -1)))].id);
  }
  if (e.key === "r") loadAll({ silent: true });
});

window.addEventListener("hashchange", () => {
  const v = location.hash.replace("#/", "");
  if (["signals", "watchlist", "live", "news", "system"].includes(v) && v !== state.view) go(v);
});

/* ---------------------------------------------------------------------- baslat */

(async function init() {
  applyTheme(localStorage.getItem("theme")
    || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark"));
  $("#auto").classList.toggle("on", state.auto);

  const v = location.hash.replace("#/", "");
  state.view = ["signals", "watchlist", "live", "news", "system"].includes(v) ? v : "signals";
  $$(".nav[data-view]").forEach((b) => b.classList.toggle("act", b.dataset.view === state.view));

  await loadPatterns();
  await loadAll();
  if (!state.selected && state.signals.length) select(state.signals[0].id);

  setInterval(() => { if (state.auto && !state.busy && !$("#ov").classList.contains("open")) loadAll({ silent: true }); }, 30000);
})();
