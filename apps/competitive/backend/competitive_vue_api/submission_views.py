from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, HttpResponse, JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt

from .domain import (
    PayloadError,
    apply_submission_patch,
    expires_from,
    parse_payload,
    queue_file_deletions,
    reopen_adopted_submission,
    require_catalog_product,
    sync_expiry_statuses,
    validate_required_collection_fields,
)
from .files import (
    FileTooLargeError,
    InvalidFileError,
    delete_stored_file,
    safe_storage_path,
    save_upload,
)
from .models import (
    CollectionDraft,
    Submission,
    SubmissionAttachment,
    SubmissionStatus,
)
from .product_catalog import ProductCatalogError, get_products
from .serializers import serialize_attachment, serialize_submission
from .view_helpers import (
    can_view_submission,
    error_response,
    json_body,
    page_result,
    pagination,
    request_access,
    submission_owner_filter,
)


INLINE_ATTACHMENT_TYPES = frozenset(
    {
        "application/pdf",
        "audio/mpeg",
        "audio/mp4",
        "audio/ogg",
        "audio/wav",
        "audio/webm",
        "image/avif",
        "image/bmp",
        "image/gif",
        "image/jpeg",
        "image/png",
        "image/webp",
        "video/mp4",
        "video/ogg",
        "video/webm",
    }
)


def _submission_query():
    return Submission.objects.filter(deleted_at__isnull=True).prefetch_related("attachments")


def _submission_or_none(submission_id, lock=False):
    queryset = _submission_query()
    if lock:
        queryset = queryset.select_for_update()
    return queryset.filter(id=submission_id).first()


@csrf_exempt
def submissions_root(request):
    if request.method == "POST":
        return create_submission(request)
    return submissions_collection(request)


def _filter_submissions(request, queryset):
    keyword = str(request.GET.get("q") or "").strip()
    status_value = str(request.GET.get("status") or "")
    if keyword:
        try:
            product_ids = [
                str(product["id"])
                for product in get_products()
                if any(
                    keyword.casefold() in str(product.get(field) or "").casefold()
                    for field in (
                        "name",
                        "shortName",
                        "fullName",
                        "model",
                        "kingdeeCode",
                    )
                )
            ]
        except ProductCatalogError as exc:
            return None, error_response(str(exc), exc.status_code)
        product_filter = Q(product_id__in=product_ids) if product_ids else Q(pk__in=[])
        queryset = queryset.filter(
            Q(owner__icontains=keyword)
            | Q(brand__icontains=keyword)
            | Q(name__icontains=keyword)
            | Q(model__icontains=keyword)
            | Q(region__icontains=keyword)
            | Q(city__icontains=keyword)
            | Q(product_id__icontains=keyword)
            | product_filter
        )
    if status_value:
        if status_value not in SubmissionStatus.values:
            return None, error_response("采集状态无效", 422)
        queryset = queryset.filter(status=status_value)
    return queryset, None


@require_http_methods(["GET"])
def submissions_collection(request):
    _access, error = request_access(request, "can_review")
    if error:
        return error
    page_values = pagination(request)
    if isinstance(page_values, JsonResponse):
        return page_values
    page, page_size = page_values
    sync_expiry_statuses()
    queryset, error = _filter_submissions(request, _submission_query())
    if error:
        return error
    queryset = queryset.order_by("-submitted_on", "id")
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


@require_http_methods(["GET"])
def my_submissions(request):
    _access, error = request_access(request, "can_collect")
    if error:
        return error
    page_values = pagination(request)
    if isinstance(page_values, JsonResponse):
        return page_values
    page, page_size = page_values
    sync_expiry_statuses()
    queryset = _submission_query().filter(submission_owner_filter(request))
    queryset, error = _filter_submissions(request, queryset)
    if error:
        return error
    queryset = queryset.order_by("-submitted_on", "id")
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


