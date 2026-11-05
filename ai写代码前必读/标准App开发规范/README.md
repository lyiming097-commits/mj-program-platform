# 标准 App 开发规范

本目录是新增独立 App 时的每次必读规范，只展示基础目录结构和开发、部署规则，不包含可运行代码。

开发新 App 前，先阅读：

1. [基础目录结构](./基础目录结构.md)
2. [开发与部署流程](./开发与部署流程.md)
3. [脚手架命令与影响范围](./脚手架命令与影响范围.md)
4. [App 协作开发与交付手册](../../docs/APP_COLLABORATION.md)

如果 App 需要按 Auth 部门或员工分配业务权限，还必须阅读 [统一组织权限页面与接口规范](../统一组织权限页面与接口规范.md)。

## 最重要的原则

正常开发一个新 App，只允许新增和修改：

```text
apps/<app-id>/
```

不得因为新增 App 手工修改：

```text
compose.yaml
docker/gateway/nginx.conf
apps/auth/
apps/portal/
apps/crm/
其他业务 App
*.env.docker.example
```

App 的容器、公开路由、门户入口、图标和 Secret 挂载，统一由该 App 自己的 `app.manifest.yaml` 声明。业务权限只能写在 App 自己的后端；门户和网关不替 App 判断用户权限。

普通业务开发不得增加额外容器，也不得修改脚手架生成的标准镜像、启动控制字段、前后端 Dockerfile 和 manifest `build` 定义。Python/npm 依赖写进 App 自己的依赖文件；导入器默认拒绝非标准运行结构。高风险例外必须由平台负责人单独审查并显式放行。

`auth`、`portal` 属于平台核心，不走 App 包导入流程；导入器会直接拒绝。核心变更必须作为平台版本升级单独发布。

清单中的 `status` 只是展示信息，不会停止容器或关闭路由。旧字段 `permissions`、路由 `access`、`redirectOnDenied` 已禁用，写入后 `appctl.py check` 会直接失败。

如果现有清单能力无法满足需求，例如需要 WebSocket 或特殊代理协议，必须先向用户说明原因，获得允许后才能修改 App 文件夹以外的代码。

多人协作时还要遵守一个中央基准：平台负责人先分配唯一 App ID 和指定 Git commit/tag，开发者从该版本开始工作。开发结束后使用标准打包器交付，不直接复制 `node_modules`、数据库、Secret 或整个仓库。

## 新 App 标准命令

假设 App ID 是 `erp`：

```bash
python3 scripts/new_app.py erp \
  --name "ERP" \
  --description "企业资源管理" \
  --no-deploy \
  --yes
```

这是多人开发的标准入口：从负责人指定的基准创建任务分支后，只生成本地骨架，不提前合入生产 `main`。交互向导现在也默认不部署；任何部署都必须显式选择环境。

需要创建后部署到开发者电脑时，必须明确传本地环境：

```bash
python3 scripts/new_app.py erp \
  --name "ERP" \
  --env-file local.env.docker \
  --deploy \
  --yes
```

该命令只在目标目录不存在时创建 `apps/erp/`，只初始化 ERP 自己的 Secret，并在落盘前检查完整清单、路由和 Compose 模型。生成内容已接入公共会话/API 客户端、Auth introspection、同源写保护和数据库 readiness。

页面内容从 `apps/erp/frontend/src/App.vue` 开始修改，页面布局和颜色从 `apps/erp/frontend/src/styles.css` 开始修改。普通页面开发不要改共享平台目录。

如果生成后的校验或部署失败，向导会保留已经生成的 App、Secret 和数据库卷，并在错误末尾打印后续校验与部署命令；不要再次运行向导覆盖目录。

底层 `appctl.py scaffold` 和 `app-deploy.sh` 命令仍然保留，供平台维护和故障排查使用。

平时只修改 ERP 页面或接口后，直接运行：

```bash
scripts/app-deploy.sh erp local.env.docker
```

上面是开发者电脑的本地部署。生产服务器才使用 `server.env.docker`。部署命令已经自动执行 Secret 检查，不需要每次手工运行 `secrets ensure`。

## 标准交付

开发者完成本地测试后，从仓库根目录打包：

```bash
python3 scripts/package_app.py erp --base app-sdk-v1
```

把 `app-sdk-v1` 换成平台负责人实际指定的 tag 或完整 commit；指定当前远端主线时，先 `git fetch origin` 再用 `--base origin/main`。打包器会拒绝 `apps/erp/` 以外的变化，并把共享平台依赖指纹写入 v2 包。

只交付 `export/erp.app.zip`、打包器打印的 SHA-256、基准 commit/tag、版本说明和测试结果。旧 v1 包必须使用当前公版重新生成。平台负责人先执行不落盘验包：

```bash
git fetch origin --tags
APP_ZIP_SHA256='把开发者单独发送的64位小写SHA256填在这里'
python3 scripts/import_app.py /path/to/erp.app.zip \
  --expected-sha256 "$APP_ZIP_SHA256" \
  --expected-base app-sdk-v1
```

验包通过仍不代表第三方代码可信。Dockerfile、依赖和 migration 必须经过审查，并先在没有生产 Secret 和生产数据的隔离环境构建测试。完整安装、更新、IPAM 重分配、数据库备份和回滚边界见 [App 协作开发与交付手册](../../docs/APP_COLLABORATION.md)。

正式流程禁止打包器的 `--allow-outside-changes`。使用它生成的包会被服务器默认拒绝；`--allow-unverified-source` 只供平台负责人对已逐项审查的紧急例外做二次放行，不能绕过共享依赖指纹不一致。

## Secret 规则

真实密码位于：

```text
secrets/apps/<app-id>/
```

该目录不属于业务代码，不提交 Git。`secrets ensure` 只创建缺少的文件，不覆盖已有 Secret。

Linux 和 macOS 上，Secret 目录必须是 `0700`、文件必须是 `0600`。Windows 上不能用模拟的 POSIX mode 判断安全性：平台会创建并验证受保护的 NTFS DACL，只允许文件所有者、`SYSTEM` 和本机 `Administrators` 访问，同时阻止从父目录继承宽松权限。FAT/exFAT、部分网络共享或不完整实现 Windows ACL 的挂载会校验失败；不要用 `--skip-secrets` 绕过部署检查。

禁止直接删除或重新生成已有数据库密码。数据库密码轮换需要同时修改 PostgreSQL 账号密码，必须作为独立操作处理。

## 支持的开发环境

- 平台 Python 工具支持 Python 3.11 至 3.14；生产 App 后端镜像固定使用 Python 3.11 系列。
- 前端宿主检查和 Docker 构建使用 Node.js 22 LTS 与随附 npm；依赖必须同时提交 `package.json` 和 `package-lock.json`。
- Windows Secret 必须位于支持持久 DACL 的本地 NTFS 文件系统。Windows 开发者可创建骨架、打包和只读验包，中央安装仍在 Linux 服务器执行。
- 打包器会清理外部 `GIT_*` 配置，并只把本次已解析的仓库绝对路径作为临时 `safe.directory` 传给 Git。不要修改用户全局 Git 配置，也禁止配置 `safe.directory=*`。
