from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_http_methods

from .models import Competitor
from .product_catalog import (
    ProductCatalogError,
    get_product,
    get_product_detail,
    get_product_image,
    get_products,
)
from .view_helpers import error_response, page_result, pagination, request_access


PRODUCT_BOARD_CACHE_TTL_SECONDS = 30
PRODUCT_BOARD_CACHE_KEY = "competitive:product-board:v2"
PRODUCT_LIST_FIELDS = (
    "id",
    "name",
    "shortName",
    "fullName",
    "model",
    "brand",
    "productDomain",
    "levelTwo",
    "category",
    "categoryA",
    "categoryB",
    "productDomainSortOrder",
    "levelTwoSortOrder",
    "categorySortOrder",
    "kingdeeCode",
    "isActive",
    "hasImage",
    "line",
    "segment",
    "coverage",
)


def invalidate_product_board_cache() -> None:
    try:
        cache.delete(PRODUCT_BOARD_CACHE_KEY)
    except Exception:
        pass


def _list_product(product: dict) -> dict:
    return {key: product.get(key) for key in PRODUCT_LIST_FIELDS}


def _ordered_category_values(
    products: list[dict],
    value_key: str,
    order_key: str,
) -> list[str]:
    values: dict[str, int] = {}
    for product in products:
        value = str(product.get(value_key) or "").strip()
        if not value:
            continue
        try:
            order = int(product.get(order_key, 1_000_000))
        except (TypeError, ValueError):
            order = 1_000_000
        values[value] = min(values.get(value, 1_000_000), order)
    return sorted(values, key=lambda value: (values[value], value.casefold()))


def _products_with_coverage() -> list[dict]:
    try:
        cached_products = cache.get(PRODUCT_BOARD_CACHE_KEY)
    except Exception:
        cached_products = None
    if isinstance(cached_products, list):
        return [dict(item) for item in cached_products]
    products = get_products()
    covered_ids = set(
        Competitor.objects.filter(deleted_at__isnull=True).values_list(
            "product_id", flat=True
        )
    )
    result = [
        {
            **_list_product(product),
            "coverage": "有竞品" if product["id"] in covered_ids else "无竞品",
        }
        for product in products
    ]
    try:
        cache.set(
            PRODUCT_BOARD_CACHE_KEY,
            result,
            timeout=PRODUCT_BOARD_CACHE_TTL_SECONDS,
        )
    except Exception:
        pass
    return [dict(item) for item in result]


def _product_options_payload(products: list[dict]) -> dict:
    domains = _ordered_category_values(
        products,
        "productDomain",
        "productDomainSortOrder",
    )
    level_twos_by_domain = {
        domain: _ordered_category_values(
            [product for product in products if product["productDomain"] == domain],
            "levelTwo",
            "levelTwoSortOrder",
        )
        for domain in domains
    }
    products_by_path = {}
    for product in products:
        key = f"{product['productDomain']}\u0000{product['levelTwo']}"
        products_by_path.setdefault(key, []).append(product)
    return {
        "domains": domains,
        "levelTwosByDomain": level_twos_by_domain,
        "categoriesByPath": {
            key: _ordered_category_values(values, "category", "categorySortOrder")
            for key, values in products_by_path.items()
        },
        "lines": domains,
        "categoriesByLine": {
            domain: _ordered_category_values(
                [product for product in products if product["productDomain"] == domain],
                "category",
                "categorySortOrder",
            )
            for domain in domains
        },
    }


@require_http_methods(["GET"])
def products_collection(request):
    _access, error = request_access(request)
    if error:
        return error
    page_values = pagination(request)
    if isinstance(page_values, JsonResponse):
        return page_values
    page, page_size = page_values
    try:
        products = _products_with_coverage()
    except ProductCatalogError as exc:
        return error_response(str(exc), exc.status_code)
    all_products = products
    keyword = str(request.GET.get("q") or "").strip().casefold()
    if keyword:
        products = [
            product
            for product in products
            if keyword
            in " ".join(
                str(product.get(key) or "")
                for key in (
                    "name",
                    "fullName",
                    "shortName",
                    "model",
                    "kingdeeCode",
                    "brand",
                    "productDomain",
                    "categoryA",
                    "categoryB",
                )
            ).casefold()
        ]
    product_domain = str(request.GET.get("productDomain") or request.GET.get("line") or "")
    level_two = str(request.GET.get("levelTwo") or "")
    category = str(request.GET.get("category") or "")
    if product_domain:
        products = [product for product in products if product["productDomain"] == product_domain]
    if level_two:
        products = [product for product in products if product["levelTwo"] == level_two]
    if category:
        products = [product for product in products if product["category"] == category]
    total = len(products)
    start = (page - 1) * page_size
    items = [_list_product(product) for product in products[start : start + page_size]]
    payload = page_result(items, total, page, page_size)
    if str(request.GET.get("includeOptions") or "").lower() in {"1", "true", "yes"}:
        payload["options"] = _product_options_payload(all_products)
    response = JsonResponse(payload)
    response["Cache-Control"] = "private, max-age=60, stale-while-revalidate=300"
    return response


@require_http_methods(["GET"])
def product_options(request):
    _access, error = request_access(request)
    if error:
        return error
    try:
        products = _products_with_coverage()
    except ProductCatalogError as exc:
        return error_response(str(exc), exc.status_code)
    response = JsonResponse(_product_options_payload(products))
    response["Cache-Control"] = "private, max-age=60"
    return response


@require_http_methods(["GET"])
def product_detail(request, product_id):
    _access, error = request_access(request)
    if error:
        return error
    try:
        product = get_product(product_id)
    except ProductCatalogError as exc:
        return error_response(str(exc), exc.status_code)
    if product is None:
        return error_response("关联产品不存在", 404)
    return JsonResponse(get_product_detail(product))


@require_http_methods(["GET"])
def product_image(request, product_id):
    _access, error = request_access(request)
    if error:
        return error
    try:
        if get_product(product_id) is None:
            return error_response("关联产品不存在", 422)
        content, content_type = get_product_image(
            product_id,
            variant=request.GET.get("variant") or "thumbnail",
        )
    except ProductCatalogError as exc:
        return error_response(str(exc), exc.status_code)
    response = HttpResponse(content, content_type=content_type)
    response["Cache-Control"] = "private, max-age=300"
    return response
