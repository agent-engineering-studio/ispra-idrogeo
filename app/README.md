# La Mappa dei dati su frane e pericolo

Una pagina per un ente: per un Comune, cosa dicono i dati ufficiali di ISPRA
IdroGEO su frane e pericolo idrogeologico, e quanto ci si può fidare di quei
dati.

> **Questa pagina non è un'allerta.** Non legge la pioggia. L'allerta
> ufficiale è il bollettino di criticità del Dipartimento della Protezione
> Civile e quello della Regione. Il quadro che unisce pioggia, soglie, frane e
> pericolo è il lavoro di [Limen](https://github.com/agent-engineering-studio/limen).

## Avviarla

Con Docker, dalla radice del repository:

```bash
make app-up                                   # http://localhost:3002
IDROGEO_COMUNE=72006 IDROGEO_ENTE="Comune di Bari" make app-up
```

Senza Docker, con [uv](https://docs.astral.sh/uv/):

```bash
make app        # scarica Bootstrap Italia e Leaflet in static/vendor e avvia su http://127.0.0.1:3002
```

Al primo avvio la pagina scarica e carica in un database locale (DuckDB) le
frane IFFI (38 MB) e la mappa PAI frane 2024 (790 MB): circa due minuti, poi
restano su un volume e si aggiornano solo se ISPRA le cambia. Nel frattempo
il pericolo frana viene dal servizio WMS di IdroGEO.

| Variabile | Che cosa fa | Senza |
|---|---|---|
| `IDROGEO_ENTE` | il nome dell'ente in testata | «Mappa dei dati su frane e pericolo» |
| `IDROGEO_COMUNE` | il Comune su cui si apre la mappa (codice ISTAT) | 65135, Sarno |
| `IDROGEO_TILES`, `IDROGEO_TILES_CREDIT` | lo sfondo della mappa e la sua attribuzione | OpenStreetMap |
| `IDROGEO_APP_PORT` | la porta con Docker | 3002 |

Nell'indirizzo, `?comune=<ISTAT>` apre un altro Comune. La porta è aperta solo
su `127.0.0.1`: per pubblicarla, mettetela dietro il proxy del vostro sito.

## Che cosa mostra

**Sulla mappa** (gli stessi dati che usa Limen):

- le aree a **pericolo frana della mappa PAI 2024** (P4 … AA);
- il **pericolo alluvione** (P3, P2, P1), dal servizio WMS di IdroGEO;
- le **frane censite IFFI**;
- le **frane datate**: il simbolo cambia con la precisione della data (ora,
  giorno, intervallo) e un alone mostra la precisione del punto, dove la fonte
  la dichiara;
- il **confine del Comune**.

**Nel pannello:**

- la **classe di predisposizione** a frana e ad alluvione: la quota di
  territorio in pericolo P3+P4 (frana) e nello scenario P2 (alluvione), in
  cinque classi fisse (nessuna 0%, bassa <5%, media 5–15%, alta 15–30%,
  molto alta ≥30%). Non usa la pioggia: non dice se una frana sta per
  arrivare;
- le **persone e i beni esposti**: residenti, edifici e beni culturali;
- le **frane IFFI** per tipo, gli eventi e le frane monitorate;
- **quanto fidarsi dei dati** in quel Comune (quante frane hanno una data,
  quanto è aggiornato l'inventario) e **cosa non è misurato**;
- lo **stato del contratto con IdroGEO**: ogni ora la pagina controlla che le
  chiamate che usa rispondano ancora come previsto;
- lo **scarico** dei dati in CSV e GeoJSON, con la citazione;
- **fonte, licenza e data** di ogni dato.

## L'API

| Indirizzo | Che cosa risponde |
|---|---|
| `GET /api/config` | ente, Comune iniziale, sfondo, la regola delle classi, i link al bollettino e a Limen |
| `GET /api/find?q=` | i Comuni per nome |
| `GET /api/comune/{istat}` | il pannello: classi, esposti, IFFI, quanto fidarsi, fonti |
| `GET /api/comune/{istat}/pai.geojson` | i poligoni PAI 2024 che toccano il Comune (CC BY 4.0) |
| `GET /api/comune/{istat}/iffi.geojson` | le frane IFFI del Comune (CC BY-SA 4.0) |
| `GET /api/comune/{istat}/dated.geojson` | le frane datate del Comune (CC BY-SA 4.0) |
| `GET /api/comune/{istat}/dati.csv` | i numeri del pannello in CSV |
| `GET /api/contract` | lo stato del contratto con IdroGEO |
| `GET /api/health` | lo stato della pagina e del caricamento dei dati |

## Dati

ISPRA — IdroGEO. IFFI ed eventi: CC BY-SA 4.0, citazione per Regione. Mappa
PAI frane 2024 e indicatori di rischio: CC BY 4.0. Bootstrap Italia e Leaflet
sono serviti dalla pagina stessa, senza CDN: l'unica chiamata a terzi dal
browser sono lo sfondo della mappa e il servizio WMS di IdroGEO.
