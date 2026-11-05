# 工商查询内部接口

适用于 CRM 等平台 App 的企业单选、多选字段。由业务后端调用 Auth，业务前端只访问自己的后端；不在浏览器保存或传递内部服务密钥、工商 AppCode。本文所述接口不提供本地企业库模糊搜索。

## 调用边界

- 内部基址：`http://auth-backend:8000/api/internal/business-registry`。
- 公网网关对 `/api/internal/*` 返回 404，Auth 后端不发布主机端口。
- 每次调用都验证已注册、已启用的服务名及其独立 Secret；普通登录 Cookie 无法替代内部服务认证。
- 业务后端先校验当前用户的业务权限。此接口不要求用户拥有 Auth 后台管理权限，不向外部开放匿名查询代理。
- 沿用 App 清单 `auth.internalService` 创建的凭据。服务名/来源 App 从 Auth 验证的凭据取得，不接受请求体伪造来源。

请求头（两个接口相同）：

```http
Content-Type: application/json
X-Internal-Service: crm-backend
X-Internal-Auth-Secret: <CRM 独立内部服务密钥，仅后端读取>
X-Request-Id: <可选的链路跟踪编号>
```

`SERVICE_NAME` 与 `AUTH_SERVICE_INTROSPECTION_SECRET` 由后端启动脚本从部署配置/Secret 注入，禁止写入前端环境变量、源码或日志。

## 查询并保存整页

`POST /search`

```json
{
  "keyword": "企业名称或统一社会信用代码",
  "pageNum": 1,
  "pageSize": 20,
  "queryRequestId": "7d81959b-e27a-44ba-9e86-856ad9e82144"
}
```

| 参数 | 规则 |
| --- | --- |
| `keyword` | 必填，去除首尾空白后 1–200 字；支持企业名称、统一社会信用代码、注册号 |
| `pageNum` | 默认 1，范围 1–100；每次只请求一页 |
| `pageSize` | 默认 20，范围 1–20 |
| `queryRequestId` | 必填 UUID；同一次、同一页查询的幂等编号 |
| `token` | 可选；用户操作时由业务后端转发当前 Auth 登录 token，不能由浏览器填写操作者 ID。纯后台任务可省略 |

传入 `token` 时 Auth 会验证会话、账号状态及代理身份，记录真实操作者和有效身份；无效 token 会拒绝请求，不降级为系统调用。不传时按调用服务记录，操作者显示服务名。token 不保存到工商记录，也不返回给调用方。

同一个 `queryRequestId` 重发只读取原结果，不再次调用工商服务。编号绑定服务、App、操作者/有效身份及查询条件；换系统、身份、关键词或页码复用会返回 409。名称等显示信息变更不影响重试。

每个新编号会调用一次已购工商 API，并在返回前保存本页全部企业、查询快照及来源。返回的 `companies` 每项只有两个业务字段，其他完整工商资料留在 Auth 的企业库和历史查询中。

成功响应示例（内容为示例）：

```json
{
  "ok": true,
  "requestId": "trace-id",
  "queryId": 123,
  "queryRequestId": "7d81959b-e27a-44ba-9e86-856ad9e82144",
  "keyword": "示例企业",
  "pageNum": 1,
  "pageSize": 20,
  "status": "succeeded",
  "message": "已保存本页 1 条企业信息",
  "totalRecords": 1,
  "resultCount": 1,
  "hasMore": false,
  "nextPageNum": null,
  "companies": [
    { "companyName": "示例企业有限公司", "creditNo": "" }
  ]
}
```

企业字段统一定义如下，内部接口、单选/多选控件和业务保存快照使用相同名称：

| 字段 | 中文名称 | 含义 |
| --- | --- | --- |
| `companyName` | 企业名称 | 工商服务返回的企业名称 |
| `creditNo` | 统一社会信用代码 | 工商服务返回的统一社会信用代码 |

没有返回统一社会信用代码时，`creditNo` 为空字符串；不用注册号代替，也不生成代码。服务返回脱敏代码时不能将其作为完整代码使用。

`requestId` 和响应头 `X-Request-Id` 是链路跟踪编号；`queryRequestId` 才是查询幂等编号，两者不要混用。`ok: true` 表示请求已处理，仍须读取业务 `status`：

| 状态 | HTTP | 处理方式 |
| --- | --- | --- |
| `succeeded` | 200 | 展示本页 `companies`，允许选择 |
| `empty` | 200 | 显示无匹配企业，不继续翻页 |
| `running` | 202 | 原查询仍在处理，通过下面的只读接口查询状态 |
| `failed` | 200 | 展示 `message`，不会自动重试；用户明确重新查询时才生成新 UUID |

