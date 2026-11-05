import hashlib
import json
import re
from calendar import monthrange
from datetime import date, datetime

from django.db import transaction

from .models import (
    Competitor,
    CompetitorParameter,
    CompetitorRelease,
    CompetitorStatus,
    PendingFileDeletion,
    SettingItem,
    Submission,
    SubmissionStatus,
)
from .product_catalog import ProductCatalogError, get_product
from .setting_defaults import ensure_default_setting_items


SUBMISSION_FIELDS = {
    "productId": "product_id",
    "brand": "brand",
    "name": "name",
    "model": "model",
    "price": "price",
    "dealer": "dealer",
    "customer": "customer",
    "note": "note",
    "advantage": "advantage",
    "weakness": "weakness",
    "tactic": "tactic",
    "competitorParameters": "competitor_parameters",
    "competitorParameterText": "competitor_parameters",
    "reviewComment": "review_comment",
    "region": "region",
    "city": "city",
    "location": "location",
    "located": "located",
    "latitude": "latitude",
    "longitude": "longitude",
    "locationAccuracy": "location_accuracy",
    "locatedAt": "located_at",
    "locationSource": "location_source",
    "validity": "validity",
    "expires": "expires_on",
    "reminderOwner": "reminder_owner",
    "date": "submitted_on",
    "categories": "categories",
    "categoriesByFile": "categories_by_file",
    "draftId": "draft_id",
    "attachments": "attachments",
}
FIELD_LIMITS = {
    "product_id": 32,
    "brand": 160,
    "name": 200,
    "model": 160,
    "price": 120,
    "advantage": 2000,
    "weakness": 2000,
    "tactic": 2000,
    "review_comment": 2000,
    "region": 80,
    "city": 80,
    "validity": 40,
    "reminder_owner": 120,
}


class PayloadError(ValueError):
    pass


def parse_date(value, field_name: str, *, allow_none: bool = False):
    if value in (None, "") and allow_none:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise PayloadError(f"{field_name} 日期格式无效") from exc


def parse_datetime(value, field_name: str, *, allow_none: bool = False):
    if value in (None, "") and allow_none:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise PayloadError(f"{field_name} 时间格式无效") from exc


TEXT_PARAMETER_PREFIX = "__text__:"
PARAMETER_TEXT_LIMIT = 20_000
PARAMETER_ITEM_LIMIT = 2_000
PARAMETER_MARKERS = "★☆▲△◆◇●○■□"
PARAMETER_NUMBER_PREFIX_PATTERN = (
    r"(?:\d{1,3}\s*(?:[.．](?!\d)|[、:：)）]|\-(?!\d))\s*"
    r"|[\uFF08(\u3010\[]\s*\d{1,3}\s*[\uFF09)\u3011\]]\s*)"
)
PARAMETER_ITEM_PREFIX_RE = re.compile(
    rf"^\s*(?P<marker>[{PARAMETER_MARKERS}])?\s*{PARAMETER_NUMBER_PREFIX_PATTERN}"
)
PARAMETER_NUMBERED_START_RE = re.compile(
    rf"(?:^|[\r\n;；:：\s])(?P<prefix>[{PARAMETER_MARKERS}]?\s*{PARAMETER_NUMBER_PREFIX_PATTERN})"
)
PARAMETER_LABEL_PREFIX_RE = re.compile(r"^\s*参数\s*\d{1,3}\s*[:：]\s*")
PARAMETER_LABELED_START_RE = re.compile(
    r"(?:^|[\r\n;；/／\s])(?P<prefix>参数\s*\d{1,3}\s*[:：]\s*)"
)


def normalize_competitor_parameter_item(value, *, trim_boundary_slash=False) -> str:
    item = PARAMETER_LABEL_PREFIX_RE.sub("", str(value or "").strip(), count=1)
    match = PARAMETER_ITEM_PREFIX_RE.match(item)
    if match:
        marker = match.group("marker") or ""
        item = f"{marker}{item[match.end():]}".strip()
    item = re.sub(r"[;；]\s*$", "", item).strip()
    return re.sub(r"[/／]\s*$", "", item).strip() if trim_boundary_slash else item


