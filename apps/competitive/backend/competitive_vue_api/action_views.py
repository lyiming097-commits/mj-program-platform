from datetime import date, datetime, timezone

from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt

from .domain import (
    PayloadError,
    apply_submission_patch,
    changed_competitor_fields,
    competitor_snapshot,
    next_version_number,
    parameter_candidate_text,
    parse_date,
    parse_payload,
    queue_file_deletions,
    split_competitor_parameter_text,
    sync_competitor_parameters,
    validate_required_collection_fields,
)
from .board_cache import invalidate_competitor_board_summary
from .models import (
    Competitor,
    CompetitorRelease,
    CompetitorStatus,
    CompetitorVersion,
    Submission,
    SubmissionStatus,
)
from .maintenance import SOFT_DELETE_RETENTION
from .product_catalog import ProductCatalogError
from .product_views import invalidate_product_board_cache
from .releases import (
    apply_release_to_competitor,
    apply_result_to_release,
    ensure_current_release,
    next_release_number,
    release_snapshot,
    sync_competitor_source_count,
)
from .serializers import (
    serialize_competitor,
    serialize_release,
    serialize_release_parameter,
    serialize_submission,
    serialize_version,
)
from .view_helpers import error_response, json_body, request_access


def _submission(submission_id, lock=True):
    queryset = Submission.objects.filter(
        id=submission_id,
        deleted_at__isnull=True,
    ).prefetch_related("attachments")
    if lock:
        queryset = queryset.select_for_update()
    return queryset.first()


def _operator_name(request):
    return request.auth_actor_name or request.auth_user_name


def _resolution(submission, competitor):
    submission = Submission.objects.prefetch_related("attachments").get(id=submission.id)
    return JsonResponse(
        {
            "submission": serialize_submission(submission),
            "competitor": serialize_competitor(competitor),
            "version": (
                serialize_release(submission.competitor_release)
                if submission.competitor_release_id
                else None
            ),
        }
    )


def _normalize_parameter_items(parameters):
    if parameters is None:
        parameters = []
    if not isinstance(parameters, list) or len(parameters) > 100:
        raise PayloadError("竞品参数格式无效")
    normalized = []
    seen = set()
    for item in parameters:
        text = parameter_candidate_text(item)
        if not text or len(text) > 2000:
            raise PayloadError("竞品参数内容无效")
        key = text.casefold()
        if key in seen:
            continue
        normalized.append(text)
        seen.add(key)
    return normalized


def _normalize_merge_result(payload):
    if not isinstance(payload, dict):
        raise PayloadError("审核结果格式无效")
    result = {}
    for field, maximum, required in (
        ("brand", 160, True),
        ("name", 200, True),
        ("model", 160, True),
        ("price", 120, False),
        ("dealer", None, False),
        ("advantage", 2000, False),
        ("weakness", 2000, False),
        ("tactic", 2000, False),
    ):
        value = str(payload.get(field) or "").strip() if required else str(payload.get(field) or "")
        if required and not value:
            raise PayloadError(f"{field} 不能为空")
        if maximum and len(value) > maximum:
            raise PayloadError(f"{field} 内容过长")
        result[field] = value
    result["expires_on"] = parse_date(payload.get("expires"), "expires")
    result["parameters"] = _normalize_parameter_items(payload.get("parameters"))
    return result


def _normalize_competitor_update(payload):
    if not isinstance(payload, dict):
        raise PayloadError("竞品资料格式无效")
    result = {}
    for field, label, maximum, required in (
        ("brand", "竞品品牌", 160, True),
        ("name", "产品名称", 200, True),
        ("model", "产品型号", 160, False),
        ("price", "单价", 120, False),
        ("dealer", "经销商", None, False),
        ("advantage", "竞品优势", 2000, False),
        ("weakness", "竞品劣势", 2000, False),
        ("tactic", "销售应对策略", 2000, False),
    ):
        value = str(payload.get(field) or "")
        if required:
            value = value.strip()
        if required and not value:
            raise PayloadError(f"{label}不能为空")
        if maximum and len(value) > maximum:
            raise PayloadError(f"{label}内容过长")
        result[field] = value
    result["expires_on"] = parse_date(payload.get("expires"), "有效期")
    if "parameters" in payload:
        result["parameters"] = _normalize_parameter_items(payload.get("parameters"))
    else:
        result["parameters"] = split_competitor_parameter_text(
            payload.get("competitorParameterText", "")
        )
    return result


