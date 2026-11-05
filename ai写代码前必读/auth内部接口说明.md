# Auth 内部接口说明

本文档给后续 CRM、线缆商城、产品档案、ERP 等子系统接入统一身份中心时使用。原则是：子系统不要直连 auth 数据库，只通过 auth-backend 的内部接口校验登录态、读取组织架构。

每次开发或接入必须遵守以下当前规则：

```text
1. Auth token 必须绑定服务端 sid；子系统不能自己签发、解码或伪造身份字段。
2. 开始代理、退出代理和退出登录都会废弃旧 sid，旧 token 不得重新写回 Cookie；代理状态下不能再次代理或切换目标。
3. canUseSystemAdmin 跟随当前有效 userId 的白名单身份；canManagePlatformSettings 是独立的后台管理能力，不能扩散为业务 App 最高权限。
4. 账号“禁用”由 Auth 统一判断；普通账号登录、Token 校验和作为代理目标都必须失败，系统级白名单账号即使被禁用也允许登录和 Token 校验。子系统不再自行判断账号禁用或白名单状态。
5. 组织同步必须先通过空快照、数量骤降和分页完整性校验，失败时不得覆盖正式组织数据。
6. 部门允许多个主管；managerUserId/manager 是第一主管兼容字段，managerUserIds/managers 是完整结果。
7. 登录、退出和代理变化通过同源跨标签页会话广播同步，页面缓存不能作为后端授权依据。
8. introspect 只校验身份，不刷新或返回 token；子系统绝对不能写回 Auth Cookie。会话续期只能由浏览器定时调用 Auth 的 `/api/auth/session/validate` 完成。
9. 跨标签收到不同 sessionId/userId/actorUserId 时必须完整重新加载页面，不能只更新顶部姓名。
10. 所有组织接口返回 orgRevision；同一次分页或跨接口快照必须使用同一版本，版本变化时调用方重新拉取。 `orgRevision` 表示实际目录变更，不能作为同步次数；无内容变化的定时同步只刷新成功同步时间，保持版本及目录行时间戳不变。同步摘要的 `organizationChanged` 表示是否发布了实际变更。
11. 少量钉钉员工详情失败时保留已有员工资料；新员工没有可保留资料时整次同步失败。失败比例超过阈值时同样整次失败，不覆盖正式数据。
12. 每个 App 必须通过 `apps/<app-id>/app.manifest.yaml` 注册容器、公开路由、门户信息和图标；业务权限由 App 后端自己判断，门户和网关不做人员授权。
13. App 密码和签名密钥只能放在 `secrets/apps/<app-id>/`，由 Docker Secret 挂载；真实值不得写入 `.env`、清单或 Git。
14. Auth 内部服务凭据由清单同步到 `internal_service_credentials`，数据库只保存加盐摘要；禁止恢复 `AUTH_INTERNAL_SERVICE_SECRETS` 或共享密钥回退。
15. 新 App 使用 `scripts/app-deploy.sh <app-id> <env-file>` 部署，只刷新该 App、Auth 接入和网关，不重启 CRM 等无关业务应用。
16. 清单 `status` 只用于展示，不停止容器、不关闭路由、不禁用内部凭据；旧 `permissions/access/redirectOnDenied` 字段禁止使用。
17. 浏览器写接口必须同源；`same-site` 子域和 `cross-site` 请求都应返回 `CROSS_ORIGIN_WRITE_BLOCKED`。
18. 失效的旧请求不得删除 Auth Cookie；收到 `401` 时先用浏览器当前 Cookie 再校验一次，防止代理切换后的新会话被旧响应冲掉。
```

## 1. 调用地址

Docker 内部网络调用：

```text
AUTH_INTROSPECTION_URL=http://auth-backend:8000/api/internal/auth/introspect
AUTH_ORG_INTERNAL_URL=http://auth-backend:8000/api/internal/org
```

公网、浏览器、前端页面不要直接调用 `/api/internal/*`。

## 2. 内部调用认证

所有 `/api/internal/*` 接口都必须带内部服务密钥。

请求头：

```http
Content-Type: application/json
X-Internal-Service: crm-backend
X-Internal-Auth-Secret: <该服务对应的内部密钥>
X-Request-Id: <可选，建议传链路追踪 id>
```

