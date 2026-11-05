from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt

from .domain import PayloadError, SUBMISSION_FIELDS, parse_payload
from .files import FileTooLargeError, InvalidFileError, delete_stored_file, save_upload
from .models import CollectionDraft, CollectionDraftAttachment
from .serializers import serialize_draft_attachment
from .view_helpers import error_response, request_access


def _draft_owner_filter(request):
    from django.db.models import Q

    operator_name = request.auth_actor_name or request.auth_user_name
    return Q(owner_user_id=request.auth_user_id) | Q(
        owner_user_id__isnull=True,
        owner=operator_name,
    )


def _owns_draft(draft, request):
    return (
        draft.owner_user_id == request.auth_user_id
        if draft.owner_user_id
        else draft.owner == (request.auth_actor_name or request.auth_user_name)
    )


def _camel_payload(values: dict) -> dict:
    reverse = {value: key for key, value in SUBMISSION_FIELDS.items()}
    result = {}
    for key, value in values.items():
        if hasattr(value, "isoformat"):
            value = value.isoformat()
        result[reverse.get(key, key)] = value
    return result


def _serialize_draft(draft):
    return {
        "id": str(draft.id),
        "owner": draft.owner,
        "payload": dict(draft.payload or {}),
        "attachments": [
            serialize_draft_attachment(item) for item in draft.attachments.all()
        ],
        "createdAt": draft.created_at.isoformat(),
        "updatedAt": draft.updated_at.isoformat(),
    }


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


@require_http_methods(["GET"])
def latest_draft(request):
    _access, error = request_access(request, "can_collect")
    if error:
        return error
    draft = (
        CollectionDraft.objects.filter(_draft_owner_filter(request))
        .prefetch_related("attachments")
        .order_by("-updated_at")
        .first()
    )
    return JsonResponse(_serialize_draft(draft) if draft else None, safe=False)


@csrf_exempt
@require_http_methods(["POST"])
def save_draft(request):
    _access, error = request_access(request, "can_collect")
    if error:
        return error
    try:
        parsed = parse_payload(request.POST.get("payload", "{}"), draft=True)
        files = request.FILES.getlist("files")
        categories = _categories_for(parsed, files)
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

    draft_id = request.POST.get("draftId")
    try:
        with transaction.atomic():
            if draft_id:
                draft = CollectionDraft.objects.select_for_update().filter(id=draft_id).first()
                if draft is None or not _owns_draft(draft, request):
                    raise PayloadError("草稿不存在")
            else:
                draft = CollectionDraft.objects.create(
                    owner=request.auth_actor_name or request.auth_user_name,
                    owner_user_id=request.auth_user_id,
                    payload={},
                )
            draft.payload = _camel_payload(
                {
                    key: value
                    for key, value in parsed.items()
                    if key not in {"categories", "categories_by_file"}
                }
            )
            draft.save(update_fields=["payload", "updated_at"])
            CollectionDraftAttachment.objects.bulk_create(
                [
                    CollectionDraftAttachment(
                        draft=draft,
                        filename=stored.original_name,
                        byte_size=stored.size,
                        media_type=stored.content_type,
                        category=categories[index],
                        storage_key=stored.storage_key,
                    )
                    for index, stored in enumerate(stored_files)
                ]
            )
    except (PayloadError, ValueError) as exc:
        for stored in stored_files:
            delete_stored_file(stored.storage_key)
        return error_response(str(exc), 404 if str(exc) == "草稿不存在" else 422)
    draft = CollectionDraft.objects.prefetch_related("attachments").get(id=draft.id)
    return JsonResponse(_serialize_draft(draft), status=201)


@csrf_exempt
@require_http_methods(["DELETE"])
def delete_draft(request, draft_id):
    _access, error = request_access(request, "can_collect")
    if error:
        return error
    with transaction.atomic():
        draft = (
            CollectionDraft.objects.select_for_update()
            .prefetch_related("attachments")
            .filter(id=draft_id)
            .first()
        )
        if draft is None or not _owns_draft(draft, request):
            return error_response("草稿不存在", 404)
        storage_keys = list(draft.attachments.values_list("storage_key", flat=True))
        draft.delete()
    for storage_key in storage_keys:
        try:
            delete_stored_file(storage_key)
        except InvalidFileError:
            pass
    return HttpResponse(status=204)