@csrf_exempt
@require_http_methods(["DELETE"])
def soft_delete_competitor(request, competitor_id):
    _access, error = request_access(request, "can_manage")
    if error:
        return error
    deleted_at = datetime.now(timezone.utc)
    with transaction.atomic():
        competitor = (
            Competitor.objects.select_for_update()
            .filter(id=competitor_id, deleted_at__isnull=True)
            .first()
        )
        if competitor is None:
            return error_response("竞品不存在", 404)
        submissions = list(
            Submission.objects.select_for_update().filter(
                competitor_id=competitor_id,
                deleted_at__isnull=True,
            )
        )
        competitor.deleted_at = deleted_at
        competitor.save(update_fields=["deleted_at", "updated_at"])
        Submission.objects.filter(id__in=[item.id for item in submissions]).update(
            deleted_at=deleted_at
        )
    invalidate_competitor_board_summary()
    invalidate_product_board_cache()
    return JsonResponse(
        {
            "competitorId": str(competitor.id),
            "submissionIds": [str(item.id) for item in submissions],
            "purgeAfter": (deleted_at + SOFT_DELETE_RETENTION).isoformat(),
        }
    )


@csrf_exempt
@require_http_methods(["PATCH"])
def update_competitor(request, competitor_id):
    _access, error = request_access(request, "can_review")
    if error:
        return error
    payload, error = json_body(request)
    if error:
        return error
    try:
        result = _normalize_competitor_update(payload)
        with transaction.atomic():
            competitor = (
                Competitor.objects.select_for_update()
                .prefetch_related("parameters", "versions", "releases")
                .filter(id=competitor_id, deleted_at__isnull=True)
                .first()
            )
            if competitor is None:
                return error_response("竞品不存在", 404)
            version_id = str(payload.get("versionId") or "").strip()
            release = (
                CompetitorRelease.objects.select_for_update()
                .filter(
                    id=version_id,
                    competitor=competitor,
                )
                .first()
                if version_id
                else ensure_current_release(
                    competitor,
                    changed_by=_operator_name(request),
                )
            )
            if release is None:
                return error_response("竞品版本不存在", 404)
            before = release_snapshot(release)
            apply_result_to_release(release, result)
            after = release_snapshot(release)
            changed_fields = changed_competitor_fields(before, after)
            version = None
            if changed_fields:
                release.save()
                if release.is_current:
                    apply_release_to_competitor(competitor, release)
                version = CompetitorVersion.objects.create(
                    competitor=competitor,
                    version=f"V{next_version_number(competitor)}",
                    changed_on=date.today(),
                    note=(
                        f"直接编辑正式竞品 {f'V{release.number}'}，"
                        f"更新：{'、'.join(changed_fields)}。"
                    ),
                    action="人工编辑",
                    changed_by=_operator_name(request),
                    snapshot=after,
                )
    except (PayloadError, ValidationError, ValueError) as exc:
        return error_response(str(exc), 422)
    if changed_fields:
        invalidate_competitor_board_summary()
        invalidate_product_board_cache()
    competitor = Competitor.objects.prefetch_related("parameters").get(id=competitor.id)
    return JsonResponse(
        {
            "competitor": serialize_competitor(competitor),
            "advantage": release.advantage,
            "weakness": release.weakness,
            "tactic": release.tactic,
            "parameters": [
                serialize_release_parameter(item, release.id, position)
                for position, item in enumerate(release.parameters or [])
            ],
            "release": serialize_release(release),
            "version": serialize_version(version) if version else None,
            "changedFields": changed_fields,
        }
    )


