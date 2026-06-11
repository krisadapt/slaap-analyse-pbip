"""Eenmalig PoC-script: onderzoekt of lifestyle-tags (gedragingen) en voedingslog
via de Garmin Connect API opgehaald kunnen worden, en in welk formaat.

Gebruik:
    python poc_lifestyle_nutrition.py              # gisteren
    python poc_lifestyle_nutrition.py 2026-06-08   # specifieke datum

Schrijft per onderdeel de ruwe JSON weg als poc_<onderdeel>_<datum>.json
zodat de structuur rustig geinspecteerd kan worden.
"""

import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv
from garminconnect import Garmin

SCRIPT_DIR = Path(__file__).resolve().parent
load_dotenv(SCRIPT_DIR / ".env")

TOKEN_DIR = SCRIPT_DIR / ".garmin_tokens"

target_date = sys.argv[1] if len(sys.argv) > 1 else (date.today() - timedelta(days=1)).isoformat()

email = os.environ.get("GARMIN_EMAIL")
password = os.environ.get("GARMIN_PASSWORD")
if not email or not password:
    raise SystemExit("GARMIN_EMAIL en/of GARMIN_PASSWORD ontbreken in .env")

client = Garmin(email=email, password=password, prompt_mfa=lambda: input("MFA-code: "))
client.login(str(TOKEN_DIR))

calls = {
    "lifestyle_logging": lambda: client.get_lifestyle_logging_data(target_date),
    "nutrition_food_log": lambda: client.get_nutrition_daily_food_log(target_date),
    "nutrition_meals": lambda: client.get_nutrition_daily_meals(target_date),
    "nutrition_settings": lambda: client.get_nutrition_daily_settings(target_date),
}

for name, call in calls.items():
    print(f"\n=== {name} voor {target_date} ===")
    try:
        result = call()
    except Exception as exc:
        print(f"  MISLUKT: {type(exc).__name__}: {exc}")
        continue

    out = SCRIPT_DIR / f"poc_{name}_{target_date}.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    if result is None:
        print("  Respons: None (geen data voor deze dag)")
    elif isinstance(result, dict):
        print(f"  Respons: dict met sleutels: {list(result.keys())}")
    elif isinstance(result, list):
        print(f"  Respons: lijst met {len(result)} entries")
    print(f"  Opgeslagen: {out.name}")
