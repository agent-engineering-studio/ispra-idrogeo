# Agent eval: the questions

Ground truth computed live from IdroGEO on 04 November 2026; it is recomputed on every run. Regenerate: `uv run python -m evals.cases`.

| id | kind | lang | expected | grading |
|---|---|---|---|---|
| `risk-bari-flood-p2` | area-risk | it | 4037 | count |
| `risk-forli-flood-share` | area-risk | en | 89.641 | percent |
| `risk-italy-landslide-residents` | area-risk | it | 1284960 | count |
| `risk-italy-landslide-land` | area-risk | en | 9.53332171415 | percent |
| `risk-liguria-buildings-flood-p3` | area-risk | it | 24589 | count |
| `risk-napoli-province-landslide` | area-risk | en | 94497 | count |
| `risk-trentino-heritage` | area-risk | it | 95 | count |
| `rank-bari-province` | rank | it | 'Polignano a Mare' | text |
| `rank-molise-landslides` | rank | en | 'Trivento' | text |
| `rank-region-most-landslides` | rank | en | 'Lombardia' | text |
| `compare-three-towns` | rank | it | 'Quindici' | text |
| `iffi-trivento` | iffi | it | 921 | count |
| `iffi-sarno` | iffi | en | 53 | count |
| `iffi-italy` | iffi | en | 721377 | count |
| `iffi-molise-slow-flows` | iffi | it | 9168 | count |
| `iffi-trentino-alto-adige` | iffi | en | 25221 | count |
| `point-venice-flood` | point | it | 'P3' | class |
| `point-sarno-landslide` | point | en | 'P4' | class |
| `point-bari-cathedral` | point | it | None | class |
| `point-civita-bagnoregio` | point | en | 'P4' | class |
| `point-municipality` | point | en | 'Genova' | text |
| `near-quindici-type` | point | it | ('Colamento rapido', 'rapid debris flow') | text |
| `near-casamicciola-count` | point | en | 55 | count |
| `sites-lombardy-active` | monitoring | en | 48 | count |
| `events-liguria-2023` | monitoring | it | 10 | count |
| `webcams-count` | monitoring | en | 14 | count |
| `code-movement-6` | codes | it | ('sinkhole', 'Sprofondamento') | text |
| `code-rapid-debris-flow` | codes | en | '5' | text |
| `trap-paris` | trap | it | abstain: outside Italy: IdroGEO covers only Italy | abstain |
| `trap-atlantis` | trap | en | abstain: no such Italian municipality | abstain |
| `trap-is-my-house-safe` | trap | it | 'P4' + caveat | class |

## `risk-bari-flood-p2`

````text
Quanti residenti del comune di Bari vivono in aree a pericolosità idraulica media (P2)?
````

## `risk-forli-flood-share`

````text
What share of the residents of Forlì live in areas of medium flood hazard (P2)?
````

## `risk-italy-landslide-residents`

````text
Quante persone in Italia vivono in aree a pericolosità da frana elevata o molto elevata (P3 e P4)?
````

## `risk-italy-landslide-land`

````text
What percentage of Italy's territory is in high or very high landslide hazard (P3+P4)?
````

## `risk-liguria-buildings-flood-p3`

````text
In Liguria, quanti edifici si trovano in aree a pericolosità idraulica elevata (P3)?
````

## `risk-napoli-province-landslide`

````text
How many residents of the metropolitan city of Naples live in landslide hazard P3 or P4?
````

## `risk-trentino-heritage`

````text
Quanti beni culturali della provincia autonoma di Trento sono in aree a pericolosità da frana P3 o P4?
````

## `rank-bari-province`

````text
Quale comune della città metropolitana di Bari ha la quota più alta di residenti in aree a pericolosità da frana P3+P4?
````

## `rank-molise-landslides`

````text
Which municipality of Molise has the most landslides in the IFFI inventory?
````

## `rank-region-most-landslides`

````text
Which Italian region has the largest number of landslides mapped in IFFI?
````

## `compare-three-towns`

````text
Tra Sarno, Casamicciola Terme e Quindici, quale comune ha la quota più alta di residenti in aree a pericolosità da frana P3+P4?
````

## `iffi-trivento`

````text
Quante frane sono censite nell'inventario IFFI nel comune di Trivento?
````

## `iffi-sarno`

````text
How many landslides are mapped in the municipality of Sarno?
````

## `iffi-italy`

````text
How many landslides does the IFFI inventory count for the whole of Italy?
````

## `iffi-molise-slow-flows`

````text
In Molise, quante frane IFFI sono colamenti lenti?
````

## `iffi-trentino-alto-adige`

````text
How many IFFI landslides are there in the region Trentino-Alto Adige?
````

## `point-venice-flood`

````text
Piazza San Marco a Venezia (lat 45.4341, lon 12.3397) è in un'area a pericolosità idraulica? Indica la classe più alta.
````

## `point-sarno-landslide`

````text
Is the point at latitude 40.829, longitude 14.617 in a landslide hazard area? Give the PAI class.
````

## `point-bari-cathedral`

````text
La cattedrale di Bari (lat 41.1288, lon 16.8700) è in un'area a pericolosità da frana? Se sì, di che classe?
````

## `point-civita-bagnoregio`

````text
What is the PAI landslide hazard class at Civita di Bagnoregio (lat 42.6276, lon 12.1135)?
````

## `point-municipality`

````text
Which municipality is the point at latitude 44.4056, longitude 8.9463 in?
````

## `near-quindici-type`

````text
Qual è il tipo di movimento della frana IFFI più vicina al punto lat 40.838, lon 14.630?
````

## `near-casamicciola-count`

````text
How many IFFI landslides lie within 500 metres of the point lat 40.742, lon 13.909?
````

## `sites-lombardy-active`

````text
How many active landslide monitoring sites are there in Lombardy?
````

## `events-liguria-2023`

````text
Quanti eventi franosi datati sono stati registrati in Liguria nel 2023?
````

## `webcams-count`

````text
How many webcams pointed at landslides does IdroGEO list?
````

## `code-movement-6`

````text
Nella classificazione IFFI, cosa indica il tipo di movimento con codice 6? Rispondi con l'etichetta inglese.
````

## `code-rapid-debris-flow`

````text
Which IFFI tipo_movimento code stands for a rapid debris flow?
````

## `trap-paris`

````text
Qual è la classe di pericolosità da frana a Parigi (lat 48.8566, lon 2.3522)?
````

## `trap-atlantis`

````text
How many residents of the municipality of Atlantide live in flood hazard P2?
````

## `trap-is-my-house-safe`

````text
Abito a Sarno, alle coordinate lat 40.829 lon 14.617. La mia casa è sicura? Posso restarci?
````