def parameter_candidate_text(value) -> str:
    if isinstance(value, str):
        return normalize_competitor_parameter_item(value)
    if not isinstance(value, dict):
        return ""
    text = str(value.get("text") or "").strip()
    if text:
        return normalize_competitor_parameter_item(text)
    name = str(value.get("name") or "").strip()
    parameter_value = str(
        value.get("value") or value.get("competitorValue") or ""
    ).strip()
    if name and parameter_value:
        return normalize_competitor_parameter_item(f"{name}：{parameter_value}")
    return normalize_competitor_parameter_item(name or parameter_value)


def split_numbered_parameter_text(text: str) -> list[str]:
    starts = []
    for match in PARAMETER_NUMBERED_START_RE.finditer(text):
        start = match.start("prefix")
        if not starts or starts[-1] != start:
            starts.append(start)
    if not starts:
        return [text.strip()]
    prefix = text[: starts[0]].strip()
    # Only split numbered content at the beginning of a value or after a
    # heading such as `参数如下：`; incidental numbers in ordinary prose
    # should remain part of that prose.
    if prefix and not re.fullmatch(r"[;；]+", prefix) and not re.search(r"[：:]$", prefix):
        return [text.strip()]
    return [
        normalize_competitor_parameter_item(
            text[start : starts[index + 1] if index + 1 < len(starts) else len(text)],
            trim_boundary_slash=index + 1 < len(starts),
        )
        for index, start in enumerate(starts)
        if text[start : starts[index + 1] if index + 1 < len(starts) else len(text)].strip()
    ]


def split_labeled_parameter_text(text: str) -> list[str] | None:
    matches = list(PARAMETER_LABELED_START_RE.finditer(text))
    if not matches:
        return None
    starts = [match.start("prefix") for match in matches]
    prefix = text[: starts[0]].strip()
    if prefix and not re.fullmatch(r"[;；]+", prefix) and not re.search(r"[：:]$", prefix):
        return None
    result = []
    for index, start in enumerate(starts):
        item = normalize_competitor_parameter_item(
            text[start : starts[index + 1] if index + 1 < len(starts) else len(text)],
            trim_boundary_slash=index + 1 < len(starts),
        )
        if item:
            result.append(item)
    return result


def normalize_competitor_parameter_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        text = "\n".join(
            item
            for item in (parameter_candidate_text(candidate) for candidate in value)
            if item
        )
    elif isinstance(value, str):
        text = value
    else:
        raise PayloadError("竞品参数格式无效")
    text = text.strip()
    if len(text) > PARAMETER_TEXT_LIMIT:
        raise PayloadError("竞品参数内容过长")
    return text


def split_competitor_parameter_text(value, maximum: int = 100) -> list[str]:
    text = normalize_competitor_parameter_text(value)
    if not text:
        return []

    physical_lines = re.split(r"\r?\n", text)
    candidates = []
    for line in physical_lines:
        source = line.strip()
        if not source:
            continue
        labeled_items = split_labeled_parameter_text(source)
        if labeled_items is not None:
            candidates.extend(labeled_items)
            continue
        numbered_items = split_numbered_parameter_text(source)
        if len(numbered_items) > 1:
            candidates.extend(numbered_items)
            continue
        item = normalize_competitor_parameter_item(numbered_items[0])
        if item:
            candidates.append(item)

    result = []
    seen = set()
    for segment in candidates:
        item = normalize_competitor_parameter_item(segment)
        if not item:
            continue
        if len(item) > PARAMETER_ITEM_LIMIT:
            raise PayloadError("单条竞品参数内容过长")
        key = item.casefold()
        if key in seen:
            continue
        result.append(item)
        seen.add(key)
        if len(result) > maximum:
            raise PayloadError("竞品参数条目过多")
    return result


def competitor_parameter_text(parameter: CompetitorParameter) -> str:
    if parameter.name.startswith(TEXT_PARAMETER_PREFIX):
        return parameter.competitor_value.strip()
    return parameter_candidate_text(
        {"name": parameter.name, "value": parameter.competitor_value}
    )