每个 App 在自己的 `app.manifest.yaml` 中声明 `auth.internalService`。部署工具为它创建独立 Secret，并向子系统容器注入：

```text
SERVICE_NAME=crm-backend
AUTH_SERVICE_INTROSPECTION_SECRET_FILE=/run/secrets/crm_auth_introspection
```

Auth 启动时读取 `.runtime/apps-registry.json`，把服务名、App ID、启用状态和 Secret 摘要同步到数据库。原始 Secret 不写入 Auth 数据库。`X-Internal-Service` 必须和数据库登记的服务名一致，否则返回 `403 UNKNOWN_INTERNAL_SERVICE`。

产品档案固定使用 `SERVICE_NAME=product-archive-backend`。它将 Auth 返回的 `canUseSystemAdmin=true` 映射为产品档案最高权限，不能在产品档案内重复校验系统白名单。

## 3. 统一返回格式

成功：

```json
{
  "ok": true,
  "requestId": "..."
}
```

失败：

```json
{
  "ok": false,
  "code": "INVALID_INTERNAL_SECRET",
  "error": "Invalid internal auth secret",
  "requestId": "..."
}
```

常见错误：

```text
400 INVALID_REQUEST
401 UNAUTHORIZED / INVALID_AUTH_TOKEN
403 INVALID_INTERNAL_SECRET / UNKNOWN_INTERNAL_SERVICE / FORBIDDEN
503 AUTH_SERVICE_UNAVAILABLE
```

## 4. 登录态校验接口

### POST /api/internal/auth/introspect

用途：子系统后端拿浏览器传来的 auth token，向 auth 校验当前用户是谁、是否代理、是否可用。

请求体：

```json
{
  "token": "<mj_auth_token 或 Authorization Bearer token>"
}
```

成功返回核心字段：

```json
{
  "ok": true,
  "knownEmployee": true,
  "sessionId": "<服务端 sid>",
  "userId": "02450963154881",
  "name": "姚欣",
  "nick": "姚欣",
  "avatarUrl": "https://...",
  "status": "在职",
  "accountStatus": "启用",
  "isSystemAdmin": false,
  "canUseSystemAdmin": false,
  "isFullAccessUser": false,
  "canManagePlatformSettings": false,
  "canConfigurePermissions": false,
  "canManageEmployeeAccountStatus": false,
  "canProxy": false,
  "canStartProxy": false,
  "canSwitchProxy": false,
  "isProxying": true,
  "actorUserId": "01333608525827896521",
  "actorName": "江颂扬",
  "actorDisplay": "江颂扬 (01333608525827896521)",
  "claims": {},
  "requestId": "..."
}
```

子系统处理建议：

```text
1. 浏览器请求子系统后端时，子系统从 Authorization: Bearer 或 cookie mj_auth_token 里取 token。
2. 子系统后端调用 /api/internal/auth/introspect。
3. introspect 返回 200 且 ok=true，才认为登录有效。
4. 子系统用 userId 做当前业务用户。
5. isProxying=true 时，userId 是被代理人，actorUserId 是实际操作人；业务逻辑需要区分两者时直接使用 Auth 返回值。
6. 子系统如需把平台级管理员映射为本系统最高权限，只能使用 canUseSystemAdmin；不得读取本系统环境变量重复判断系统白名单。
7. introspect 不返回新 token；子系统不得设置、刷新或覆盖 mj_auth_token cookie。
```

字段权限语义：

```text
isSystemAdmin：当前有效 userId 是否属于 Auth 的 FULL_ACCESS_USER_IDS，只表示身份。
isProxying：当前是否为代理会话；代理时 userId 是被代理人，actorUserId 是实际操作者。
canUseSystemAdmin：等于当前有效 userId 的白名单能力；不继承 actor，但代理到白名单目标时仍为 true。
canManagePlatformSettings / canConfigurePermissions：当前有效 userId 的后台管理能力，可来自白名单或权限设置；子系统不得据此授予业务最高权限。
canStartProxy / canProxy：只有非代理白名单会话为 true。
canSwitchProxy：兼容字段，固定为 false；代理后不能再次代理或切换目标。
isFullAccessUser：兼容旧前端的身份别名，新接入的子系统不要读取或返回它进行授权。
```

