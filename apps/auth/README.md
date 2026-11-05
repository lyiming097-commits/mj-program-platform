# Auth 认证中心

Auth 是整个系统的“认证中心”，负责确认用户是谁。以后 CRM、线缆商城、门户、ERP 等子系统都不要自己做登录，也不要自己解 token，而是统一问 Auth。

接口清单、输入输出规范和结构说明见：[STRUCTURE.md](./STRUCTURE.md)

行政区内部目录支持 `ifRevision` 条件快照读取，搜索支持按 `province`、`city` 名称或代码限定父级，以及 `revision` 冲突校验；CRM 使用版本化快照接入。接口参数与更新约定见 [平台基础数据查询接口](../../docs/PLATFORM_BASE_DATA_API.md#省市区域)。

一句话理解：

```text
Auth 管登录和身份
子系统管自己的业务权限
```

## Auth 负责什么

- 登录页面：用户从 `/auth/` 进入登录。
- 登录回调：钉钉扫码或工作台登录后回到 `/auth/result`。
- token 发放：用户登录成功后，Auth 把 token 写入 `HttpOnly` Cookie；前端只保存展示所需的非敏感会话字段，不读取 token。
- token 校验：其他后端拿到前端传来的 token 后，调用 Auth 内部接口确认这个 token 是否有效。
- token 刷新：只有 Auth 自己的接口可以续期和写回 Cookie，子系统 introspect 只校验身份。
- 钉钉登录：Auth 统一处理钉钉扫码、工作台免登、JSAPI 配置。
- 钉钉组织：Auth 统一保存从钉钉同步的部门、员工及其关系。
- 全系统启用部门：管理员从钉钉部门树中启用实际参与平台业务的部门；所有子系统只能读取这些部门及其在职启用人员。
- 异步同步：通讯录同步由 `auth-sync-worker` 后台执行，页面只负责提交任务和查询进度。
- 白名单高权限：平台级高权限只来自 `.env.docker` / `local.env.docker` 里的 `FULL_ACCESS_USER_IDS`。
- 内部组织查询：其他系统需要查员工、部门关系时，走 Auth 的内部接口，不直接读 `auth_db`。
- 行政区目录：Auth 提供由国家标准数据生成的省、市、区县目录和名称/代码/拼音搜索；业务系统不自行维护另一份行政区基础目录。

## 目录结构

```text
apps/auth/
  frontend/   登录页面、登录结果页、认证中心管理页面
  backend/    Auth 后端接口
  README.md   当前说明文件
```

前端主要入口：

```text
apps/auth/frontend/src/apps/auth/AuthApp.vue
```

后端主要模块：

```text
apps/auth/backend/identity_api/auth/       登录、token、会话、代理登录
apps/auth/backend/identity_api/dingtalk/   钉钉接口
apps/auth/backend/identity_api/org/        组织架构、员工、部门
apps/auth/backend/identity_api/internal.py 内部系统调用密钥校验
```

## 数据库归属

Auth 只连接自己的 PostgreSQL 容器：

```text
auth-postgres -> auth_db
```

`auth_db` 里放：

- 用户身份信息
- 员工信息
- 部门信息
- 员工和部门关系
- 全系统启用部门、后台管理权限范围规则和配置版本
- token 相关的认证版本信息
- token 撤销记录
- 通讯录同步记录
- 应用内部服务凭据摘要
- 平台我司主体及变更历史
- 省市区目录版本、行政区代码、名称、父级关系及权威拼音
- 工商企业资料及查询历史

默认规则：

```text
Auth 只改 auth_db
CRM 只改 crm_db
Portal 只改 portal_db
Cable Mall 只改 cable_mall_db
```

如果 CRM 想查某个人的部门，不要直接连 `auth-postgres` 或 `auth_db`，要调用 Auth 的内部组织接口。

## 外部访问地址

用户浏览器访问：

```text
/auth/
```

常用页面：

```text
/auth/                  登录页
/auth/result            登录结果页
/auth/settings/organization         组织架构 > 钉钉组织架构（桌面端同时维护启用部门）
/auth/settings/permissions          组织架构 > 权限设置（后台管理员）
/auth/settings/handover             离职人员（保留原链接）
/auth/settings/company-entities     我司主体（后台管理员，平台独立维护）
/auth/settings/regions              省市区域（后台管理员，全国省、市、区县只读目录）
/auth/settings/business-registry    工商信息查询（后台管理员，企业查询与持久化记录）
/auth/settings/application-template 应用模板旧地址（保留打开原应用的入口）
```

桌面后台管理在“开发工具”分组提供“应用模板”链接，仅后台管理员可见，点击在平台顶部打开“应用模板”页签，复用原 `/starter-app/` 页面，重复点击切回已有页签，当前后台页面和草稿保留。独立打开后台时，链接在新窗口进入门户的 `/?app=starter-app` 工作区。Auth 不再维护模板页面副本、模板样式或调用模板业务 API；示例表格、示例字段、权限设置及优化建议统一使用原模板页面，原模板仍是脚手架蓝本。门户的模板入口通过 `portal.visible=false` 隐藏，手机后台不新增入口；模板业务接口仍独立检查自身权限。旧 `/auth/settings/application-template` 地址保留一个打开原应用的入口，旧 `templatePage` 参数不再加载复制页面。

验证：`node --test apps/auth/frontend/tests/application-template.browser.test.mjs apps/auth/frontend/tests/organization-sidebar.browser.test.mjs`；浏览器使用隔离上下文并模拟全部 API，不修改真实权限、记录或建议。

桌面后台的临时操作反馈统一复用应用模板的共享 `PlatformActionToast`：顶部居中、白底橙色边框及进度条，不占用内容布局；成功和一般提示 3 秒关闭，操作失败 5 秒关闭，均可手动关闭。通知、我司主体、部门启用范围、账号操作、通讯录同步、权限保存和机器人群发共用一个反馈入口，连续操作替换当前提示，相同文字重新计时。表单校验、权限版本冲突、加载失败及待核实发送状态保留原有处理入口；业务通知弹窗仅在门户首页运行。手机后台不挂载此桌面反馈入口。

反馈回归：`node --test --test-concurrency=1 apps/auth/frontend/tests/settings-feedback.browser.test.mjs apps/auth/frontend/tests/company-entities.browser.test.mjs apps/auth/frontend/tests/organization-improvements.browser.test.mjs apps/auth/frontend/tests/robot-messages.browser.test.mjs`。测试仅使用模拟 API；设置 `SETTINGS_FEEDBACK_BASE_URL` 可在发布后的静态资源上运行反馈专项检查。截图位于 `.codex-artifacts/settings-feedback/`。

“我司主体”是平台级基础数据，由后台管理桌面端独立维护，权威数据存于 `auth_db` 的 `platform_company_entities`，变更记录存于 `platform_company_entity_history`。CRM 与其他应用通过 Auth 只读 API 使用；后台管理不调用 CRM，也不依赖 CRM 服务或数据库。应用迁移 `0021_platform_company_entities` 后，按 [主体迁移步骤](../../docs/PLATFORM_COMPANY_ENTITY_MIGRATION.md) 将原主体记录按原 ID 导入。

主体查询支持公司名称、税号、ID、全拼和拼音首字母；内部 `search`、`profiles/search` 传 `{"all":true}` 一次返回全部当前主体，不受分页上限截断，也可组合关键词返回全部匹配结果。全量模式不能同时传 `limit`/`offset`。桌面主体页通过 `GET /api/directory/company-entities?all=true` 一次加载全部资料，搜索框同步支持名称、拼音、税号和ID。目录响应保持最小字段，完整资料仍受原业务服务授权限制，详见 [平台基础数据查询接口](../../docs/PLATFORM_BASE_DATA_API.md)。

“省市区域”只在后台管理桌面端展示，权威目录存于 `auth_db` 的 `platform_administrative_regions`，发布版本及来源指纹存于 `platform_administrative_region_directories`。迁移 `0022_administrative_region_database` 将冻结的 `@vant/area-data@2.2.0` 初始目录（34 个省级、369 个市级、3478 个区县）及拼音一次性导入。管理页和服务间查询均读取当前数据库版本；目录文件只作迁移种子，不参与运行时读取或失败回退。完整目录、统计、搜索及精确取数在每次响应内使用同一个数据库版本，未初始化、数据不完整或数据库不可用时返回 `503 REGION_DIRECTORY_UNAVAILABLE`。区域仍为只读基础目录，业务省市配置由业务应用维护。

桌面三级列表与搜索均读取 Auth 后端目录，列表不再采用前端自带目录作为数据来源或失败回退。其他应用后端使用完整目录、按父级/层级查询及代码精确查询接口；接口、鉴权和后续基础数据接入规则见 [平台基础数据查询接口](../../docs/PLATFORM_BASE_DATA_API.md)。

桌面后台管理左侧“基础资料”分组依次包含“我司主体”“省市区域”“工商信息查询”。在“工商信息查询”页面点击工具栏“查询企业”打开查询抽屉，初始显示单选和多选两个企业查询字段，“查询”按钮嵌在输入框同一圆角边框内靠右，查询时右侧仅显示加载转圈，字段下方不显示额外的查询进度文字，按钮宽度保持不变；输入企业名称、统一社会信用代码或注册号，点击“查询”或按 Enter 调用阿里云市场 `cmapi00066571` 主接口，从第 1 页开始（每页 20 条），下拉列表底部提供“加载更多”，向下滚动到底部会查询下一页并追加到当前列表，最多加载至第 100 页；查询和加载可能消耗服务额度。仅在滚动到底部或点击加载时请求，不预取、不连续遍历。查询结果名称未必包含关键词，页面保留服务原始匹配结果供人工核对。输入时不发请求，中文输入法确认不触发查询；结果使用模板下拉单选样式，每项紧凑显示名称和下一行统一社会信用代码，点击或按 Enter 选择企业后回填名称并收起菜单；方向键及 Home/End 在结果间移动，Esc 先收起菜单，再按 Esc 关闭抽屉。输入框右侧仅保留查询按钮；直接删除文字可清空，点击输入框或按上下方向键可重新展开已有结果。结果菜单跟随字段定位并在窗口边缘翻转。整页在选择前即已保存，选择只查看本次快照，不再次请求外部接口，也不查询本地企业库。处理中禁止重复提交和关闭，仍保留超时后同条件重试的请求编号；“刷新查询状态”只读取原查询记录。

桌面工商列表参照应用模板 `ExampleTable`：紧凑工具栏、浅色网格表头和表头下的列筛选行、48px 基础行高、冻结序号/企业名称/历史查询操作列，信用代码与注册号分列，底部页码居中。已保存企业、查询记录和详情中的企业列表共用表格滚动外壳，支持鼠标横向拖拽和左右键浏览；列筛选在整个已存数据库中组合生效，输入防抖后自动搜索并回到第 1 页，筛选条件和页码可通过 URL 恢复；加载、出错和无结果时仍保留筛选控件。本地筛选、重置、分页及查看历史记录不调用外部工商服务。

企业资料和查询记录存放在 `auth_db`，需应用迁移 `0018_business_registry` 与 `0019_business_registry_company_history`。返回的本页企业自动保存名称、信用代码、注册号、法定代表人、经营状态和成立日期；以未脱敏的信用代码优先、注册号其次识别企业，均缺失时使用名称、法人、成立日期组合。相同标识再次查询会更新资料，较早但较慢完成的请求不会覆盖更新的资料。每次查询保留独立结果快照、关键词、页码、时间、真实操作人及代理身份、HTTP/业务状态、查询单号和脱敏后的 JSON 响应；非 JSON 响应只记录状态。失败与空结果也记入历史。查看、筛选和翻阅已保存记录不调用外部服务。工商资料仅辅助录入，不等于已完成工商核验。

企业与查询通过关联表保存多对多关系：同一家企业被不同关键词或不同次查询命中，都关联到该企业，重复提交同一请求不会重复计数。企业列表支持点击整行、企业名称或使用 Enter/空格打开企业详情抽屉，默认展示“工商信息”页签中的已保存企业名称、统一社会信用代码、注册号、法定代表人、经营状态、成立日期及首次/最近查询时间；表格横向拖动不会误开抽屉。抽屉顶部固定提供“工商信息”和“历史查询”两个页签，支持方向键切换；点击列表中的查询次数直接进入“历史查询”。历史查询按时间倒序、每页 20 条，点击某次记录查看当次返回的全部企业快照；切换页签保留历史页码和正在查看的查询结果，返回历史列表时恢复页码和焦点。查看资料和切换页签不调用外部工商 API。历史详情只读，不提供付费翻页按钮；新查询通过下拉列表底部加载下一页，每页仍保存为独立查询快照。迁移 0019 根据既有成功查询快照与最新来源关系补齐关联，不改写原快照。

查询抽屉上下展示“单选企业”和“多选企业”两个独立字段，各自维护关键词、查询结果、分页与失败重试编号。单选选择后回填名称并关闭列表；多选按应用模板的详情字段样式展示框内名称气泡，每次选择一家即收起结果并清空输入，之后可继续输入查询或点击输入框重新选择已加载结果。翻页和更换关键词不会丢失气泡，通过气泡上的移除按钮取消选择；重复选择同一家不会增加或移除已有气泡。已选气泡名称只读，点击不会展开结果或重新查询；只能通过 × 移除，再在后面的输入框继续添加新企业。多选按未脱敏信用代码、注册号、名称/法人/成立日期组合依次去重，选中值保留完整快照及信用代码，不显示额外清空或展开图标。两种查询都在返回整页结果时完成保存，选择/取消选择不会调用外部接口。

企业查询字段实现位于 `frontend/src/components/settings/BusinessRegistryLookup.vue`，通过 `modelValue` 接收输入文本、`selectedCompany` 接收已选企业、`result` 接收当前查询已加载的企业集合，`select` 事件返回完整企业快照（清空时为 null）。多选使用 `multiple`、`selectedCompanies` 和 `update:selectedCompanies` 传递快照数组；`label` 同时提供可见标题和区域名称。独立查询状态及 API 调用复用 `useBusinessRegistryLookup.js`。分页由 `hasMore`、`loadingMore`、`morePending`、`moreError` 和 `endMessage` 描述状态，`load-more` / `refresh-more` 通知宿主加载下一页或只读刷新处理中的查询。宿主按页累积结果，追加时保持滚动位置与选择；网络失败的重试复用原请求编号，已明确失败的查询只在点击重试时重新发起。失败不会因滚动自动重试，空页、已到总数或未知总数的不足一页结果会停止加载；改关键词提交新查询后重置列表。组件本身不调用接口；宿主负责查询、记录保存、权限和错误提示，可将选中快照写入其他表单字段。当前只在 Auth 工商查询抽屉中使用，尚未接入其他系统。 查询完成只在用户仍操作当前字段时恢复焦点；多选下拉以末尾输入行定位，气泡多行时仍可向上展开。键盘 Tab 可到达“加载更多”，Enter 明确加载，Esc 先关闭结果并归还输入焦点；程序为显示高亮项或分页按钮而滚动时不自动请求下一页。

工商服务凭证通过清单中的可选 Docker Secret 配置：`secrets/apps/auth/business-registry-appcode.secret`，仅包含 AppCode，挂载后供 `auth-backend` 的 `BUSINESS_REGISTRY_APPCODE_SECRET`（启动时从对应 `_FILE` 加载） 使用。不要在前端、源码、README 或普通环境文件写入真实值。未配置时保留本地记录读取，外部查询返回 `503 REGISTRY_NOT_CONFIGURED`。部署使用 `scripts/app-deploy.sh auth server.env.docker`，更新前先备份 Auth 数据库；缺少接口凭证不影响模块部署与历史记录读取。

CRM 等平台后端可通过[工商查询内部接口](./BUSINESS_REGISTRY_INTERNAL_API.md)调用工商服务；每条返回企业只含企业名称 `companyName` 和统一社会信用代码 `creditNo`，单选、多选及业务保存快照统一使用这两个字段。整页仍保存到 Auth 并记录来源服务。新增 `0020_business_registry_source` 迁移。内部接口验证独立服务凭据，公网网关屏蔽，不依赖浏览器 Cookie；业务系统负责自己的使用权限。

管理页工商接口均复用 Auth 登录、同源写入校验和 `can_manage_organization` 后台管理权限；代理按有效身份授权，记录实际操作者。接口路径：

```text
GET  /api/org/business-registry/companies?page=1&keyword=...
GET  /api/org/business-registry/companies/<id>/queries?page=1
GET  /api/org/business-registry/queries?page=1&keyword=...
GET  /api/org/business-registry/queries/<id>
POST /api/org/business-registry/search
```

企业列表支持 `companyName`、`creditNo`、`companyCode`、`legalPerson` 模糊筛选，`companyStatus` 精确筛选，以及 `establishDate`、`lastQueriedOn` 日期筛选；经营状态选项来自所有已存企业。查询记录支持 `keyword`、`actor` 模糊筛选，`pageNum`、`status`、`resultCount` 精确筛选和 `createdOn` 日期筛选。日期统一传 `YYYY-MM-DD`，查询时间按北京时间整日匹配；原有列表 `keyword` 参数保持兼容。

查询请求为 JSON：`keyword`、`pageNum`（1–100）、`pageSize`（1–20）、`requestId`（UUID）。Auth 再以表单格式调用外部接口。`requestId` 在库中唯一，绑定条件及操作身份；同一编号再次提交只读取原记录，不重新调用外部服务，处理中返回 HTTP 202。完成后的 HTTP 200 表示查询记录已保存，实际业务结果须检查 `status`（`succeeded`、`empty`、`failed`）；不要仅按 HTTP 200 推断查询成功。进程中断遗留的 `running` 记录不会自动重发，需先核实服务状态与额度。

验收命令（隔离数据库与模拟 API，不消耗真实额度）：

```bash
PYTHONPATH=packages/platform-backend DB_ENGINE=sqlite SQLITE_NAME=:memory: .local/venvs/auth-org-review/bin/python apps/auth/backend/manage.py test identity_api.tests.test_business_registry
node --test apps/auth/frontend/tests/business-registry.browser.test.mjs apps/auth/frontend/tests/business-registry-interactions.browser.test.mjs
npm --prefix apps/auth/frontend run build
```

界面截图位于 `.codex-artifacts/business-registry/`，使用明确标识的测试企业数据；覆盖 1440、1024、800 像素桌面和查询详情。SQLite 测试不代替生产 PostgreSQL 并发及迁移验证。

## 公开后端接口

这些接口是给前端页面用的，会走正常登录 token：

```text
POST /api/auth/code
GET  /api/auth/session/validate
POST /api/auth/logout
POST /api/auth/proxy/start
POST /api/auth/proxy/stop
GET  /api/auth/proxy/candidates
GET  /api/health/live
GET  /api/health/ready

GET  /api/dingtalk/check_env
GET  /api/dingtalk/jsapi_config
POST /api/dingtalk/sync_contacts
GET  /api/dingtalk/sync_contacts/status
GET  /api/dingtalk/sync_contacts/status/<runId>

GET  /api/directory/administrative-regions
GET  /api/directory/administrative-regions/search

GET  /api/org/departments
GET  /api/org/departments/tree
GET  /api/org/departments/search
GET  /api/org/departments/<deptId>
GET  /api/org/departments/<deptId>/manager
GET  /api/org/departments/<deptId>/subdepartments
GET  /api/org/departments/<deptId>/employees
GET  /api/org/employees
GET  /api/org/employees/inactive
GET  /api/org/employees/<userId>
GET  /api/org/enabled-departments
PUT  /api/org/enabled-departments
GET  /api/org/permissions
PUT  /api/org/permissions
POST /api/org/employees/account-status/bulk
POST /api/org/employees/<userId>/account-status
POST /api/org/employees/<userId>/handover
```

`GET /api/org/enabled-departments` 供已登录页面读取全系统启用范围；只有后台管理员可以调用 `PUT` 修改配置。

钉钉组织架构是平台唯一部门来源。桌面端在“钉钉组织架构”页直接维护启用范围，默认隐藏未启用部门；`PUT /api/org/enabled-departments` 按 `deptId` 独立保存每个部门，不会因为启用子部门而自动启用父部门。首次迁移启用当时已有的全部部门，以后新同步到的部门默认不启用。保存必须同时提交配置 `revision` 和钉钉 `orgRevision`，任一版本过期都会返回 `409`。旧地址 `/auth/settings/enabled-departments` 会归一到组织架构页。

`PUT /api/org/permissions` 配置后台管理权限，规则支持 `department`、`departmentSub`、`employee` 和 `excludedEmployee`，但部门和人员候选均受全系统启用范围约束。后台管理员可以使用后台管理内全部功能，包括继续维护权限名单，但不会因此获得代理能力或各业务 App 的最高权限。

员工姓名、部门名称和代理候选搜索支持名称、userId/deptId、全拼和拼音首字母；拼音不区分大小写并忽略空格、连字符和英文撇号，例如 `Jiang Song Yang` 与 `jsy` 都可匹配“江颂扬”。不支持汉字和拼音混合搜索。返回对象包含 `pinyin` 与 `pinyinInitials`。

通讯录同步接口返回 `202` 和 `syncRun.runId`，不再让浏览器等待整个同步过程。前端随后轮询 `/api/dingtalk/sync_contacts/status/<runId>`，状态只有 `running`、`succeeded`、`failed`。同一时间只允许一个同步任务；`auth-sync-scheduler` 默认每 15 分钟自动触发一次兜底同步。

`GET /api/dingtalk/sync_contacts/status` 同时返回 `lastSyncedAt`，取最近一次成功完成同步的时间（即使目录内容没有变化也更新）；无成功同步记录时为空字符串。失败或进行中的任务不会改变该时间。

同步仅在部门、员工资料/状态、成员关系或主管关系实际变化时增加 `orgRevision`，并在任务摘要返回 `organizationChanged`。相同数据的周期同步不增加版本、不重写未变化记录的 `updatedAt`，不重建未变化的成员/主管关系；避免任务管理、CRM 等已打开页面每 15 分钟误报组织版本冲突。真实目录或权限变化的版本保护继续有效。

同步在写数据库前会校验快照。部门、员工或关系为空，数量下降超过安全阈值，或者钉钉分页游标重复/不前进时，本次任务直接失败，正式组织数据保持不变。部门支持多个主管，旧字段 `managerUserId` 仍表示第一主管，新接口同时返回 `managerUserIds` 和 `managers`。

员工首次从在职变为离职时，同步会在覆盖旧组织关系前保存离职前钉钉部门路径；返职后清除，以便再次离职时重新记录。已有离职员工没有可核实的历史快照，页面显示“未记录”，不从当前部门反推历史。组织架构页中的离职人员列表只读，不再提供交接操作；旧交接 API 暂保留兼容调用方。

离职人员页的“离职日期”取首次同步发现离职并记录组织快照的日期（按查看者本地时区显示），不是钉钉提供的实际离职日期。上线前已经离职且没有该时间记录的员工显示“未记录”。

后台管理权限覆盖权限设置、启用部门维护、通讯录同步及状态、离职员工查看、账号启停、我司主体、省市区域和工商信息查询；它不包含代理能力。只有非代理状态的 `FULL_ACCESS_USER_IDS` 白名单账号可以发起代理，进入代理后不能再次查询代理候选或切换目标。代理后的全部能力按当前有效 `userId` 重新计算：普通目标不继承操作者白名单，后台管理员目标保留后台管理权限，白名单目标保留白名单权限。每次登录、开始代理、退出代理和退出登录都会撤销旧 `sid`；代理操作者被移出白名单后，现有代理会话立即失效。

`accountStatus=禁用` 是系统级硬限制，即使员工仍在 `FULL_ACCESS_USER_IDS` 中，也不能登录、校验 Token 或作为代理目标。需要恢复访问时必须先在 Auth 中重新启用账号。

## 内部 token 校验接口

这个接口是给其他后端用的，不是给浏览器直接用的。

Docker 内部地址：

```text
POST http://auth-backend:8000/api/internal/auth/introspect
```

请求头必须带：

```text
X-Internal-Auth-Secret: <该服务的 Docker Secret>
X-Internal-Service: crm-backend
X-Request-Id: 可选，不传 Auth 自动生成
```

请求体：

```json
{
  "token": "前端传给子系统后端的 Bearer token"
}
```

返回值大概长这样：

```json
{
  "ok": true,
  "sessionId": "服务端会话 sid",
  "userId": "当前被操作的用户ID",
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

字段解释：

- `ok`：是否校验成功。
- `userId`：当前业务上被当作“登录用户”的人。
- `actorUserId`：实际操作者。如果没有代理登录，一般等于 `userId`。
- `isSystemAdmin`：当前有效 `userId` 是否属于 Auth 系统白名单，只表示身份。
- `canUseSystemAdmin`：当前有效 `userId` 是否可使用系统管理员能力；它跟随被代理人，代理到白名单目标时仍为 `true`。
- `isFullAccessUser`：兼容旧前端的身份别名，不应直接用于新子系统后端授权。
- `canManagePlatformSettings`：当前有效 `userId` 是否可使用后台管理全部功能；可来自白名单或权限设置，但不授予业务 App 最高权限。
- `canConfigurePermissions`：`canManagePlatformSettings` 的权限页能力别名。
- `isProxying`：是否处于代理登录。
- `canStartProxy`：只有非代理状态下的当前白名单账号为 `true`。
- `canSwitchProxy`：兼容字段，固定为 `false`；代理后不能再次代理或切换目标。
- `claims`：token 里的基础声明。

`introspect` 只负责校验，不再返回刷新 token。子系统不得写回 `mj_auth_token`；浏览器每 10 分钟调用 Auth 的 `/api/auth/session/validate` 续期，Auth 会在响应结束时再次确认 sid 有效。

子系统拿到 `userId` 后，再判断这个用户在自己系统里能不能访问某个功能。需要把系统管理员映射为本系统最高权限时，只使用 Auth 返回的 `canUseSystemAdmin`，不要在子系统里重复读取 `FULL_ACCESS_USER_IDS`。

## 内部组织架构接口

这些接口也是给后端调用的，只能在 Docker 内部网络用。

基础地址：

```text
http://auth-backend:8000/api/internal/org
```

请求头必须带：

```text
X-Internal-Auth-Secret: <该服务的 Docker Secret>
X-Internal-Service: crm-backend
X-Request-Id: 可选，不传 Auth 自动生成
```

标准规则：

- 全部使用 `POST`。
- 全部用数组传入，多个输入就返回多个结果。
- 查不到用户、部门或关系不成立时，返回空数组或 `null`，不直接报错。
- `status` 默认 `active`，可选 `active`、`inactive`、`all`。
- `accountStatus` 默认 `enabled`，可选 `enabled`、`disabled`、`all`。
- `includeDepartmentPath` 默认 `false`，传 `true` 时返回部门完整路径。
- `includeSubDepartments` 默认 `false`，传 `true` 时包含所有下级部门。
- `maxDepth` 不传就是一直查到根部门。
- 同部门同事默认包含自己。

当前标准接口：

```text
POST /users/search
POST /users/departments
POST /users/leader-chain
POST /users/colleagues
POST /users/managed-departments
POST /users/managed-employees

POST /departments/search
POST /departments/employees
POST /departments/managers
POST /departments/children
POST /departments/ancestor-chain
```

国家标准行政区目录使用独立服务间端点：

```text
POST /api/internal/directory/administrative-regions/search
```

它按名称、行政区代码、全拼和拼音首字母搜索，返回目录 revision、分页信息以及包含 `pinyin`、`pinyinInitials` 的最小行政区字段。

所有内部组织接口统一按全系统启用部门裁剪结果：未启用部门不会被搜索或关系接口返回，只有至少属于一个启用部门的在职启用员工才进入人员目录。启用部门的直接父部门未启用时，该部门在裁剪后的目录中作为根部门返回，`parentDeptId` 为 `null`。子系统不得绕过这些接口读取完整钉钉组织，也不得自行维护另一套平台部门树。

CRM 离职成员页另使用 `POST /api/internal/org/users/departure-history`（最多500个明确 `userIds`）。此历史接口只允许认证凭据所属 App 为 `crm` 的内部服务调用，由 CRM 再校验管理员权限；不开放全量检索，不改变当前目录的启用部门裁剪。离职人员没有现有部门关系时，仍返回离职前保存的 `formerDingTalkDepartments` 和 `formerOrganizationRecordedAt`；已恢复在职的人员只返回当前身份状态以便 CRM 排除，未知 ID 返回 `found: false`。历史快照时间不代表真实离职日期。回归：`manage.py test identity_api.tests.test_departure_history`。

### 查询人的所在部门

```text
POST /users/departments
```

请求体：

```json
{
  "userIds": ["001", "002"],
  "status": "active",
  "accountStatus": "enabled",
  "includeDepartmentPath": true,
  "includeEmployeeProfiles": false
}
```

用途：批量查询员工属于哪些部门。一个人可以属于多个部门。

### 查询人的领导链

```text
POST /users/leader-chain
```

请求体：

```json
{
  "items": [
    {
      "userId": "001",
      "departmentId": 10
    }
  ],
  "maxDepth": 3,
  "includeDepartmentPath": true
}
```

用途：按“用户 + 归属部门”查询 1级、2级、3级领导。1级是传入部门的主管，2级是上级部门主管，继续往根部门查。某一级主管为空时，`manager` 返回 `null`，但继续往上查。

### 查询同部门同事

```text
POST /users/colleagues
```

请求体：

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

用途：按“用户 + 归属部门”查询同部门同事。传错部门时，`validMembership` 为 `false`，人员数组为空。

### 查询人管理的部门

```text
POST /users/managed-departments
```

请求体：

```json
{
  "userIds": ["001", "002"],
  "includeSubDepartments": true,
  "includeDepartmentPath": true
}
```

用途：查询某个人直接主管的部门。`includeSubDepartments=true` 时，会把这些部门下面的所有子部门也返回。

### 查询人管理部门下面的人员

```text
POST /users/managed-employees
```

请求体：

```json
{
  "userIds": ["001", "002"],
  "includeSubDepartments": true,
  "status": "active",
  "accountStatus": "enabled",
  "includeDepartments": true,
  "includeDepartmentPath": true
}
```

用途：查询某个人管理的部门下面有哪些人。返回两份数据：

- `groups`：按这个人直接管理的部门分组。
- `uniqueEmployees`：所有分组合并后的去重人员列表。

### 查询部门员工

```text
POST /departments/employees
```

请求体：

```json
{
  "departmentIds": [10, 20],
  "includeSubDepartments": true,
  "status": "active",
  "accountStatus": "enabled",
  "includeDepartments": true
}
```

用途：查询部门员工。`includeSubDepartments=true` 时，包含下面所有子部门员工，并按 `userId` 去重。

### 查询部门主管

```text
POST /departments/managers
```

请求体：

```json
{
  "departmentIds": [10, 20],
  "status": "active",
  "accountStatus": "enabled"
}
```

用途：批量查询部门主管。部门没有主管时，`manager` 返回 `null`。

### 查询部门下面的部门

```text
POST /departments/children
```

请求体：

```json
{
  "departmentIds": [10, 20],
  "includeSubDepartments": true,
  "includeDepartmentPath": true
}
```

用途：查询部门下面的部门。`includeSubDepartments=false` 时只查直接子部门；`true` 时递归到底。

### 查询部门上级链

```text
POST /departments/ancestor-chain
```

请求体：

```json
{
  "departmentIds": [10, 20],
  "maxDepth": 3,
  "includeDepartmentPath": true
}
```

用途：查询部门的 1级、2级、3级上级链。1级是父部门，2级是爷爷部门，3级继续向上。不传 `maxDepth` 就一直查到根部门。

## 子系统应该怎么接 Auth

以 CRM 为例：

1. Auth 登录成功后把 token 写入 `HttpOnly` Cookie，业务前端不保存也不读取 token。
2. CRM 前端请求 CRM 后端时使用同源请求，浏览器自动携带 Cookie。
3. CRM 后端从 Cookie（兼容时也可从 Bearer Header）取 token，但不自己解 token。
4. CRM 后端调用 `auth-backend` 的 `/api/internal/auth/introspect`。
5. Auth 返回 `userId`、`isSystemAdmin`、`isProxying` 和最终能力 `canUseSystemAdmin`。
6. CRM 用 `userId` 判断 CRM 自己的普通业务权限；仅在 `canUseSystemAdmin=true` 时映射为 CRM 管理员。
7. 如果 CRM 需要部门或员工信息，再调用 `/api/internal/org/*`。

核心规则：

```text
认证归 Auth
业务权限归各子系统
组织基础数据归 Auth
跨系统查数据走 API
不要直接连接或修改别人的 PostgreSQL 容器
```

## Docker 里的服务名

其他容器访问 Auth 后端时，用：

```text
http://auth-backend:8000
```

不要在容器里写：

```text
localhost
```

因为 `localhost` 在容器里表示“当前容器自己”，不是 Auth 容器。

## 相关环境变量

在 `.env.docker` 里：

```text
AUTH_INTROSPECTION_URL=http://auth-backend:8000/api/internal/auth/introspect
AUTH_ORG_INTERNAL_URL=http://auth-backend:8000/api/internal/org
AUTH_TOKEN_TTL_SECONDS=1800
AUTH_SESSION_MAX_AGE_SECONDS=43200
AUTH_TOKEN_CLOCK_LEEWAY_SECONDS=30
AUTH_CACHE_REDIS_URL=redis://redis:6379/2
AUTH_CELERY_BROKER_URL=redis://redis:6379/1
AUTH_SYNC_SOFT_TIME_LIMIT_SECONDS=1200
AUTH_SYNC_TIME_LIMIT_SECONDS=1260
DINGTALK_ORG_SYNC_STALE_AFTER_SECONDS=1800
AUTH_ORG_SYNC_INTERVAL_SECONDS=900
DINGTALK_ORG_SYNC_MAX_USER_DETAIL_ERROR_RATIO=0.05
DINGTALK_JSAPI_ALLOWED_ORIGINS=https://正式域名
DINGTALK_ORG_SYNC_MAX_DEPARTMENT_DROP_RATIO=0.35
DINGTALK_ORG_SYNC_MAX_EMPLOYEE_DROP_RATIO=0.25
DINGTALK_ORG_SYNC_MAX_MEMBERSHIP_DROP_RATIO=0.35
AUTH_HISTORY_RETENTION_DAYS=180
FULL_ACCESS_USER_IDS=系统级白名单用户ID
```

说明：

- `AUTH_TOKEN_SECRET`：Auth 用它签发 token。真实值由 `apps/auth/app.manifest.yaml` 挂载的 Docker Secret 提供，不写入 `.env.docker`。
- `AUTH_TOKEN_TTL_SECONDS`：单个 token 的有效期，默认 1800 秒。
- `AUTH_SESSION_MAX_AGE_SECONDS`：一次登录会话的绝对最长有效期，默认 43200 秒。即使一直刷新 token，到时间也必须重新登录。
- `AUTH_TOKEN_CLOCK_LEEWAY_SECONDS`：服务器时间轻微偏差容忍秒数，默认 30 秒。
- `AUTH_CACHE_REDIS_URL`：登录和 JSAPI 后端限流使用的 Redis，默认数据库编号 2。
- `AUTH_CELERY_BROKER_URL`：异步通讯录任务队列使用的 Redis，默认数据库编号 1。
- `AUTH_SYNC_SOFT_TIME_LIMIT_SECONDS` / `AUTH_SYNC_TIME_LIMIT_SECONDS`：单次后台同步的软、硬超时时间。
- `DINGTALK_ORG_SYNC_STALE_AFTER_SECONDS`：运行中任务超过此时间后可判定为失败并允许重新发起，默认 1800 秒。
- `AUTH_ORG_SYNC_INTERVAL_SECONDS`：自动通讯录同步间隔，默认 900 秒，最小 300 秒。
- `DINGTALK_ORG_SYNC_MAX_USER_DETAIL_ERROR_RATIO`：允许已有员工详情失败并保留原资料的最大比例，默认 0.05；超过后拒绝覆盖。新员工详情失败时因无原资料可保留，会直接拒绝本次同步。
- 三个 `DINGTALK_ORG_SYNC_MAX_*_DROP_RATIO`：相对上一次正式数据允许的最大下降比例，超过后拒绝覆盖。
- `DINGTALK_JSAPI_ALLOWED_ORIGINS`：允许签发钉钉 JSAPI 配置的明确来源列表，正式环境必填，不能使用请求 Host 自动放行。
- 内部服务凭据：每个 App 在自己的 `app.manifest.yaml` 中声明，原始值位于 `secrets/apps/<app-id>/auth-introspection.secret`。Auth 数据库只保存加盐摘要，不支持共享密钥回退。
- `AUTH_HISTORY_RETENTION_DAYS`：已结束组织同步记录的保留天数，默认 180 天；过期登录会话同时在启动清理和定时任务中删除。
- `FULL_ACCESS_USER_IDS`：系统级白名单，适合放白名单钉钉 userId。

生产密钥由 `scripts/appctl.py secrets ensure` 生成。Auth 正式启动会拒绝通配符 `DJANGO_ALLOWED_HOSTS`、默认/短密钥、相同的 Django 与 Token 密钥、开发登录、非 Secure Cookie 和空 JSAPI 来源配置。Django `/admin/` 已关闭。


## 组织管理桌面优化

“部门与成员”保留钉钉作为唯一组织来源。左侧“启用范围”仅维护参与平台业务的部门，父子部门独立启停；未启用上级下的可见部门注明“上级部门未启用”。部门目录标题下直接展示搜索框，部门名称悬停可看完整路径，支持逐级展开/收起和方向键浏览。侧栏分为“组织管理”“基础资料”和“开发工具”；“基础资料”包含我司主体、省市区域和工商信息查询。

桌面成员区首行放大显示部门名称及人数，第二行左侧显示当前部门路径，右侧排列“包含下级部门”、成员搜索和操作按钮。成员表格显示账号状态、部门名称和员工 ID，采用 64px 行高、40px 头像与更宽松的上下留白；当前部门的所有主管沿用头像左上角金色皇冠和金色描边，不单设主管列。头像失败时使用姓名回退。本部门/含下级人数取部门详情，当前匹配数取搜索结果，均统计在职人员（包含账号被禁用的在职人员）。桌面成员搜索固定在当前选中部门，通过“包含下级部门”控制范围；移除“搜索范围”选择器，旧链接中的 `scope=all` 自动清除。URL 保存 `dept`、`q`、`children=0` 和 `treeQ`，不保存配置草稿。

成员区第二行右侧的“操作”集中展示最近成功同步时间、最近任务状态、失败原因、同步通讯录、变更数量及账号操作记录，页面顶部不再单独占用同步信息行。打开同步详情或账号记录时暂停底层操作窗口的键盘交互，关闭详情后返回操作窗口。同步前经过启用范围的未保存保护，同步期间不允许编辑启用范围。部门/成员分别提供加载失败重试，过期人员搜索响应不会覆盖新结果。

桌面单人和批量启停均先调用 `GET /api/org/account-status/preview?accountStatus=启用|禁用&userId=可选`。批量范围是全部在职钉钉账号，不受当前部门或启用范围影响，预览只统计实际会改变状态的人，并提示是否影响当前会话。确认携带 `confirmationToken` 调用原账号状态接口；令牌有效期 5 分钟，绑定操作者、有效身份、目标、目标状态和人员状态快照。快照变化或令牌失效返回 `409 ACCOUNT_PREVIEW_CHANGED`，用户必须重新核对。原手机调用保持兼容。

实际发生的账号状态变更与 `OrganizationAccountOperation` 操作记录在同一事务内保存，记录实际操作者、有效身份、时间和人员前后状态；无变化不重复记账。管理员通过 `GET /api/org/account-operations?offset=0` 查看，每页 20 条。记录自功能上线起积累，不回填不存在的历史。上线需应用迁移 `0017_organization_account_operations`，前后端一起更新。

回归使用模拟 API、隔离浏览器和测试数据库，不改真实人员或权限：

```bash
node --test apps/auth/frontend/tests/organization-improvements.browser.test.mjs apps/auth/frontend/tests/organization-sidebar.browser.test.mjs apps/auth/frontend/tests/platform-permissions.browser.test.mjs
PYTHONPATH=packages/platform-backend DB_ENGINE=sqlite SQLITE_NAME=:memory: .local/venvs/auth-org-review/bin/python apps/auth/backend/manage.py test identity_api.tests.test_account_operations identity_api.tests.test_organization_access identity_api.tests.test_security_and_org
```

截图保存在 `.codex-artifacts/organization-improvements/`，包含 1440、1024、800 像素桌面与启停确认；原手机入口另由 sidebar 回归覆盖。SQLite 测试不代替生产 PostgreSQL 并发及迁移验证。


## 机器人群发（桌面）

后台管理新增“消息工具 → 机器人群发”，地址 `/auth/settings/robot-messages`。主界面按应用模板展示发送历史流水账，表头下方按日期、发送人、对象、内容和结果逐列筛选，支持分页和详情；右上角“发送消息”打开新增弹窗，上方多选群聊和人员，下方复用应用模板的富文本输入区，可直接输入文字、粘贴截图或添加图片，统一发送文字/图片/图文消息，历史支持缩略图和原图预览；权限管理沿用部门、含下级、人员授权与排除规则。后台管理员管理权限和登记群，普通授权人员仅查看自己的发送记录。

部署需迁移 `0023_robot_messages` 和 `0024_robot_rich_messages`（富文本与图片记录）、`0025_robot_application_notifications`（内部应用通知来源）、`0026_robotmessagemedia_robotmessagebatch_message_spec`（多类型消息与素材），同步更新 Auth 后端及 `auth-robot-worker`，沿用现有钉钉应用凭据。消息使用专用 `auth_robot_messages` 队列和独立 worker（2 并发），与通讯录同步的 `auth_sync` 队列隔离，发送接口不自动重试。详见 [机器人群发说明与 API](ROBOT_MESSAGES.md)。

内部应用通知提供文字、Markdown、图片、链接、操作卡片、文件、语音、视频共 8 类消息，包含服务鉴权的发送、结果查询、群查询、能力查询及素材上传/查询接口，并共用机器人发送历史。人工发送页面继续仅使用图文编辑。Python 共享调用封装位于 `packages/platform-backend/platform_auth/robot_messages.py`；接入请读 [内部应用机器人通知接口](../../docs/ROBOT_NOTIFICATIONS_INTERNAL_API.md)。

## Auth 定向通知（桌面管理、全站提醒）

桌面通知页沿用应用模板的顶部页签和内容面板结构：通知列表、我的通知、分类管理、权限管理位于白色页签栏，内容区保留 12–16px 留白，使用紧凑标题和蓝色“新建通知”操作。权限页的通知管理员、通知发布者在左侧“权限选择”中竖排切换，中间配置部门/人员，右侧显示具体生效人员；角色说明随左侧选项展示，不再重复设置顶部角色按钮和说明栏。页签支持方向键、Home/End 切换；权限草稿在切换角色或页面前统一确认放弃，保存中禁止切换。手机端继续沿用原设置布局。

“消息工具 → 通知”位于 `/auth/settings/notifications`。通知包含标题、富文本正文、附件、必选分类、到期日期和部门/人员对象。部门选项左侧为勾选框和部门名称，右侧用灰字显示完整路径，末尾可独立勾选“包含所有下级部门”；默认包含下级，取消后仅通知该部门本身，直接勾选末尾也会选中该部门。已选部门在包含下级时显示与权限管理一致的黄色“含下级”标识，取消勾选后同步移除；范围切换即时更新去重人数，保存草稿后恢复，首次发布后锁定。支持名称、路径、ID、全拼和拼音首字母搜索；首次发布时按当时在职且启用的目录成员解析接收人并去重，生成不可变接收名单及独立已读时间。编辑已发布通知时可改内容、分类和到期日期，但名单保持不变。撤回和到期通知停止弹窗；重新发布继续使用原接收名单，清空所有已读时间并更新发布时间，让原接收人重新收到提醒。接收人可在“我的通知”中查看历史并按标题、分类和日期查询，只能打开自己收到的通知和附件。

通知列表和我的通知最左侧使用模板式 48px 固定序号列，按当前页跨页连续编号；底部分页沿用模板的居中页码、上一页/下一页和长页码省略号，左侧显示总条数及每页条数。通知列表的标题搜索、分类、时间范围和发布状态筛选位于表头各列标题下方；接收人和未读列各提供人员搜索单选，支持姓名、工号/ID、全拼和拼音首字母，候选项保留姓名和部门用于区分同名人员，选中后仅显示姓名；编辑页人员多选标签也仅显示姓名。两列的数据行留空，人数及名单在详情“已读情况”中查看。`GET /api/org/notices` 的 `recipientUserId` 根据发布时固化的接收名单筛选，`unreadUserId` 根据该人员尚无已读时间的接收记录筛选；两项可叠加，分页前过滤，通知权限和整份名单统计保持不变。筛选值写入 URL，并可分别清除或一起重置。清除筛选和刷新位于列表右上角；表头两行一起固定，横向滚动时筛选与所属列保持对齐。通知列表取消右侧操作列，点击整行或通过标题按钮的键盘入口打开详情抽屉。抽屉标题栏下使用模板页签“通知详情”和“已读情况”；阅读名单默认未读，支持已读/全部筛选、分页和失败重试。查看与编辑复用同一个抽屉外壳，点击编辑只替换内容，不关闭或重新播放抽屉动画；取消编辑（含未保存确认）及保存成功后在原抽屉返回详情，失败保留输入。详情保留“通知信息”，其下“通知内容”将标题、正文、附件作为三个字段统一展示。底部操作文字为“撤回 / 发布 / 重新发布、删除、编辑”，删除红底白字、编辑蓝底白字，移除底部关闭按钮，保留右上角 ×；发布后留在同一抽屉查看未读情况，撤回后即时更新状态，删除后关闭抽屉。仅有此通知管理权限的人员显示阅读名单及管理操作，普通接收人和收到他人通知的发布者仅查看内容。

编辑页统一使用“保存”：只保存内容并保留发布状态及已读记录；草稿另提供“保存并发布”，已发布、撤回、失效的通知另提供“保存并重新发布”。重新发布先确认会清空已读记录；`POST /api/org/notices/<id>/publish` 显式传 `{"resetRead": true}`，在同一事务中保留固化接收名单、清空 `read_at`、更新发布时间并恢复已发布状态。过期校验和通知管理权限通过后才清空记录；默认不传该参数的普通发布仍保留既有已读状态，重复发布已发布通知保持幂等。发布响应包含通知正文，保存并发布后在原抽屉查看完整内容。

通知等级必选，默认“普通通知”（`ordinary`），另有“确认”（`confirm`）和“确认并接受”（`accept`）。等级与分类、到期日期、通知对象放在“通知信息”组；确认类会显示固定声明预览。普通通知点击“已读”；确认类在门户桌面首页通过普通文本框填写确认内容，支持复制粘贴、拖入和中文输入法；填写内容与提示声明逐字一致后点击“确认知晓”或“确认并接受”，粘贴仅保留纯文本，不忽略额外空白或标点。确认声明为“本人已阅读并知晓本次通知的全部内容”；确认并接受声明为“本人已阅读并知晓本次通知的全部内容，并同意按通知要求执行相关规定”，包含中文逗号，末尾不加句号。服务端独立校验确认内容逐字一致、接收资格、有效状态和 `confirmationVersion`，过期、撤回、内容或附件更新后的旧确认拒绝写入。状态统计继续使用 `read_at`，按等级显示已读/已确认/已接受，列表“未完成”人员筛选覆盖三类未完成状态。

已发布通知的等级只能通过 `publish` 携带新 `level` 和 `resetRead: true` 生效，普通 PATCH 不允许变更等级。保存并重新发布在最终发布事务中应用等级、保留原接收名单、递增发布版本并清空当前完成状态；修改等级时普通“保存”禁用。确认记录存于 `notification_acknowledgements`，包含确认人和实际操作人、时间、等级、当时声明、用户输入及通知标题/正文/附件名称快照（详情同时展示声明与实际填写内容）；重复确认幂等，重新发布保留旧记录并要求本轮重新确认。管理员/发布者可在完成名单展开当前确认记录，接收人可在自己的通知详情查看本人记录。新迁移 `0029_notification_levels` 将现有通知归为普通通知并保留已读状态。

新增和编辑表单统一分为“通知信息”和“通知内容”：前者放分类、到期日期、通知等级及通知对象（部门、人员），后者依次放标题、正文和附件。到期日期默认留空、非必填，留空表示长期有效，仍可撤回或删除。到期只选择年月日，所选日期当天仍有效，从次日北京时间零点起失效。创建/编辑接口的 `expiresAt` 接受 `YYYY-MM-DD`，服务端换算为次日零点；传空字符串或 `null` 可清空日期，更新时不传该字段则保留原值。响应保留时间戳 `expiresAt` 并提供日期 `expiresOn`，未设置时均为空字符串。迁移 `0028_notification_optional_expiration` 允许失效时间为空，不批量改写既有失效时间；原有时间戳请求和历史记录继续兼容。

通知角色由通知管理员分配：管理员管理全部通知、分类和通知角色；发布者创建通知、管理本人通知并查看未读/已读名单；普通用户只看自己的通知。平台后台管理员自动拥有通知管理员能力。分类为必选项；已用分类可改名，不能删除。附件最多 10 个，单文件不超过 20 MiB，本次上传总量不超过 30 MiB；附件经身份和接收权限校验后下载。附件的 `url` 始终强制下载；PDF 和浏览器支持的常用图片提供 `previewUrl`（原下载接口加 `?preview=1`），按文件扩展名白名单返回准确 MIME 及 inline 响应，预览沿用相同权限校验。其他格式不提供预览地址，强行请求预览返回 415。Auth 的 `/api/org/` 网关入口设置 32 MiB 上传上限，以容纳附件和 multipart 边界。

通知弹窗仅由门户桌面首页在登录校验和页面初始化成功后挂载，查询最早的一条未读通知；后台管理、其他应用及其共享顶部栏、登录页与登录回调页均不挂载、不请求未读通知，避免通知请求干扰钉钉免登或扫码回调。离开首页即卸载提醒并停止轮询，返回首页时重新查询。桌面弹窗右上角提供“关闭通知”，关闭仅暂停当前页面访问期间的弹窗，不记已读，重新进入首页后仍会提醒；底部“已读”按钮居中，点击后继续逐条处理。定期刷新撤回/到期状态。接口包括 `/api/org/notices/capabilities`、`/permissions/<role>`、`/categories`、`/history`、`/unread`、通知 CRUD、`/<id>/publish`、`/<id>/withdraw`、`/<id>/recipients`、`/<id>/read` 和附件上传/下载。新表由 `0027_platform_notifications` 创建，依赖现有 `0023`–`0026` Auth 群发迁移。

隔离 SQLite 验证：

```bash
PYTHONPATH=packages/platform-backend DB_ENGINE=sqlite SQLITE_NAME=:memory: .local/venvs/auth-org-review/bin/python apps/auth/backend/manage.py test identity_api.tests.test_notifications
node --test apps/portal/frontend/tests/notifications-reminder.browser.test.mjs apps/auth/frontend/tests/login-notification-isolation.browser.test.mjs
```

## 2026-10-20 无变化组织同步版本修复

- 原因：定时同步无条件递增全局组织版本，并重写全部目录行和成员/主管关系；各应用的旧目录提交因此容易返回 `ORG_REVISION_CONFLICT`。
- 已于 **2026-10-20 14:51:02（北京时间）**发布 Auth 统一修复。按实际字段及关系差异写入，只有真实变化才递增 `orgRevision`；无变化同步仍更新 `synced_at`，摘要增加 `organizationChanged`。无需修改 CRM、任务管理等应用即可消除无变化定时同步造成的版本失效。
- 51 项同步安全、组织权限和会话测试通过，包含 11 项新增差异检测用例；1 项仅适用于 PostgreSQL 的并发快照测试在 SQLite 中跳过。正式 PostgreSQL 用现有 79 个部门、173 名成员回放 3 次相同目录，版本始终为 5127，目录/关系 ID/时间戳保持不变，成功同步时间正常刷新；验证事务已回滚，未请求钉钉或修改正式目录。
- 资料、部门、成员和主管关系的真实变化仍发布新版本，账号停用/离职继续更新认证版本；没有忽略各业务应用已有的真实组织冲突或自动重放权限写入。已经持有旧版本的页面仍需保留草稿后重载一次。
- 无新增迁移；源码校验、迁移一致性、19 个清单检查、生产构建、HTTP/HTTPS 和两个 worker 消费队列检查通过。Auth 前端镜像与发布前一致。
- 备份：`backups/apps/auth/auth-db-20261020-064741.dump`；日志、旧镜像、源码及上线验证回执：`.runtime/auth-org-revision-release-20261020064741/`。