@csrf_exempt
@require_http_methods(["POST"])
def extend_expiry(request, submission_id):
    _access, error = request_access(request, "can_review")
    if error:
        return error
    payload, error = json_body(request)
    if error:
        return error
    try:
        expires_on = parse_date(payload.get("expires"), "expires")
    except PayloadError as exc:
        return error_response(str(exc), 422)
    with transaction.atomic():
        submission = _submission(submission_id)
        if submission is None:
            return error_response("采集记录不存在", 404)
        if submission.status != SubmissionStatus.EXPIRED:
            return error_response("只有已过期的采集记录可以延长时间", 409)
        if expires_on <= date.today():
            return error_response("新的有效期必须晚于今天", 422)
        previous_expiry = submission.expires_on
        submission.expires_on = expires_on
        submission.status = (
            SubmissionStatus.ADOPTED
            if submission.competitor_id is not None
            else SubmissionStatus.PENDING
        )
        submission.save(update_fields=["expires_on", "status", "updated_at"])
        competitor = None
        if submission.competitor_id:
            competitor = (
                Competitor.objects.select_for_update()
                .prefetch_related("parameters", "versions", "releases")
                .filter(id=submission.competitor_id, deleted_at__isnull=True)
                .first()
            )
            if competitor is None:
                return error_response("已关联记录缺少竞品档案", 409)
            release = (
                CompetitorRelease.objects.select_for_update()
                .filter(id=submission.competitor_release_id, competitor=competitor)
                .first()
                if submission.competitor_release_id
                else ensure_current_release(competitor)
            )
            release.expires_on = expires_on
            release.changed_on = date.today()
            release.status = CompetitorStatus.NORMAL
            release.save(
                update_fields=[
                    "expires_on",
                    "changed_on",
                    "status",
                    "updated_at",
                ]
            )
            if submission.competitor_release_id is None:
                submission.competitor_release = release
                submission.save(update_fields=["competitor_release", "updated_at"])
            if release.is_current:
                apply_release_to_competitor(competitor, release)
            CompetitorVersion.objects.create(
                competitor=competitor,
                version=f"V{next_version_number(competitor)}",
                changed_on=date.today(),
                note=(
                    f"正式竞品 V{release.number} 有效期由 "
                    f"{previous_expiry.isoformat()} 延长至 {expires_on.isoformat()}。"
                ),
                action="延长有效期",
                changed_by=_operator_name(request),
                source_submission=submission,
                snapshot=release_snapshot(release),
            )
    submission = Submission.objects.prefetch_related("attachments").get(id=submission.id)
    return JsonResponse(
        {
            "submission": serialize_submission(submission),
            "competitor": serialize_competitor(competitor) if competitor else None,
        }
    )


@csrf_exempt
@require_http_methods(["POST"])
def return_submission(request, submission_id):
    _access, error = request_access(request, "can_review")
    if error:
        return error
    payload, error = json_body(request)
    if error:
        return error
    comment = str(payload.get("reviewComment") or "").strip()
    if not comment or len(comment) > 2000:
        return error_response("退回原因不能为空", 422)
    try:
        patch = parse_payload(payload.get("submission") or {}, partial=True)
        with transaction.atomic():
            submission = _submission(submission_id)
            if submission is None:
                return error_response("采集记录不存在", 404)
            storage_keys = apply_submission_patch(submission, patch)
            queue_file_deletions(storage_keys)
            submission.review_comment = comment
            submission.status = SubmissionStatus.NEEDS_INFO
            submission.save(update_fields=["review_comment", "status", "updated_at"])
    except ProductCatalogError as exc:
        return error_response(str(exc), exc.status_code)
    except PayloadError as exc:
        return error_response(str(exc), 422)
    submission = Submission.objects.prefetch_related("attachments").get(id=submission.id)
    return JsonResponse(serialize_submission(submission))


