from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import hashlib
import json

from django.utils import timezone

from .models import (
    FieldFeedback,
    ProjectAssignment,
    ProjectEvent,
    ProjectMessage,
    ProjectNode,
    Reward,
    Settlement,
    ServiceProject,
    ServiceProvider,
    ServiceRating,
    ServiceResource,
    ServiceTicket,
    TicketMessage,
)
from .presales_task_schedule import pending_presales_task_schedules


def iso(value) -> str:
    return value.isoformat() if value else ""


def date_only(value) -> str:
    if not value:
        return ""
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        return value.date().isoformat()
    return value.isoformat()


def project_planned_end(item: ServiceProject, node_rows: list[ProjectNode]) -> str:
    if item.service_type == ServiceProject.TYPE_PRESALES:
        if hasattr(item, "presales_task_deadline"):
            return date_only(item.presales_task_deadline)
        deadline = pending_presales_task_schedules().filter(
            node__project=item, planned_end_date__isnull=False,
        ).order_by("planned_end_date", "id").values_list("planned_end_date", flat=True).first()
        return date_only(deadline)
    enabled_nodes = [node for node in node_rows if node.enabled]
    current = next((node for node in enabled_nodes if node.node_key == item.current_node_key), None)
    if current and current.planned_end_at:
        return date_only(current.planned_end_at)
    planned = [node.planned_end_at for node in enabled_nodes if node.planned_end_at]
    if planned:
        return date_only(max(planned))
    return date_only(item.planned_end_date)


def decimal_text(value: Decimal | None) -> str:
    return format(value, "f") if value is not None else ""


def score_text(value) -> str:
    if value in (None, ""):
        return "0.00"
    try:
        return format(Decimal(str(value)).quantize(Decimal("0.01")), "f")
    except (ArithmeticError, TypeError, ValueError):
        return "0.00"


def audit_fields(item) -> dict:
    return {
        "createdBy": item.created_by,
        "createdActorId": item.created_actor_id,
        "updatedBy": item.updated_by,
        "updatedActorId": item.updated_actor_id,
        "createdAt": iso(item.created_at),
        "updatedAt": iso(item.updated_at),
    }


def serialize_provider(item: ServiceProvider, *, detail: bool = False) -> dict:
    metric_score = getattr(item, "metric_score", None)
    metric_score_count = getattr(item, "metric_score_count", None)
    if detail:
        ratings = list(ServiceRating.objects.filter(
            assignment__provider=item,
        ).select_related(
            "assignment__project",
            "assignment__node",
        ).order_by("-created_at", "-id")[:20])
        if metric_score_count is None:
            metric_score_count = len(ratings)
    else:
        ratings = []
    score_value = metric_score if metric_score is not None else item.score
    score_count = int(metric_score_count or 0)
    month_orders = getattr(item, "metric_month_orders", None)
    total_orders = getattr(item, "metric_total_orders", None)
    data = {
        "id": item.id,
        "authUserId": item.auth_user_id,
        "identitySource": item.identity_source,
        "identitySourceLabel": item.get_identity_source_display(),
        "name": item.name,
        "role": item.role,
        "roleLabel": item.get_role_display(),
        "phone": item.phone,
        "city": item.city,
        "regions": item.regions if isinstance(item.regions, list) else [],
        "skills": item.skills if isinstance(item.skills, list) else [],
        "certificationStatus": item.certification_status,
        "certificationStatusLabel": item.get_certification_status_display(),
        "score": score_text(score_value),
        "scoreRatingCount": score_count,
        "scoreSource": "rating" if score_count else "manual" if item.score else "none",
        "monthOrders": item.month_orders if month_orders is None else month_orders,
        "totalOrders": item.total_orders if total_orders is None else total_orders,
        "bio": item.bio,
        "lastActiveAt": iso(item.last_active_at),
        **audit_fields(item),
    }
    if detail:
        assignments = list(item.assignments.select_related("project", "node", "service_rating").exclude(
            status=ProjectAssignment.STATUS_CANCELLED,
        )[:20])
        data["serviceRecords"] = []
        for assignment in assignments:
            service_rating = getattr(assignment, "service_rating", None)
            data["serviceRecords"].append({
                "id": assignment.id,
                "projectId": assignment.project_id,
                "projectCode": assignment.project.code,
                "projectName": assignment.project.name,
                "serviceType": assignment.project.service_type,
                "serviceTypeLabel": assignment.project.get_service_type_display(),
                "nodeId": assignment.node_id,
                "nodeKey": assignment.node.node_key,
                "nodeName": assignment.node.name,
                "status": assignment.status,
                "statusLabel": assignment.get_status_display(),
                "time": iso(assignment.completed_at or assignment.accepted_at or assignment.assigned_at),
                "rating": service_rating.rating if service_rating else None,
                "ratingId": service_rating.id if service_rating else None,
            })
        data["scoreSummary"] = {
            "average": score_text(score_value),
            "count": score_count,
            "source": "rating" if score_count else "manual" if item.score else "none",
            "items": [
                {
                    "id": service_rating.id,
                    "rating": service_rating.rating,
                    "projectName": service_rating.assignment.project.name,
                    "nodeName": service_rating.assignment.node.name,
                    "ratedAt": iso(service_rating.created_at),
                }
                for service_rating in ratings
            ],
        }
    return data