@csrf_exempt
@require_http_methods(["GET", "PATCH"])
def submission_detail(request, submission_id):
    access, error = request_access(request)
    if error:
        return error
    if request.method == "GET":
        submission = _submission_or_none(submission_id)
        if submission is None or not can_view_submission(request, access, submission):
            return error_response("采集记录不存在", 404)
        return JsonResponse(serialize_submission(submission))
    payload, error = json_body(request)
    if error:
        return error
    try:
        patch = parse_payload(payload, partial=True)
        with transaction.atomic():
            submission = _submission_or_none(submission_id, lock=True)
            if submission is None or not can_view_submission(request, access, submission):
                return error_response("采集记录不存在", 404)
            if submission.status == SubmissionStatus.EXPIRED:
                return error_response("已过期采集记录不能修改，请先延长有效期", 409)
            storage_keys = apply_submission_patch(submission, patch)
            queue_file_deletions(storage_keys)
    except ProductCatalogError as exc:
        return error_response(str(exc), exc.status_code)
    except PayloadError as exc:
        return error_response(str(exc), 422)
    submission = _submission_or_none(submission_id)
    return JsonResponse(serialize_submission(submission))


def _categories_for(parsed: dict, files: list) -> list[str]:
    categories = parsed.get("categories") or []
    if categories and len(categories) != len(files):
        raise PayloadError("categories 数量必须与 files 数量一致")
    if categories:
        return [str(item) for item in categories]
    by_file = parsed.get("categories_by_file") or {}
    return [
        str(by_file.get(f"{upload.name}-{index}") or "待归类")
        for index, upload in enumerate(files)
    ]


@csrf_exempt
@require_http_methods(["POST"])
def create_submission(request):
    _access, error = request_access(request, "can_collect")
    if error:
        return error
    try:
        parsed = parse_payload(request.POST.get("payload", "{}"))
        files = request.FILES.getlist("files")
        categories = _categories_for(parsed, files)
        require_catalog_product(parsed["product_id"])
    except ProductCatalogError as exc:
        return error_response(str(exc), exc.status_code)
    except PayloadError as exc:
        return error_response(str(exc), 422)
    stored_files = []
    try:
        stored_files = [save_upload(upload) for upload in files]
    except FileTooLargeError as exc:
        for stored in stored_files:
            delete_stored_file(stored.storage_key)
        return error_response(str(exc), 413)
    except InvalidFileError as exc:
        for stored in stored_files:
            delete_stored_file(stored.storage_key)
        return error_response(str(exc), 422)

    try:
        with transaction.atomic():
            draft = None
            draft_id = parsed.pop("draft_id", None)
            if draft_id:
                draft = (
                    CollectionDraft.objects.select_for_update()
                    .prefetch_related("attachments")
                    .filter(id=draft_id)
                    .first()
                )
                owns = draft and (
                    draft.owner_user_id == request.auth_user_id
                    if draft.owner_user_id
                    else draft.owner == (request.auth_actor_name or request.auth_user_name)
                )
                if not owns:
                    raise PayloadError("草稿不存在")
            draft_categories = list(draft.attachments.values_list("category", flat=True)) if draft else []
            validate_required_collection_fields(parsed, [*draft_categories, *categories])
            region_value = parsed.pop("region")
            city_value = parsed.pop("city", "")
            region, separator, city_from_region = region_value.partition("/")
            submitted_on = parsed.pop("submitted_on")
            expires_on = parsed.pop("expires_on", None) or expires_from(
                submitted_on, parsed["validity"]
            )
            for key in ("categories", "categories_by_file", "attachments", "review_comment"):
                parsed.pop(key, None)
            submission = Submission.objects.create(
                **parsed,
                owner=request.auth_actor_name or request.auth_user_name,
                owner_user_id=request.auth_user_id,
                region=region.strip(),
                city=city_value or (city_from_region.strip() if separator else ""),
                expires_on=expires_on,
                submitted_on=submitted_on,
                review_comment="",
                status=SubmissionStatus.PENDING,
            )
            draft_attachments = list(draft.attachments.all()) if draft else []
            SubmissionAttachment.objects.bulk_create(
                [
                    SubmissionAttachment(
                        submission=submission,
                        filename=item.filename,
                        byte_size=item.byte_size,
                        media_type=item.media_type,
                        category=item.category,
                        storage_key=item.storage_key,
                    )
                    for item in draft_attachments
                ]
                + [
                    SubmissionAttachment(
                        submission=submission,
                        filename=stored.original_name,
                        byte_size=stored.size,
                        media_type=stored.content_type,
                        category=categories[index],
                        storage_key=stored.storage_key,
                    )
                    for index, stored in enumerate(stored_files)
                ]
            )
            if draft:
                draft.delete()
    except (PayloadError, TypeError, ValueError) as exc:
        for stored in stored_files:
            delete_stored_file(stored.storage_key)
        return error_response(str(exc), 404 if str(exc) == "草稿不存在" else 422)
    submission = _submission_or_none(submission.id)
    return JsonResponse(serialize_submission(submission), status=201)


