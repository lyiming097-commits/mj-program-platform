# Auth 结构说明

Auth 是系统认证中心，负责登录、token、钉钉认证、钉钉组织、全系统启用部门、员工、部门，以及给其他子系统提供内部身份和组织查询接口。系统管理员身份与代理能力只来自 `FULL_ACCESS_USER_IDS` 白名单；后台管理能力还可由权限设置授予。

## 访问入口

| 入口 | 说明 |
| --- | --- |
| `/auth/` | 登录页面入口。 |
| `/auth/result` | 登录回调结果页。 |
| `/auth/settings/organization` | 钉钉同步的部门和员工架构；桌面端在同一页面配置全系统启用范围。 |
| `/auth/settings/permissions` | 配置后台管理权限来源，后台管理员可修改。 |
| `/auth/settings/handover` | 离职人员只读页面。 |
| `/admin/` | 已在网关和 Auth 路由中关闭。 |
| `/api/health/live` | Auth 进程存活检查。 |
| `/api/health/ready` | 检查数据库、缓存、任务队列、同步 worker、定时调度器和钉钉配置。 |

## 外部接口

外部接口是给浏览器前端、认证中心管理页面使用的接口。除了登录、钉钉环境检查等公开入口外，大部分接口需要通过 HttpOnly Cookie 携带登录会话。

| 方法 | 接口 | 说明 |
| --- | --- | --- |
| `POST` | `/api/auth/code` | 使用钉钉登录 code 换取 Auth token 和用户会话信息。 |
| `GET` | `/api/auth/session/validate` | 校验当前登录 token 是否有效，并返回当前用户信息。 |
| `POST` | `/api/auth/logout` | 撤销当前登录会话并删除 Auth Cookie。 |
| `GET` | `/api/auth/proxy/candidates` | 查询可被代理登录的用户候选列表。 |
| `POST` | `/api/auth/proxy/start` | 非代理白名单账号开始代理并原子撤销旧 sid；代理状态下拒绝再次调用。 |
| `POST` | `/api/auth/proxy/stop` | 停止代理登录，撤销代理 sid 并用新 sid 切回实际操作者。 |
| `GET` | `/api/dingtalk/check_env` | 检查钉钉相关环境变量是否配置。 |
| `GET` | `/api/dingtalk/jsapi_config` | 获取钉钉 JSAPI 配置。 |
| `POST` | `/api/dingtalk/sync_contacts` | 提交通讯录后台同步任务，返回 `202` 和 `runId`。 |
| `GET` | `/api/dingtalk/sync_contacts/status/{runId}` | 查询后台同步任务状态和结果。 |
| `GET` | `/api/org/departments` | 查询部门列表，可按父部门查询直接下级。 |
| `GET` | `/api/org/departments/tree` | 查询部门树。 |
| `GET` | `/api/org/departments/search` | 按名称、deptId、全拼或拼音首字母搜索部门。 |
| `GET/POST` | `/api/directory/company-entities` | 平台独立主体管理；仅后台管理员。 |
| `GET/PUT/DELETE` | `/api/directory/company-entities/<id>` | 主体管理，写入校验记录 revision。 |
| `GET` | `/api/directory/administrative-regions` | 返回 Auth 数据库当前发布的省、市、区县目录及 revision。 |
| `GET` | `/api/directory/administrative-regions/search` | 按名称、行政区代码、全拼或拼音首字母搜索行政区。 |
| `GET` | `/api/org/departments/{deptId}` | 查询单个部门详情、主管、子部门、人数统计。 |
| `GET` | `/api/org/departments/{deptId}/manager` | 查询单个部门主管。 |
| `GET` | `/api/org/departments/{deptId}/subdepartments` | 查询单个部门下面的部门，可选递归。 |
| `GET` | `/api/org/departments/{deptId}/employees` | 查询单个部门下面的员工，可选包含子部门。 |
| `GET` | `/api/org/employees` | 查询员工列表，可按部门、状态、关键字过滤。 |
| `GET` | `/api/org/employees/inactive` | 查询离职员工列表。 |
| `GET` | `/api/org/enabled-departments` | 查询全系统启用的钉钉部门 ID 和配置版本。 |
| `PUT` | `/api/org/enabled-departments` | 后台管理员按 `revision + orgRevision` 保存启用部门。 |
| `GET` | `/api/org/permissions` | 查询后台管理权限来源规则和生效人员。 |
| `PUT` | `/api/org/permissions` | 后台管理员按 `revision + orgRevision` 保存后台管理权限规则。 |
| `GET` | `/api/org/account-status/preview` | 管理员预览账号启停影响人数及当前会话影响，返回 5 分钟有效的确认令牌。 |
| `GET` | `/api/org/account-operations` | 管理员查看账号启停记录，offset 分页，每页 20 条。 |
| `POST` | `/api/org/employees/account-status/bulk` | 批量启用或禁用在职员工账号。 |
| `GET` | `/api/org/employees/{userId}` | 查询单个员工详情和所在部门。 |
| `POST` | `/api/org/employees/{userId}/account-status` | 启用或禁用单个员工账号。 |
| `POST` | `/api/org/employees/{userId}/handover` | 设置或清空离职员工交接人。 |