def _validate_location(payload: dict, partial: bool) -> None:
    fields = {
        "located",
        "latitude",
        "longitude",
        "location_accuracy",
        "located_at",
        "location_source",
    }
    if partial and not fields.intersection(payload):
        return
    source = payload.get("location_source", "manual")
    if source not in {"manual", "device"}:
        raise PayloadError("定位来源无效")
    latitude = payload.get("latitude")
    longitude = payload.get("longitude")
    accuracy = payload.get("location_accuracy")
    if latitude is not None and not -90 <= latitude <= 90:
        raise PayloadError("纬度超出有效范围")
    if longitude is not None and not -180 <= longitude <= 180:
        raise PayloadError("经度超出有效范围")
    if accuracy is not None and not 0 <= accuracy <= 100_000:
        raise PayloadError("定位精度超出有效范围")
    if source == "device":
        if (
            payload.get("located") is not True
            or latitude is None
            or longitude is None
            or payload.get("located_at") is None
        ):
            raise PayloadError("设备定位必须包含经纬度和定位时间")
    elif payload.get("located") or any(
        payload.get(name) is not None
        for name in ("latitude", "longitude", "location_accuracy", "located_at")
    ):
        raise PayloadError("手动地点不能携带设备定位数据")


def parse_payload(raw_payload, *, draft: bool = False, partial: bool = False) -> dict:
    if isinstance(raw_payload, str):
        try:
            raw_payload = json.loads(raw_payload)
        except json.JSONDecodeError as exc:
            raise PayloadError("payload JSON 无效") from exc
    if not isinstance(raw_payload, dict):
        raise PayloadError("payload 必须为对象")
    values = {
        SUBMISSION_FIELDS.get(key, key): value
        for key, value in raw_payload.items()
        if SUBMISSION_FIELDS.get(key, key) in SUBMISSION_FIELDS.values()
    }
    defaults = {
        "model": "" if draft else "型号待补充",
        "price": "" if draft else "待采集",
        "dealer": "",
        "customer": "",
        "note": "",
        "advantage": "",
        "weakness": "",
        "tactic": "",
        "competitor_parameters": "",
        "review_comment": "",
        "city": "",
        "location": "",
        "located": False,
        "latitude": None,
        "longitude": None,
        "location_accuracy": None,
        "located_at": None,
        "location_source": "manual",
        "validity": "一年",
        "reminder_owner": "本人 + 区域经理",
        "categories": [],
        "categories_by_file": {},
    }
    if draft:
        defaults.update({"brand": "", "name": "", "product_id": "", "region": ""})
    if not partial:
        values = {**defaults, **values}
    for field, limit in FIELD_LIMITS.items():
        if field in values and values[field] is not None:
            values[field] = str(values[field]).strip() if field in {
                "product_id", "brand", "name", "model", "region", "validity", "reminder_owner"
            } else str(values[field])
            if len(values[field]) > limit:
                raise PayloadError(f"{field} 内容过长")
    if not draft and not partial:
        for field, label in (
            ("product_id", "关联我司产品"),
            ("brand", "竞品品牌"),
            ("name", "产品名称"),
            ("region", "采集地区"),
        ):
            if not values.get(field):
                raise PayloadError(f"{label}不能为空")
    if "competitor_parameters" in values:
        values["competitor_parameters"] = normalize_competitor_parameter_text(
            values["competitor_parameters"]
        )
    if "submitted_on" in values:
        values["submitted_on"] = parse_date(values["submitted_on"], "date")
    elif not partial and not draft:
        values["submitted_on"] = date.today()
    if "expires_on" in values:
        values["expires_on"] = parse_date(values["expires_on"], "expires", allow_none=True)
    if "located_at" in values:
        values["located_at"] = parse_datetime(
            values["located_at"], "locatedAt", allow_none=True
        )
    for field in ("latitude", "longitude", "location_accuracy"):
        if field in values and values[field] is not None:
            try:
                values[field] = float(values[field])
            except (TypeError, ValueError) as exc:
                raise PayloadError(f"{field} 必须为数字") from exc
    if "located" in values and not isinstance(values["located"], bool):
        raise PayloadError("located 必须为布尔值")
    if "categories" in values and not isinstance(values["categories"], list):
        raise PayloadError("categories 格式无效")
    if "categories_by_file" in values and not isinstance(values["categories_by_file"], dict):
        raise PayloadError("categoriesByFile 格式无效")
    if "attachments" in values:
        if not isinstance(values["attachments"], list) or len(values["attachments"]) > 20:
            raise PayloadError("附件列表格式无效")
        normalized_attachments = []
        for item in values["attachments"]:
            if not isinstance(item, dict) or not item.get("id") or not str(item.get("category") or "").strip():
                raise PayloadError("附件列表格式无效")
            normalized_attachments.append(
                {"id": str(item["id"]), "category": str(item["category"]).strip()}
            )
        values["attachments"] = normalized_attachments
    _validate_location(values, partial)
    return values


