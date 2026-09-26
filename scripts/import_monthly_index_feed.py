from __future__ import annotations

import argparse
from datetime import (
    datetime,
    timezone,
)
import json
from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from src.index.feed_bridge import (
    MISSING_AFTER_GRACE,
    NOT_DUE,
    READY_TO_IMPORT,
    WAITING_FOR_SOURCE,
    resolve_feed_bridge_expectation,
)
from src.index.feed_bridge_promotion import (
    ALREADY_CURRENT,
    PROMOTED,
    promote_validated_feed,
    read_stable_source,
    validate_feed_content,
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

        return yaml.safe_load(
            file
        )


def resolve_root_path(
    value: str,
) -> Path:

    path = Path(value)

    if path.is_absolute():
        return path

    return (
        ROOT
        / path
    )


def write_manifest(
    *,
    validated,
    archive_path: Path,
    source_path: Path,
) -> Path:

    manifest_path = (
        archive_path.parent
        / (
            archive_path.stem
            + ".manifest.json"
        )
    )

    manifest = {
        "imported_at_utc": (
            datetime.now(
                timezone.utc
            ).isoformat()
        ),
        "source_path": str(
            source_path
        ),
        "source_filename": (
            source_path.name
        ),
        "source_size": (
            validated.source.size
        ),
        "source_mtime_ns": (
            validated.source.mtime_ns
        ),
        "source_sha256": (
            validated.source.sha256
        ),
        "cutoff_date": (
            validated.cutoff_date
            .isoformat()
        ),
        "cutoff_local": (
            validated.cutoff_local
            .isoformat()
        ),
        "cutoff_utc": (
            validated.cutoff_utc
            .isoformat()
        ),
        "index_level": str(
            validated.index_level
        ),
        "constituent_count": (
            validated.constituent_count
        ),
        "total_weight_pct": str(
            validated.total_weight_pct
        ),
    }

    temporary = (
        manifest_path.parent
        / (
            "."
            + manifest_path.name
            + ".tmp"
        )
    )

    temporary.write_text(
        json.dumps(
            manifest,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    temporary.replace(
        manifest_path
    )

    return manifest_path


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--promote",
        action="store_true",
        help=(
            "Promote the validated monthly "
            "index portfolio to the ETF runtime "
            "feed. Default is dry-run only."
        ),
    )

    args = parser.parse_args()

    config = load_config()

    bridge = config.get(
        "index_feed_bridge"
    )

    if not bridge:
        raise RuntimeError(
            "index_feed_bridge configuration "
            "is missing."
        )

    if bridge.get(
        "enabled"
    ) is not True:

        print(
            "Decision           : "
            "NO_ACTION_DISABLED"
        )

        return

    cutoff_cfg = bridge[
        "cutoff"
    ]

    if (
        cutoff_cfg.get(
            "frequency"
        )
        != "monthly"
    ):
        raise RuntimeError(
            "Feed bridge frequency must "
            "be monthly."
        )

    if (
        cutoff_cfg.get(
            "rule"
        )
        != "last_calendar_day"
    ):
        raise RuntimeError(
            "Feed bridge cutoff rule must "
            "be last_calendar_day."
        )

    source_directory = Path(
        bridge[
            "source_directory"
        ]
    )

    filename_template = bridge[
        "filename_template"
    ]

    now_utc = datetime.now(
        timezone.utc
    )

    # First pass calculates the exact filename/path.
    provisional = (
        resolve_feed_bridge_expectation(
            now_utc=now_utc,
            timezone_name=(
                cutoff_cfg[
                    "timezone"
                ]
            ),
            time_local=(
                cutoff_cfg[
                    "time_local"
                ]
            ),
            grace_minutes=int(
                cutoff_cfg[
                    "grace_minutes"
                ]
            ),
            source_directory=(
                source_directory
            ),
            filename_template=(
                filename_template
            ),
            source_exists=False,
        )
    )

    source_exists = (
        provisional
        .expected_source_path
        .is_file()
    )

    expectation = (
        resolve_feed_bridge_expectation(
            now_utc=now_utc,
            timezone_name=(
                cutoff_cfg[
                    "timezone"
                ]
            ),
            time_local=(
                cutoff_cfg[
                    "time_local"
                ]
            ),
            grace_minutes=int(
                cutoff_cfg[
                    "grace_minutes"
                ]
            ),
            source_directory=(
                source_directory
            ),
            filename_template=(
                filename_template
            ),
            source_exists=(
                source_exists
            ),
        )
    )

    print("=" * 94)

    print(
        "ETF MONTHLY INDEX FEED BRIDGE"
    )

    print("=" * 94)

    print()

    print(
        f"Expected cutoff    : "
        f"{expectation.cutoff_date}"
    )

    print(
        f"Expected filename  : "
        f"{expectation.expected_filename}"
    )

    print(
        f"Source path        : "
        f"{expectation.expected_source_path}"
    )

    print(
        f"Scheduled local    : "
        f"{expectation.scheduled_local.isoformat()}"
    )

    print(
        f"Grace deadline     : "
        f"{expectation.grace_deadline_local.isoformat()}"
    )

    print(
        f"Calendar status    : "
        f"{expectation.status}"
    )

    if (
        expectation.status
        == NOT_DUE
    ):

        print()

        print(
            "Decision           : "
            "NO_ACTION_NOT_DUE"
        )

        print(
            "No feed was copied or promoted."
        )

        return

    if (
        expectation.status
        == WAITING_FOR_SOURCE
    ):

        print()

        print(
            "Decision           : "
            "WAITING_FOR_MONTH_END_FEED"
        )

        print(
            "No feed was copied or promoted."
        )

        return

    if (
        expectation.status
        == MISSING_AFTER_GRACE
    ):

        print()

        print(
            "Decision           : "
            "BLOCKED_MISSING_MONTHLY_FEED"
        )

        raise SystemExit(2)

    if (
        expectation.status
        != READY_TO_IMPORT
    ):

        raise RuntimeError(
            "Unknown feed bridge state: "
            f"{expectation.status}"
        )

    stable = read_stable_source(
        expectation.expected_source_path,
        settle_seconds=float(
            bridge.get(
                "source_stability",
                {},
            ).get(
                "settle_seconds",
                1.0,
            )
        ),
    )

    validated = validate_feed_content(
        stable,
        expected_cutoff_date=(
            expectation.cutoff_date
        ),
        timezone_name=(
            cutoff_cfg[
                "timezone"
            ]
        ),
        time_local=(
            cutoff_cfg[
                "time_local"
            ]
        ),
    )

    destination = bridge[
        "destination"
    ]

    current_path = (
        resolve_root_path(
            destination[
                "current_file"
            ]
        )
    )

    archive_directory = (
        resolve_root_path(
            destination[
                "archive_directory"
            ]
        )
    )

    print()

    print(
        f"Source SHA256      : "
        f"{stable.sha256}"
    )

    print(
        f"Source size        : "
        f"{stable.size}"
    )

    print(
        f"Feed cutoff local  : "
        f"{validated.cutoff_local.isoformat()}"
    )

    print(
        f"Feed cutoff UTC    : "
        f"{validated.cutoff_utc.isoformat()}"
    )

    print(
        f"Index level        : "
        f"{validated.index_level}"
    )

    print(
        f"Constituents       : "
        f"{validated.constituent_count}"
    )

    print(
        f"Total weight       : "
        f"{validated.total_weight_pct}%"
    )

    print(
        f"ETF current target : "
        f"{current_path}"
    )

    print(
        f"ETF archive target : "
        f"{archive_directory}"
    )

    print()

    print(
        "Validation          : OK"
    )

    if not args.promote:

        print()

        print(
            "Decision           : "
            "READY_FOR_PROMOTION"
        )

        print(
            "DRY RUN ONLY."
        )

        print(
            "No ETF runtime feed was modified."
        )

        return

    result = promote_validated_feed(
        validated,
        current_path=current_path,
        archive_directory=(
            archive_directory
        ),
    )

    manifest_path = (
        write_manifest(
            validated=validated,
            archive_path=(
                result.archive_path
            ),
            source_path=(
                expectation
                .expected_source_path
            ),
        )
    )

    print()

    print(
        f"Decision           : "
        f"{result.status}"
    )

    print(
        f"Current feed       : "
        f"{result.current_path}"
    )

    print(
        f"Archive snapshot   : "
        f"{result.archive_path}"
    )

    print(
        f"Audit manifest     : "
        f"{manifest_path}"
    )

    print(
        f"Promoted SHA256    : "
        f"{result.sha256}"
    )

    if (
        result.status
        == PROMOTED
    ):

        print(
            "Atomic promotion   : OK"
        )

    elif (
        result.status
        == ALREADY_CURRENT
    ):

        print(
            "Idempotency        : OK"
        )


if __name__ == "__main__":
    main()