浏览器端员工、部门和代理候选搜索支持名称、userId/deptId、全拼和拼音首字母；拼音不区分大小写并忽略常见分隔符，不支持汉字与拼音混合搜索。普通员工接口默认只返回在职员工；离职资料和后台管理操作要求当前有效用户拥有后台管理权限，代理入口则只允许非代理白名单账号。

通讯录同步由最小权限 Compose 服务 `auth-sync-worker` 串行执行，`auth-sync-scheduler` 默认每 15 分钟触发一次。数据库单例锁保证同一时间只能创建一个运行中的同步任务。空快照、异常骤降和错误分页会在写正式表前被拒绝。

Auth token 必须包含服务端会话 `sid`。代理身份切换会撤销旧 sid，Token 刷新只能沿用仍处于 active 状态的 sid。部门主管使用 `DepartmentManager` 多主管关系；`Department.manager_user_id` 继续保留为兼容的第一主管字段。

钉钉组织架构是唯一部门来源。全系统启用范围只保存明确勾选的钉钉 `deptId`，父子部门独立启停；首次迁移启用已有全部部门，后续新同步部门默认关闭。启用部门的直接父部门未启用时，内部裁剪目录会将该部门作为根节点返回。后台管理权限范围支持 `department`、`departmentSub`、`employee`、`excludedEmployee`，但只能引用启用部门以及至少属于一个启用部门的在职启用员工。

## 内部接口

内部接口是给其他后端容器调用的接口，例如 CRM、Portal、Cable Mall。调用地址使用 Docker 服务名：

```text
http://auth-backend:8000
```

所有内部接口都必须带内部密钥和调用方服务名：

```text
X-Internal-Auth-Secret: <该服务的 Docker Secret>
X-Internal-Service: crm-backend
```

每个后端服务必须在自己的 `app.manifest.yaml` 中声明独立内部凭据。部署工具通过 Docker Secret 同时挂载给调用方和 Auth；Auth 将其加盐摘要写入 `internal_service_credentials`。不再支持环境变量密钥表或共享密钥回退。

