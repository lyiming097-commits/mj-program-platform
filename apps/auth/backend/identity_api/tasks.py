from __future__ import annotations

import json
import os
import threading

from celery import shared_task
from celery.signals import beat_init, worker_ready
from django.core.cache import cache
from django.utils import timezone

from .dingtalk.client import DingTalkAPIError
from .models import AuthSession, OrganizationSyncRun
from .org.sync import sync_organization_contacts
from .org.sync_runs import mark_sync_enqueue_failed, start_sync_run


SYNC_WORKER_HEARTBEAT_KEY = "auth-sync-worker-heartbeat"


@shared_task(name="auth.send_robot_messages", acks_late=True, reject_on_worker_lost=True,
             soft_time_limit=3540, time_limit=3600)
def send_robot_messages_task(batch_id):
    from .robot_messages import deliver_batch
    deliver_batch(batch_id)

SYNC_SCHEDULER_HEARTBEAT_KEY = "auth-sync-scheduler-heartbeat"
SYNC_WORKER_HEARTBEAT_INTERVAL_SECONDS = 60
SYNC_WORKER_HEARTBEAT_TIMEOUT_SECONDS = 180
_heartbeat_thread = None
_scheduler_heartbeat_thread = None


def _publish_sync_worker_heartbeat() -> None:
    cache.set(
        SYNC_WORKER_HEARTBEAT_KEY,
        timezone.now().isoformat(),
        timeout=SYNC_WORKER_HEARTBEAT_TIMEOUT_SECONDS,
    )


def _sync_worker_heartbeat_loop() -> None:
    while True:
        try:
            _publish_sync_worker_heartbeat()
        except Exception:
            pass
        threading.Event().wait(SYNC_WORKER_HEARTBEAT_INTERVAL_SECONDS)


def _publish_sync_scheduler_heartbeat() -> None:
    cache.set(
        SYNC_SCHEDULER_HEARTBEAT_KEY,
        timezone.now().isoformat(),
        timeout=SYNC_WORKER_HEARTBEAT_TIMEOUT_SECONDS,
    )


def _sync_scheduler_heartbeat_loop() -> None:
    while True:
        try:
            _publish_sync_scheduler_heartbeat()
        except Exception:
            pass
        threading.Event().wait(SYNC_WORKER_HEARTBEAT_INTERVAL_SECONDS)


@worker_ready.connect
def publish_worker_ready_heartbeat(**_kwargs) -> None:
    global _heartbeat_thread
    if os.getenv("AUTH_RUNTIME_ROLE", "").strip().lower() != "sync-worker":
        return
    _publish_sync_worker_heartbeat()
    if _heartbeat_thread is None or not _heartbeat_thread.is_alive():
        _heartbeat_thread = threading.Thread(
            target=_sync_worker_heartbeat_loop,
            name="auth-sync-worker-heartbeat",
            daemon=True,
        )
        _heartbeat_thread.start()


@beat_init.connect
def publish_scheduler_ready_heartbeat(**_kwargs) -> None:
    global _scheduler_heartbeat_thread
    if os.getenv("AUTH_RUNTIME_ROLE", "").strip().lower() != "beat":
        return
    _publish_sync_scheduler_heartbeat()
    if _scheduler_heartbeat_thread is None or not _scheduler_heartbeat_thread.is_alive():
        _scheduler_heartbeat_thread = threading.Thread(
            target=_sync_scheduler_heartbeat_loop,
            name="auth-sync-scheduler-heartbeat",
            daemon=True,
        )
        _scheduler_heartbeat_thread.start()


@shared_task(name="auth.prune_expired_sessions")
def prune_expired_sessions_task() -> dict:
    deleted_count, _details = AuthSession.objects.filter(expires_at__lte=timezone.now()).delete()
    return {"ok": True, "deletedCount": deleted_count}


def _json_safe(value):
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


@shared_task(bind=True, acks_late=True, reject_on_worker_lost=True, name="auth.sync_organization_contacts")
def sync_organization_contacts_task(self, run_id: str) -> dict:
    sync_run = OrganizationSyncRun.objects.filter(run_id=run_id).first()
    if sync_run is None or sync_run.status != OrganizationSyncRun.STATUS_RUNNING:
        return {"ignored": True, "runId": str(run_id)}

    try:
        result = sync_organization_contacts()
    except DingTalkAPIError as exc:
        summary = {"detail": _json_safe(exc.detail)} if exc.detail is not None else {}
        OrganizationSyncRun.objects.filter(
            run_id=run_id,
            status=OrganizationSyncRun.STATUS_RUNNING,
        ).update(
            status=OrganizationSyncRun.STATUS_FAILED,
            finished_at=timezone.now(),
            error=str(exc),
            summary=summary,
            updated_at=timezone.now(),
        )
        return {"ok": False, "runId": str(run_id), "error": str(exc)}
    except Exception as exc:
        OrganizationSyncRun.objects.filter(
            run_id=run_id,
            status=OrganizationSyncRun.STATUS_RUNNING,
        ).update(
            status=OrganizationSyncRun.STATUS_FAILED,
            finished_at=timezone.now(),
            error=str(exc),
            updated_at=timezone.now(),
        )
        raise

    OrganizationSyncRun.objects.filter(
        run_id=run_id,
        status=OrganizationSyncRun.STATUS_RUNNING,
    ).update(
        status=OrganizationSyncRun.STATUS_SUCCEEDED,
        finished_at=timezone.now(),
        summary=result,
        error="",
        updated_at=timezone.now(),
    )
    return {"ok": True, "runId": str(run_id), **result}


@shared_task(name="auth.schedule_organization_sync")
def schedule_organization_sync_task() -> dict:
    start_result = start_sync_run("system:scheduled")
    if not start_result.created:
        return {
            "ok": True,
            "queued": False,
            "reason": "already_running",
            "runId": str(start_result.run.run_id),
        }

    sync_run = start_result.run
    try:
        task = sync_organization_contacts_task.delay(str(sync_run.run_id))
    except Exception as exc:
        mark_sync_enqueue_failed(sync_run, exc)
        return {"ok": False, "queued": False, "runId": str(sync_run.run_id), "error": str(exc)}
    return {"ok": True, "queued": True, "runId": str(sync_run.run_id), "taskId": task.id}