def serialize_service_rating(item: ServiceRating) -> dict:
    assignment = item.assignment
    return {
        "id": item.id,
        "assignmentId": assignment.id,
        "projectId": assignment.project_id,
        "projectName": assignment.project.name,
        "nodeId": assignment.node_id,
        "nodeKey": assignment.node.node_key,
        "nodeName": assignment.node.name,
        "providerId": assignment.provider_id,
        "providerName": assignment.provider.name,
        "rating": item.rating,
        **audit_fields(item),
    }


def serialize_node(item: ProjectNode) -> dict:
    return {
        "id": item.id,
        "nodeKey": item.node_key,
        "name": item.name,
        "sequence": item.sequence,
        "kind": item.kind,
        "description": item.description,
        "enabled": item.enabled,
        "status": item.status,
        "statusLabel": item.get_status_display(),
        "plannedStartAt": iso(item.planned_start_at),
        "plannedEndAt": iso(item.planned_end_at),
        "actualStartAt": iso(item.actual_start_at),
        "actualEndAt": iso(item.actual_end_at),
        "estimatedFee": decimal_text(item.estimated_fee),
        "actualFee": decimal_text(item.actual_fee),
        "businessData": item.business_data if isinstance(item.business_data, dict) else {},
        "completedBy": item.completed_by,
        "completedActorId": item.completed_actor_id,
        "completedAt": iso(item.completed_at),
        **audit_fields(item),
    }


def serialize_mobile_task_node(item: ProjectNode, assignment_id: int | None = None) -> dict:
    data = serialize_node(item)
    business_data = dict(data["businessData"])
    has_other_records = False
    own_records = {}
    for key in ("fieldDrafts", "field_drafts", "fieldSubmissions", "field_submissions"):
        records = business_data.get(key)
        if not isinstance(records, dict):
            business_data.pop(key, None)
            continue
        own = records.get(str(assignment_id)) if assignment_id is not None else None
        has_other_records |= any(str(record_id) != str(assignment_id) for record_id in records)
        if own is not None:
            business_data[key] = {str(assignment_id): own}
            if isinstance(own, dict):
                own_records.update(own)
        else:
            business_data.pop(key, None)
    # Older reassignments may still have the former provider's execution mirror.
    if has_other_records:
        data["actualEndAt"] = own_records.get("actualEndAt", "")
        data["actualFee"] = own_records.get("actualFee", "")
        for record_key, mirror_keys in (
            ("actualEndAt", ("actualEndTime", "actual_end_time")),
            ("actualDuration", ("actualDuration", "actual_duration")),
            ("actualFeeNote", ("feeActualNote", "fee_actual_note")),
            ("settlementEligible", ("settlementEligible", "settlement_eligible")),
        ):
            for key in mirror_keys:
                business_data.pop(key, None)
            if record_key in own_records:
                business_data[mirror_keys[0]] = own_records[record_key]
        if not own_records.get("submitted"):
            for key in ("managerReviewStatus", "managerReviewNote", "managerReviewedAt", "managerReviewedBy"):
                business_data.pop(key, None)
    data["businessData"] = business_data
    return data