| 方法 | 接口 | 说明 |
| --- | --- | --- |
| `POST` | `/api/internal/auth/introspect` | 子系统拿前端 token 问 Auth：这个用户是谁，token 是否有效。 |
| `POST` | `/api/internal/org/users/search` | 搜索员工，支持姓名、userId、全拼和拼音首字母。 |
| `POST` | `/api/internal/org/users/departure-history` | 仅 CRM 注册服务可按明确 userIds 读取离职前部门快照及当前状态；不支持全量枚举。 |
| `POST` | `/api/internal/directory/company-entities/search`、`get` | 主体名称/税号/ID/拼音搜索，`all:true` 一次全返回；ID精确取数，最小字段。 |
| `POST` | `/api/internal/directory/company-entities/profiles/search`、`profiles/get` | 获准业务服务读取合同/财务主体资料，全部只读。 |
| `POST` | `/api/internal/directory/administrative-regions` | 读取完整省市区目录、统计及数据库发布版本，与后台管理使用相同来源。 |
| `POST` | `/api/internal/directory/administrative-regions/search` | 搜索或列举省市区，支持名称、代码、全拼、首字母及 level/parentCode 条件。 |
| `POST` | `/api/internal/directory/administrative-regions/get` | 按六位字符串 code 精确查询区域及归属路径。 |
| `POST` | `/api/internal/org/users/departments` | 批量查询员工所在部门。 |
| `POST` | `/api/internal/org/users/leader-chain` | 批量查询员工在某个归属部门下的 1级、2级、3级领导链。 |
| `POST` | `/api/internal/org/users/colleagues` | 批量查询员工在某个归属部门下的同部门同事，默认包含自己。 |
| `POST` | `/api/internal/org/users/managed-departments` | 批量查询员工直接管理的部门，可选包含所有子部门。 |
| `POST` | `/api/internal/org/users/managed-employees` | 批量查询员工管理部门下面的人员，可选递归子部门，并返回分组和去重两份结果。 |
| `POST` | `/api/internal/org/departments/employees` | 批量查询部门员工，可选包含所有子部门员工。 |
| `POST` | `/api/internal/org/departments/search` | 搜索部门，支持名称、deptId、全拼和拼音首字母。 |
| `POST` | `/api/internal/org/departments/managers` | 批量查询部门主管。 |
| `POST` | `/api/internal/org/departments/children` | 批量查询部门下面的部门，可选递归到底。 |
| `POST` | `/api/internal/org/departments/ancestor-chain` | 批量查询部门向上的 1级、2级、3级部门链。 |

当前目录内部接口只返回全系统启用部门及其在职启用人员。未启用部门不会出现在搜索、上下级、主管或人员关系结果中；子系统不能通过内部接口读取完整钉钉通讯录。`departure-history` 是 CRM 离职成员页的受限历史查询例外，读取离职时已保存的部门，不要求仍有当前部门关系；CRM 须校验管理员权限并仅提交自己已有历史记录中的 ID，不用于权限授予。

## 内部接口通用规范

### 调用头

所有内部接口都必须带：

```text
Content-Type: application/json
X-Internal-Auth-Secret: <该服务的 Docker Secret>
X-Internal-Service: crm-backend
X-Request-Id: 可选，不传则 Auth 自动生成
```

说明：

- `X-Internal-Auth-Secret`：内部系统密钥，所有内部接口必传。
- `X-Internal-Service`：调用方服务名，每个子系统都要传，例如 `crm-backend`、`portal-backend`、`cable-mall-backend`。Auth 用它查询数据库中的启用凭据并校验 Secret 摘要。
- `X-Request-Id`：链路追踪 ID。调用方传了就沿用，不传 Auth 会自动生成。

没有内部密钥或密钥错误时返回：

```json
{
  "ok": false,
  "code": "INVALID_INTERNAL_SECRET",
  "error": "Invalid internal auth secret",
  "requestId": "99fd899b5dcd4dbeb1f04fe2b48c3eb2"
}
```

### 通用返回格式

成功时：

```json
{
  "ok": true,
  "count": 1,
  "items": [],
  "requestId": "demo-request-001"
}
```

失败时：

```json
{
  "ok": false,
  "code": "INVALID_REQUEST",
  "error": "错误原因",
  "requestId": "demo-request-001"
}
```

常见错误码：