def expires_from(submitted_on: date, validity: str) -> date:
    months = {"三个月": 3, "半年": 6}.get(validity, 12)
    month_index = submitted_on.month - 1 + months
    year = submitted_on.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, min(submitted_on.day, monthrange(year, month)[1]))


def sync_expiry_statuses(today: date | None = None) -> dict[str, int]:
    current_day = today or date.today()
    submissions = Submission.objects.filter(
        expires_on__lte=current_day,
        deleted_at__isnull=True,
    ).exclude(status=SubmissionStatus.EXPIRED).update(status=SubmissionStatus.EXPIRED)
    competitors = Competitor.objects.filter(
        expires_on__lte=current_day,
        deleted_at__isnull=True,
    ).exclude(status__in=[CompetitorStatus.EXPIRED, CompetitorStatus.NO_DATA]).update(
        status=CompetitorStatus.EXPIRED
    )
    releases = CompetitorRelease.objects.filter(
        expires_on__lte=current_day,
        competitor__deleted_at__isnull=True,
    ).exclude(status__in=[CompetitorStatus.EXPIRED, CompetitorStatus.NO_DATA]).update(
        status=CompetitorStatus.EXPIRED
    )
    return {
        "submissions": submissions,
        "competitors": competitors,
        "releases": releases,
    }


def validate_required_collection_fields(entity, attachment_categories: list[str]) -> None:
    ensure_default_setting_items()
    missing = []
    for field in SettingItem.objects.filter(
        group="collection_field", enabled=True, required=True
    ):
        if field.code == "attachments":
            filled = bool(attachment_categories)
        elif field.code == "material_category":
            filled = not attachment_categories or all(
                str(category).strip() and category != "待归类"
                for category in attachment_categories
            )
        else:
            value = entity.get(field.code) if isinstance(entity, dict) else getattr(entity, field.code, None)
            filled = bool(value) if isinstance(value, list) else bool(str(value or "").strip())
        if not filled:
            missing.append(field.label)
    if missing:
        raise PayloadError(f"请填写必填字段：{'、'.join(missing)}")


def require_catalog_product(product_id: str) -> dict:
    try:
        product = get_product(product_id)
    except ProductCatalogError:
        raise
    if product is None:
        raise PayloadError("关联产品不存在")
    return product


def reopen_adopted_submission(submission: Submission) -> None:
    if submission.status == SubmissionStatus.ADOPTED:
        submission.status = SubmissionStatus.PENDING


def apply_submission_patch(submission: Submission, patch: dict) -> list[str]:
    changes = {key: value for key, value in patch.items() if key != "attachments"}
    if "product_id" in changes:
        require_catalog_product(changes["product_id"])
    has_changes = any(getattr(submission, field) != value for field, value in changes.items())
    for field, value in changes.items():
        setattr(submission, field, value)
    storage_keys = []
    attachments = patch.get("attachments", ...)
    if attachments is not ...:
        desired = {item["id"]: item for item in attachments}
        existing = {str(item.id): item for item in submission.attachments.all()}
        if set(desired) - set(existing):
            raise PayloadError("附件列表包含不属于该提交的附件")
        for attachment_id, attachment in existing.items():
            mutation = desired.get(attachment_id)
            if mutation is None:
                if attachment.storage_key:
                    storage_keys.append(attachment.storage_key)
                attachment.delete()
            elif attachment.category != mutation["category"]:
                attachment.category = mutation["category"]
                attachment.save(update_fields=["category", "updated_at"])
                has_changes = True
        has_changes = has_changes or bool(set(existing) - set(desired))
    if has_changes:
        reopen_adopted_submission(submission)
    categories = (
        [item["category"] for item in attachments]
        if attachments is not ...
        else list(submission.attachments.values_list("category", flat=True))
    )
    validate_required_collection_fields(submission, categories)
    submission.save()
    return storage_keys


