import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .domain import queue_file_deletions, sync_expiry_statuses
from .files import delete_stored_file
from .models import (
    Competitor,
    PendingFileDeletion,
    Submission,
    SubmissionAttachment,
)
from .setting_defaults import ensure_default_setting_items


logger = logging.getLogger(__name__)
SOFT_DELETE_RETENTION = timedelta(days=30)


def purge_expired_soft_deletions(*, now=None, batch_size=100):
    cutoff = (now or timezone.now()) - SOFT_DELETE_RETENTION
    with transaction.atomic():
        competitor_ids = list(
            Competitor.objects.select_for_update(skip_locked=True)
            .filter(deleted_at__isnull=False, deleted_at__lte=cutoff)
            .order_by("deleted_at", "id")
            .values_list("id", flat=True)[:batch_size]
        )
        if not competitor_ids:
            return 0

        storage_keys = list(
            SubmissionAttachment.objects.filter(
                submission__competitor_id__in=competitor_ids,
                storage_key__isnull=False,
            ).values_list("storage_key", flat=True)
        )
        queue_file_deletions(storage_keys)
        Submission.objects.filter(competitor_id__in=competitor_ids).delete()
        Competitor.objects.filter(id__in=competitor_ids).delete()
    return len(competitor_ids)


def process_pending_file_deletions(*, batch_size=100):
    with transaction.atomic():
        pending = list(
            PendingFileDeletion.objects.select_for_update(skip_locked=True)
            .order_by("created_at")[:batch_size]
        )
        completed = 0
        for item in pending:
            try:
                delete_stored_file(item.storage_key)
            except Exception as exc:
                item.attempts += 1
                item.last_error = str(exc)[:2000]
                item.save(update_fields=["attempts", "last_error", "updated_at"])
                logger.warning(
                    "file cleanup failed for %s (attempt %s): %s",
                    item.storage_key,
                    item.attempts,
                    exc,
                )
            else:
                item.delete()
                completed += 1
    return completed


def run_maintenance_cycle(*, now=None, batch_size=100):
    ensure_default_setting_items()
    expiry = sync_expiry_statuses(today=(now or timezone.now()).date())
    purged = purge_expired_soft_deletions(now=now, batch_size=batch_size)
    files = process_pending_file_deletions(batch_size=batch_size)
    return {"expiry": expiry, "purged": purged, "files": files}