| 错误码 | 说明 |
| --- | --- |
| `INVALID_INTERNAL_SECRET` | 内部系统密钥错误或未传。 |
| `INTERNAL_AUTH_NOT_CONFIGURED` | Auth 内部密钥环境变量未配置。 |
| `MISSING_INTERNAL_SERVICE` | 已启用服务级密钥，但请求没有传 `X-Internal-Service`。 |
| `UNKNOWN_INTERNAL_SERVICE` | 已启用服务级密钥，但调用方服务名不在允许列表里。 |
| `MISSING_AUTH_TOKEN` | token 校验接口未传 token。 |
| `INVALID_AUTH_TOKEN` | token 无效、过期或被拒绝。 |
| `EMPLOYEE_INACTIVE` | 员工已离职，当前 token 被拒绝。 |
| `ACCOUNT_DISABLED` | 账号已禁用，当前 token 被拒绝。 |
| `AUTH_VERSION_MISMATCH` | 用户认证版本已变化，需要重新登录。 |
| `AUTH_SESSION_NOT_FOUND` | sid 不存在，通常是旧版或伪造 token。 |
| `AUTH_SESSION_REVOKED` | sid 已退出、被替换或过期。 |
| `AUTH_SESSION_MISMATCH` | sid 与 token 中的用户或代理身份不一致。 |
| `PROXY_ACTOR_NOT_FOUND` | 代理登录的实际操作者不存在。 |
| `PROXY_ACTOR_INACTIVE` | 代理登录的实际操作者已离职。 |
| `PROXY_ACTOR_ACCOUNT_DISABLED` | 代理登录的实际操作者账号已禁用。 |
| `PROXY_AUTH_VERSION_MISMATCH` | 代理登录版本已变化，需要重新登录。 |
| `PROXY_ACTOR_NOT_SYSTEM_ADMIN` | 代理操作者已被移出系统白名单。 |
| `INVALID_REQUEST` | 请求参数格式不对。 |
| `METHOD_NOT_ALLOWED` | 请求方法不允许，例如内部接口要求 `POST` 却用了 `GET`。 |

### 员工过滤参数

所有返回员工列表或员工资料的标准内部组织接口，都支持：

| 参数 | 默认值 | 可选值 | 说明 |
| --- | --- | --- | --- |
| `status` | `active` | `active`、`inactive`、`all` | 员工状态。`active` 只返回在职员工，`inactive` 只返回离职员工，`all` 不按员工状态过滤。 |
| `accountStatus` | `enabled` | `enabled`、`disabled`、`all` | 账号状态。员工在职和账号启用是两回事。 |
| `includeDepartments` | `false` | `true`、`false` | 员工资料里是否带所在部门。 |
| `includeDepartmentPath` | `false` | `true`、`false` | 部门信息里是否带完整部门路径。 |

### 部门递归参数

部门相关接口常用：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `includeSubDepartments` | `false` | 是否包含所有下级部门。 |
| `maxDepth` | 不限制 | 最大向上查询层级。不传就一直查到根部门。 |
| `includeDepartmentPath` | `false` | 是否返回部门完整路径。 |

### 空值规则

- 传入多个 `userId` 或 `departmentId` 时，按传入顺序返回多个结果。
- 用户不存在时，`found=false`。
- 部门不存在时，`found=false`。
- 传入 `userId + departmentId` 但用户不属于该部门时，`validMembership=false`，人员结果为空数组。
- 部门没有主管时，`manager=null`。
- 领导链中某一级部门主管为空时，该级 `manager=null`，但继续向上查。
- 部门员工递归查询时，按 `userId` 去重。

## 内部接口输入输出详解

### token 校验

接口：

```text
POST /api/internal/auth/introspect
```

输入：

```json
{
  "token": "前端传给子系统后端的 Bearer token"
}
```

输出：

