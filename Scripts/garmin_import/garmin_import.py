"""Haalt Garmin-slaapdata en lifestyle-tags op via de Garmin Connect API en
upsert ze in twee master-CSV's.

Gebruik:
    python garmin_import.py                 # knop-druk: vult aan + hervraagt de laatste 7 dagen
    python garmin_import.py --days 90       # geen last_export.json: laatste 90 dagen
    python garmin_import.py --start 2026-04-13 --end 2026-06-07   # expliciete periode (geen venster)
    python garmin_import.py --geen-tags     # sla de lifestyle-tags over (halveert het aantal API-calls)

Output (in de output-map):
    garmin_sleep_master.csv  - één rij per nacht; bestaande datums worden overschreven (upsert)
    garmin_tags_master.csv   - lifestyle-tags in lang formaat (één rij per gelogd gedrag per
                               dag); per dag worden de rijen vervangen zodra er nieuwe tags zijn

Sync-model (waarom het 7-daags hervraagvenster bestaat):
    - HORLOGEDATA (slaap, Body Battery, SpO₂, hartslag): wordt handmatig gesynct en komt
      dus mogelijk dagen later binnen, maar is daarna onveranderlijk. Dagen zonder
      slaapdata schuiven het hervatpunt (last_export.json) niet op en worden bij de
      volgende run opnieuw geprobeerd.
    - TELEFOONDATA (lifestyle-tags, voeding): staat direct in Garmin Connect, maar kan
      tot ±7 dagen terug retroactief ingevuld of aangepast worden. Daarom hervraagt het
      script in knop-druk-modus ALTIJD de laatste 7 dagen en overschrijft het die in de
      masters — retroactieve aanvullingen komen zo vanzelf goed.
    Een dag in de master mét slaapdata wordt nooit overschreven door een lege her-ophaling.

Schema-evolutie (afgesproken beleid):
    Nieuwe velden/kolommen verschijnen vanzelf in de master zodra het script ze aanlevert;
    bestaande rijen krijgen daarvoor een lege waarde en worden NIET retroactief gevuld
    (kan desgewenst wel, door de betreffende periode opnieuw op te halen met --start/--end).
    Nieuwe gedragingen (ook eigen/custom velden in Garmin) zijn in de tags-master gewoon
    nieuwe rijen — lang formaat, dus nooit een schemawijziging.

⚠️ SpO₂-caveat: de absolute zuurstofsaturatiewaarden van dit Garmin-toestel zijn
niet betrouwbaar (structureel te laag). De kolommen heten daarom bewust
spo2_*_trend: gebruik ze enkel als TREND-indicator (vergelijking tussen nachten),
nooit als absolute meting of medische waarde.

ℹ️ Datum-semantiek:
    - Slaaprij met datum D = de nacht die eindigt op de ochtend van dag D.
    - Lifestyle-tags met datum D = gelogd voor kalenderdag D. Voor dag-gedragingen
      (alcohol, cafeïne, late maaltijden) beïnvloedt dag D dus de slaaprij D+1;
      slaapgerelateerde tags (CPAP, lezen in bed, ...) horen vermoedelijk bij de
      nacht die eindigt op ochtend D (= slaaprij D). Nog te verifiëren met enkele
      dagen logging — tot dan bewust ruw (ongeshift) geëxporteerd.

Configuratie via .env (zie .env.example):
    GARMIN_EMAIL, GARMIN_PASSWORD   - Garmin Connect login
    GARMIN_OUTPUT_DIR               - (optioneel) doelmap voor de CSV-output
    GARMIN_TOKEN_DIR                - (optioneel) map waar de sessie/login-tokens gecached worden
    GARMIN_REQUEST_DELAY            - (optioneel) pauze in seconden tussen API-aanroepen (default 1.5)
    GARMIN_HERVRAAG_DAGEN           - (optioneel) grootte van het hervraagvenster (default 7)
"""

import argparse
import json
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from garminconnect import Garmin

SCRIPT_DIR = Path(__file__).resolve().parent
load_dotenv(SCRIPT_DIR / ".env")