@csrf_exempt
@require_http_methods(["POST"])
def resubmit_submission(request, submission_id):
    _access, error = request_access(request, "can_collect")
    if error:
        return error
    with transaction.atomic():
        submission = _submission(submission_id)
        if submission is None:
            return error_response("采集记录不存在", 404)
        owns = (
            submission.owner_user_id == request.auth_user_id
            if submission.owner_user_id
            else submission.owner == _operator_name(request)
        )
        if not owns:
            return error_response("不能提交他人的采集记录", 403)
        if submission.status not in {
            SubmissionStatus.PENDING,
            SubmissionStatus.NEEDS_INFO,
            SubmissionStatus.ADOPTED,
        }:
            return error_response("当前状态不能重新提交审核", 409)
        try:
            validate_required_collection_fields(
                submission,
                list(submission.attachments.values_list("category", flat=True)),
            )
        except PayloadError as exc:
            return error_response(str(exc), 422)
        submission.review_comment = ""
        submission.status = SubmissionStatus.PENDING
        submission.save(update_fields=["review_comment", "status", "updated_at"])
    submission = Submission.objects.prefetch_related("attachments").get(id=submission.id)
    return JsonResponse(serialize_submission(submission))


@csrf_exempt
@require_http_methods(["POST"])
def create_competitor(request, submission_id):
    _access, error = request_access(request, "can_review")
    if error:
        return error
    payload, error = json_body(request)
    if error:
        return error
    try:
        patch = parse_payload(payload.get("submission") or {}, partial=True)
        with transaction.atomic():
            submission = _submission(submission_id)
            if submission is None:
                return error_response("采集记录不存在", 404)
            if submission.status == SubmissionStatus.ADOPTED:
                competitor = (
                    Competitor.objects.prefetch_related("parameters", "releases")
                    .filter(id=submission.competitor_id)
                    .first()
                )
                if competitor is None:
                    return error_response("已采纳记录缺少关联竞品", 409)
                if submission.competitor_release_id is None:
                    submission.competitor_release = ensure_current_release(competitor)
                    submission.save(update_fields=["competitor_release", "updated_at"])
                return _resolution(submission, competitor)
            if submission.competitor_id is not None:
                return error_response("已关联竞品的采集记录不能新建竞品，只能差异更新原竞品", 409)
            if submission.status != SubmissionStatus.PENDING:
                return error_response("只有待审核的采集记录可以新建竞品", 409)
            storage_keys = apply_submission_patch(submission, patch)
            queue_file_deletions(storage_keys)
            competitor = Competitor.objects.create(
                product_id=submission.product_id,
                brand=submission.brand,
                name=submission.name,
                model=submission.model,
                regions=[submission.region],
                sources=1,
                updated_on=date.today(),
                expires_on=submission.expires_on,
                status=CompetitorStatus.NORMAL,
                price=submission.price,
                dealer=submission.dealer,
                advantage=submission.advantage,
                weakness=submission.weakness,
                tactic=submission.tactic,
            )
            sync_competitor_parameters(competitor, submission.competitor_parameters)
            snapshot = competitor_snapshot(competitor)
            release = ensure_current_release(
                competitor,
                changed_by=_operator_name(request),
                note="由审核通过的采集申请生成首个正式版本。",
            )
            submission.competitor = competitor
            submission.competitor_release = release
            submission.status = SubmissionStatus.ADOPTED
            submission.save(
                update_fields=[
                    "competitor",
                    "competitor_release",
                    "status",
                    "updated_at",
                ]
            )
            apply_release_to_competitor(competitor, release)
            CompetitorVersion.objects.create(
                competitor=competitor,
                version=f"V{next_version_number(competitor)}",
                changed_on=date.today(),
                note="根据审核通过的采集资料新建竞品档案 V1。",
                action="新建竞品",
                changed_by=_operator_name(request),
                source_submission=submission,
                snapshot=snapshot,
            )
    except ProductCatalogError as exc:
        return error_response(str(exc), exc.status_code)
    except PayloadError as exc:
        return error_response(str(exc), 422)
    invalidate_competitor_board_summary()
    invalidate_product_board_cache()
    return _resolution(submission, competitor)


