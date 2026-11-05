from dataclasses import dataclass

from .models import SettingItem


@dataclass(frozen=True)
class CollectionFieldDefault:
    code: str
    label: str
    required: bool = False


DEFAULT_COLLECTION_FIELDS = (
    CollectionFieldDefault("brand", "竞品品牌", True),
    CollectionFieldDefault("name", "产品名称", True),
    CollectionFieldDefault("model", "产品型号"),
    CollectionFieldDefault("price", "采集单价"),
    CollectionFieldDefault("attachments", "现场资料"),
    CollectionFieldDefault("product_id", "关联我司产品", True),
    CollectionFieldDefault("dealer", "现有经销商"),
    CollectionFieldDefault("customer", "现有客户"),
    CollectionFieldDefault("note", "一线备注"),
    CollectionFieldDefault("competitor_parameters", "竞品参数"),
    CollectionFieldDefault("advantage", "竞品优势"),
    CollectionFieldDefault("weakness", "竞品劣势"),
    CollectionFieldDefault("tactic", "销售应对策略"),
    CollectionFieldDefault("material_category", "资料归属", True),
    CollectionFieldDefault("region", "采集地区", True),
    CollectionFieldDefault("location", "具体地点", True),
    CollectionFieldDefault("validity", "资料有效期"),
    CollectionFieldDefault("reminder_owner", "到期提醒责任人"),
)

PROVINCE_NAMES = (
    "北京市", "天津市", "河北省", "山西省", "内蒙古自治区",
    "辽宁省", "吉林省", "黑龙江省", "上海市", "江苏省",
    "浙江省", "安徽省", "福建省", "江西省", "山东省",
    "河南省", "湖北省", "湖南省", "广东省", "广西壮族自治区",
    "海南省", "重庆市", "四川省", "贵州省", "云南省",
    "西藏自治区", "陕西省", "甘肃省", "青海省", "宁夏回族自治区",
    "新疆维吾尔自治区", "台湾省", "香港特别行政区", "澳门特别行政区",
)

DEFAULT_SETTING_OPTIONS = {
    "material_category": (
        "产品图片",
        "技术参数",
        "价格信息",
        "渠道信息",
        "铭牌信息",
        "报价信息",
        "售后政策",
        "客户反馈",
    ),
    "validity": ("一年", "半年", "三个月", "自定义"),
    "reminder_owner": (
        "本人 + 区域经理",
        "仅本人",
        "产品经理",
        "产品经理 + 区域经理",
    ),
}


def ensure_default_setting_items() -> None:
    rows = [
        SettingItem(
            group="collection_field",
            code=field.code,
            label=field.label,
            enabled=True,
            required=field.required,
            position=position,
        )
        for position, field in enumerate(DEFAULT_COLLECTION_FIELDS)
    ]
    rows.extend(
        SettingItem(
            group=group,
            code=f"{group}_{position}",
            label=label,
            enabled=True,
            required=False,
            position=position,
        )
        for group, labels in DEFAULT_SETTING_OPTIONS.items()
        for position, label in enumerate(labels)
    )
    SettingItem.objects.bulk_create(rows, ignore_conflicts=True)
