# 审批中心

App ID: `approval-center`。这是一个独立的审批应用，复用平台登录、组织架构和应用管理员权限。

## 功能范围

- 审批首页：展示可发起的审批、待办摘要和最近申请。
- 审批中心：按待处理、已处理、我发起的分类查询审批单。
- 草稿箱：继续编辑或删除尚未提交的申请。
- 表单管理：配置表单字段、顺序审批节点、会签/或签和抄送节点，并发布不可变版本。
- 数据中心：按状态筛选和查询当前应用内的审批数据。
- 权限设置：基于 Auth 组织人员配置审批管理员。

申请详情和发起表单使用共享 `PlatformDetailDrawer`，列表保留在抽屉后方。自定义遮罩使用 `@platform-ui/backdrop-dismiss.js`，并保留未保存变更和忙碌状态保护。

## 代码入口

- `frontend/src/App.vue`：平台外壳、导航和前端路由。
- `frontend/src/components/approval/`：审批工作台、申请抽屉、详情抽屉和模板设计器。
- `frontend/src/components/AdminPermissionSettings.vue`：审批管理员设置。
- `backend/approval_center_api/models.py`：模板、版本、申请、任务、事件和草稿模型。
- `backend/approval_center_api/approval_views.py`：审批业务 API。
- `backend/approval_center_api/workflow.py`：流程创建和节点推进逻辑。

发布后的申请固定使用提交时的模板版本。当前版本支持顺序节点、会签、或签和抄送；条件分支、加签、委托、自动化和真实附件存储不在当前范围内。
首版中，退回会结束当前申请；如需修改内容，发起人应重新发起一份新申请，原申请不支持重提。

## 验证

Run from the repository root:

```bash
python3 scripts/appctl.py secrets ensure --app approval-center
python3 scripts/appctl.py check
```

## 后端

Create one isolated Python environment for this App from the repository root.

Linux / macOS:

```bash
python3 -m venv .local/venvs/approval-center
.local/venvs/approval-center/bin/python -m pip install -r apps/approval-center/backend/requirements.txt
.local/venvs/approval-center/bin/python apps/approval-center/backend/manage.py makemigrations
.local/venvs/approval-center/bin/python apps/approval-center/backend/manage.py makemigrations --check --dry-run
.local/venvs/approval-center/bin/python apps/approval-center/backend/manage.py check
.local/venvs/approval-center/bin/python apps/approval-center/backend/manage.py test
```

Windows PowerShell:

```powershell
py -3 -m venv .local/venvs/approval-center
./.local/venvs/approval-center/Scripts/python.exe -m pip install -r apps/approval-center/backend/requirements.txt
$AppPython = (Resolve-Path ./.local/venvs/approval-center/Scripts/python.exe).Path
& $AppPython apps/approval-center/backend/manage.py makemigrations
& $AppPython apps/approval-center/backend/manage.py makemigrations --check --dry-run
& $AppPython apps/approval-center/backend/manage.py check
& $AppPython apps/approval-center/backend/manage.py test
```

Commit generated migration files together with every model change. Host-side checks use an in-memory SQLite database and must not be treated as a production migration test. `app-deploy` runs migrations against the App's Docker PostgreSQL database; the handoff packager rejects any file-based local database left in the App source.

## 前端

```bash
npm --prefix apps/approval-center/frontend ci
npm --prefix apps/approval-center/frontend run build
```

## Package For Handoff

Run from the repository root after validation:

```bash
python3 scripts/package_app.py approval-center --base TASK_BASE_TAG_OR_COMMIT
```

Windows PowerShell:

```powershell
py -3 scripts/package_app.py approval-center --base TASK_BASE_TAG_OR_COMMIT
```

Replace `TASK_BASE_TAG_OR_COMMIT` with the exact tag or commit assigned by the platform owner. Packaging checks committed, staged, unstaged and untracked changes and rejects anything outside `apps/approval-center/`. Send the generated `export/approval-center.app.zip`, its printed SHA-256, the assigned platform baseline, and the test results. Do not manually archive local Secret, database, upload, cache or build directories.

## Deploy

Linux developers must explicitly deploy with `local.env.docker`:

```bash
bash scripts/app-deploy.sh approval-center local.env.docker
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File ./scripts/app-deploy.ps1 -AppId approval-center -EnvFileName local.env.docker
```

macOS with PowerShell 7:

```bash
pwsh -NoProfile -File ./scripts/app-deploy.ps1 -AppId approval-center -EnvFileName local.env.docker
```

The Linux shell script depends on Linux Bash, `flock` and `timeout`; do not use it on macOS.

Platform maintainers deploy the accepted package on the target machine with `server.env.docker`. Developers must never receive or use the server environment file, production Secrets or production data.

<!-- software-suggestions-rollout -->
## 本软件优化建议（桌面）

桌面工作台新增「本软件优化建议」，地址为 `/approval-center/suggestions/`；共用应用模板的 `PlatformSoftwareSuggestions`。建议按 App ID 隔离，经 `/api/feedback/apps/approval-center/suggestions` 正式接口读写，保留本应用原有访问与业务权限；建议服务仍独立校验我要提议的使用权限。原型版本管理沿用原建议和附件记录。

支持状态表格、关注/未读提醒、富文本与图片、视频附件、讨论意见弹窗、编辑、软删除、转为任务及真实任务抽屉；建议不提供分类或阶段字段。宿主导航、浏览器返回和门户提醒深链接入草稿/提交保护。手机菜单保持原有入口；桌面专用系统仍按原终端范围使用。
