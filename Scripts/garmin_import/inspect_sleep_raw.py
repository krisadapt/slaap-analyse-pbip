"""Eenmalig diagnostisch script: print de volledige ruwe Garmin-slaap-respons voor één dag.

Gebruik:
    python inspect_sleep_raw.py              # gisteren
    python inspect_sleep_raw.py 2026-06-08   # specifieke datum
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

print(f"\n=== Ruwe slaap-respons voor {target_date} ===\n")
raw = client.get_sleep_data(target_date)

# Top-level sleutels
print("TOP-LEVEL SLEUTELS:", list(raw.keys()))
print()

# Samenvatting van de interessante velden
for key in ("sleepLevels", "sleepMovement", "hrvData", "sleepStress"):
    val = raw.get(key)
    if val is None:
        print(f"{key}: afwezig in respons")
    elif isinstance(val, list):
        print(f"{key}: {len(val)} entries — eerste 3:")
        for entry in val[:3]:
            print(f"  {entry}")
    else:
        print(f"{key}: {val}")
    print()

# Volledige JSON wegschrijven voor inspectie
out = SCRIPT_DIR / f"sleep_raw_{target_date}.json"
out.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"Volledige JSON opgeslagen: {out}")
