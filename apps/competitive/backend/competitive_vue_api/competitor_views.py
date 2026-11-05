from django.db.models import Q
from django.db.models.functions import Lower, Trim
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from .domain import (
    normalize_competitor_parameter_text,
    sync_expiry_statuses,
    version_sort_key,
)
from .models import (
    Competitor,
    CompetitorRelease,
    CompetitorStatus,
    Submission,
    SubmissionAttachment,
)
from .board_cache import get_competitor_board_summary
from .product_catalog import ProductCatalogError, get_product, get_product_detail, get_products
from .serializers import (
    serialize_attachment,
    serialize_competitor,
    serialize_parameter,
    serialize_release,
    serialize_release_parameter,
    serialize_submission,
    serialize_version,
)
from .view_helpers import error_response, page_result, pagination, request_access


def _competitor_or_none(competitor_id):
    return (
        Competitor.objects.filter(id=competitor_id, deleted_at__isnull=True)
        .prefetch_related(
            "parameters",
            "versions",
            "releases__submissions",
            "submissions__attachments",
        )
        .first()
    )


def _historical_product(product_id: str) -> dict:
    """Keep archived competitors readable when their catalog product was removed."""
    normalized_id = str(product_id or "").strip() or "未知"
    label = f"历史产品（ID: {normalized_id}）"
    return {
        "id": normalized_id,
        "name": label,
        "shortName": "",
        "fullName": "",
        "model": "",
        "brand": "",
        "productDomain": "历史产品",
        "levelTwo": "",
        "category": "",
        "categoryA": "",
        "categoryB": "",
        "kingdeeCode": "",
        "unit": "",
        "unitPrice": "",
        "salespersonPrice": "",
        "distributorPrice": "",
        "budgetPrice": "",
        "marketReferencePrice": "",
        "bidPara": "",
        "tenderPara": "",
        "planPara": "",
        "specText": "",
        "comments": "产品档案已下线或删除，以下内容来自历史竞品资料。",
        "phase": 0,
        "archiveUpdatedAt": "",
        "isActive": False,
        "archiveUnavailable": True,
        "hasImage": False,
        "line": "历史产品",
        "segment": "",
        "image": "",
        "imagePreview": "",
        "coverage": "有竞品",
    }


def _serialize_competitor_rows(rows: list[Competitor]) -> list[dict]:
    product_ids = {str(item.product_id) for item in rows if item.product_id}
    competitor_ids = [item.id for item in rows]
    product_map = {}
    if product_ids:
        try:
            product_map = {
                product["id"]: product
                for product in get_products()
                if product["id"] in product_ids
            }
        except ProductCatalogError:
            product_map = {}
    cover_map = {}
    if competitor_ids:
        image_attachments = (
            SubmissionAttachment.objects.filter(
                submission__competitor_id__in=competitor_ids,
                submission__deleted_at__isnull=True,
            )
            .annotate(normalized_media_type=Lower(Trim("media_type")))
            .filter(normalized_media_type__startswith="image/")
            .select_related("submission")
            .only(
                "id",
                "submission_id",
                "filename",
                "media_type",
                "category",
                "created_at",
                "submission__competitor_id",
            )
            .order_by("created_at", "id")
        )
        for attachment in image_attachments:
            competitor_id = attachment.submission.competitor_id
            current = cover_map.get(competitor_id)
            is_product_image = attachment.category.strip() == "产品图片"
            if current is None or (
                is_product_image and current.category.strip() != "产品图片"
            ):
                cover_map[competitor_id] = attachment
    result = []
    for competitor in rows:
        item = serialize_competitor(competitor)
        product = product_map.get(str(competitor.product_id))
        item["product"] = (
            {
                "id": product["id"],
                "name": product["name"],
                "fullName": product.get("fullName", ""),
                "hasImage": bool(product.get("hasImage")),
            }
            if product
            else None
        )
        cover = cover_map.get(competitor.id)
        item["coverSubmission"] = (
            {
                "id": str(cover.submission_id),
                "attachments": [
                    {
                        "id": str(cover.id),
                        "name": cover.filename,
                        "type": cover.media_type,
                        "category": cover.category,
                    }
                ],
            }
            if cover
            else None
        )
        result.append(item)
    return result


