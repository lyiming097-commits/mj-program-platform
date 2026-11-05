from __future__ import annotations

from dataclasses import dataclass

from django.db import DatabaseError
from django.http import JsonResponse

from ..models import AdministrativeRegion, AdministrativeRegionDirectory
from .queries import is_pinyin_initial_keyword, normalize_pinyin_keyword


class AdministrativeRegionDirectoryUnavailable(RuntimeError):
    pass


def directory_error_response():
    return JsonResponse({
        "ok": False, "code": "REGION_DIRECTORY_UNAVAILABLE",
        "error": "行政区目录暂不可用，请稍后重试",
    }, status=503)


@dataclass
class AdministrativeRegionSnapshot:
    revision: str
    tree: list[dict]
    items: list[dict]
    by_code: dict[str, dict]
    stats: dict[str, int]

    def query(self, keyword: str = "", *, level: str = "", parent_code: str | None = None) -> list[dict]:
        normalized = str(keyword or "").strip().casefold()
        compact_pinyin = normalize_pinyin_keyword(normalized) if is_pinyin_initial_keyword(normalized) else ""
        return [
            item for item in self.items
            if (not level or item["level"] == level)
            and (parent_code is None or item["parentCode"] == parent_code)
            and (
                not normalized or normalized in item["name"].casefold() or normalized in item["code"]
                or (compact_pinyin and (
                    compact_pinyin in item["pinyin"] or compact_pinyin in item["pinyinInitials"]
                ))
            )
        ]


def load_administrative_region_directory() -> AdministrativeRegionSnapshot:
    """Read one published database revision for the whole response; never use a file fallback."""
    try:
        directory = AdministrativeRegionDirectory.objects.filter(is_current=True).first()
        if directory is None:
            raise AdministrativeRegionDirectoryUnavailable("No published administrative region directory")
        rows = list(AdministrativeRegion.objects.filter(directory=directory).values(
            "code", "name", "level", "parent_code", "pinyin", "pinyin_initials",
        ))
    except DatabaseError as exc:
        raise AdministrativeRegionDirectoryUnavailable("Administrative region database unavailable") from exc
    if not rows or len(rows) != directory.region_count:
        raise AdministrativeRegionDirectoryUnavailable("Administrative region directory is incomplete")

    def item(row):
        return {"code": row["code"], "name": row["name"],
                "pinyin": row["pinyin"], "pinyinInitials": row["pinyin_initials"]}

    provinces = {row["code"]: {**item(row), "cities": []} for row in rows if row["level"] == "province"}
    cities = {}
    for row in rows:
        if row["level"] == "province":
            if row["parent_code"]:
                raise AdministrativeRegionDirectoryUnavailable("Province has an invalid parent")
        elif row["level"] == "city":
            province = provinces.get(row["parent_code"])
            if province is None:
                raise AdministrativeRegionDirectoryUnavailable("City has no province")
            city = {**item(row), "districts": []}
            cities[row["code"]] = city
            province["cities"].append(city)
        elif row["level"] != "district":
            raise AdministrativeRegionDirectoryUnavailable("Unknown administrative region level")
    for row in rows:
        if row["level"] == "district":
            city = cities.get(row["parent_code"])
            if city is None:
                raise AdministrativeRegionDirectoryUnavailable("District has no city")
            city["districts"].append(item(row))
    if not provinces:
        raise AdministrativeRegionDirectoryUnavailable("Administrative region directory has no provinces")

    items = []
    for province in provinces.values():
        fields = {key: province[key] for key in ("code", "name", "pinyin", "pinyinInitials")}
        items.append({**fields, "level": "province", "parentCode": "", "levelLabel": "省级",
                      "path": province["name"], "provinceCode": province["code"],
                      "cityCode": province["cities"][0]["code"] if province["cities"] else ""})
        for city in province["cities"]:
            fields = {key: city[key] for key in ("code", "name", "pinyin", "pinyinInitials")}
            items.append({**fields, "level": "city", "parentCode": province["code"], "levelLabel": "市级",
                          "path": f"{province['name']} / {city['name']}",
                          "provinceCode": province["code"], "cityCode": city["code"]})
            for district in city["districts"]:
                items.append({**district, "level": "district", "parentCode": city["code"], "levelLabel": "区县",
                              "path": f"{province['name']} / {city['name']} / {district['name']}",
                              "provinceCode": province["code"], "cityCode": city["code"]})
    return AdministrativeRegionSnapshot(
        revision=directory.revision, tree=list(provinces.values()), items=items,
        by_code={item["code"]: item for item in items},
        stats={"provinces": len(provinces), "cities": len(cities),
               "districts": len(rows) - len(provinces) - len(cities)},
    )