安全要求：以上字段只能由子系统后端从 Auth 内部 introspect 响应读取。浏览器传入、查询参数、请求体或前端缓存里的同名字段一律不可信。CRM 将 `canUseSystemAdmin=true` 映射为 CRM 管理员，不读取 `canManagePlatformSettings` 扩权。代理后的全部能力按目标 `userId` 重新计算：普通目标不继承 actor 的白名单，白名单目标保留自己的白名单能力，目标在各 App 内原有的业务角色仍然有效。

### POST /api/internal/auth/service/validate

用途：目标子系统收到另一个 App 的 `X-Internal-Service` 和 `X-Internal-Auth-Secret` 后，将这两个头原样转交 Auth 校验。成功返回 `serviceName` 和 `appId`，目标子系统再按自己的调用方白名单授权。该接口不校验用户登录态，也不签发 token。

## 5. 子系统后端 Cookie 规则

auth cookie 名称：

```text
mj_auth_token
```

Cookie 只能由 Auth 登录、代理切换、退出代理和 `/api/auth/session/validate` 设置或删除：

```text
HttpOnly=true
Secure=true
SameSite=Lax
Path=/
```

子系统业务响应不得携带 `Set-Cookie: mj_auth_token=...`。这是为了避免代理切换或退出时，较慢的旧请求在最后返回并覆盖新会话。

## 工商查询内部接口

CRM 等业务系统后端可使用相同的注册服务凭据调用：

```text
POST http://auth-backend:8000/api/internal/business-registry/search
POST http://auth-backend:8000/api/internal/business-registry/queries/get
```

`/search` 按显式指定页调用已购工商服务并保存整页；`/queries/get` 仅读取该调用服务和身份的原查询，不消耗额度。每条企业仅返回企业名称 `companyName`、统一社会信用代码 `creditNo`，供业务系统保存单选对象或多选数组。查询 UUID 使用 `queryRequestId`，与链路 `requestId` 分开。可由后端转发有效用户 `token` 记录实际操作/代理身份；纯后台任务不传 token 时按服务记名。

两者只走 Docker 内网，网关不开放；业务后端独立校验 App 使用权限，不把内部服务 Secret 交给前端。完整请求、分页、幂等、错误处理和选中值格式见 [工商查询内部接口文档](../apps/auth/BUSINESS_REGISTRY_INTERNAL_API.md)。

## 6. 组织架构内部接口通用参数

所有组织内部接口都是 POST，路径前缀：

```text
/api/internal/org
```

所有成功响应都包含非负整数 `orgRevision`，响应头同时包含 `X-Organization-Revision`。分页读取、部门和员工分批读取必须确认版本一致；发现变化时废弃本次结果并重新拉取。内部目录只返回全系统明确启用的部门；如果某个启用部门的直接父部门未启用，该部门作为裁剪目录的根节点返回，`parentDeptId` 为 `null`，不会为了补齐路径自动启用父部门。

常用过滤参数：

```json
{
  "status": "active",
  "accountStatus": "enabled",
  "includeDepartments": true,
  "includeDepartmentPath": true,
  "includeSubDepartments": true
}
```

取值说明：

```text
status:
  active / 在职
  inactive / 离职
  all / *

accountStatus:
  enabled / 启用
  disabled / 禁用
  all / *

includeDepartmentPath:
  true 时，部门对象会额外返回 departmentPath 和 departmentPathText
```

数量限制：

```text
userIds 最多 500 个
departmentIds 最多 200 个
items 最多 500 个
搜索接口 limit 最大 100，默认 20
```

员工对象字段：

```json
{
  "userId": "02450963154881",
  "name": "姚欣",
  "rawName": "姚欣",
  "pinyin": "yaoxin",
  "pinyinInitials": "yx",
  "avatarUrl": "https://...",
  "status": "在职",
  "accountStatus": "启用",
  "isSystemAdmin": false,
  "handoverUserId": "",
  "handoverEmployee": null,
  "createTime": "...",
  "updatedAt": "...",
  "departments": []
}
```

内部组织接口返回的 `isSystemAdmin` 只描述员工是否属于 Auth 系统管理员名单，不参与 App 当前请求授权。人员选择器不得因此隐藏系统管理员；系统管理员也可以像普通员工一样预先分配 App 业务权限。

部门对象字段：