```json
{
  "ok": true,
  "userId": "当前业务身份用户ID",
  "actorUserId": "实际操作者用户ID",
  "isSystemAdmin": false,
  "canUseSystemAdmin": false,
  "isFullAccessUser": false,
  "canManagePlatformSettings": false,
  "canConfigurePermissions": false,
  "isProxying": false,
  "canStartProxy": false,
  "canSwitchProxy": false,
  "claims": {}
}
```

说明：

- `userId` 是当前被当作登录用户的人。
- `actorUserId` 是实际操作的人。没有代理登录时通常等于 `userId`。
- `isSystemAdmin` 表示当前有效 `userId` 是否属于 Auth 系统白名单，只表示身份。
- `canUseSystemAdmin` 是子系统可直接消费的系统管理员能力，按当前有效 `userId` 计算；不继承代理操作者，但代理到白名单目标时保留。
- `isFullAccessUser` 是兼容旧前端的身份别名，新子系统不要用它直接授权。
- `canManagePlatformSettings` / `canConfigurePermissions` 表示后台管理能力，可来自白名单或权限设置；业务 App 不得把它映射为本系统最高权限。
- `isProxying` 表示是否正在代理登录。
- `canStartProxy` 只在非代理白名单会话中为 `true`；`canSwitchProxy` 固定为 `false`。
- introspect 不刷新 token，子系统不得设置或覆盖 Auth Cookie；会话续期由前端调用 `/api/auth/session/validate`。

子系统只能信任后端调用 introspect 得到的字段，不能信任浏览器传入的同名字段。普通业务权限仍由子系统维护；需要继承系统管理员能力时使用 `canUseSystemAdmin`，不要重复读取 `FULL_ACCESS_USER_IDS`。

### 查询员工所在部门

接口：

```text
POST /api/internal/org/users/departments
```

输入：

```json
{
  "userIds": ["001", "002"],
  "status": "active",
  "accountStatus": "enabled",
  "includeDepartmentPath": true,
  "includeEmployeeProfiles": false
}
```

输出：

```json
{
  "ok": true,
  "status": "active",
  "accountStatus": "enabled",
  "includeDepartmentPath": true,
  "count": 2,
  "items": [
    {
      "userId": "001",
      "found": true,
      "matchesFilters": true,
      "departmentIds": [10],
      "departments": []
    }
  ]
}
```

### 查询员工领导链

接口：

```text
POST /api/internal/org/users/leader-chain
```

输入：

```json
{
  "items": [
    {
      "userId": "001",
      "departmentId": 10
    }
  ],
  "maxDepth": 3,
  "status": "active",
  "accountStatus": "enabled",
  "includeDepartmentPath": true
}
```

输出：

```json
{
  "ok": true,
  "items": [
    {
      "userId": "001",
      "departmentId": 10,
      "found": true,
      "departmentFound": true,
      "validMembership": true,
      "count": 3,
      "items": [
        {
          "level": 1,
          "department": {},
          "managerUserId": "100",
          "manager": {},
          "isSelf": false
        }
      ]
    }
  ]
}
```

说明：

- 1级部门是传入的 `departmentId`。
- 2级部门是父部门。
- 3级部门是爷爷部门。
- 主管为空时 `manager=null`。

### 查询同部门同事

接口：

```text
POST /api/internal/org/users/colleagues
```

输入：

```json
{
  "items": [
    {
      "userId": "001",
      "departmentId": 10
    }
  ],
  "includeSelf": true,
  "status": "active",
  "accountStatus": "enabled"
}
```

输出：

```json
{
  "ok": true,
  "items": [
    {
      "userId": "001",
      "departmentId": 10,
      "found": true,
      "departmentFound": true,
      "validMembership": true,
      "includeSelf": true,
      "count": 5,
      "items": []
    }
  ]
}
```

### 查询人管理的部门

接口：

```text
POST /api/internal/org/users/managed-departments
```

输入：

```json
{
  "userIds": ["001"],
  "includeSubDepartments": true,
  "includeDepartmentPath": true
}
```

输出：