def serialize_assignment(item: ProjectAssignment) -> dict:
    return {
        "id": item.id,
        "projectId": item.project_id,
        "nodeId": item.node_id,
        "nodeUpdatedAt": iso(item.node.updated_at),
        "nodeKey": item.node.node_key if hasattr(item, "node") else "",
        "providerId": item.provider_id,
        "provider": serialize_provider(item.provider) if hasattr(item, "provider") else None,
        "role": item.role,
        "status": item.status,
        "statusLabel": item.get_status_display(),
        "plannedStartDate": iso(item.planned_start_date),
        "standardDuration": item.standard_duration,
        "assignedAt": iso(item.assigned_at),
        "acceptedAt": iso(item.accepted_at),
        "completedAt": iso(item.completed_at),
        "note": item.note,
        **audit_fields(item),
    }


def serialize_event(item: ProjectEvent) -> dict:
    return {
        "id": item.id,
        "projectId": item.project_id,
        "nodeId": item.node_id,
        "eventType": item.event_type,
        "title": item.title,
        "detail": item.detail,
        "beforeValues": item.before_values if isinstance(item.before_values, dict) else {},
        "afterValues": item.after_values if isinstance(item.after_values, dict) else {},
        "authUserId": item.auth_user_id,
        "authUserName": item.auth_user_name,
        "actorUserId": item.actor_user_id,
        "actorName": item.actor_name,
        "createdAt": iso(item.created_at),
    }


def serialize_project_message(item: ProjectMessage, *, user_id: str = "") -> dict:
    is_read = (
        item.author_user_id == user_id
        or bool(getattr(item, "_read_by_user", False))
    )
    node_key = item.node.node_key if item.node_id and hasattr(item, "node") and item.node else ""
    conversation_key = node_key or "project"
    return {
        "id": item.id,
        "projectId": item.project_id,
        "projectCode": item.project.code if hasattr(item, "project") else "",
        "projectName": item.project.name if hasattr(item, "project") else "",
        "nodeId": item.node_id,
        "nodeKey": node_key,
        "nodeName": item.node.name if item.node_id and hasattr(item, "node") and item.node else "项目沟通",
        "conversationType": "node" if item.node_id else "project",
        "conversationId": f"{item.project_id}:{conversation_key}",
        "conversationKey": conversation_key,
        "visibility": "node_participants" if item.node_id else "project_participants",
        "authorUserId": item.author_user_id,
        "authorName": item.author_name,
        "senderName": item.author_name,
        "actorUserId": item.actor_user_id,
        "messageType": item.message_type,
        "content": item.content,
        "isRead": is_read,
        "createdAt": iso(item.created_at),
        "time": iso(item.created_at),
    }


def serialize_message_conversation(item: ProjectMessage, *, unread_count: int, user_id: str = "") -> dict:
    data = serialize_project_message(item, user_id=user_id)
    return {
        "id": f"{item.project_id}:{data['conversationKey']}",
        "projectId": item.project_id,
        "projectCode": data["projectCode"],
        "projectName": data["projectName"],
        "nodeId": item.node_id,
        "nodeKey": data["nodeKey"],
        "nodeName": data["nodeName"],
        "conversationType": data["conversationType"],
        "conversationKey": data["conversationKey"],
        "visibility": data["visibility"],
        "senderName": data["authorName"],
        "lastMessage": data["content"],
        "content": data["content"],
        "lastMessageId": item.id,
        "lastMessageAt": data["createdAt"],
        "time": data["createdAt"],
        "unreadCount": unread_count,
    }


def serialize_active_project_nodes(item: ServiceProject, node_rows=None) -> list[dict]:
    if item.service_type != ServiceProject.TYPE_PRESALES or item.status != ServiceProject.STATUS_IN_PROGRESS:
        return []
    if node_rows is None:
        node_rows = getattr(item, "active_node_summary", None)
    if node_rows is None:
        node_rows = item.nodes.filter(enabled=True, status=ProjectNode.STATUS_ACTIVE).only(
            "id", "project_id", "node_key", "name", "sequence", "status", "enabled",
        )
    return [
        {"nodeKey": node.node_key, "name": node.name}
        for node in sorted(node_rows, key=lambda row: (row.sequence, row.id))
        if node.enabled and node.status == ProjectNode.STATUS_ACTIVE
    ]