# Standaardlocaties zijn relatief aan dit script (Scripts/garmin_import -> 18 CPAP Analyse/...).
# Via .env overschrijfbaar zodat de map probleemloos verplaatst kan worden.
DEFAULT_OUTPUT_DIR = SCRIPT_DIR.parent.parent / "Export" / "Garmin"
DEFAULT_TOKEN_DIR = SCRIPT_DIR / ".garmin_tokens"
STATE_FILE = SCRIPT_DIR / "last_export.json"

OUTPUT_DIR = Path(os.environ.get("GARMIN_OUTPUT_DIR", DEFAULT_OUTPUT_DIR))
TOKEN_DIR = Path(os.environ.get("GARMIN_TOKEN_DIR", DEFAULT_TOKEN_DIR))
DEFAULT_DAYS_BACK = int(os.environ.get("GARMIN_DAYS_BACK", "30"))
REQUEST_DELAY = float(os.environ.get("GARMIN_REQUEST_DELAY", "1.5"))
# Telefoondata (tags/voeding) is tot ±7 dagen terug muteerbaar — zie docstring.
HERVRAAG_DAGEN = int(os.environ.get("GARMIN_HERVRAAG_DAGEN", "7"))

SLEEP_MASTER = OUTPUT_DIR / "garmin_sleep_master.csv"
TAGS_MASTER = OUTPUT_DIR / "garmin_tags_master.csv"


def parse_args():
    parser = argparse.ArgumentParser(description="Garmin-slaapdata importeren naar master-CSV's")
    parser.add_argument("--start", type=str, help="Startdatum (YYYY-MM-DD) - negeert last_export.json én het hervraagvenster")
    parser.add_argument("--end", type=str, help="Einddatum (YYYY-MM-DD), default vandaag")
    parser.add_argument(
        "--days", type=int, default=DEFAULT_DAYS_BACK,
        help=(
            "Aantal dagen terug vanaf --end, gebruikt als er geen --start is opgegeven "
            f"EN er nog geen last_export.json bestaat (default {DEFAULT_DAYS_BACK})"
        ),
    )
    parser.add_argument(
        "--yes", "-y", action="store_true",
        help="Sla de [J/n]-bevestiging over (handig voor lange historische ophalingen of geautomatiseerde runs)",
    )
    parser.add_argument(
        "--geen-tags", action="store_true",
        help=(
            "Haal geen lifestyle-tags op (scheelt één API-call per dag; nuttig voor lange "
            "historische runs over periodes waarin nog niet gelogd werd)"
        ),
    )
    return parser.parse_args()


def load_last_export_date() -> date | None:
    if not STATE_FILE.exists():
        return None
    try:
        # utf-8-sig: leest ook correct als het bestand met een UTF-8 BOM is weggeschreven
        # (bv. door PowerShell Set-Content of Kladblok op Windows).
        data = json.loads(STATE_FILE.read_text(encoding="utf-8-sig"))
        return datetime.strptime(data["last_exported_date"], "%Y-%m-%d").date()
    except (json.JSONDecodeError, KeyError, ValueError):
        return None


def save_last_export_date(day: date) -> None:
    STATE_FILE.write_text(
        json.dumps({"last_exported_date": day.isoformat()}, indent=2),
        encoding="utf-8",
    )


def resolve_date_range(args) -> tuple[date, date]:
    end = datetime.strptime(args.end, "%Y-%m-%d").date() if args.end else date.today()

    if args.start:
        return datetime.strptime(args.start, "%Y-%m-%d").date(), end

    last_export = load_last_export_date()
    if last_export is not None:
        print(f"Laatste export ({STATE_FILE.name}): {last_export.isoformat()}")
        start = last_export + timedelta(days=1)
        # Hervraagvenster: telefoondata (tags) is tot HERVRAAG_DAGEN terug muteerbaar,
        # dus die periode wordt altijd opnieuw opgehaald en in de masters overschreven.
        window_start = end - timedelta(days=HERVRAAG_DAGEN - 1)
        if window_start < start:
            print(f"Hervraagvenster: laatste {HERVRAAG_DAGEN} dagen worden opnieuw opgehaald (retroactieve tags/sync).")
            start = window_start
    else:
        start = end - timedelta(days=args.days)

    return start, end


