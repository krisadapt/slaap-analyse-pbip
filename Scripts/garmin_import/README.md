# Garmin slaapdata import

Haalt Garmin-slaapdata én lifestyle-tags op via de Garmin Connect API en **upsert** ze
in twee master-CSV's in `../../Export/Garmin/`:

- `garmin_sleep_master.csv` — één rij per nacht (slaapfases, score, hartslag,
  HRV, ontwakingen, Body Battery, SpO₂-trend, ...); bestaande datums worden overschreven
- `garmin_tags_master.csv` — lifestyle-tags in lang formaat (één rij per gelogd
  gedrag per dag: alcohol, cafeïne, lezen in bed, CPAP, ...); per dag vervangen

De oude `garmin_sleep_<start>_<eind>.csv`-bestanden (per run) zijn archief — de masters
zijn op 2026-06-10 daaruit geseed en zijn sindsdien de enige bron voor de analyse
(`Scripts/slaapanalyse/merge_nachten.py` leest de slaap-master).

**Schema-beleid:** nieuwe kolommen verschijnen vanzelf in de master; oude rijen krijgen
daar een lege waarde en worden niet retroactief gevuld (kan wel via een her-ophaling met
`--start/--end`). Nieuwe (ook custom) gedragingen in Garmin zijn in de tags-master gewoon
nieuwe rijen — nooit een schemawijziging.

⚠️ **SpO₂-caveat:** de absolute saturatiewaarden van het toestel zijn niet betrouwbaar
(structureel te laag). De kolommen heten daarom `spo2_*_trend` — enkel bruikbaar als
trend tussen nachten, nooit als absolute/medische waarde.

Volledige documentatie en context: zie de notitie "Garmin slaapdata import" in het
Obsidian-project `CPAP analyse`.

## Setup

```
pip install -r requirements.txt
copy .env.example .env
```

Vul in `.env` je Garmin Connect e-mailadres en wachtwoord in.

## Runnen

Standaard ("knop-druk"): het script onthoudt de laatst opgehaalde dag in `last_export.json`,
vult bij elke run automatisch aan tot vandaag **en hervraagt altijd de laatste 7 dagen**
(instelbaar via `GARMIN_HERVRAAG_DAGEN`). Dat venster bestaat omdat de twee datastromen
verschillend gedrag hebben:

- **Horlogedata** (slaap, Body Battery, SpO₂): komt pas binnen na handmatige sync — soms
  dagen later — maar is daarna onveranderlijk. Nachten zonder data schuiven het hervatpunt
  niet op en worden opnieuw geprobeerd.
- **Telefoondata** (lifestyle-tags, voeding): staat direct in Garmin Connect maar kan tot
  ±7 dagen terug retroactief ingevuld worden. Het venster haalt die aanvullingen vanzelf op.

Een nacht mét slaapdata in de master wordt nooit overschreven door een lege her-ophaling.
Het script toont eerst de op te halen periode en vraagt een bevestiging.

```
python garmin_import.py                                  # vanaf laatste export tot vandaag
python garmin_import.py --days 90                        # negeert last_export.json: laatste 90 dagen
python garmin_import.py --start 2026-04-13 --end 2026-06-07
python garmin_import.py --geen-tags                      # zonder lifestyle-tags (helft minder API-calls)
```

Tussen de API-aanroepen zit een korte pauze (default 1,5s, instelbaar via
`GARMIN_REQUEST_DELAY` in `.env`) om Garmin's rate-limiting te respecteren.
Met tags zijn dat twee aanroepen per dag (slaap + tags).

Echte gaten (horloge niet gedragen) blokkeren het hervatpunt niet: zodra een latere
dag wél data heeft, springt het eroverheen. Door de upsert in de masters is
ontdubbeling in de analyse niet meer nodig.