def _release_competitor(competitor: Competitor, release: CompetitorRelease) -> dict:
    result = serialize_competitor(competitor)
    result.update(
        {
            "brand": release.brand,
            "name": release.name,
            "model": release.model,
            "regions": list(release.regions or []),
            "sources": serialize_release(release)["sourceCount"],
            "updated": release.changed_on.isoformat(),
            "expires": release.expires_on.isoformat(),
            "status": release.status,
            "price": release.price,
            "dealer": release.dealer,
        }
    )
    return result


@require_http_methods(["GET"])
def competitors_collection(request):
    _access, error = request_access(request)
    if error:
        return error
    page_values = pagination(request)
    if isinstance(page_values, JsonResponse):
        return page_values
    page, page_size = page_values
    sync_expiry_statuses()
    queryset = Competitor.objects.filter(deleted_at__isnull=True)
    keyword = str(request.GET.get("q") or "").strip()
    if keyword:
        try:
            product_ids = [
                product["id"]
                for product in get_products()
                if keyword.casefold()
                in " ".join(
                    (
                        product["name"],
                        product["model"],
                        product["line"],
                    )
                ).casefold()
            ]
        except ProductCatalogError as exc:
            return error_response(str(exc), exc.status_code)
        queryset = queryset.filter(
            Q(brand__icontains=keyword)
            | Q(name__icontains=keyword)
            | Q(model__icontains=keyword)
            | Q(product_id__in=product_ids)
        )
    product_id = str(request.GET.get("productId") or "")
    status_value = str(request.GET.get("status") or "")
    region = str(request.GET.get("region") or "")
    if product_id:
        queryset = queryset.filter(product_id=product_id)
    if status_value:
        if status_value not in CompetitorStatus.values:
            return error_response("竞品状态无效", 422)
        queryset = queryset.filter(status=status_value)
    if region:
        matching_ids = [
            item["id"]
            for item in queryset.values("id", "regions")
            if region in (item.get("regions") or [])
        ]
        queryset = queryset.filter(id__in=matching_ids)
    total = queryset.count()
    start = (page - 1) * page_size
    rows = list(queryset.order_by("-updated_on", "id")[start : start + page_size])
    response = JsonResponse(
        page_result(_serialize_competitor_rows(rows), total, page, page_size),
    )
    response["Cache-Control"] = "private, max-age=5"
    return response


@require_http_methods(["GET"])
def competitor_board_summary(request):
    _access, error = request_access(request)
    if error:
        return error
    response = JsonResponse({"items": get_competitor_board_summary()})
    response["Cache-Control"] = "private, max-age=15"
    return response


@require_http_methods(["GET"])
def competitor_detail_legacy(request, competitor_id):
    _access, error = request_access(request)
    if error:
        return error
    sync_expiry_statuses()
    competitor = _competitor_or_none(competitor_id)
    if competitor is None:
        return error_response("竞品不存在", 404)
    return JsonResponse(
        {
            **serialize_competitor(competitor),
            "submissions": [
                serialize_submission(item)
                for item in competitor.submissions.filter(deleted_at__isnull=True)
            ],
        }
    )