```json
{
  "ok": true,
  "items": [
    {
      "userId": "001",
      "found": true,
      "directDepartmentIds": [10],
      "directDepartments": [],
      "departmentIds": [10, 11, 12],
      "departments": []
    }
  ]
}
```

### 查询人管理部门下面的人员

接口：

```text
POST /api/internal/org/users/managed-employees
```

输入：

```json
{
  "userIds": ["001"],
  "includeSubDepartments": true,
  "status": "active",
  "accountStatus": "enabled",
  "includeDepartments": true,
  "includeDepartmentPath": true
}
```

输出：

```json
{
  "ok": true,
  "items": [
    {
      "userId": "001",
      "found": true,
      "directDepartmentIds": [10],
      "groups": [
        {
          "departmentId": 10,
          "department": {},
          "scopeDepartmentIds": [10, 11, 12],
          "count": 20,
          "employees": []
        }
      ],
      "uniqueEmployeeCount": 20,
      "uniqueEmployees": []
    }
  ]
}
```

说明：

- `groups` 是按这个人直接管理的部门分组。
- `uniqueEmployees` 是所有分组合并后的去重人员。

### 查询部门员工

接口：

```text
POST /api/internal/org/departments/employees
```

输入：

```json
{
  "departmentIds": [10, 20],
  "includeSubDepartments": true,
  "status": "active",
  "accountStatus": "enabled",
  "includeDepartments": true
}
```

输出：

```json
{
  "ok": true,
  "items": [
    {
      "departmentId": 10,
      "found": true,
      "department": {},
      "scopeDepartmentIds": [10, 11, 12],
      "count": 20,
      "items": []
    }
  ]
}
```

### 查询部门主管

接口：

```text
POST /api/internal/org/departments/managers
```

输入：

```json
{
  "departmentIds": [10, 20],
  "status": "active",
  "accountStatus": "enabled"
}
```

输出：

```json
{
  "ok": true,
  "items": [
    {
      "departmentId": 10,
      "found": true,
      "department": {},
      "managerUserId": "001",
      "manager": {}
    }
  ]
}
```

### 查询部门下面的部门

接口：

```text
POST /api/internal/org/departments/children
```

输入：

```json
{
  "departmentIds": [10],
  "includeSubDepartments": true,
  "includeDepartmentPath": true
}
```

输出：

```json
{
  "ok": true,
  "items": [
    {
      "departmentId": 10,
      "found": true,
      "department": {},
      "childDepartmentIds": [11, 12],
      "children": []
    }
  ]
}
```

### 查询部门上级链

接口：

```text
POST /api/internal/org/departments/ancestor-chain
```

输入：

```json
{
  "departmentIds": [10],
  "maxDepth": 3,
  "includeDepartmentPath": true
}
```

输出：

```json
{
  "ok": true,
  "items": [
    {
      "departmentId": 10,
      "found": true,
      "department": {},
      "count": 3,
      "items": [
        {
          "level": 1,
          "department": {}
        }
      ]
    }
  ]
}
```

说明：

- 1级是父部门。
- 2级是爷爷部门。
- 3级继续向上。
- 不传 `maxDepth` 就一直查到根部门。


## 机器人群发模块

- `backend/identity_api/robot_messages.py`：浏览器 API、独立发送授权、群登记、历史与任务执行。
- `backend/identity_api/dingtalk/messages.py`：钉钉文本群消息/私聊单次发送，统一明确失败与不确定结果。
- `backend/identity_api/tasks.py`：`auth.send_robot_messages` 队列入口。
- `backend/identity_api/migrations/0023_robot_messages.py`：四张消息表及已验证群登记。
- `frontend/src/components/settings/SettingsRobotMessagesPanel_web.vue`：聊天发送与权限页签，复用 `SettingsOrganizationPermissionsPanel.vue`。
- `ROBOT_MESSAGES.md`：权限、API、状态、幂等及运行说明。