def project_draft_version(item: ServiceProject) -> str:
    values = {key: getattr(item, key) for key in (
        "name", "customer", "owner_user_id", "owner_name", "address", "province", "summary", "business_data",
    )}
    return hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def serialize_project(item: ServiceProject, *, detail: bool = False, include_nodes: bool = False) -> dict:
    prefetched_nodes = getattr(item, "_prefetched_objects_cache", {}).get("nodes")
    node_rows = list(item.nodes.all()) if detail or include_nodes or prefetched_nodes is not None else []
    # List queries select just the two project roles, without loading every
    # node's business data or issuing an additional query for each project.
    project_leads = getattr(item, "presales_project_leads", None)
    if item.service_type == ServiceProject.TYPE_PRESALES and not hasattr(item, "presales_project_leads"):
        early_node = next((row for row in node_rows if row.node_key == "early-approval"), None)
        if early_node is not None and "business_data" not in early_node.get_deferred_fields():
            project_leads = (early_node.business_data or {}).get("projectLeads")
    data = {
        "id": item.id,
        "code": item.code,
        "serviceType": item.service_type,
        "serviceTypeLabel": item.get_service_type_display(),
        "source": "crm" if item.source_crm_id else "local",
        "sourceCrmId": item.source_crm_id,
        "presalesProjectId": item.presales_project_id,
        "crmStage": (item.crm_snapshot or {}).get("stage", ""),
        "crmStatus": (item.crm_snapshot or {}).get("status", ""),
        "crmOrderType": (item.crm_snapshot or {}).get("orderType", ""),
        "crmSyncedAt": iso(item.crm_synced_at),
        "crmCreatedAt": (item.crm_snapshot or {}).get("createdAt", "") if item.source_crm_id else "",
        "name": item.name,
        "customer": item.customer,
        "ownerUserId": item.owner_user_id,
        "ownerName": item.owner_name,
        "status": item.status,
        "statusLabel": item.get_status_display(),
        "currentNodeKey": item.current_node_key,
        "activeNodes": serialize_active_project_nodes(item, node_rows if detail or include_nodes or prefetched_nodes is not None else None),
        "address": item.address,
        "province": item.province,
        "plannedStartDate": "" if item.service_type == ServiceProject.TYPE_PRESALES else iso(item.planned_start_date),
        "plannedEndDate": project_planned_end(item, node_rows),
        "actualStartDate": iso(item.actual_start_date),
        "actualEndDate": iso(item.actual_end_date),
        "summary": item.summary,
        "businessData": item.business_data if isinstance(item.business_data, dict) else {},
        "deleted": bool(item.deleted_at),
        "deletedAt": iso(item.deleted_at),
        "deletedBy": item.deleted_by,
        **audit_fields(item),
    }
    if item.service_type == ServiceProject.TYPE_PRESALES:
        data["projectLeads"] = project_leads if isinstance(project_leads, dict) else {}
    if detail:
        data["draftVersion"] = project_draft_version(item)
        data["midsalesProjectId"] = (
            ServiceProject.objects.filter(presales_project_id=item.id, deleted_at__isnull=True)
            .values_list("id", flat=True).first()
        ) if item.service_type == ServiceProject.TYPE_PRESALES else None
        data.update({
            "nodes": [serialize_node(row) for row in node_rows],
            "assignments": [serialize_assignment(row) for row in item.assignments.all()],
            "events": [serialize_event(row) for row in item.events.all()
                       if not (item.source_crm_id and row.event_type == "project_created")],
        })
    elif include_nodes:
        data["nodes"] = [serialize_node(row) for row in node_rows]
    if detail or include_nodes:
        chargeable_keys = {
            "onsite-service", "mail-service", "school-inspection",
            "construction-work", "furniture-install", "device-install",
            "device-debug", "school-support",
        }
        pending_settlements = []
        from .services import field_completion_submitted
        for node in node_rows:
            chargeable = (
                item.service_type in {ServiceProject.TYPE_MIDSALES, ServiceProject.TYPE_AFTERSALES} and node.node_key in chargeable_keys
            )
            if not chargeable or node.actual_fee is None or node.actual_fee <= 0:
                continue
            ready_for_settlement = node.status == ProjectNode.STATUS_COMPLETED or (
                node.status == ProjectNode.STATUS_ACTIVE and (
                    item.service_type == ServiceProject.TYPE_PRESALES or field_completion_submitted(node)
                )
            )
            if not ready_for_settlement:
                continue
            settlement = next(
                (row for row in node.settlements.all() if row.status != Settlement.STATUS_CANCELLED),
                None,
            )
            if settlement and settlement.status == Settlement.STATUS_SETTLED:
                continue
            pending_settlements.append({
                "nodeId": node.id,
                "nodeKey": node.node_key,
                "nodeName": node.name,
                "actualFee": decimal_text(node.actual_fee),
                "settlementId": settlement.id if settlement else None,
                "settlementStatus": settlement.status if settlement else "available",
                "settlementStatusLabel": settlement.get_status_display() if settlement else "可结算",
            })
        data["settlementRequired"] = bool(pending_settlements)
        data["settlementItems"] = pending_settlements
    return data