```json
{
  "deptId": 1,
  "name": "杭州迈杰教育科技有限公司",
  "pinyin": "hangzhoumaijiejiaoyukejiyouxiangongsi",
  "pinyinInitials": "hzmjjykjyxgs",
  "managerUserId": "02450963154881",
  "managerUserIds": ["02450963154881", "另一个主管userId"],
  "parentDeptId": null,
  "updatedAt": "..."
}
```

部门对象中的 `managerUserId` 是第一主管兼容字段，`managerUserIds` 是全部主管 userId。主管查询和领导链同时返回 `manager` 与 `managers`；新代码需要完整主管范围时必须使用复数字段。

## 7. 组织架构接口列表

### POST /api/internal/org/users/departure-history

CRM 管理员“离职成员”页专用的只读批量接口。请求必须带 CRM App 注册凭据（认证后的 `app_id=crm`）；其他 App 返回403。CRM 后端须先校验当前用户的 CRM 管理员及以上权限，只传 CRM 已有历史名单/交接记录中的 ID。请求体 `{"userIds":["001","002"]}`，必传数组、最多500个，空数组不列出任何人员。响应含 `orgRevision`，多批次必须校验同一版本。

返回 `items`：每项包含 `userId`、`found`；找到钉钉员工时另返回 `name`、`status`、`pinyin`、`pinyinInitials`。拼音使用 Auth 统一目录转换，供 CRM 历史人员搜索及管理员执行既有员工快照的搜索元数据补齐，不扩充业务候选。只有当前离职人员返回 `formerDingTalkDepartments: [{deptId,name,pathText}]` 和 `formerOrganizationRecordedAt`。当前在职者不返回历史部门，调用方应排除出离职名单；找不到时 `found=false`，不能仅凭姓名推测身份。快照为空时不使用当前部门补齐。

该接口读取离职时已保存的历史，不要求仍有现行部门关系，因此不套用当前启用部门的关系过滤；这不扩展现有搜索/权限目录，也不能用于授予离职人员访问权。不支持关键词搜索或全量枚举，不返回电话、账号状态等额外资料。记录时间仅表示同步首次发现离职的时间，不是人事离职日期。

### POST /api/internal/org/users/search

用途：按关键字搜索员工，供 CRM、线材商城、ERP 等子系统做人员选择器。默认只返回在职且启用账号。

请求：

```json
{
  "keyword": "姚欣",
  "limit": 20,
  "offset": 0,
  "status": "active",
  "accountStatus": "enabled",
  "includeDepartments": true,
  "includeDepartmentPath": true,
  "departmentIds": [1],
  "includeSubDepartments": true
}
```

参数说明：

```text
keyword / q：匹配员工姓名、userId、姓名全拼或拼音首字母，可为空；为空时按姓名和 userId 返回前 limit 条
纯英文拼音不区分大小写，并忽略空格、连字符和英文撇号，例如 jiang song yang 与 jsy 都可匹配 江颂扬
不支持字和拼音混合搜索，例如 江sy 不会按拼音拆开匹配
departmentIds：可选，用于把搜索范围限制在指定部门
includeSubDepartments：departmentIds 存在时生效，true 表示包含下级部门
status/accountStatus：默认 active/enabled；需要搜索离职或禁用账号时显式传 inactive/all、disabled/all
```

返回：

```json
{
  "ok": true,
  "keyword": "姚欣",
  "limit": 20,
  "offset": 0,
  "status": "active",
  "accountStatus": "enabled",
  "includeDepartments": true,
  "includeDepartmentPath": true,
  "departmentIds": [1],
  "scopeDepartmentIds": [1, 2, 3],
  "total": 1,
  "count": 1,
  "items": [
    {
      "userId": "02450963154881",
      "name": "姚欣",
      "rawName": "姚欣",
      "pinyin": "yaoxin",
      "pinyinInitials": "yx",
      "avatarUrl": "https://...",
      "status": "在职",
      "accountStatus": "启用",
      "departments": []
    }
  ]
}
```

### POST /api/internal/org/departments/search

用途：按关键字搜索部门，供子系统做部门选择器或权限范围选择。支持按部门名称模糊搜索，也支持用完整 deptId 搜索。

请求：

```json
{
  "keyword": "商务",
  "limit": 20,
  "offset": 0,
  "includeDepartmentPath": true,
  "departmentIds": [1],
  "includeSubDepartments": true
}
```

参数说明：

