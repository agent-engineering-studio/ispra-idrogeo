# Riuso per gli enti

La **Mappa dei dati su frane e pericolo** è una pagina pronta per il sito di
un Comune o di un altro ente. Si apre sul Comune e mostra cosa dicono i dati
ufficiali di ISPRA IdroGEO e quanto ci si può fidare di quei dati.

!!! warning "Non è un'allerta"
    La pagina non legge la pioggia e non dà allerte. L'allerta ufficiale è il
    [bollettino di criticità del Dipartimento della Protezione Civile](https://mappe.protezionecivile.gov.it/it/mappe-rischi/bollettino-di-criticita)
    e quello della Regione. La classe di predisposizione dice quanta parte del
    territorio è in pericolo secondo le mappe ufficiali, non se una frana sta
    per arrivare.

## Che cosa trova pronto l'ente

- Una pagina in italiano con Bootstrap Italia, servita senza CDN.
- La mappa del Comune: aree a pericolo frana della mappa PAI 2024, pericolo
  alluvione, frane censite e frane datate, confine comunale.
- Il pannello: classe di predisposizione a frana e alluvione, persone e beni
  esposti, frane per tipo, quanto fidarsi dei dati, fonti e licenze, stato del
  servizio IdroGEO, scarico dei dati.
- Un'immagine Docker e un comando per avviarla: `make app-up`.

## Come configurarla

| Variabile | Esempio |
|---|---|
| `IDROGEO_ENTE` | `Comune di Gioia del Colle` |
| `IDROGEO_COMUNE` | `72021` (codice ISTAT del Comune) |
| `IDROGEO_TILES` | l'indirizzo delle tessere di sfondo dell'ente, se ne ha |

## Incorporarla nel sito

```html
<iframe src="https://mappa.comune.example.it/?comune=72021"
        title="Mappa dei dati su frane e pericolo"
        width="100%" height="900" style="border:0" loading="lazy"></iframe>
```

## Che cosa resta all'ente

- **Non è un'allerta**: va detto anche nel testo della pagina che la ospita.
- **Citare la fonte**: i dati IFFI e gli eventi sono CC BY-SA 4.0 (chi
  ridistribuisce dati derivati li deve condividere con la stessa licenza); la
  mappa PAI frane 2024 e gli indicatori sono CC BY 4.0. La pagina riporta le
  citazioni.
- **Lo sfondo della mappa**: per impostazione è OpenStreetMap, che vede
  l'indirizzo IP di chi visita. L'ente può usare tessere proprie.
- **Dati personali**: la pagina non ne raccoglie e non usa cookie.
- **Accessibilità**: la pagina usa Bootstrap Italia e testi alternativi, ma
  non ha avuto una verifica WCAG 2.1 AA completa: la dichiarazione di
  accessibilità resta all'ente.
- **Pubblicazione**: HTTPS, proxy e limiti di traffico sono del server che la
  ospita. La porta è aperta solo su `127.0.0.1`.

## Intelligenza artificiale

Nessun testo della pagina è scritto da un modello. I numeri vengono dai dati
di IdroGEO tramite codice aperto, verificato su un benchmark pubblico di casi
noti.

## Catalogo di Developers Italia

Il repository ha un `publiccode.yml`, validato in CI. Oggi è software aperto
di terzi (il campo `codiceIPA` è vuoto); quando un ente lo adotta, può
entrare nel catalogo come software a riuso.
