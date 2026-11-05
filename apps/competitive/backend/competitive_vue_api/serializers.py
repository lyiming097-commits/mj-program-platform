from uuid import NAMESPACE_URL, uuid5

from .domain import competitor_parameter_text, normalize_competitor_parameter_text
from .models import (
    Competitor,
    CompetitorParameter,
    CompetitorRelease,
    CompetitorVersion,
    SettingItem,
    Submission,
    SubmissionAttachment,
)
from .setting_defaults import PROVINCE_NAMES


def serialize_competitor(item: Competitor) -> dict:
    return {
        "id": str(item.id),
        "productId": item.product_id,
        "brand": item.brand,
        "name": item.name,
        "model": item.model,
        "regions": list(item.regions or []),
        "sources": item.sources,
        "updated": item.updated_on.isoformat(),
        "expires": item.expires_on.isoformat(),
        "status": item.status,
        "price": item.price,
        "dealer": item.dealer,
        "createdAt": item.created_at.isoformat(),
        "updatedAt": item.updated_at.isoformat(),
    }


def serialize_attachment(item: SubmissionAttachment) -> dict:
    return {
        "id": str(item.id),
        "submissionId": str(item.submission_id) if item.submission_id else None,
        "name": item.filename,
        "size": item.byte_size,
        "type": item.media_type,
        "category": item.category,
        "storageKey": item.storage_key,
        "createdAt": item.created_at.isoformat(),
        "updatedAt": item.updated_at.isoformat(),
    }


def serialize_draft_attachment(item) -> dict:
    return {
        "id": str(item.id),
        "submissionId": None,
        "name": item.filename,
        "size": item.byte_size,
        "type": item.media_type,
        "category": item.category,
        "storageKey": item.storage_key,
        "createdAt": item.created_at.isoformat(),
        "updatedAt": item.updated_at.isoformat(),
    }


def serialize_submission(item: Submission) -> dict:
    parameter_text = normalize_competitor_parameter_text(item.competitor_parameters)
    return {
        "id": str(item.id),
        "competitorId": str(item.competitor_id) if item.competitor_id else None,
        "competitorVersionId": (
            str(item.competitor_release_id) if item.competitor_release_id else None
        ),
        "productId": item.product_id,
        "owner": item.owner,
        "brand": item.brand,
        "name": item.name,
        "model": item.model,
        "price": item.price,
        "dealer": item.dealer,
        "customer": item.customer,
        "note": item.note,
        "advantage": item.advantage,
        "weakness": item.weakness,
        "tactic": item.tactic,
        "competitorParameterText": parameter_text,
        "reviewComment": item.review_comment,
        "region": item.region,
        "city": item.city,
        "location": item.location,
        "located": item.located,
        "latitude": item.latitude,
        "longitude": item.longitude,
        "locationAccuracy": item.location_accuracy,
        "locatedAt": item.located_at.isoformat() if item.located_at else None,
        "locationSource": item.location_source,
        "validity": item.validity,
        "expires": item.expires_on.isoformat(),
        "reminderOwner": item.reminder_owner,
        "status": item.status,
        "date": item.submitted_on.isoformat(),
        "attachments": [serialize_attachment(row) for row in item.attachments.all()],
        "createdAt": item.created_at.isoformat(),
        "updatedAt": item.updated_at.isoformat(),
    }


def serialize_setting(item: SettingItem) -> dict:
    return {
        "id": str(item.id),
        "group": item.group,
        "code": item.code,
        "label": item.label,
        "enabled": item.enabled,
        "required": item.required,
        "position": item.position,
        "createdAt": item.created_at.isoformat(),
        "updatedAt": item.updated_at.isoformat(),
    }


def serialize_settings(items) -> list[dict]:
    # Legacy region settings remain stored for history, but are no longer selectable.
    settings = [serialize_setting(item) for item in items if item.group != "region"]
    settings.extend(
        {
            "id": str(uuid5(NAMESPACE_URL, f"competitive:province:{name}")),
            "group": "region",
            "code": f"province_{position}",
            "label": name,
            "enabled": True,
            "required": False,
            "position": position,
        }
        for position, name in enumerate(PROVINCE_NAMES)
    )
    return settings


def serialize_parameter(item: CompetitorParameter) -> dict:
    return {
        "id": str(item.id),
        "name": item.name,
        "competitorValue": item.competitor_value,
        "ownValue": item.own_value,
        "comparisonStatus": item.comparison_status,
        "deviation": item.deviation,
        "position": item.position,
        "text": competitor_parameter_text(item),
    }


def serialize_version(item: CompetitorVersion) -> dict:
    return {
        "id": str(item.id),
        "version": item.version,
        "date": item.changed_on.isoformat(),
        "note": item.note,
        "action": item.action,
        "changedBy": item.changed_by,
        "sourceSubmissionId": (
            str(item.source_submission_id) if item.source_submission_id else None
        ),
        "snapshot": dict(item.snapshot or {}),
    }


def serialize_release(item: CompetitorRelease) -> dict:
    prefetched = getattr(item, "_prefetched_objects_cache", {}).get("submissions")
    source_count = (
        sum(row.deleted_at is None for row in prefetched)
        if prefetched is not None
        else item.submissions.filter(deleted_at__isnull=True).count()
    )
    return {
        "id": str(item.id),
        "version": f"V{item.number}",
        "number": item.number,
        "date": item.changed_on.isoformat(),
        "expires": item.expires_on.isoformat(),
        "status": item.status,
        "note": item.note,
        "createdBy": item.created_by,
        "isDefault": item.is_current,
        # Kept for older clients; is_current only selects the initially displayed release.
        "isCurrent": item.is_current,
        "sourceCount": source_count,
    }


def serialize_release_parameter(item: dict, release_id, position: int) -> dict:
    return {
        "id": f"{release_id}:{position}",
        "name": "",
        "competitorValue": str(item.get("text") or ""),
        "ownValue": str(item.get("ownValue") or "待产品经理确认"),
        "comparisonStatus": str(item.get("comparisonStatus") or "待判断"),
        "deviation": str(item.get("deviation") or "待结合我司规格书确认具体差异"),
        "position": position,
        "text": str(item.get("text") or ""),
    }