def serialize_message(item: TicketMessage) -> dict:
    return {
        "id": item.id,
        "authorUserId": item.author_user_id,
        "authorName": item.author_name,
        "actorUserId": item.actor_user_id,
        "messageType": item.message_type,
        "content": item.content,
        "statusSnapshot": item.status_snapshot,
        "createdAt": iso(item.created_at),
    }


def serialize_ticket(item: ServiceTicket, *, detail: bool = False) -> dict:
    data = {
        "id": item.id,
        "code": item.code,
        "projectId": item.project_id,
        "projectCode": item.project.code if hasattr(item, "project") else "",
        "projectName": item.project.name if hasattr(item, "project") else "",
        "nodeId": item.node_id,
        "nodeKey": item.node.node_key if item.node_id and hasattr(item, "node") and item.node else "",
        "nodeName": item.node.name if item.node_id and hasattr(item, "node") and item.node else "",
        "title": item.title,
        "ticketType": item.ticket_type,
        "priority": item.priority,
        "priorityLabel": item.get_priority_display(),
        "status": item.status,
        "statusLabel": item.get_status_display(),
        "ownerUserId": item.owner_user_id,
        "ownerName": item.owner_name,
        "reporterUserId": item.reporter_user_id,
        "reporterName": item.reporter_name,
        "description": item.description,
        "resolution": item.resolution,
        "businessData": item.business_data if isinstance(item.business_data, dict) else {},
        "completedAt": iso(item.completed_at),
        "closedAt": iso(item.closed_at),
        **audit_fields(item),
    }
    if detail:
        data["messages"] = [serialize_message(row) for row in item.messages.all()]
    return data


def serialize_feedback(item: FieldFeedback) -> dict:
    return {
        "id": item.id,
        "projectId": item.project_id,
        "projectCode": item.project.code if hasattr(item, "project") else "",
        "projectName": item.project.name if hasattr(item, "project") else "",
        "nodeId": item.node_id,
        "nodeKey": item.node.node_key if item.node_id and hasattr(item, "node") and item.node else "",
        "nodeName": item.node.name if item.node_id and hasattr(item, "node") and item.node else "",
        "providerId": item.provider_id,
        "providerName": item.provider.name if hasattr(item, "provider") else "",
        "title": item.title,
        "feedbackType": item.feedback_type,
        "feedbackTypeLabel": item.get_feedback_type_display(),
        "content": item.content,
        "status": item.status,
        "statusLabel": item.get_status_display(),
        "reviewNote": item.review_note,
        "reviewedBy": item.reviewed_by,
        "reviewedAt": iso(item.reviewed_at),
        "rewardGenerated": item.reward_generated,
        "businessData": item.business_data if isinstance(item.business_data, dict) else {},
        **audit_fields(item),
    }


def serialize_reward(item: Reward) -> dict:
    return {
        "id": item.id,
        "code": item.code,
        "providerId": item.provider_id,
        "providerName": item.provider.name if hasattr(item, "provider") else "",
        "providerCity": item.provider.city if hasattr(item, "provider") else "",
        "projectId": item.project_id,
        "projectName": item.project.name if item.project_id and hasattr(item, "project") and item.project else "",
        "projectProvince": item.project.province if item.project_id and hasattr(item, "project") and item.project else "",
        "feedbackId": item.feedback_id,
        "rewardType": item.reward_type,
        "rewardTypeLabel": item.get_reward_type_display(),
        "title": item.title,
        "description": item.description,
        "amount": decimal_text(item.amount),
        "points": item.points,
        "prize": item.prize,
        "status": item.status,
        "statusLabel": item.get_status_display(),
        "issuedAt": iso(item.issued_at),
        "transitionNote": item.transition_note,
        **audit_fields(item),
    }


