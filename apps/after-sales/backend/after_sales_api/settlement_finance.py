"""Settlement ledger, authoritative subjects and paginated settlement workspace."""
from decimal import Decimal

from django.db.models import BooleanField, Exists, F, Func, OuterRef, Prefetch, Q
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .crm_source import assert_crm_project_access, scope_crm_queryset
from .models import ProjectAssignment, ProjectNode, ServiceProject, Settlement, SettlementEvent
from .org_client import AuthOrgClientError, get_auth_company_entities
from .product_search import filter_queryset_search
from .project_personnel import management_member_q
from .serializers import serialize_settlement
from .services import DomainValidationError, create_audit_fields, request_identity, text


def related_projects(user_id=""):
    rows = ServiceProject.objects.filter(deleted_at__isnull=True).exclude(service_type=ServiceProject.TYPE_PRESALES)
    if user_id:
        management = ProjectNode.objects.filter(
            management_member_q(user_id), project_id=OuterRef("pk"),
        )
        providers = ProjectAssignment.objects.filter(
            project_id=OuterRef("pk"), provider__auth_user_id=user_id,
        ).exclude(status=ProjectAssignment.STATUS_CANCELLED)
        rows = rows.annotate(_management=Exists(management), _provider=Exists(providers)).filter(
            Q(owner_user_id=user_id) | Q(_management=True) | Q(_provider=True),
        )
    return rows


def validate_subject(fields, current=None):
    """Names are snapshots; never resolve new references by fuzzy matching names."""
    from .views import _active_employee_directory
    bearer = fields.get("bearer", current.bearer if current else "")
    if bearer == Settlement.BEARER_CUSTOMER:
        fields.update(subject_type="customer", subject_id="", subject_name=fields.get("customer", current.customer if current else ""), related_project=None)
        return
    subject_type = fields.get("subject_type", current.subject_type if current else "company") or "company"
    if subject_type not in {"company", "person"}:
        raise DomainValidationError("承担主体类型无效", code="INVALID_SETTLEMENT_SUBJECT")
    subject_id = fields.get("subject_id", current.subject_id if current else "")
    subject_name = fields.get("subject_name", current.subject_name if current else "")
    changed = current is None or any(
        fields.get(field, getattr(current, field)) != getattr(current, field)
        for field in ("subject_type", "subject_id", "subject_name")
    )
    if changed:
        if not subject_id and subject_name:
            raise DomainValidationError("请从目录重新选择承担主体", code="SETTLEMENT_SUBJECT_ID_REQUIRED")
        if subject_id:
            try:
                if subject_type == "company":
                    candidates = get_auth_company_entities()
                    match = next((row for row in candidates if str(row["id"]) == subject_id), None)
                    name = match.get("companyName") if match else ""
                else:
                    candidates, _revision = _active_employee_directory()
                    match = next((row for row in candidates if row["userId"] == subject_id), None)
                    name = match.get("name") if match else ""
            except AuthOrgClientError as exc:
                raise DomainValidationError(str(exc), code="SETTLEMENT_DIRECTORY_UNAVAILABLE", status=503) from exc
            if not match:
                raise DomainValidationError("承担主体已失效，请重新选择", code="SETTLEMENT_SUBJECT_NOT_FOUND", status=409)
            fields["subject_name"] = name
    fields["subject_type"] = subject_type
    related = fields.get("related_project", current.related_project if current else None)
    if related and subject_type == "person" and (
        not subject_id or not related_projects(subject_id).filter(pk=related.pk).exists()
    ):
        raise DomainValidationError("所选项目与该人员没有关联，请重新选择", code="SETTLEMENT_PERSON_PROJECT_MISMATCH", status=409)


SNAPSHOT_FIELDS = (
    "status", "received_amount", "invoiced_amount", "invoice_type", "invoice_number",
    "subject_type", "subject_id", "subject_name", "related_project_id", "remark",
)


def finance_snapshot(item):
    return {field: str(getattr(item, field)) if isinstance(getattr(item, field), Decimal) else getattr(item, field)
            for field in SNAPSHOT_FIELDS}


def record_finance_event(item, request, before=None, *, reason="", kind="update"):
    after = finance_snapshot(item)
    before = before or {}
    if before == after:
        return
    SettlementEvent.objects.create(
        settlement=item, revision=item.revision, kind=kind, before=before, after=after, reason=reason,
        operator_name=request_identity(request)["user_name"], actor_name=request_identity(request)["actor_name"],
        receipt_delta=item.received_amount - Decimal(before.get("received_amount", "0")),
        invoice_delta=item.invoiced_amount - Decimal(before.get("invoiced_amount", "0")),
        **create_audit_fields(request),
    )


