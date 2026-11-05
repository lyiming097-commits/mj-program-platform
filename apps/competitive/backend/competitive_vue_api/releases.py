from datetime import date

from django.db.models import Max

from .models import Competitor, CompetitorRelease, CompetitorStatus


RELEASE_FIELDS = (
    "brand",
    "name",
    "model",
    "regions",
    "price",
    "dealer",
    "advantage",
    "weakness",
    "tactic",
    "expires_on",
    "status",
)


def release_parameter_rows(competitor: Competitor) -> list[dict]:
    from .domain import competitor_parameter_text

    return [
        {
            "text": competitor_parameter_text(item),
            "ownValue": item.own_value,
            "comparisonStatus": item.comparison_status,
            "deviation": item.deviation,
        }
        for item in competitor.parameters.all()
    ]


def release_values_from_competitor(competitor: Competitor) -> dict:
    return {
        field: list(getattr(competitor, field) or [])
        if field == "regions"
        else getattr(competitor, field)
        for field in RELEASE_FIELDS
    } | {"parameters": release_parameter_rows(competitor)}


def ensure_current_release(
    competitor: Competitor,
    *,
    changed_by: str = "系统",
    note: str = "根据现有正式竞品资料生成初始版本。",
) -> CompetitorRelease:
    current = competitor.releases.filter(is_current=True).first()
    if current is not None:
        return current
    latest = competitor.releases.order_by("-number").first()
    if latest is not None:
        latest.is_current = True
        latest.save(update_fields=["is_current", "updated_at"])
        return latest
    return CompetitorRelease.objects.create(
        competitor=competitor,
        number=1,
        changed_on=competitor.updated_on,
        note=note,
        created_by=changed_by,
        is_current=True,
        **release_values_from_competitor(competitor),
    )


def next_release_number(competitor: Competitor) -> int:
    maximum = competitor.releases.aggregate(value=Max("number"))["value"]
    return int(maximum or 0) + 1


def release_snapshot(release: CompetitorRelease) -> dict:
    return {
        "brand": release.brand,
        "name": release.name,
        "model": release.model,
        "productId": release.competitor.product_id,
        "regions": list(release.regions or []),
        "price": release.price,
        "dealer": release.dealer,
        "advantage": release.advantage,
        "weakness": release.weakness,
        "tactic": release.tactic,
        "expires": release.expires_on.isoformat(),
        "status": release.status,
        "parameters": list(release.parameters or []),
    }


def apply_result_to_release(
    release: CompetitorRelease,
    result: dict,
    *,
    regions: list[str] | None = None,
) -> None:
    for field in (
        "brand",
        "name",
        "model",
        "price",
        "dealer",
        "advantage",
        "weakness",
        "tactic",
        "expires_on",
    ):
        setattr(release, field, result[field])
    if regions is not None:
        release.regions = list(dict.fromkeys(region for region in regions if region))
    existing_parameters = {
        str(item.get("text") or "").strip().casefold(): item
        for item in (release.parameters or [])
        if str(item.get("text") or "").strip()
    }
    release.parameters = [
        existing_parameters.get(text.casefold())
        or {
            "text": text,
            "ownValue": "待产品经理确认",
            "comparisonStatus": "待判断",
            "deviation": "待结合我司规格书确认具体差异",
        }
        for text in result["parameters"]
    ]
    release.changed_on = date.today()
    release.status = (
        CompetitorStatus.EXPIRED
        if release.expires_on <= date.today()
        else CompetitorStatus.NORMAL
    )


def apply_release_to_competitor(
    competitor: Competitor,
    release: CompetitorRelease,
) -> None:
    from .domain import sync_competitor_parameters

    for field in RELEASE_FIELDS:
        value = getattr(release, field)
        setattr(competitor, field, list(value or []) if field == "regions" else value)
    competitor.updated_on = release.changed_on
    competitor.sources = competitor.submissions.filter(deleted_at__isnull=True).count()
    competitor.save()
    sync_competitor_parameters(
        competitor,
        [item.get("text", "") for item in (release.parameters or [])],
    )


def sync_competitor_source_count(competitor: Competitor) -> None:
    source_count = competitor.submissions.filter(deleted_at__isnull=True).count()
    if competitor.sources == source_count:
        return
    competitor.sources = source_count
    competitor.save(update_fields=["sources", "updated_at"])


def sync_current_release_from_competitor(competitor: Competitor) -> CompetitorRelease:
    release = ensure_current_release(competitor)
    values = release_values_from_competitor(competitor)
    for field, value in values.items():
        setattr(release, field, value)
    release.changed_on = competitor.updated_on
    release.save()
    return release