def serialize_settlement(item: Settlement, *, detail: bool = False) -> dict:
    source_node = item.source_node if item.source_node_id and hasattr(item, "source_node") else None
    source_assignment = (
        item.source_assignment
        if item.source_assignment_id and hasattr(item, "source_assignment")
        else None
    )
    data = {
        "id": item.id,
        "code": item.code,
        "projectId": item.project_id,
        "projectName": item.project.name if hasattr(item, "project") else "",
        "projectOwnerName": item.project.owner_name if hasattr(item, "project") else "",
        "relatedProjectId": item.related_project_id,
        "relatedProjectName": item.related_project.name if item.related_project_id and hasattr(item, "related_project") else "",
        "sourceNodeId": item.source_node_id,
        "sourceNodeKey": source_node.node_key if source_node else "",
        "sourceNodeName": source_node.name if source_node else "",
        "sourceNodeStatus": source_node.status if source_node else "",
        "sourceActualFee": decimal_text(source_node.actual_fee) if source_node else "",
        "sourceAssignmentId": item.source_assignment_id,
        "sourceProviderId": source_assignment.provider_id if source_assignment else None,
        "sourceProviderName": (
            source_assignment.provider.name
            if source_assignment and hasattr(source_assignment, "provider")
            else ""
        ),
        "serviceType": item.service_type,
        "serviceTypeLabel": item.get_service_type_display(),
        "customer": item.customer,
        "bearer": item.bearer,
        "bearerLabel": item.get_bearer_display(),
        "serviceContent": item.service_content,
        "budgetAmount": decimal_text(item.budget_amount),
        "finalAmount": decimal_text(item.final_amount),
        "orderAmount": decimal_text(item.order_amount),
        "externalQuote": decimal_text(item.external_quote),
        "revision": item.revision,
        "receivedAmount": decimal_text(item.received_amount),
        "invoiceDueAmount": decimal_text(item.invoice_due_amount),
        "invoicedAmount": decimal_text(item.invoiced_amount),
        "remainingReceivable": decimal_text(max(item.order_amount - item.received_amount, Decimal("0")) if item.bearer == Settlement.BEARER_CUSTOMER else Decimal("0")),
        "remainingInvoice": decimal_text(max(item.invoice_due_amount - item.invoiced_amount, Decimal("0"))),
        "invoiceType": item.invoice_type,
        "invoiceNumber": item.invoice_number,
        "subjectType": item.subject_type,
        "subjectName": item.subject_name,
        "subjectId": item.subject_id,
        "status": item.status,
        "statusLabel": item.get_status_display(),
        "remark": item.remark,
        **audit_fields(item),
    }
    if detail:
        data["events"] = [{
            "id": event.id, "revision": event.revision, "kind": event.kind,
            "operatorName": event.operator_name, "actorName": event.actor_name,
            "receiptDelta": decimal_text(event.receipt_delta),
            "invoiceDelta": decimal_text(event.invoice_delta),
            "reason": event.reason, "before": event.before, "after": event.after,
            **audit_fields(event),
        } for event in item.events.all()]
    return data


def serialize_resource(item: ServiceResource) -> dict:
    status = "enabled" if item.enabled else "disabled"
    return {
        "id": item.id,
        "projectId": item.project_id,
        "projectName": item.project.name if item.project_id and hasattr(item, "project") and item.project else "",
        "nodeKey": item.node_key,
        "title": item.title,
        "resourceType": item.resource_type,
        "resourceTypeLabel": item.get_resource_type_display(),
        "category": item.get_resource_type_display(),
        "audience": item.audience,
        "audienceLabel": item.get_audience_display(),
        "authorizationDisplay": item.get_audience_display(),
        "summary": item.summary,
        "description": item.summary,
        "content": item.content,
        "externalUrl": item.external_url,
        "tags": item.tags if isinstance(item.tags, list) else [],
        "enabled": item.enabled,
        "status": status,
        "statusLabel": "已启用" if item.enabled else "已停用",
        "authorizationNote": item.authorization_note,
        **audit_fields(item),
    }