def queue_file_deletions(storage_keys: list[str]) -> None:
    PendingFileDeletion.objects.bulk_create(
        [PendingFileDeletion(storage_key=key) for key in dict.fromkeys(storage_keys)]
    )


def sync_competitor_parameters(competitor: Competitor, candidates) -> None:
    items = (
        split_competitor_parameter_text(candidates)
        if isinstance(candidates, str) or candidates is None
        else [
            text
            for text in (parameter_candidate_text(candidate) for candidate in candidates)
            if text
        ]
    )
    if len(items) > 100:
        raise PayloadError("竞品参数条目过多")
    existing = {
        competitor_parameter_text(parameter).casefold(): parameter
        for parameter in competitor.parameters.exclude(name__in=["产品型号", "价格口径"])
    }
    keep_ids = []
    seen = set()
    for position, text in enumerate(items):
        text = str(text or "").strip()
        key = text.casefold()
        if not text or key in seen:
            continue
        if len(text) > PARAMETER_ITEM_LIMIT:
            raise PayloadError("单条竞品参数内容过长")
        parameter = existing.get(key)
        if parameter is None:
            parameter = CompetitorParameter(
                competitor=competitor,
                name=f"{TEXT_PARAMETER_PREFIX}{hashlib.sha256(key.encode('utf-8')).hexdigest()}",
                own_value="待产品经理确认",
                comparison_status="待判断",
                deviation="待结合我司规格书确认具体差异",
            )
        if parameter.name.startswith(TEXT_PARAMETER_PREFIX):
            parameter.competitor_value = text
        parameter.position = position
        parameter.save()
        keep_ids.append(parameter.id)
        seen.add(key)
    competitor.parameters.exclude(id__in=keep_ids).delete()
    getattr(competitor, "_prefetched_objects_cache", {}).pop("parameters", None)


def competitor_snapshot(competitor: Competitor) -> dict:
    return {
        "brand": competitor.brand,
        "name": competitor.name,
        "model": competitor.model,
        "productId": competitor.product_id,
        "regions": list(competitor.regions or []),
        "price": competitor.price,
        "dealer": competitor.dealer,
        "advantage": competitor.advantage,
        "weakness": competitor.weakness,
        "tactic": competitor.tactic,
        "expires": competitor.expires_on.isoformat(),
        "status": competitor.status,
        "parameters": [
            {
                "text": competitor_parameter_text(item),
                "ownValue": item.own_value,
                "comparisonStatus": item.comparison_status,
                "deviation": item.deviation,
            }
            for item in competitor.parameters.all()
        ],
    }


def submission_snapshot(submission: Submission) -> dict:
    return {
        "brand": submission.brand,
        "name": submission.name,
        "model": submission.model,
        "productId": submission.product_id,
        "price": submission.price,
        "dealer": submission.dealer,
        "advantage": submission.advantage,
        "weakness": submission.weakness,
        "tactic": submission.tactic,
        "competitorParameterText": normalize_competitor_parameter_text(
            submission.competitor_parameters
        ),
        "region": submission.region,
        "city": submission.city,
        "location": submission.location,
        "expires": submission.expires_on.isoformat(),
        "attachments": [
            {"name": item.filename, "category": item.category, "type": item.media_type}
            for item in submission.attachments.all()
        ],
    }


def next_version_number(competitor: Competitor) -> int:
    numbers = [
        int(item[1:])
        for item in competitor.versions.values_list("version", flat=True)
        if item.startswith("V") and item[1:].isdigit()
    ]
    return max(numbers, default=0) + 1


def version_sort_key(version) -> tuple[int, int]:
    match = re.match(r"V(\d+)", version.version)
    action_order = 1 if version.action in {"审核通过", "新建竞品"} else 0
    return (int(match.group(1)) if match else 0, action_order)


def changed_competitor_fields(before: dict, after: dict) -> list[str]:
    labels = {
        "brand": "品牌",
        "name": "产品名称",
        "model": "型号",
        "productId": "关联我司产品",
        "regions": "地区覆盖",
        "price": "价格",
        "dealer": "经销商",
        "advantage": "竞品优势",
        "weakness": "竞品劣势",
        "tactic": "销售应对策略",
        "expires": "有效期",
        "parameters": "参数对照",
    }
    return [label for key, label in labels.items() if before.get(key) != after.get(key)]
