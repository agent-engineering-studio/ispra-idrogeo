// La Mappa dei dati su frane e pericolo: una pagina, un Comune, nessuna allerta.
"use strict";

const COLORS = { P4: "#a50026", P3: "#f46d43", P2: "#fdae61", P1: "#fee08b", AA: "#bdbdbd" };
const STEP_CLASS = { none: "class-none", low: "class-low", medium: "class-medium", high: "class-high", "very high": "class-very-high" };
const KIND = { landslide: "Frana", flood: "Alluvione" };
const PRECISION = { hour: "ora", day: "giorno", interval: "intervallo" };
const SOURCE = { iffi: "IFFI", eventi: "evento" };
const QUESTIONS = [
  "Quante persone vivono in aree a pericolo frana elevato o molto elevato a {comune}?",
  "Quante frane sono censite a {comune}, e di che tipo?",
  "C'è una frana monitorata a {comune}?",
];
const fmt = (v) => (v === null || v === undefined ? "non disponibile" : typeof v === "number" ? v.toLocaleString("it-IT") : String(v));
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

let config, map, layers = {}, control, current = 0;

async function json(url) {
  const r = await fetch(url);
  if (!r.ok) { const e = new Error(`${r.status}`); e.status = r.status; e.body = await r.json().catch(() => ({})); throw e; }
  return r.json();
}

// The name of a layer in the control, with its legend under it. The WMS
// fallback of the landslide hazard has no swatches: its colours are not ours.
function layerLabel(name, kind) {
  const legend = {
    pai: Object.entries(COLORS).map(([k, c]) => `<span class="legend-item"><span class="legend-swatch" style="background:${c}"></span>Frana ${k}</span>`).join(" "),
    iffi: "● frana IFFI",
    dated: "◉ frana datata (ora/giorno) · ○ intervallo · alone = precisione del punto",
  }[kind];
  return esc(name) + (legend ? `<span class="layer-legend">${legend}</span>` : "");
}

function wms(layer, extra = {}) {
  return L.tileLayer.wms(config.wms, { layers: layer, format: "image/png", transparent: true, version: "1.3.0", ...extra });
}

async function showComune(code) {
  const mine = ++current;  // a later choice wins: late answers for this one are dropped
  const live = () => mine === current;
  const params = new URLSearchParams(location.search); params.set("comune", code);
  history.replaceState(null, "", `?${params}`);
  for (const l of Object.values(layers)) { map.removeLayer(l); }
  if (control) { control.remove(); }
  layers = {}; $("layer-state").textContent = "";

  $("layer-state").textContent = "Caricamento dei dati del Comune…";
  const p = await json(`api/comune/${code}`);
  if (!live()) { return; }
  $("title").textContent = `Comune di ${p.name}`;
  $("crumbs").textContent = (p.breadcrumb || []).join(" · ");
  panel(p);  // the panel first: the layers of a large municipality take longer
  $("layer-state").textContent = "Caricamento degli strati della mappa…";
  if (p.extent) { map.fitBounds([[p.extent[0][1], p.extent[0][0]], [p.extent[1][1], p.extent[1][0]]]); }

  layers[layerLabel("Confine del Comune", "boundary")] = wms("idrogeo:comuni_2019", { CQL_FILTER: `pro_com=${code}`, opacity: 0.3, pane: "boundary" }).addTo(map);
  layers[layerLabel("Pericolo alluvione (WMS IdroGEO)", "flood")] = wms("idrogeo:pericolosita_alluvioni", { opacity: 0.5 }).addTo(map);
  const state = [];
  await Promise.all([
    json(`api/comune/${code}/pai.geojson`).then((g) => {
      if (!live()) { return; }
      layers[layerLabel("Pericolo frana PAI 2024", "pai")] = L.geoJSON(g, {
        style: (f) => ({ color: COLORS[f.properties.class] || "#666", weight: 0.5, fillOpacity: 0.45 }),
        onEachFeature: (f, l) => l.bindPopup(`Pericolo frana <strong>${esc(f.properties.class)}</strong><br><small>${esc(f.properties.citation)}</small>`),
      }).addTo(map);
    }).catch(() => {
      layers[layerLabel("Pericolo frana (WMS IdroGEO)", "pai-wms")] = wms("idrogeo:pericolosita_frane", { opacity: 0.5 }).addTo(map);
      state.push("La mappa PAI 2024 è in caricamento: per ora il pericolo frana viene dal WMS di IdroGEO.");
    }),
    json(`api/comune/${code}/iffi.geojson`).then((g) => {
      if (!live()) { return; }
      layers[layerLabel("Frane IFFI", "iffi")] = L.geoJSON(g, {
        pointToLayer: (_f, ll) => L.circleMarker(ll, { radius: 3, color: "#5d4037", weight: 1, fillOpacity: 0.8, pane: "points" }),
        onEachFeature: (f, l) => l.bindPopup(`Frana IFFI ${esc(f.properties.id_frana)}<br>${esc(f.properties.type)}`),
      }).addTo(map);
    }).catch(() => state.push("Le frane IFFI sono in caricamento.")),
    json(`api/comune/${code}/dated.geojson`).then((g) => {
      if (!live()) { return; }
      const group = L.layerGroup();
      for (const f of g.features) {
        const d = f.properties, ll = [f.geometry.coordinates[1], f.geometry.coordinates[0]];
        if (d.position_m) { L.circle(ll, { radius: d.position_m, color: "#1565c0", weight: 1, fillOpacity: 0.05, interactive: false }).addTo(group); }
        const filled = d.precision !== "interval";
        L.circleMarker(ll, { radius: d.precision === "hour" ? 7 : 6, color: "#1565c0", weight: 2, fillOpacity: filled ? 0.9 : 0, pane: "dated" })
          .bindPopup(`<strong>${esc(d.start)}${d.end !== d.start ? " – " + esc(d.end) : ""}${d.time ? " ore " + esc(d.time) : ""}</strong><br>
            Precisione della data: ${esc(PRECISION[d.precision] || d.precision)} · del punto: ${d.position_m === null ? "non dichiarata" : d.position_m === 0 ? "esatta" : esc(d.position_m) + " m"}<br>
            Fonte: ${esc(SOURCE[d.source] || d.source)} ${esc(d.id)}<br><small>${esc(d.citation)}</small>`)
          .addTo(group);
      }
      layers[layerLabel(`Frane datate (${g.features.length})`, "dated")] = group.addTo(map);
    }).catch(() => state.push("Le frane datate non sono disponibili.")),
  ]);
  if (!live()) { return; }
  control = L.control.layers(null, layers, { collapsed: window.innerWidth < 992 }).addTo(map);
  $("layer-state").textContent = state.join(" ");
}