def confirm_range(start: date, end: date, skip_prompt: bool = False) -> bool:
    days = (end - start).days + 1
    if days <= 0:
        print(f"Niets op te halen: alles tot en met {end.isoformat()} is al geëxporteerd.")
        return False

    print(f"Op te halen: {start.isoformat()} t/m {end.isoformat()} ({days} dag{'en' if days != 1 else ''})")
    if skip_prompt:
        return True

    answer = input("Doorgaan? [J/n] ").strip().lower()
    return answer in ("", "j", "ja", "y", "yes")


def login() -> Garmin:
    email = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")
    if not email or not password:
        raise SystemExit("GARMIN_EMAIL en/of GARMIN_PASSWORD ontbreken. Vul .env aan (zie .env.example).")

    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    client = Garmin(email=email, password=password, prompt_mfa=lambda: input("Garmin MFA-code: "))
    # client.login(tokenstore) laadt gecachete tokens indien aanwezig/geldig, valt anders
    # terug op een nieuwe login met email/password, en cachet de (vernieuwde) tokens nadien.
    client.login(str(TOKEN_DIR))
    return client


def extract_sleep_row(day: date, raw: dict) -> dict:
    """Plat de relevante velden uit de ruwe Garmin-sleepdata-respons voor één dag."""
    dto = raw.get("dailySleepDTO") or {}
    scores = dto.get("sleepScores") or {}
    overall = scores.get("overall") or {}

    def to_hours(seconds):
        return round(seconds / 3600, 2) if seconds is not None else None

    def to_local_datetime(epoch_millis):
        # *Local timestamps van Garmin staan zelf al in lokale tijd, maar als epoch UTC-millis;
        # fromtimestamp(..., tz=timezone.utc) + strippen van tz geeft de juiste lokale "wandklok"-tijd.
        if epoch_millis is None:
            return None
        return (
            datetime.fromtimestamp(epoch_millis / 1000, tz=timezone.utc)
            .replace(tzinfo=None)
            .strftime("%Y-%m-%d %H:%M")
        )

    # Body Battery tijdens de slaap: lijst van {value, startGMT} per ~3 minuten.
    # Start/einde/laagste/hoogste samen tonen het herstel tijdens de nacht;
    # bodyBatteryChange is Garmins eigen netto-verandering over de slaapsessie.
    bb_values = [
        entry.get("value")
        for entry in (raw.get("sleepBodyBattery") or [])
        if entry.get("value") is not None
    ]

    return {
        "datum": day.isoformat(),
        "slaap_start": to_local_datetime(dto.get("sleepStartTimestampLocal")),
        "slaap_einde": to_local_datetime(dto.get("sleepEndTimestampLocal")),
        "totale_slaap_uur": to_hours(dto.get("sleepTimeSeconds")),
        "diepe_slaap_uur": to_hours(dto.get("deepSleepSeconds")),
        "lichte_slaap_uur": to_hours(dto.get("lightSleepSeconds")),
        "rem_slaap_uur": to_hours(dto.get("remSleepSeconds")),
        "wakker_uur": to_hours(dto.get("awakeSleepSeconds")),
        "slaapscore": overall.get("value"),
        "slaapscore_kwalificatie": overall.get("qualifierKey"),
        "gemiddelde_ademhaling": dto.get("averageRespirationValue"),
        "gemiddelde_hartslag_in_slaap": raw.get("restingHeartRate"),
        "gemiddelde_hrv": raw.get("avgOvernightHrv"),
        "aantal_ontwakingen": dto.get("awakeCount"),
        "onrustige_momenten": raw.get("restlessMomentsCount"),
        "gem_slaapstress": dto.get("avgSleepStress"),
        "bb_start": bb_values[0] if bb_values else None,
        "bb_einde": bb_values[-1] if bb_values else None,
        "bb_laagste": min(bb_values) if bb_values else None,
        "bb_hoogste": max(bb_values) if bb_values else None,
        "bb_verandering": raw.get("bodyBatteryChange"),
        # ⚠️ Enkel als trend gebruiken — absolute waarden van dit toestel zijn te laag (zie docstring).
        "spo2_gem_trend": dto.get("averageSpO2Value"),
        "spo2_laagste_trend": dto.get("lowestSpO2Value"),
        "spo2_hoogste_trend": dto.get("highestSpO2Value"),
    }


