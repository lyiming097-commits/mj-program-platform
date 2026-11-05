"""Single, explicitly requested Aliyun lookup. No retries or automatic pagination."""
import hashlib
import json

import requests

QUERY_URL = "https://kzgsmhv1.market.alicloudapi.com/api/company_search/query"
FIELD_LIMITS = {
    "companyName": 512, "creditNo": 128, "companyCode": 128,
    "legalPerson": 255, "companyStatus": 128, "establishDate": 32,
}


class RegistryResponseError(ValueError):
    pass


def normalize_companies(payload, page_size):
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("companyList"), list):
        raise RegistryResponseError("工商服务返回的数据格式异常")
    rows = data["companyList"]
    if len(rows) > page_size:
        raise RegistryResponseError("工商服务返回的企业数量超出请求范围")
    companies = []
    for row in rows:
        if not isinstance(row, dict):
            raise RegistryResponseError("工商服务返回的企业信息格式异常")
        company = {}
        for field, limit in FIELD_LIMITS.items():
            value = row.get(field)
            if value is not None and not isinstance(value, (str, int)):
                raise RegistryResponseError("工商服务返回的企业字段格式异常")
            value = str(value if value is not None else "").strip()
            if len(value) > limit:
                raise RegistryResponseError("工商服务返回的企业字段过长")
            company[field] = value
        if not company["companyName"]:
            raise RegistryResponseError("工商服务返回的企业名称为空")
        companies.append(company)
    return companies


def identity_key(company):
    # Masked identifiers are not unique identifiers. Retain a conservative fallback.
    for field in ("creditNo", "companyCode"):
        value = company[field].upper()
        if value and "*" not in value:
            return field + ":" + hashlib.sha256(value.encode()).hexdigest()
    value = json.dumps([company[key] for key in ("companyName", "legalPerson", "establishDate")], ensure_ascii=False)
    return "name:" + hashlib.sha256(value.encode()).hexdigest()


def query_company_service(appcode, keyword, page_num, page_size):
    with requests.post(
        QUERY_URL,
        headers={"Authorization": f"APPCODE {appcode}", "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
        data={"keyword": keyword, "pageNum": str(page_num), "pageSize": str(page_size)},
        timeout=(5, 20), allow_redirects=False, stream=True,
    ) as response:
        content = bytearray()
        for chunk in response.iter_content(16384):
            content.extend(chunk)
            if len(content) > 2 * 1024 * 1024:
                raise RegistryResponseError("工商服务响应过大")
        try:
            # Never persist a credential even if a gateway echoes it in an error.
            raw = content.decode("utf-8-sig").replace(appcode, "[redacted]")
            payload = json.loads(raw)
        except (UnicodeDecodeError, ValueError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        return response.status_code, payload, response.headers.get("X-Ca-Request-Id", "")[:128]
