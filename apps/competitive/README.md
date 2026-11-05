# 竞品情报中心（Vue版）

App ID: `competitive`.

项目介绍、业务流程、技术架构、权限、产品档案对接及部署运维见 [项目交接文档](项目交接文档.md)。

## Start Here

- Edit `frontend/src/App.vue` for page content and interactions.
- Edit `frontend/src/styles.css` for page layout, colors and responsive styles.
- Keep routine work inside `apps/competitive/`; leave `api.js`, `session.js` and `config.js` unchanged unless the App's API or login integration really changes.

## Validate

Run from the repository root:

```bash
python3 scripts/appctl.py secrets ensure --app competitive
python3 scripts/appctl.py check
```

## Backend

Create one isolated Python environment for this App from the repository root.

Linux / macOS:

```bash
python3 -m venv .local/venvs/competitive
.local/venvs/competitive/bin/python -m pip install -r apps/competitive/backend/requirements.txt
.local/venvs/competitive/bin/python apps/competitive/backend/manage.py makemigrations
.local/venvs/competitive/bin/python apps/competitive/backend/manage.py makemigrations --check --dry-run
.local/venvs/competitive/bin/python apps/competitive/backend/manage.py check
.local/venvs/competitive/bin/python apps/competitive/backend/manage.py test
```

Windows PowerShell:

```powershell
py -3 -m venv .local/venvs/competitive
./.local/venvs/competitive/Scripts/python.exe -m pip install -r apps/competitive/backend/requirements.txt
$AppPython = (Resolve-Path ./.local/venvs/competitive/Scripts/python.exe).Path
& $AppPython apps/competitive/backend/manage.py makemigrations
& $AppPython apps/competitive/backend/manage.py makemigrations --check --dry-run
& $AppPython apps/competitive/backend/manage.py check
& $AppPython apps/competitive/backend/manage.py test
```

Commit generated migration files together with every model change. Host-side checks use an in-memory SQLite database and must not be treated as a production migration test. `app-deploy` runs migrations against the App's Docker PostgreSQL database; the handoff packager rejects any file-based local database left in the App source.

## Frontend

```bash
npm --prefix apps/competitive/frontend ci
npm --prefix apps/competitive/frontend run build
```

## Package For Handoff

Run from the repository root after validation:

```bash
python3 scripts/package_app.py competitive --base TASK_BASE_TAG_OR_COMMIT
```

Windows PowerShell:

```powershell
py -3 scripts/package_app.py competitive --base TASK_BASE_TAG_OR_COMMIT
```

Replace `TASK_BASE_TAG_OR_COMMIT` with the exact tag or commit assigned by the platform owner. Packaging checks committed, staged, unstaged and untracked changes and rejects anything outside `apps/competitive/`. Send the generated `export/competitive.app.zip`, its printed SHA-256, the assigned platform baseline, and the test results. Do not manually archive local Secret, database, upload, cache or build directories.

## Deploy

Linux developers must explicitly deploy with `local.env.docker`:

```bash
bash scripts/app-deploy.sh competitive local.env.docker
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File ./scripts/app-deploy.ps1 -AppId competitive -EnvFileName local.env.docker
```

macOS with PowerShell 7:

```bash
pwsh -NoProfile -File ./scripts/app-deploy.ps1 -AppId competitive -EnvFileName local.env.docker
```

The Linux shell script depends on Linux Bash, `flock` and `timeout`; do not use it on macOS.

Platform maintainers deploy the accepted package on the target machine with `server.env.docker`. Developers must never receive or use the server environment file, production Secrets or production data.

<!-- software-suggestions-rollout -->
## 本软件优化建议（桌面）

桌面工作台新增「本软件优化建议」，地址为 `/competitive/suggestions/`；共用应用模板的 `PlatformSoftwareSuggestions`。建议按 App ID 隔离，经 `/api/feedback/apps/competitive/suggestions` 正式接口读写，保留本应用原有访问与业务权限；建议服务仍独立校验我要提议的使用权限。原型版本管理沿用原建议和附件记录。

支持状态表格、关注/未读提醒、富文本与图片、视频附件、讨论意见弹窗、编辑、软删除、转为任务及真实任务抽屉；建议不提供分类或阶段字段。宿主导航、浏览器返回和门户提醒深链接入草稿/提交保护。手机菜单保持原有入口；桌面专用系统仍按原终端范围使用。