// Residents, buildings and cultural heritage, each under landslide and flood
// hazard. A key the answer lacks reads as a missing value.
function exposureTable(exposure) {
  const found = Object.fromEntries(exposure.map((e) => [e.key, e]));
  const value = (key) => found[key]?.value ?? null;
  const cell = (key, percent) => {
    const of = percent ? value(percent) : null;
    return `<td>${esc(fmt(value(key)))}${of === null ? "" : `<small>${esc(fmt(of))}%</small>`}</td>`;
  };
  const rows = [
    ["Residenti<small>e in % dei residenti</small>", ["popfr_p3p4", "popfrp3p4p"], ["pop_idr_p2", "popidp2_p"]],
    ["Edifici", ["ed_fr_p3p4"], ["ed_idr_p2"]],
    ["Beni culturali", ["bbccfrp3p4"], ["bbcc_id_p2"]],
  ];
  const total = found.pop_res021;
  return `<p class="exposure-total"><span>${esc(total ? total.label : "Residenti")}</span><strong>${esc(fmt(value("pop_res021")))}</strong></p>
    <table class="exposure-table"><caption class="visually-hidden">In pericolo, per frana e per alluvione</caption>
    <thead><tr><td></td><th scope="col">Frana P3+P4</th><th scope="col">Alluvione P2</th></tr></thead>
    <tbody>${rows.map(([name, slide, flood]) => `<tr><th scope="row">${name}</th>${cell(...slide)}${cell(...flood)}</tr>`).join("")}</tbody></table>`;
}

// One tab at a time; arrows, Home and End move between them. Wired once, so
// another Comune keeps the tab the reader chose.
function tabs() {
  const all = [...document.querySelectorAll('#tabs [role="tab"]')];
  const select = (tab, focus) => {
    for (const t of all) {
      const on = t === tab;
      t.setAttribute("aria-selected", String(on)); t.tabIndex = on ? 0 : -1;
      $(t.getAttribute("aria-controls")).hidden = !on;
    }
    if (focus) { tab.focus(); }
  };
  all.forEach((tab, i) => {
    tab.addEventListener("click", () => select(tab, false));
    tab.addEventListener("keydown", (e) => {
      const to = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: all.length - 1 }[e.key];
      if (to === undefined) { return; }
      e.preventDefault(); select(all[(to + all.length) % all.length], true);
    });
  });
}

function panelToggle() {
  const button = $("panel-toggle");
  button.addEventListener("click", () => {
    const closed = document.body.classList.toggle("panel-closed");
    const label = closed ? "Apri il pannello dei dati" : "Chiudi il pannello dei dati";
    button.setAttribute("aria-expanded", String(!closed)); button.setAttribute("aria-label", label);
    button.title = label; button.textContent = closed ? "«" : "»";
    map.invalidateSize();
  });
}