```text
keyword / q：匹配部门名称、deptId、名称全拼或拼音首字母
纯英文拼音不区分大小写，并忽略空格、连字符和英文撇号，例如 shang wu bu men 与 swbm 都可匹配 商务部门
不支持字和拼音混合搜索
departmentIds：可选，用于把搜索范围限制在指定部门
includeSubDepartments：departmentIds 存在时生效，true 表示包含下级部门
```

返回：

```json
{
  "ok": true,
  "keyword": "商务",
  "limit": 20,
  "offset": 0,
  "includeDepartmentPath": true,
  "departmentIds": [1],
  "scopeDepartmentIds": [1, 2, 3],
  "total": 1,
  "count": 1,
  "items": [
    {
      "deptId": 10,
      "name": "商务部门",
      "pinyin": "shangwubumen",
      "pinyinInitials": "swbm",
      "managerUserId": "",
      "parentDeptId": 1,
      "departmentPath": [],
      "departmentPathText": "杭州迈杰教育科技有限公司 / 商务部门",
      "updatedAt": "..."
    }
  ]
}
```

### POST /api/internal/directory/administrative-regions/search

用途：从 Auth 发布的国家标准省、市、区县目录中按名称、行政区代码、全拼或拼音首字母搜索。可传 `level`（province/city/district）及 `parentCode`（直属父级的六位字符串，空字符串表示根级）组合筛选；空关键词时列举当前条件下的区域。该接口使用相同的内部服务认证头，但路径不在 `/api/internal/org` 下，也不返回 `orgRevision`。

其他应用可用 `POST /api/internal/directory/administrative-regions`、请求体 `{}` 读取完整三级目录、统计和同一个 `revision`；用 `POST /api/internal/directory/administrative-regions/get`、请求体 `{"code":"330110"}` 精确读取单条区域。平铺记录还包含实际直属父级 `parentCode`。完整调用说明以及平台我司主体查询见 [平台基础数据查询接口](../docs/PLATFORM_BASE_DATA_API.md)。

请求：

```json
{
  "keyword": "yu hang qu",
  "limit": 20,
  "offset": 0
}
```

返回包含目录 `revision`、`total`、`count` 以及最小目录字段：

```json
{
  "ok": true,
  "revision": "vant-area-data-2.2.0",
  "items": [
    {
      "code": "330110",
      "name": "余杭区",
      "pinyin": "yuhangqu",
      "pinyinInitials": "yhq",
      "level": "district",
      "levelLabel": "区县",
      "path": "浙江省 / 杭州市 / 余杭区",
      "provinceCode": "330000",
      "cityCode": "330100"
    }
  ]
}
```

### POST /api/internal/org/users/departments

用途：查询用户所在部门。

请求：

```json
{
  "userIds": ["02450963154881"],
  "status": "active",
  "accountStatus": "enabled",
  "includeDepartmentPath": true,
  "includeEmployeeProfiles": true
}
```

返回每个用户：

```json
{
  "userId": "02450963154881",
  "found": true,
  "matchesFilters": true,
  "departmentIds": [1, 2],
  "departments": [],
  "employee": {}
}
```

### POST /api/internal/org/users/leader-chain

用途：查询某员工在某部门向上的主管链。

请求：

```json
{
  "items": [
    { "userId": "02450963154881", "departmentId": 1 }
  ],
  "maxDepth": 5,
  "includeDepartmentPath": true
}
```

返回每个输入项：

```json
{
  "userId": "02450963154881",
  "departmentId": 1,
  "found": true,
  "departmentFound": true,
  "validMembership": true,
  "count": 2,
  "items": [
    {
      "level": 1,
      "department": {},
      "managerUserId": "...",
      "manager": {},
      "isSelf": false
    }
  ]
}
```

### POST /api/internal/org/users/colleagues

用途：查询员工在某部门的同部门同事。

请求：

```json
{
  "items": [
    { "userId": "02450963154881", "departmentId": 1 }
  ],
  "includeSelf": false,
  "includeDepartments": true
}
```

返回每个输入项：

```json
{
  "userId": "02450963154881",
  "departmentId": 1,
  "validMembership": true,
  "count": 10,
  "items": []
}
```

### POST /api/internal/org/users/managed-departments

用途：查询某人直接负责的部门，必要时包含下级部门。

请求：