@csrf_exempt
@require_http_methods(["POST"])
def merge_submission(request, submission_id):
    _access, error = request_access(request, "can_review")
    if error:
        return error
    payload, error = json_body(request)
    if error:
        return error
    try:
        competitor_id = payload.get("competitorId")
        if not competitor_id:
            raise PayloadError("请选择目标竞品")
        mode = str(payload.get("mode") or "mergeExisting")
        if mode not in {"mergeExisting", "newVersion"}:
            raise PayloadError("采纳方式无效")
        target_version_id = str(payload.get("versionId") or "").strip()
        patch = parse_payload(payload.get("submission") or {}, partial=True)
        result = _normalize_merge_result(payload.get("result"))
        with transaction.atomic():
            submission = _submission(submission_id)
            if submission is None:
                return error_response("采集记录不存在", 404)
            if submission.status != SubmissionStatus.PENDING:
                return error_response("只有待审核的采集记录可以归并", 409)
            if submission.competitor_id and str(submission.competitor_id) != str(competitor_id):
                return error_response("已关联竞品的采集记录只能更新原竞品", 409)
            competitor = (
                Competitor.objects.select_for_update()
                .prefetch_related("parameters", "versions", "releases")
                .filter(id=competitor_id, deleted_at__isnull=True)
                .first()
            )
            if competitor is None:
                return error_response("目标竞品不存在", 404)
            if competitor.product_id != submission.product_id:
                return error_response("只能选择同一我司产品下的竞品", 422)
            default_release = None
            target_release = None
            if mode == "mergeExisting":
                target_release = (
                    CompetitorRelease.objects.select_for_update()
                    .filter(id=target_version_id, competitor=competitor)
                    .first()
                    if target_version_id
                    else ensure_current_release(competitor)
                )
                if target_release is None:
                    return error_response("目标竞品版本不存在", 404)
            else:
                # Preserve the existing release-numbering behavior for a parallel version.
                default_release = ensure_current_release(competitor)

            # Validate every target-dependent branch before mutating the submission. This
            # keeps early error responses from committing a partial patch inside atomic().
            storage_keys = apply_submission_patch(submission, patch)
            queue_file_deletions(storage_keys)
            if mode == "newVersion":
                CompetitorRelease.objects.filter(
                    competitor=competitor,
                    is_current=True,
                ).update(is_current=False)
                release = CompetitorRelease(
                    competitor=competitor,
                    number=next_release_number(competitor),
                    brand=result["brand"],
                    name=result["name"],
                    model=result["model"],
                    regions=[],
                    changed_on=date.today(),
                    expires_on=result["expires_on"],
                    note="由本次采集资料创建的独立版本。",
                    created_by=_operator_name(request),
                    is_current=True,
                )
                before = {}
                release_regions = [submission.region]
            else:
                release = target_release
                before = release_snapshot(target_release)
                release_regions = list(
                    dict.fromkeys([*(target_release.regions or []), submission.region])
                )
            apply_result_to_release(release, result, regions=release_regions)
            release.save()
            after = release_snapshot(release)
            changed_fields = changed_competitor_fields(before, after)
            submission.competitor = competitor
            submission.competitor_release = release
            submission.status = SubmissionStatus.ADOPTED
            submission.save(
                update_fields=[
                    "competitor",
                    "competitor_release",
                    "status",
                    "updated_at",
                ]
            )
            if release.is_current:
                apply_release_to_competitor(competitor, release)
            else:
                sync_competitor_source_count(competitor)
            action = "新建版本" if mode == "newVersion" else "资料归并"
            note = (
                f"将采集资料作为正式竞品的独立并列版本 V{release.number}。"
                if mode == "newVersion"
                else f"将采集资料归并到正式竞品 V{release.number}。"
            )
            if mode == "newVersion":
                note += " 各字段、地区和参数均由本次审核结果独立保存。"
            elif changed_fields:
                note += f" 更新：{'、'.join(changed_fields)}。"
            else:
                note += " 正式字段无变化，仅补充来源资料。"
            CompetitorVersion.objects.create(
                competitor=competitor,
                version=f"V{next_version_number(competitor)}",
                changed_on=date.today(),
                note=note,
                action=action,
                changed_by=_operator_name(request),
                source_submission=submission,
                snapshot=after,
            )
    except ProductCatalogError as exc:
        return error_response(str(exc), exc.status_code)
    except (PayloadError, ValidationError, ValueError) as exc:
        return error_response(str(exc), 422)
    invalidate_competitor_board_summary()
    invalidate_product_board_cache()
    return _resolution(submission, competitor)
