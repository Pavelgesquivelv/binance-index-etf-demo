from __future__ import annotations

from dataclasses import dataclass
from datetime import (
    date,
    datetime,
    timezone,
)
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import time
from zoneinfo import ZoneInfo

from src.index.feed_bridge import (
    parse_local_time,
)
from src.index.portfolio_feed import (
    PortfolioFeedLoader,
)


ZERO = Decimal("0")
ONE_HUNDRED = Decimal("100")


@dataclass(frozen=True)
class StableSource:
    path: Path
    content: bytes
    sha256: str
    size: int
    mtime_ns: int


@dataclass(frozen=True)
class ValidatedFeed:
    source: StableSource
    cutoff_date: date
    cutoff_local: datetime
    cutoff_utc: datetime
    index_level: Decimal
    constituent_count: int
    total_weight_pct: Decimal


@dataclass(frozen=True)
class PromotionResult:
    status: str
    current_path: Path
    archive_path: Path
    sha256: str
    cutoff_date: date


PROMOTED = "PROMOTED"
ALREADY_CURRENT = "ALREADY_CURRENT"


def sha256_bytes(
    content: bytes,
) -> str:

    return hashlib.sha256(
        content
    ).hexdigest()


def read_stable_source(
    path: str | Path,
    *,
    settle_seconds: float = 1.0,
) -> StableSource:

    path = Path(path)

    if not path.is_file():
        raise FileNotFoundError(
            f"Source feed does not exist: {path}"
        )

    if settle_seconds < 0:
        raise ValueError(
            "settle_seconds cannot be negative."
        )

    stat_before = path.stat()

    first = path.read_bytes()
    first_hash = sha256_bytes(
        first
    )

    if settle_seconds:
        time.sleep(
            settle_seconds
        )

    stat_after = path.stat()

    second = path.read_bytes()
    second_hash = sha256_bytes(
        second
    )

    stable = (
        stat_before.st_size
        == stat_after.st_size
        and stat_before.st_mtime_ns
        == stat_after.st_mtime_ns
        and first_hash
        == second_hash
        and first
        == second
    )

    if not stable:
        raise RuntimeError(
            "Source feed changed while being "
            "read. Import blocked."
        )

    if not second:
        raise RuntimeError(
            "Source feed is empty."
        )

    return StableSource(
        path=path,
        content=second,
        sha256=second_hash,
        size=stat_after.st_size,
        mtime_ns=stat_after.st_mtime_ns,
    )


def _aware_datetime(
    value: str,
    *,
    field: str,
) -> datetime:

    result = datetime.fromisoformat(
        value
    )

    if (
        result.tzinfo is None
        or result.utcoffset() is None
    ):
        raise RuntimeError(
            f"{field} must contain "
            "timezone information."
        )

    return result


def validate_feed_content(
    source: StableSource,
    *,
    expected_cutoff_date: date,
    timezone_name: str,
    time_local: str,
) -> ValidatedFeed:

    try:
        payload = json.loads(
            source.content.decode(
                "utf-8"
            )
        )

    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:

        raise RuntimeError(
            "Source portfolio is not valid "
            "UTF-8 JSON."
        ) from exc

    if not isinstance(
        payload,
        dict,
    ):
        raise RuntimeError(
            "Portfolio JSON root must "
            "be an object."
        )

    required = {
        "cutoff_local",
        "cutoff_utc",
        "index_level",
        "positions",
    }

    missing = sorted(
        required
        - set(payload)
    )

    if missing:
        raise RuntimeError(
            "Portfolio feed is missing "
            "required fields: "
            + ", ".join(missing)
        )

    timezone_local = ZoneInfo(
        timezone_name
    )

    expected_local = datetime.combine(
        expected_cutoff_date,
        parse_local_time(
            time_local
        ),
        tzinfo=timezone_local,
    )

    expected_utc = (
        expected_local.astimezone(
            timezone.utc
        )
    )

    cutoff_local = (
        _aware_datetime(
            str(
                payload[
                    "cutoff_local"
                ]
            ),
            field="cutoff_local",
        )
    )

    cutoff_utc = (
        _aware_datetime(
            str(
                payload[
                    "cutoff_utc"
                ]
            ),
            field="cutoff_utc",
        )
    )

    if (
        cutoff_local.astimezone(
            timezone_local
        )
        != expected_local
    ):
        raise RuntimeError(
            "cutoff_local does not match "
            "the expected monthly cutoff. "
            f"expected="
            f"{expected_local.isoformat()}, "
            f"actual="
            f"{cutoff_local.isoformat()}"
        )

    if (
        cutoff_utc.astimezone(
            timezone.utc
        )
        != expected_utc
    ):
        raise RuntimeError(
            "cutoff_utc does not match "
            "the expected monthly cutoff. "
            f"expected="
            f"{expected_utc.isoformat()}, "
            f"actual="
            f"{cutoff_utc.isoformat()}"
        )

    if (
        cutoff_local.astimezone(
            timezone.utc
        )
        != cutoff_utc.astimezone(
            timezone.utc
        )
    ):
        raise RuntimeError(
            "cutoff_local and cutoff_utc "
            "do not represent the same instant."
        )

    index_level = Decimal(
        str(
            payload[
                "index_level"
            ]
        )
    )

    if index_level <= ZERO:
        raise RuntimeError(
            "index_level must be positive."
        )

    positions = payload[
        "positions"
    ]

    if (
        not isinstance(
            positions,
            list,
        )
        or not positions
    ):
        raise RuntimeError(
            "positions must be a "
            "non-empty list."
        )

    assets: set[str] = set()
    total_weight = ZERO

    for index, row in enumerate(
        positions,
        start=1,
    ):

        if not isinstance(
            row,
            dict,
        ):
            raise RuntimeError(
                f"Position {index} must "
                "be an object."
            )

        asset = str(
            row.get(
                "asset",
                "",
            )
        ).strip().upper()

        if not asset:
            raise RuntimeError(
                f"Position {index} "
                "has no asset."
            )

        if asset in assets:
            raise RuntimeError(
                "Duplicate portfolio asset: "
                f"{asset}"
            )

        assets.add(
            asset
        )

        if (
            "target_weight_pct"
            not in row
        ):
            raise RuntimeError(
                f"{asset}: missing "
                "target_weight_pct."
            )

        weight = Decimal(
            str(
                row[
                    "target_weight_pct"
                ]
            )
        )

        if weight <= ZERO:
            raise RuntimeError(
                f"{asset}: target weight "
                "must be positive."
            )

        total_weight += weight

    if total_weight != ONE_HUNDRED:
        raise RuntimeError(
            "Portfolio target weights must "
            "sum exactly to 100%. "
            f"actual={total_weight}"
        )

    # Canonical ETF validation.
    #
    # Write the exact bytes to a temporary sibling
    # file and ask the production loader to parse it.
    validation_path = (
        source.path.parent
        / (
            ".etf-feed-validation-"
            + source.sha256[:16]
            + ".json"
        )
    )

    try:

        validation_path.write_bytes(
            source.content
        )

        PortfolioFeedLoader(
            validation_path
        ).load()

    finally:

        try:
            validation_path.unlink()
        except FileNotFoundError:
            pass

    return ValidatedFeed(
        source=source,
        cutoff_date=(
            expected_cutoff_date
        ),
        cutoff_local=cutoff_local,
        cutoff_utc=cutoff_utc,
        index_level=index_level,
        constituent_count=len(
            positions
        ),
        total_weight_pct=(
            total_weight
        ),
    )