```json
{
  "userIds": ["02450963154881"],
  "includeSubDepartments": true,
  "includeDepartmentPath": true
}
```

返回每个用户：

```json
{
  "userId": "02450963154881",
  "found": true,
  "directDepartmentIds": [1],
  "directDepartments": [],
  "departmentIds": [1, 2, 3],
  "departments": []
}
```

### POST /api/internal/org/users/managed-employees

用途：查询某人负责部门下的员工。

请求：

```json
{
  "userIds": ["02450963154881"],
  "includeSubDepartments": true,
  "includeDepartments": true,
  "status": "active",
  "accountStatus": "enabled"
}
```

返回每个用户：

```json
{
  "userId": "02450963154881",
  "found": true,
  "directDepartmentIds": [1],
  "uniqueEmployeeCount": 20,
  "uniqueEmployees": [],
  "groups": [
    {
      "departmentId": 1,
      "department": {},
      "scopeDepartmentIds": [1, 2, 3],
      "count": 20,
      "employees": []
    }
  ]
}
```

### POST /api/internal/org/departments/employees

用途：查询部门员工，可选包含子部门。

请求：

```json
{
  "departmentIds": [1],
  "includeSubDepartments": true,
  "includeDepartments": true,
  "status": "active",
  "accountStatus": "enabled"
}
```

返回每个部门：

```json
{
  "departmentId": 1,
  "found": true,
  "department": {},
  "scopeDepartmentIds": [1, 2, 3],
  "count": 20,
  "items": []
}
```

### POST /api/internal/org/departments/managers

用途：查询部门主管。

请求：

```json
{
  "departmentIds": [1, 2],
  "status": "active",
  "accountStatus": "enabled",
  "includeDepartments": true
}
```

返回每个部门：

```json
{
  "departmentId": 1,
  "found": true,
  "department": {},
  "managerUserId": "02450963154881",
  "manager": {}
}
```

### POST /api/internal/org/departments/children

用途：查询子部门。

请求：

```json
{
  "departmentIds": [1],
  "includeSubDepartments": true,
  "includeDepartmentPath": true
}
```

返回每个部门：

```json
{
  "departmentId": 1,
  "found": true,
  "department": {},
  "childDepartmentIds": [2, 3],
  "children": []
}
```

### POST /api/internal/org/departments/ancestor-chain

用途：查询部门向上的祖先链。

请求：

```json
{
  "departmentIds": [10],
  "maxDepth": 5,
  "includeDepartmentPath": true
}
```

返回每个部门：

```json
{
  "departmentId": 10,
  "found": true,
  "department": {},
  "count": 3,
  "items": []
}
```

## 8. 子系统接入建议

每个子系统后端建议封装一个统一 auth middleware：

```text
1. 对公开接口放行，例如健康检查、静态资源。
2. 对业务接口读取 Authorization Bearer，读不到再读 cookie mj_auth_token。
3. 调 auth introspect。
4. 把 userId/name/avatar/isProxying/actorUserId 挂到 request 上。
5. 不设置或刷新 Auth Cookie，会话续期由前端调用 Auth 自己的校验接口。
6. 子系统自己的权限仍由子系统判断，不要把 auth 的 full access 当成所有系统业务权限。
```

## 9. curl 示例

校验 token：

```bash
curl -sS \
  -H 'Content-Type: application/json' \
  -H 'X-Internal-Service: crm-backend' \
  -H 'X-Internal-Auth-Secret: <crm-secret>' \
  -d '{"token":"<mj_auth_token>"}' \
  http://auth-backend:8000/api/internal/auth/introspect
```

查询用户部门：

```bash
curl -sS \
  -H 'Content-Type: application/json' \
  -H 'X-Internal-Service: crm-backend' \
  -H 'X-Internal-Auth-Secret: <crm-secret>' \
  -d '{"userIds":["02450963154881"],"includeDepartmentPath":true,"includeEmployeeProfiles":true}' \
  http://auth-backend:8000/api/internal/org/users/departments
```

## 10. Auth 管理端补充接口

以下接口是 Auth 页面使用的登录态接口，不属于 `/api/internal/*`，子系统后端查组织数据仍应使用前面的内部接口。

### 部门搜索

```http
GET /api/org/departments/search?keyword=jsy&limit=20
```

