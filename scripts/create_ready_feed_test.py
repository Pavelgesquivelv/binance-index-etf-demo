from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml


ROOT = Path(__file__).resolve().parents[1]

TARGET = (
    ROOT
    / "data"
    / "portfolio_ready_test.json"
)


def load_config() -> dict:

    with (
        ROOT
        / "config"
        / "runtime.yaml"
    ).open(
        "r",
        encoding="utf-8",
    ) as file:

        return yaml.safe_load(file)


def resolve_runtime_feed() -> Path:

    config = load_config()

    configured = Path(
        config[
            "index_feed"
        ][
            "portfolio_file"
        ]
    )

    if configured.is_absolute():
        return configured

    return ROOT / configured


def main():

    source = resolve_runtime_feed()

    if not source.is_file():
        raise RuntimeError(
            "Configured runtime portfolio "
            f"does not exist: {source}"
        )

    with source.open(
        "r",
        encoding="utf-8",
    ) as file:

        payload = json.load(
            file
        )

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
        f"Source  : {source}"
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
        "Configured runtime portfolio "
        "was not modified."
    )


if __name__ == "__main__":
    main()