def extract_tag_rows(day: date, raw: dict) -> list[dict]:
    """Plat de lifestyle-tags (gedragingen) voor één dag naar lang formaat.

    Garmin geeft per dag het volledige gevolgde gedragsprofiel terug; alleen op
    dagen waarop effectief gelogd is bevatten de entries een logStatus (YES/NO).
    Dagen zonder logging leveren dus geen rijen op. Bij QUANTITY-gedragingen
    (alcohol, cafeïne) komt er één rij per gelogd subtype met de hoeveelheid.
    """
    rows = []
    for entry in raw.get("dailyLogsReport") or []:
        status = entry.get("logStatus")
        if status is None:
            continue  # die dag is dit gedrag (nog) niet gelogd

        base = {
            "datum": day.isoformat(),
            "categorie": entry.get("category"),
            "gedrag": entry.get("name"),
            "gedrag_id": entry.get("behaviourId"),
            "status": status,
            "slaap_gerelateerd": entry.get("sleepRelated"),
        }
        details = entry.get("details") or []
        if status == "YES" and entry.get("measurementType") == "QUANTITY" and details:
            for detail in details:
                rows.append({**base, "subtype": detail.get("subTypeName"), "aantal": detail.get("amount")})
        else:
            rows.append({**base, "subtype": None, "aantal": None})
    return rows


def fetch_data(client: Garmin, start: date, end: date, include_tags: bool) -> tuple[pd.DataFrame, pd.DataFrame, date | None]:
    """Haalt per dag de slaapdata (en optioneel lifestyle-tags) op. Geeft de data terug,
    plus de laatste dag van de aaneengesloten reeks geslaagde ophalingen vanaf 'start'
    (= veilig hervatpunt voor een volgende run: een eventuele tussenliggende mislukking
    wordt bij de volgende run opnieuw geprobeerd in plaats van permanent overgeslagen).
    Een mislukte tags-ophaling telt ook als mislukking voor het hervatpunt, zodat de
    tags van die dag bij een volgende run alsnog meekomen.

    Dagen waarvoor de API slaagt maar (nog) géén slaapdata teruggeeft — typisch de
    laatste nacht(en) zolang het horloge niet handmatig gesynct is — schuiven het
    hervatpunt NIET op: ze worden bij de volgende run opnieuw geprobeerd. Zodra een
    latere dag binnen dezelfde run wél data heeft, springt het hervatpunt daaroverheen,
    zodat echte gaten (horloge niet gedragen) niet eindeloos blijven blokkeren."""
    sleep_rows = []
    tag_rows = []
    last_contiguous_success = None
    gap_found = False
    current = start
    while current <= end:
        day_ok = True
        day_has_data = False
        try:
            raw = client.get_sleep_data(current.isoformat())
            row = extract_sleep_row(current, raw)
            sleep_rows.append(row)
            day_has_data = row["slaap_start"] is not None
        except Exception as exc:
            print(f"  Overgeslagen {current.isoformat()} (slaap): {exc}")
            day_ok = False

        if include_tags:
            time.sleep(REQUEST_DELAY)
            try:
                raw_tags = client.get_lifestyle_logging_data(current.isoformat())
                tag_rows.extend(extract_tag_rows(current, raw_tags))
            except Exception as exc:
                print(f"  Overgeslagen {current.isoformat()} (tags): {exc}")
                day_ok = False

        if day_ok and day_has_data and not gap_found:
            last_contiguous_success = current
        elif not day_ok:
            gap_found = True

        if current < end:
            time.sleep(REQUEST_DELAY)
        current += timedelta(days=1)

    return pd.DataFrame(sleep_rows), pd.DataFrame(tag_rows), last_contiguous_success


