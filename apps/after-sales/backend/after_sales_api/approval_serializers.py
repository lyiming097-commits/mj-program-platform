from __future__ import annotations

from .approval_models import PresalesApprovalRevision, PresalesApprovalStep


def _iso(value) -> str:
    return value.isoformat() if value else ""


def serialize_approval_revision(item: PresalesApprovalRevision) -> dict:
    return {
        "id": item.id,
        "revision": item.revision,
        "title": item.title,
        "approverUserId": item.approver_user_id,
        "approverName": item.approver_name,
        "status": item.status,
        "statusLabel": item.get_status_display(),
        "opinion": item.opinion,
        "decidedAt": _iso(item.decided_at),
        "recordedByUserId": item.recorded_by_user_id,
        "recordedByName": item.recorded_by_name,
        "recordedActorId": item.recorded_actor_id,
        "recordedAt": _iso(item.recorded_at),
    }


def serialize_approval_step(item: PresalesApprovalStep) -> dict:
    revisions = list(item.revisions.all())
    return {
        "id": item.id,
        "nodeId": item.node_id,
        "sequence": item.sequence,
        "title": item.title,
        "approverUserId": item.approver_user_id,
        "approverName": item.approver_name,
        "status": item.status,
        "statusLabel": item.get_status_display(),
        "opinion": item.opinion,
        "decidedAt": _iso(item.decided_at),
        "revision": max((revision.revision for revision in revisions), default=0),
        "history": [serialize_approval_revision(revision) for revision in revisions],
        "createdBy": item.created_by,
        "createdActorId": item.created_actor_id,
        "createdAt": _iso(item.created_at),
        "updatedBy": item.updated_by,
        "updatedActorId": item.updated_actor_id,
        "updatedAt": _iso(item.updated_at),
    }