def _atomic_write(
    destination: Path,
    content: bytes,
) -> None:

    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = (
        destination.parent
        / (
            "."
            + destination.name
            + f".tmp-{os.getpid()}"
        )
    )

    try:

        with temporary.open(
            "wb",
        ) as file:

            file.write(
                content
            )

            file.flush()

            os.fsync(
                file.fileno()
            )

        os.replace(
            temporary,
            destination,
        )

    finally:

        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _current_cutoff(
    path: Path,
) -> date | None:

    if not path.exists():
        return None

    try:

        payload = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

        cutoff_local = (
            _aware_datetime(
                str(
                    payload[
                        "cutoff_local"
                    ]
                ),
                field="cutoff_local",
            )
        )

    except Exception as exc:

        raise RuntimeError(
            "Existing current ETF feed "
            "cannot be parsed safely."
        ) from exc

    return cutoff_local.date()


def promote_validated_feed(
    validated: ValidatedFeed,
    *,
    current_path: str | Path,
    archive_directory: str | Path,
) -> PromotionResult:

    current_path = Path(
        current_path
    )

    archive_directory = Path(
        archive_directory
    )

    current_cutoff = (
        _current_cutoff(
            current_path
        )
    )

    if (
        current_cutoff is not None
        and current_cutoff
        > validated.cutoff_date
    ):
        raise RuntimeError(
            "Current ETF feed has a "
            "future cutoff relative to "
            "the source being imported."
        )

    current_hash = None

    if current_path.exists():
        current_hash = sha256_bytes(
            current_path.read_bytes()
        )

    if (
        current_cutoff
        == validated.cutoff_date
    ):

        if (
            current_hash
            == validated.source.sha256
        ):

            archive_path = (
                archive_directory
                / (
                    "portfolio_"
                    + validated
                    .cutoff_date
                    .isoformat()
                    + "_"
                    + validated
                    .source
                    .sha256[:16]
                    + ".json"
                )
            )

            return PromotionResult(
                status=ALREADY_CURRENT,
                current_path=current_path,
                archive_path=archive_path,
                sha256=(
                    validated
                    .source
                    .sha256
                ),
                cutoff_date=(
                    validated
                    .cutoff_date
                ),
            )

        raise RuntimeError(
            "A different ETF feed is already "
            "promoted for the same cutoff. "
            "Manual investigation required."
        )

    archive_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    archive_path = (
        archive_directory
        / (
            "portfolio_"
            + validated
            .cutoff_date
            .isoformat()
            + "_"
            + validated
            .source
            .sha256[:16]
            + ".json"
        )
    )

    if archive_path.exists():

        existing_hash = sha256_bytes(
            archive_path.read_bytes()
        )

        if (
            existing_hash
            != validated.source.sha256
        ):
            raise RuntimeError(
                "Archive filename collision "
                "with different content."
            )

    else:

        _atomic_write(
            archive_path,
            validated.source.content,
        )

    # Promotion happens last.
    _atomic_write(
        current_path,
        validated.source.content,
    )

    promoted_hash = sha256_bytes(
        current_path.read_bytes()
    )

    if (
        promoted_hash
        != validated.source.sha256
    ):
        raise RuntimeError(
            "Post-promotion SHA256 "
            "verification failed."
        )

    return PromotionResult(
        status=PROMOTED,
        current_path=current_path,
        archive_path=archive_path,
        sha256=(
            validated
            .source
            .sha256
        ),
        cutoff_date=(
            validated.cutoff_date
        ),
    )