@require_http_methods(["GET"])
def competitor_detail(request, competitor_id):
    _access, error = request_access(request)
    if error:
        return error
    sync_expiry_statuses()
    competitor = _competitor_or_none(competitor_id)
    if competitor is None:
        return error_response("竞品不存在", 404)
    try:
        product = get_product(competitor.product_id)
    except ProductCatalogError as exc:
        return error_response(str(exc), exc.status_code)
    if product is None:
        product = _historical_product(competitor.product_id)
    else:
        product = get_product_detail(product)
    releases = sorted(competitor.releases.all(), key=lambda item: item.number, reverse=True)
    requested_version_id = str(request.GET.get("versionId") or "").strip()
    selected_release = next(
        (
            item
            for item in releases
            if requested_version_id and str(item.id) == requested_version_id
        ),
        None,
    )
    if requested_version_id and selected_release is None:
        return error_response("竞品版本不存在", 404)
    if selected_release is None:
        selected_release = next(
            (item for item in releases if item.is_current),
            releases[0] if releases else None,
        )
    all_sources = sorted(
        (
            item
            for item in competitor.submissions.all()
            if item.deleted_at is None
        ),
        key=lambda item: (item.submitted_on, item.created_at),
        reverse=True,
    )
    sources = (
        [
            item
            for item in all_sources
            if item.competitor_release_id == selected_release.id
        ]
        if selected_release is not None
        else all_sources
    )
    parameter_source = None
    for item in sources:
        source_text = normalize_competitor_parameter_text(item.competitor_parameters)
        if source_text:
            parameter_source = {
                "submissionId": str(item.id),
                "owner": item.owner,
                "date": item.submitted_on.isoformat(),
                "text": source_text,
            }
            break
    region_sources = [
        {
            "id": str(item.id),
            "owner": item.owner,
            "region": item.region,
            "city": item.city,
            "price": item.price,
            "dealer": item.dealer,
            "customer": item.customer,
            "date": item.submitted_on.isoformat(),
            "status": item.status,
            "files": len(item.attachments.all()),
            "note": item.note,
            "location": item.location,
            "located": item.located,
            "latitude": item.latitude,
            "longitude": item.longitude,
            "locationAccuracy": item.location_accuracy,
            "locatedAt": item.located_at.isoformat() if item.located_at else None,
            "locationSource": item.location_source,
        }
        for item in sources
    ]
    media = [
        serialize_attachment(attachment)
        for item in sources
        for attachment in item.attachments.all()
    ]
    history = sorted(competitor.versions.all(), key=version_sort_key, reverse=True)
    competitor_payload = (
        _release_competitor(competitor, selected_release)
        if selected_release is not None
        else serialize_competitor(competitor)
    )
    parameters = (
        [
            serialize_release_parameter(item, selected_release.id, position)
            for position, item in enumerate(selected_release.parameters or [])
            if str(item.get("text") or "").strip()
        ]
        if selected_release is not None
        else [serialize_parameter(item) for item in competitor.parameters.all()]
    )
    return JsonResponse(
        {
            "competitor": competitor_payload,
            "product": product,
            "advantage": selected_release.advantage if selected_release else competitor.advantage,
            "weakness": selected_release.weakness if selected_release else competitor.weakness,
            "tactic": selected_release.tactic if selected_release else competitor.tactic,
            "parameters": parameters,
            "parameterSource": parameter_source,
            "selectedVersion": (
                serialize_release(selected_release) if selected_release else None
            ),
            "versions": [serialize_release(item) for item in releases],
            "history": [serialize_version(item) for item in history],
            "regionSources": region_sources,
            "media": media,
        }
    )


@require_http_methods(["GET"])
def competitor_submissions(request, competitor_id):
    _access, error = request_access(request)
    if error:
        return error
    if not Competitor.objects.filter(id=competitor_id, deleted_at__isnull=True).exists():
        return error_response("竞品不存在", 404)
    page_values = pagination(request)
    if isinstance(page_values, JsonResponse):
        return page_values
    page, page_size = page_values
    queryset = (
        Submission.objects.filter(
            competitor_id=competitor_id,
            deleted_at__isnull=True,
        )
        .prefetch_related("attachments")
        .order_by("-submitted_on", "id")
    )
    total = queryset.count()
    start = (page - 1) * page_size
    return JsonResponse(
        page_result(
            [serialize_submission(item) for item in queryset[start : start + page_size]],
            total,
            page,
            page_size,
        )
    )
