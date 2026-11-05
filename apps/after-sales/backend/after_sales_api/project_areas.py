import re
from datetime import date
from decimal import Decimal

from .services import DomainValidationError


PRESALES_PROJECT_LEVELS = (
    "常规，金额小", "常规，金额大", "特殊，金额小", "特殊，金额大", "重要，金额小", "重要，金额大",
)
PRESALES_PROJECT_URGENCIES = ("一般", "紧急", "非常紧急")


def presales_project_data_equal(previous, current):
    """Ignore empty optional metadata and harmless area-number formatting."""
    if previous == current:
        return True
    if not isinstance(previous, dict) or not isinstance(current, dict):
        return False

    def normalized(data):
        info = data.get("projectInfo", {})
        if not isinstance(info, dict):
            return data
        defaults = normalize_presales_project_info({
            key: info.get(key) for key in ("totalArea", "designArea", "projectLevel", "urgency", "expectedBidAt")
        })
        return {**data, "projectInfo": {**info, **defaults}}

    try:
        return normalized(previous) == normalized(current)
    except DomainValidationError:
        # Invalid legacy values must still be writable as a real correction.
        return False


def normalize_presales_project_info(value):
    required = {"totalArea", "designArea", "projectLevel"}
    if not isinstance(value, dict) or not required.issubset(value) or set(value) - required - {"urgency", "expectedBidAt"}:
        raise DomainValidationError("请提交完整的项目信息，可留空", code="INVALID_PROJECT_INFO")
    level = value["projectLevel"]
    if level is None:
        level = ""
    if not isinstance(level, str) or (level.strip() and level.strip() not in PRESALES_PROJECT_LEVELS):
        raise DomainValidationError("请选择有效的项目等级", code="INVALID_PROJECT_LEVEL")
    result = {**normalize_presales_areas({key: value[key] for key in ("totalArea", "designArea")}),
              "projectLevel": level.strip()}
    # Older clients omit urgency; updating areas/level must preserve its saved value.
    if "urgency" in value:
        urgency = value["urgency"]
        if urgency is None:
            urgency = ""
        if not isinstance(urgency, str) or (urgency.strip() and urgency.strip() not in PRESALES_PROJECT_URGENCIES):
            raise DomainValidationError("请选择有效的紧急程度", code="INVALID_PROJECT_URGENCY")
        result["urgency"] = urgency.strip()
    # Omitted optional fields from older clients must not clear local dates.
    if "expectedBidAt" in value:
        expected = value["expectedBidAt"]
        if expected is None:
            expected = ""
        if not isinstance(expected, str):
            raise DomainValidationError("请选择有效的预计招标日期", code="INVALID_EXPECTED_BID_DATE")
        expected = expected.strip()
        if expected:
            try:
                if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", expected):
                    raise ValueError
                date.fromisoformat(expected)
            except ValueError:
                raise DomainValidationError("请选择有效的预计招标日期", code="INVALID_EXPECTED_BID_DATE")
        result["expectedBidAt"] = expected
    return result


def normalize_presales_areas(value):
    labels = {"totalArea": "项目总面积", "designArea": "设计面积"}
    if not isinstance(value, dict) or set(value) != set(labels):
        raise DomainValidationError("请提交项目总面积和设计面积，可留空", code="INVALID_PROJECT_AREAS")
    result = {}
    for key, label in labels.items():
        area = value[key]
        if area is None or (isinstance(area, str) and not area.strip()):
            result[key] = None
            continue
        raw = str(area).strip()
        if (isinstance(area, bool) or not isinstance(area, (str, int, float)) or len(raw) > 32
                or not re.fullmatch(r"(?:[0-9]+(?:\.[0-9]{0,2})?|\.[0-9]{1,2})", raw)
                or Decimal(raw) > Decimal("9999999999.99")):
            raise DomainValidationError(
                f"{label}须为 0 至 9999999999.99 的数字，最多两位小数", code="INVALID_PROJECT_AREAS",
            )
        result[key] = format(Decimal(raw), ".2f")
    return result