匹配部门名称、`deptId`、中文部门名全拼和拼音首字母。拼音不区分大小写并忽略空格、连字符和英文撇号，不支持汉字与拼音混合搜索。返回部门对象包含 `pinyin` 与 `pinyinInitials`。

### 行政区目录与搜索

```http
GET /api/directory/administrative-regions
GET /api/directory/administrative-regions/search?keyword=yuhangqu&limit=20
```

完整目录和搜索结果使用 Auth 数据库当前发布的同一个 revision；搜索支持名称、行政区代码、全拼和拼音首字母。行政区记录及拼音存于 `platform_administrative_regions`，发布版本及种子指纹存于 `platform_administrative_region_directories`，通过迁移 `0022_administrative_region_database` 初始化。运行时不读目录文件或重新推断拼音；未初始化、数据不完整或数据库不可用返回 `503 REGION_DIRECTORY_UNAVAILABLE`。其他子系统后端使用前述 `POST /api/internal/directory/administrative-regions/search`，不要抓取管理页接口建立另一套基础数据。

### 异步通讯录同步

```text
POST /api/dingtalk/sync_contacts
GET  /api/dingtalk/sync_contacts/status/<runId>
```

`POST` 成功时返回 `202 Accepted`，从 `syncRun.runId` 取得任务编号，再轮询状态接口。状态为 `running`、`succeeded` 或 `failed`。任务由最小权限 `auth-sync-worker` 执行，同一时间只允许一个同步任务；`auth-sync-scheduler` 默认每 15 分钟触发兜底同步。

同步抓取完成后才会进入数据库事务。员工、部门或关系为空，任一数量相对上次下降超过安全阈值，钉钉分页游标缺失、重复或不前进时，任务必须失败并保留原正式数据。不要为了让任务显示成功而删除这些保护。

### 健康检查与管理后台

```text
GET /api/health/live
GET /api/health/ready
```

`live` 只表示进程存活；`ready` 检查 PostgreSQL、Redis 缓存、Celery broker、同步 worker、定时调度器心跳和钉钉配置。Django `/admin/` 已关闭，不得在网关重新开放独立账号入口。

Auth 不保存接口调用或管理员操作审计表。仅保留登录会话状态、组织同步任务状态以及应用内部服务凭据。

## 平台我司主体目录

我司主体是后台管理独立维护的平台基础数据，存于 Auth，不归 CRM。CRM 和其他 App 是只读使用方。后台管理使用 `/api/directory/company-entities`（GET/POST）和 `/api/directory/company-entities/<id>`（GET/PUT/DELETE），独立校验后台管理权限和记录 revision。

服务间目录使用 `POST /api/internal/directory/company-entities/search`、`get`，支持名称、税号、ID、全拼和首字母搜索，目录只返回 ID、名称和拼音。`search` 传 `{"all":true}` 一次返回全部当前主体，不能同时传 `limit`/`offset`；管理列表也支持 `?all=true`。合同/财务资料通过受调用应用限制的 `profiles/search`、`profiles/get` 读取，资料搜索同样支持税号和全量模式，目前允许 CRM 与生产订单新系统。详情、版本契约和原 ID 迁移说明见 [平台基础数据查询接口](../docs/PLATFORM_BASE_DATA_API.md)。


## 内部应用机器人通知

统一服务前缀 `http://auth-backend:8000/api/internal/robot-messages`，使用本文第 2 节相同的内部服务鉴权头。已登记且启用的应用后端可调用 `POST /send`、`POST /requests/get`、`POST /groups/query`，支持无人员登录的系统通知、群聊及个人、文字和图文混排。来源从服务凭据获取，业务权限与收件范围由调用应用校验；应用只能查询自己服务发出的通知。

防重复发送使用持久 UUID 字段 `messageRequestId`，不能与 HTTP 链路 `requestId` 混用。Auth 记录来源应用、业务编号和逐目标结果，管理员可从机器人发送历史查询；不确定结果禁止自动新建编号重发。内部接口另支持 `message` 结构化消息对象（文字、Markdown、图片、链接、操作卡片、文件、语音、视频），以及 `capabilities`、`media/upload`、`media/get`；人工发送页面保持图文编辑。完整请求、共享 Python 客户端、素材限制和接入规范见 [内部应用机器人通知接口](../docs/ROBOT_NOTIFICATIONS_INTERNAL_API.md)。
