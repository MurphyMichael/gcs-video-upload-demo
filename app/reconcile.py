"""Keep the database and the bucket in agreement.

Run `python -m app.reconcile` for a report, or add `--fix` to apply it.
"""

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from itertools import batched

from sqlmodel import Session, col, select

from app.config import Settings, get_settings
from app.db import make_engine
from app.models import KEY_PREFIX, Upload, UploadStatus, utcnow
from app.storage import GcsStorage, ObjectInfo, Storage

# Refuse to delete anything if this share of the bucket looks orphaned...
MAX_ORPHAN_RATIO = 0.30
# ...once at least this many objects have been scanned.
MIN_SAMPLE = 25
LOOKUP_BATCH = 500


@dataclass
class Report:
    fixed: bool
    objects_scanned: int = 0
    unreferenced_objects: int = 0
    safety_stop: bool = False
    stuck_uploads: list[str] = field(default_factory=list)
    orphan_objects: list[str] = field(default_factory=list)
    purged_uploads: list[str] = field(default_factory=list)


def find_stuck_uploads(
    session: Session, storage: Storage, cutoff: datetime
) -> list[Upload]:
    """Pending uploads older than `cutoff` whose object never arrived."""
    pending = session.exec(
        select(Upload).where(
            Upload.status == UploadStatus.PENDING, Upload.created_at < cutoff
        )
    ).all()
    return [u for u in pending if storage.get_info(u.object_key) is None]


def find_orphans(
    session: Session, storage: Storage, cutoff: datetime
) -> tuple[int, int, list[ObjectInfo]]:
    """Scan the bucket for objects no upload record points to.

    Returns (objects scanned, unreferenced objects, orphans older than `cutoff`).
    The database is checked one batch of keys at a time, so memory stays flat
    however large the bucket grows.
    """
    scanned = unreferenced = 0
    orphans: list[ObjectInfo] = []
    for batch in batched(storage.list_objects(KEY_PREFIX), LOOKUP_BATCH):
        scanned += len(batch)
        keys = [obj.key for obj in batch]
        known = set(
            session.exec(
                select(Upload.object_key).where(col(Upload.object_key).in_(keys))
            ).all()
        )
        for obj in batch:
            if obj.key not in known:
                unreferenced += 1
                if obj.created_at < cutoff:
                    orphans.append(obj)
    return scanned, unreferenced, orphans


def find_purgeable(session: Session, cutoff: datetime) -> Sequence[Upload]:
    """Failed uploads that have been failed since before `cutoff`."""
    return session.exec(
        select(Upload).where(
            Upload.status == UploadStatus.FAILED, Upload.updated_at < cutoff
        )
    ).all()


def reconcile(
    session: Session, storage: Storage, settings: Settings, now: datetime, fix: bool
) -> Report:
    stale_cutoff = now - timedelta(hours=settings.stale_after_hours)
    purge_cutoff = now - timedelta(days=settings.purge_grace_days)

    stuck = find_stuck_uploads(session, storage, stale_cutoff)
    scanned, unreferenced, orphans = find_orphans(session, storage, stale_cutoff)
    purgeable = find_purgeable(session, purge_cutoff)

    report = Report(
        fixed=False,
        objects_scanned=scanned,
        unreferenced_objects=unreferenced,
        # Mostly-orphaned usually means the wrong database or bucket, not real
        # orphans. Change nothing: "missing" objects would also be false.
        safety_stop=scanned >= MIN_SAMPLE and unreferenced / scanned > MAX_ORPHAN_RATIO,
        stuck_uploads=[str(u.id) for u in stuck],
        orphan_objects=[obj.key for obj in orphans],
        purged_uploads=[str(u.id) for u in purgeable],
    )
    if not fix or report.safety_stop:
        return report

    for upload in stuck:
        upload.status = UploadStatus.FAILED
        upload.updated_at = now
        session.add(upload)
    for obj in orphans:
        storage.delete(obj.key)
    for upload in purgeable:
        storage.delete(upload.object_key)
        session.delete(upload)
    session.commit()
    report.fixed = True
    return report


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fix", action="store_true", help="apply the changes (default: report only)"
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    with Session(make_engine(settings.database_url)) as session:
        report = reconcile(
            session, GcsStorage(settings), settings, now=utcnow(), fix=args.fix
        )
    print(json.dumps(asdict(report), indent=2))
    # A non-zero exit lets a scheduler alert on the safety stop.
    raise SystemExit(1 if report.safety_stop else 0)


if __name__ == "__main__":
    main()