class SubmissionConfirmed(Func):
    """Read the submission for this exact, non-cancelled assignment in SQL."""
    output_field = BooleanField()

    def as_sql(self, compiler, connection, **extra_context):
        data, data_params = compiler.compile(self.source_expressions[0])
        assignment, assignment_params = compiler.compile(self.source_expressions[1])
        if connection.vendor == "postgresql":
            expressions = [f"({data} -> '{key}' -> CAST({assignment} AS text) ->> 'submitted') = 'true'"
                           for key in ("fieldSubmissions", "field_submissions")]
        else:
            expressions = [f"json_extract({data}, '$.{key}.\"' || CAST({assignment} AS text) || '\".submitted') = 1"
                           for key in ("fieldSubmissions", "field_submissions")]
        return "(" + " OR ".join(expressions) + ")", (data_params + assignment_params) * 2


@require_GET
def settlement_workspace(request):
    from . import views
    denied = views._ensure_finance_manager(request)
    if denied is not None:
        return denied
    try:
        visible_records = scope_crm_queryset(request, Settlement.objects.exclude(
            project__service_type=ServiceProject.TYPE_PRESALES,
        ).exclude(service_type=ServiceProject.TYPE_PRESALES), "project__")
        visible_records = scope_crm_queryset(request, visible_records, "related_project__")
        active = visible_records.exclude(status="cancelled")
        any_active = Settlement.objects.filter(source_node_id=OuterRef("pk")).exclude(status="cancelled")
        confirmed = ProjectAssignment.objects.filter(node_id=OuterRef("pk")).exclude(status="cancelled").annotate(
            _submitted=SubmissionConfirmed(F("node__business_data"), F("pk")),
        ).filter(_submitted=True)
        rows = scope_crm_queryset(request, ProjectNode.objects.filter(project__deleted_at__isnull=True), "project__")
        rows = rows.annotate(
            _confirmed=Exists(confirmed), _any=Exists(any_active),
            _record=Exists(active.filter(source_node_id=OuterRef("pk"))),
            _settled=Exists(active.filter(source_node_id=OuterRef("pk"), status="settled")),
        ).filter(Q(_any=False) | Q(_record=True)).filter(
            Q(_record=True) | (
                Q(enabled=True, actual_fee__gt=0)
                & (Q(project__service_type="midsales", node_key__in=views.MIDSALES_SETTLEMENT_NODE_KEYS)
                   | Q(project__service_type="aftersales", node_key__in=["onsite-service", "mail-service", "school-inspection"]))
                & (Q(status="completed") | Q(status="active", _confirmed=True))
            )
        )
        legacy = active.filter(source_node__isnull=True, project__deleted_at__isnull=True)
        service_type = text(request.GET.get("type"))
        if service_type:
            rows, legacy = rows.filter(project__service_type=service_type), legacy.filter(service_type=service_type)
        project_id = text(request.GET.get("projectId"))
        if project_id:
            project_id = views._bounded_int(project_id, "项目", minimum=1)
            rows, legacy = rows.filter(project_id=project_id), legacy.filter(project_id=project_id)
        source_node_id = text(request.GET.get("sourceNodeId"))
        if source_node_id:
            rows = rows.filter(pk=views._bounded_int(source_node_id, "来源节点", minimum=1))
            legacy = legacy.none()
        node_name = text(request.GET.get("nodeName"))
        # Options span the complete authorized scope, not just the current page.
        node_names = list(rows.order_by().values_list("name", flat=True).distinct())
        if node_name:
            rows, legacy = rows.filter(name=node_name), legacy.filter(source_node__name=node_name)
        state = text(request.GET.get("state")) or "available"
        if state == "available":
            rows, legacy = rows.filter(_record=False), legacy.none()
        elif state in {"processing", "unsettled"}:
            rows, legacy = rows.filter(_record=True, _settled=False), legacy.exclude(status="settled")
        elif state == "settled":
            rows, legacy = rows.filter(_settled=True), legacy.filter(status="settled")
        elif state != "all":
            return views._error("结算来源状态无效", status=400, code="INVALID_SETTLEMENT_SOURCE_STATE")
        bearer = text(request.GET.get("bearer"))
        if bearer == "unselected":
            rows, legacy = rows.filter(_record=False), legacy.none()
        elif bearer in {"customer", "company"}:
            rows = rows.annotate(_bearer=Exists(active.filter(source_node_id=OuterRef("pk"), bearer=bearer))).filter(_bearer=True)
            legacy = legacy.filter(bearer=bearer)
        search = views._search_filter(request)
        if search:
            matching_records = filter_queryset_search(active, search, ("subject_name", "remark", "code"))
            matched_nodes = filter_queryset_search(rows, search, ("project__name", "project__code", "project__customer", "project__owner_name", "name", "description"))
            rows = rows.filter(Q(pk__in=matched_nodes.values("pk")) | Q(pk__in=matching_records.values("source_node_id")))
            legacy = filter_queryset_search(legacy, search, ("project__name", "project__code", "customer", "project__owner_name", "service_content", "subject_name", "remark", "code"))
        # Each table input filters only its own displayed column, before pagination.
        for param, node_field, legacy_field in (
            ("projectSearch", "project__name", "project__name"),
            ("customerSearch", "project__customer", "customer"),
            ("ownerSearch", "project__owner_name", "project__owner_name"),
        ):
            value = text(request.GET.get(param))
            if value:
                rows = rows.filter(**{f"{node_field}__icontains": value})
                legacy = legacy.filter(**{f"{legacy_field}__icontains": value})
        page, size = views._page(request)
        node_total = rows.count()
        total = node_total + legacy.count()
        total_pages = max(1, (total + size - 1) // size)
        page = min(page, total_pages)
        offset = (page - 1) * size
        page_nodes = rows.select_related("project").prefetch_related(
            Prefetch("settlements", queryset=active.select_related("project", "source_node", "related_project", "source_assignment__provider")),
            "assignments__provider",
        ).order_by("-completed_at", "-id")[offset:offset + size]
        items = []
        for node in page_nodes:
            item = views._serialize_settlement_source(node)
            record = next(iter(node.settlements.all()), None)
            item["settlement"] = serialize_settlement(record) if record else None
            if record:
                item.update(estimatedFee=str(record.budget_amount), actualFee=str(record.final_amount), externalQuote=str(record.external_quote or ""))
            items.append(item)
        if len(items) < size:
            legacy_offset = max(0, offset - node_total)
            for record in legacy.select_related("project", "related_project").order_by("-id")[legacy_offset:legacy_offset + size - len(items)]:
                items.append({
                    "id": f"legacy-{record.id}", "sourceNodeId": None, "nodeName": "历史结算",
                    "projectId": record.project_id, "projectName": record.project.name, "projectCode": record.project.code,
                    "customer": record.customer, "ownerName": record.project.owner_name,
                    "serviceType": record.service_type, "serviceTypeLabel": record.get_service_type_display(),
                    "serviceContent": record.service_content, "estimatedFee": str(record.budget_amount),
                    "actualFee": str(record.final_amount), "externalQuote": str(record.external_quote or ""),
                    "settlement": serialize_settlement(record), "settlementId": record.id, "settlementStatus": record.status,
                })
        return JsonResponse({"items": items, "page": page, "pageSize": size, "total": total, "totalPages": total_pages, "nodeNames": sorted(node_names)})
    except DomainValidationError as exc:
        return views._domain_error(exc)


@require_GET
def settlement_companies(request):
    from . import views
    denied = views._ensure_finance_manager(request)
    if denied is not None:
        return denied
    try:
        return JsonResponse({"items": get_auth_company_entities()})
    except AuthOrgClientError as exc:
        return views._error(str(exc), code="SETTLEMENT_DIRECTORY_UNAVAILABLE", status=exc.status_code)


@require_GET
def settlement_projects(request):
    from . import views
    denied = views._ensure_finance_manager(request)
    if denied is not None:
        return denied
    rows = related_projects(text(request.GET.get("userId")))
    try:
        rows = scope_crm_queryset(request, rows)
    except DomainValidationError as exc:
        return views._domain_error(exc)
    search = views._search_filter(request)
    if search:
        rows = filter_queryset_search(rows, search, ("name", "code", "customer"))
    return views._paginated(rows.order_by("-id"), request, lambda item: {
        "id": item.id, "name": item.name, "code": item.code,
        "customer": item.customer, "serviceTypeLabel": item.get_service_type_display(),
    })