@csrf_exempt
@require_http_methods(["POST"])
def add_attachment(request, submission_id):
    access, error = request_access(request)
    if error:
        return error
    upload = request.FILES.get("file")
    category = str(request.POST.get("category") or "").strip()
    if upload is None or not category or len(category) > 80:
        return error_response("附件和资料归属不能为空", 422)
    try:
        stored = save_upload(upload)
    except FileTooLargeError as exc:
        return error_response(str(exc), 413)
    except InvalidFileError as exc:
        return error_response(str(exc), 422)
    try:
        with transaction.atomic():
            submission = _submission_or_none(submission_id, lock=True)
            if submission is None or not can_view_submission(request, access, submission):
                raise PayloadError("采集记录不存在")
            if submission.status == SubmissionStatus.EXPIRED:
                delete_stored_file(stored.storage_key)
                return error_response("已过期采集记录不能修改，请先延长有效期", 409)
            reopen_adopted_submission(submission)
            submission.save(update_fields=["status", "updated_at"])
            attachment = SubmissionAttachment.objects.create(
                submission=submission,
                filename=stored.original_name,
                byte_size=stored.size,
                media_type=stored.content_type,
                category=category,
                storage_key=stored.storage_key,
            )
    except PayloadError as exc:
        delete_stored_file(stored.storage_key)
        return error_response(str(exc), 404)
    return JsonResponse(serialize_attachment(attachment), status=201)


@csrf_exempt
@require_http_methods(["PATCH", "DELETE"])
def attachment_detail(request, submission_id, attachment_id):
    access, error = request_access(request)
    if error:
        return error
    with transaction.atomic():
        submission = _submission_or_none(submission_id, lock=True)
        if submission is None or not can_view_submission(request, access, submission):
            return error_response("采集记录不存在", 404)
        if submission.status == SubmissionStatus.EXPIRED:
            return error_response("已过期采集记录不能修改，请先延长有效期", 409)
        attachment = SubmissionAttachment.objects.filter(
            id=attachment_id, submission_id=submission_id
        ).first()
        if attachment is None:
            return error_response("附件不存在", 404)
        reopen_adopted_submission(submission)
        submission.save(update_fields=["status", "updated_at"])
        if request.method == "DELETE":
            storage_key = attachment.storage_key
            attachment.delete()
            if storage_key:
                queue_file_deletions([storage_key])
            return HttpResponse(status=204)
        payload, error = json_body(request)
        if error:
            return error
        category = str(payload.get("category") or "").strip()
        if not category or len(category) > 80:
            return error_response("资料归属不能为空", 422)
        attachment.category = category
        attachment.save(update_fields=["category", "updated_at"])
    return JsonResponse(serialize_attachment(attachment))


@require_http_methods(["GET"])
def attachment_content(request, submission_id, attachment_id):
    access, error = request_access(request)
    if error:
        return error
    submission = _submission_or_none(submission_id)
    if submission is None or not can_view_submission(request, access, submission):
        return error_response("采集记录不存在", 404)
    attachment = SubmissionAttachment.objects.filter(
        id=attachment_id, submission_id=submission_id
    ).first()
    if attachment is None or not attachment.storage_key:
        return error_response("附件文件不存在", 404)
    try:
        path = safe_storage_path(attachment.storage_key)
    except InvalidFileError:
        return error_response("附件文件不存在", 404)
    if not path.is_file():
        return error_response("附件文件不存在", 404)
    normalized_type = attachment.media_type.partition(";")[0].strip().lower()
    download = str(request.GET.get("download") or "").lower() in {"1", "true", "yes"}
    disposition = "inline" if not download and normalized_type in INLINE_ATTACHMENT_TYPES else "attachment"
    return FileResponse(
        path.open("rb"),
        content_type=attachment.media_type,
        as_attachment=disposition == "attachment",
        filename=attachment.filename,
    )
