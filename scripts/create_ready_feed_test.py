from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]

SOURCE = ROOT / "data" / "portfolio_seed.json"
TARGET = ROOT / "data" / "portfolio_ready_test.json"


def main():

    with SOURCE.open(
        "r",
        encoding="utf-8",
    ) as file:
        payload = json.load(file)

    # Support either a metadata block or
    # metadata fields at the JSON root.
    metadata = payload.get(
        "metadata",
        payload,
    )

    now_utc = datetime.now(
        timezone.utc
    )

    now_local = now_utc.astimezone(
        ZoneInfo(
            "America/Mexico_City"
        )
    )

    metadata["cutoff_utc"] = (
        now_utc.isoformat()
    )

    metadata["cutoff_local"] = (
        now_local.isoformat()
    )

    metadata["ranking_date"] = (
        now_local.date().isoformat()
    )

    with TARGET.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            payload,
            file,
            indent=2,
            ensure_ascii=False,
        )

    print(
        f"Created : {TARGET}"
    )

    print(
        f"cutoff_utc   : "
        f"{metadata['cutoff_utc']}"
    )

    print(
        f"cutoff_local : "
        f"{metadata['cutoff_local']}"
    )

    print(
        f"ranking_date : "
        f"{metadata['ranking_date']}"
    )

    print()
    print(
        "Original portfolio was not modified."
    )


if __name__ == "__main__":
    main()