def upsert_sleep_master(new_df: pd.DataFrame) -> tuple[int, int]:
    """Upsert slaaprijen in de master op datum. Nieuwe kolommen worden toegevoegd
    (bestaande rijen krijgen daar een lege waarde — bewust beleid, zie docstring).
    Een bestaande rij mét slaapdata wordt nooit vervangen door een lege her-ophaling.
    Geeft (aantal_bijgewerkt, aantal_nieuw) terug."""
    if new_df.empty:
        return 0, 0

    if SLEEP_MASTER.exists():
        master = pd.read_csv(SLEEP_MASTER, dtype={"datum": str})
    else:
        master = pd.DataFrame(columns=["datum"])

    existing_dates = set(master["datum"])
    protected = {
        row["datum"]
        for _, row in new_df.iterrows()
        if pd.isna(row.get("slaap_start"))
        and row["datum"] in existing_dates
        and master.loc[master["datum"] == row["datum"], "slaap_start"].notna().any()
    }
    new_df = new_df[~new_df["datum"].isin(protected)]

    updated = len(set(new_df["datum"]) & existing_dates)
    added = len(set(new_df["datum"]) - existing_dates)

    kept = master[~master["datum"].isin(new_df["datum"])]
    combined = pd.concat([kept, new_df], ignore_index=True).sort_values("datum")
    combined.to_csv(SLEEP_MASTER, index=False, encoding="utf-8")
    return updated, added


def upsert_tags_master(new_tags: pd.DataFrame) -> int:
    """Vervang per dag de tag-rijen in de master door de nieuw opgehaalde rijen.
    Dagen zonder nieuwe tag-rijen blijven onaangeroerd (een dag met eerder gelogde
    tags wordt dus nooit leeggemaakt door een her-ophaling zonder logStatus).
    Geeft het aantal vervangen/toegevoegde dagen terug."""
    if new_tags.empty:
        return 0

    if TAGS_MASTER.exists():
        master = pd.read_csv(TAGS_MASTER, dtype={"datum": str})
        kept = master[~master["datum"].isin(new_tags["datum"])]
    else:
        kept = pd.DataFrame()

    combined = pd.concat([kept, new_tags], ignore_index=True).sort_values(["datum", "gedrag_id"])
    combined.to_csv(TAGS_MASTER, index=False, encoding="utf-8")
    return new_tags["datum"].nunique()


def main():
    args = parse_args()
    start, end = resolve_date_range(args)

    if not confirm_range(start, end, skip_prompt=args.yes):
        print("Geannuleerd.")
        return

    print("Inloggen op Garmin Connect...")
    client = login()

    include_tags = not args.geen_tags
    print(f"Slaapdata{' + lifestyle-tags' if include_tags else ''} ophalen van {start.isoformat()} tot {end.isoformat()}...")
    sleep_df, tags_df, last_success = fetch_data(client, start, end, include_tags)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    updated, added = upsert_sleep_master(sleep_df)
    print(f"Slaap-master ({SLEEP_MASTER.name}): {added} nieuwe nacht(en), {updated} bijgewerkt.")

    if include_tags:
        tag_days = upsert_tags_master(tags_df)
        if tag_days:
            print(f"Tags-master ({TAGS_MASTER.name}): {tag_days} dag(en) vervangen/toegevoegd ({len(tags_df)} rijen).")
        else:
            print("Lifestyle-tags: geen gelogde gedragingen in deze periode — tags-master onaangeroerd.")

    if last_success is not None and (load_last_export_date() is None or last_success > load_last_export_date()):
        save_last_export_date(last_success)
        print(f"Laatste export bijgewerkt naar {last_success.isoformat()} ({STATE_FILE.name})")
    else:
        print(
            f"Hervatpunt niet opgeschoven ({STATE_FILE.name}): geen nieuwere dag met slaapdata "
            "opgehaald — nog niet gesyncte nachten worden bij de volgende run opnieuw geprobeerd."
        )


if __name__ == "__main__":
    main()