`hasMore: true` 时，“加载更多”用 `nextPageNum`、相同关键词/页容量和新 UUID 请求下一页，再把结果追加到选项。每页都保存为独立历史查询。达到第 100 页、空页、已知总数末尾，或未知总数下不足一页时停止。禁止预取和自动遍历全部页。

请求超时/连接中断时保留原 `queryRequestId`，先读取状态或用原编号重发，不能直接生成新编号自动重试，以免重复计费。后端建议连接/读取超时 `(5, 40)` 秒并关闭自动重试和跨地址重定向。

## 读取查询结果，不调用付费接口

`POST /queries/get`

```json
{ "queryRequestId": "7d81959b-e27a-44ba-9e86-856ad9e82144" }
```

如果原查询带了用户 `token`，这里也需转发同一操作者/有效身份的有效 token（可以是正常刷新后的 token）。响应结构与 `/search` 相同。只允许读取该服务、App 和身份对应的查询；不存在或越权均返回 404。不会列出其他系统查询，也不会自动恢复中断的付费任务。

常见请求错误：400 `INVALID_REQUEST`；401/403 无效登录凭证；403 内部服务/密钥无效、未注册或停用；404 `NOT_FOUND`；409 `REGISTRY_REQUEST_CONFLICT`；503 `REGISTRY_NOT_CONFIGURED`。服务调用失败时不要把用户 token、内部 Secret 或上游认证信息写入错误日志。

## 复用已购企业身份（不收费）

`POST /companies/cached`，请求 `{"keywords":["完整企业名称","完整统一社会信用代码"]}`，最多100个条件。使用同一内部服务鉴权，按名称或代码**精确匹配**，不做模糊搜索、不触发上游、不创建查询记录。响应 `items` 按条件返回 `keyword`、`truncated` 及最多20个 `companies`；企业仅包含 `companyName`、`creditNo`、持久证据编号 `evidenceId`、`queriedAt`。证据编号用于业务审计，不赋予读取原查询的权限；原查询身份、上游回执和完整响应不公开。结果是已购历史快照，不保证即时最新；使用方须核验完整代码及主体匹配，不能把无结果当工商不存在。超过20条的条件返回 `truncated: true`，不能自动认定唯一主体。

## 单选、多选落库

业务后端在所属业务表单保存时，仅保存已选企业的企业名称和统一社会信用代码快照。选择、取消选择本身不调用付费服务，也不影响 Auth 已保存的整页结果。

单选字段：

```json
{ "companyName": "选中的企业名称", "creditNo": "对应统一社会信用代码" }
```

多选字段：

```json
[
  { "companyName": "企业甲", "creditNo": "企业甲统一社会信用代码" },
  { "companyName": "企业乙", "creditNo": "企业乙统一社会信用代码" }
]
```

单选未选择时用 `null`，多选未选择时用 `[]`。选中值须将企业名称与统一社会信用代码作为一组快照保存；更改企业名称时应同步重新选择对应代码。完整、未脱敏的统一社会信用代码可用于去重；缺少可靠代码时应保守处理，不能仅凭同名认定为同一家。

现有 Auth 单选、多选组件直接使用 `companyName` 展示企业名称、`creditNo` 展示统一社会信用代码。后续嵌入业务 App 时，提交业务表单也保存这两个字段。本次提供内部接口与数据契约，具体 CRM 表单入口由后续业务接入决定。

## 部署和验证

迁移 `0020_business_registry_source` 为查询记录增加来源 App、服务两个字段；原管理页记录空来源代表 Auth。新增列保留数据库默认空字符串，兼容更新窗口中旧版本写入。管理页历史响应新增 `sourceAppId` / `sourceService`，原企业库和历史查询契约保留。

```bash
PYTHONPATH=packages/platform-backend DB_ENGINE=sqlite SQLITE_NAME=:memory: .local/venvs/auth-org-review/bin/python apps/auth/backend/manage.py test identity_api.tests.test_business_registry_internal identity_api.tests.test_business_registry identity_api.tests.test_internal_service_credentials
```

测试隔离数据库、模拟工商服务，不消耗实际查询额度。上线后核对网关 404、后端无公开端口、缺失/错误服务凭据被拒绝，并通过内部服务做只读或参数校验请求；不要为验收发起真实付费查询。