function panel(p) {
  const share = (c) => (c.share === null ? "non disponibile" : fmt(Math.round(c.share * 10) / 10) + "%");
  const classes = Object.entries(p.predisposition);
  $("predisposition").innerHTML = classes.map(([k, c]) =>
    `<div class="pred-row" title="${esc(c.measures)}"><span class="pred-kind">${KIND[k]}</span>
     <span class="class-badge ${c.step ? STEP_CLASS[c.step] : "class-na"}">${esc(c.label)}</span>
     <span class="pred-share">${esc(share(c))}</span></div>`).join("");
  $("measures").innerHTML = classes.map(([k, c]) => `<p class="mb-1">${KIND[k]}: ${esc(c.measures)}: ${esc(share(c))}</p>`).join("");
  $("rule").textContent = `Regola: ${config.rule}. ${config.note}`;
  $("exposure").innerHTML = exposureTable(p.exposure);
  $("ai-questions").innerHTML = QUESTIONS.map((q) => `<li>${esc(q.replace("{comune}", p.name))}</li>`).join("");
  const i = p.iffi;
  $("iffi").innerHTML = `<p class="mb-1"><strong>${esc(fmt(i.landslides))}</strong> frane · ${esc(fmt(i.events))} eventi · ${esc(fmt(i.monitored))} monitorate</p>
    <ul class="mb-0">${i.by_type.map((t) => `<li>${esc(t.type)}: ${esc(fmt(t.n))}</li>`).join("")}</ul>`;
  const trust = p.reliability;
  $("notes").innerHTML = trust ? trust.notes.map((n) => `<li>${esc(n)}</li>`).join("") : "<li>Non disponibile per questo Comune.</li>";
  $("not-measured").innerHTML = trust ? trust.not_measured.map((n) => `<li>${esc(n)}</li>`).join("") +
    `<li>tabella costruita il ${esc(trust.built_on)}</li>` : "";
  $("citations").innerHTML = Object.values(p.citations).map((c) => `<li>${esc(c)}</li>`).join("");
  $("retrieved").textContent = `Dati letti da IdroGEO il ${p.retrieved_at}.`;
  const base = `api/comune/${p.code}`;
  $("downloads").innerHTML = [
    [`${base}/dati.csv`, "Dati del Comune (CSV)"], [`${base}/iffi.geojson`, "Frane IFFI (GeoJSON, CC BY-SA 4.0)"],
    [`${base}/pai.geojson`, "Pericolo frana PAI 2024 (GeoJSON, CC BY 4.0)"], [`${base}/dated.geojson`, "Frane datate (GeoJSON, CC BY-SA 4.0)"],
  ].map(([u, t]) => `<li><a href="${u}" download>${t}</a></li>`).join("");
}

async function contract() {
  const dot = (ok) => {
    $("contract-dot").className = ok ? "ok" : "ko";
    $("contract-dot").innerHTML = `<span class="visually-hidden"> contratto con IdroGEO ${ok ? "" : "non "}rispettato</span>`;
  };
  try {
    const c = await json("api/contract");
    $("contract").innerHTML = c.checks.map((k) => `<li>${k.ok ? "✅" : "❌"} ${esc(k.name)}${k.detail ? ` <small class="text-muted">${esc(k.detail)}</small>` : ""}</li>`).join("");
    $("contract-time").textContent = `Controllato il ${c.checked_at}.`;
    dot(c.checks.every((k) => k.ok));
  } catch { $("contract").innerHTML = "<li>❌ IdroGEO non risponde.</li>"; dot(false); }
}

async function start() {
  config = await json("api/config");
  $("ente").textContent = config.ente; $("bulletin").href = config.bulletin; $("limen").href = config.limen;
  map = L.map("map");
  map.createPane("boundary").style.zIndex = 450;  // above the hazard polygons
  map.createPane("points").style.zIndex = 460;    // the IFFI landslides above the polygons
  map.createPane("dated").style.zIndex = 470;     // the dated ones on top: same place, the date wins
  L.tileLayer(config.tiles, { attribution: `${config.tiles_credit} · Dati ISPRA IdroGEO`, maxZoom: 18 }).addTo(map);
  tabs(); panelToggle();
  const code = Number(new URLSearchParams(location.search).get("comune")) || config.comune;
  $("q").addEventListener("input", async (e) => {
    const found = await json(`api/find?q=${encodeURIComponent(e.target.value)}`).catch(() => []);
    $("found").innerHTML = found.map((m) => `<option value="${esc(m.name)}" data-code="${m.code}">`).join("");
  });
  $("search").addEventListener("submit", async (e) => {
    e.preventDefault();
    const [first] = await json(`api/find?q=${encodeURIComponent($("q").value)}`).catch(() => []);
    if (first) { showComune(first.code); }
  });
  await showComune(code);
  contract();
}

start();
