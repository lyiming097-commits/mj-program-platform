from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from ..models import OrganizationSyncLock, OrganizationSyncRun


@dataclass(frozen=True)
class SyncRunStartResult:
    run: OrganizationSyncRun
    created: bool


def sync_running_stale_after_seconds() -> int:
    try:
        return max(60, int(os.getenv("DINGTALK_ORG_SYNC_STALE_AFTER_SECONDS", "1800") or "1800"))
    except (TypeError, ValueError):
        return 1800


def start_sync_run(started_by: str) -> SyncRunStartResult:
    with transaction.atomic():
        OrganizationSyncLock.objects.get_or_create(lock_id=1)
        OrganizationSyncLock.objects.select_for_update().get(lock_id=1)
        now = timezone.now()
        running_run = OrganizationSyncRun.objects.filter(status=OrganizationSyncRun.STATUS_RUNNING).first()
        if running_run is not None:
            stale_before = now - timedelta(seconds=sync_running_stale_after_seconds())
            if running_run.started_at and running_run.started_at >= stale_before:
                return SyncRunStartResult(run=running_run, created=False)
            running_run.status = OrganizationSyncRun.STATUS_FAILED
            running_run.finished_at = now
            running_run.error = "Marked failed because the previous sync exceeded the stale threshold."
            running_run.save(update_fields=["status", "finished_at", "error", "updated_at"])

        return SyncRunStartResult(
            run=OrganizationSyncRun.objects.create(
                status=OrganizationSyncRun.STATUS_RUNNING,
                started_by=str(started_by or "system")[:64],
            ),
            created=True,
        )


def mark_sync_enqueue_failed(sync_run: OrganizationSyncRun, error: Exception) -> None:
    OrganizationSyncRun.objects.filter(
        run_id=sync_run.run_id,
        status=OrganizationSyncRun.STATUS_RUNNING,
    ).update(
        status=OrganizationSyncRun.STATUS_FAILED,
        finished_at=timezone.now(),
        error=f"Failed to enqueue organization sync: {error}",
        updated_at=timezone.now(),
    )
