# 售后系统生产上线手册

本文用于首次正式上线及后续升级。管理端通过钉钉登录，服务人员通过微信小程序登录。要让所有微信用户可用，最终必须在微信公众平台发布正式版。

## 1. 上线前确认

- 确认 `miniapp/src/manifest.json` 中的 AppID `wxce762bf0d0e8f3c3` 归属于杭州迈杰教育科技有限公司；如公司后续更换小程序主体，需同步替换这里及服务器配置。
- `server.env.docker` 设置相同的 `WECHAT_MINI_APP_ID`，并保持 `WECHAT_MINI_DEV_LOGIN_ENABLED=0`。
- 在 `server.env.docker` 的 `DJANGO_ALLOWED_HOSTS` 中加入 `service.hzmaijie.com`；管理端继续使用现有域名时不要移除原 Host。钉钉管理端域名还必须保留在 `DINGTALK_JSAPI_ALLOWED_ORIGINS` 中。
- 将正式 AppSecret 单独写入 `secrets/apps/auth/wechat-mini-app.secret`，权限设为 `0600`。不要把 Secret 写入 Git、环境示例文件或小程序包。
- `service.hzmaijie.com` 的 DNS 指向生产服务器，服务器通过独立小程序入口对公网提供 HTTPS 4433，证书有效且证书域名匹配。
- HTTPS 边缘代理按域名转发到独立 `service-nginx:18443`，再由该入口转发到平台网关。不要把小程序入口并入 OA 应用路由。
- 完成网站 ICP 备案和小程序备案，并在微信公众平台填写隐私保护指引及图片、文件相关权限用途。
- 在微信公众平台将 `https://service.hzmaijie.com:4433` 配为 request、uploadFile 和 downloadFile 合法域名。

上线前运行仓库检查：

```bash
python3 scripts/appctl.py check --skip-secrets
```

正式 Secret 准备好后，再运行不跳过 Secret 的完整检查：

```bash
python3 scripts/appctl.py check
```

## 2. 备份与恢复演练

选择维护窗口，暂停管理端和小程序写入。分别备份 Auth 与售后数据库：

```bash
python3 scripts/backup_app_db.py auth --env-file server.env.docker
python3 scripts/backup_app_db.py after-sales --env-file server.env.docker
```

数据库备份不包含附件。另行备份 Docker 卷 `mj_program_after_sales_uploads`，并把备份放到服务器外的受控存储。示例中的目录和文件名应按公司的备份策略调整：

```bash
upload_backup="after-sales-uploads-$(date -u +%Y%m%d-%H%M%S).tar.gz"
docker run --rm \
  -e BACKUP_NAME="$upload_backup" \
  --mount type=volume,src=mj_program_after_sales_uploads,dst=/source,readonly \
  --mount type=bind,src=/secure-backups,dst=/backup \
  alpine:3.20 sh -c 'tar -C /source -czf "/backup/$BACKUP_NAME" .'
```

确认两个数据库 dump 非空且工具校验通过，确认附件归档可列出。首次生产上线前，必须在非生产环境实际演练恢复。只验证数据库恢复计划、不修改数据库的命令如下：

```bash
python3 scripts/restore_app_db.py auth backups/apps/auth/AUTH_DUMP.dump \
  --env-file server.env.docker
python3 scripts/restore_app_db.py after-sales backups/apps/after-sales/AFTER_SALES_DUMP.dump \
  --env-file server.env.docker
```

实际恢复是破坏性操作，只能在已批准的恢复窗口使用 `--restore --yes`。容器回滚不会自动回滚数据库迁移。

## 3. 部署顺序

先部署 Auth，再部署售后系统：

```bash
bash scripts/app-deploy.sh auth server.env.docker
bash scripts/app-deploy.sh after-sales server.env.docker
```

Auth 必须先上线，因为小程序登录依赖新的微信认证路由、身份模型及 token 渠道声明。部署会自动执行 Django 迁移。重点复核：

- Auth 微信身份迁移与售后 `0020_service_provider_identity_source`。
- 售后 `0014` 至 `0018` 包含业务数据调整，迁移前必须完成备份和恢复演练。
- `0020` 保留历史服务档案和任务，但把非 `wxmini:` 档案标为钉钉历史来源，禁止再接新售中、售后任务。

部署后检查容器和接口：

```bash
docker compose -f compose.yaml -f .runtime/compose.apps.yaml \
  --env-file server.env.docker ps
curl --fail --silent --show-error https://service.hzmaijie.com:4433/api/after-sales/health/ready
```

再完成一次端到端冒烟测试：钉钉管理账号进入管理端；新微信用户注册后出现在“服务团队 / 待审核”；未审核用户不可接单；审核通过后可被售中、售后派单；售前选人列表只显示钉钉通讯录人员；小程序只显示本人的任务。

## 4. 构建并发布微信小程序

在代码版本和服务器 API 完全一致时构建正式包：

```bash
npm --prefix apps/after-sales/miniapp ci
npm --prefix apps/after-sales/miniapp run type-check
VITE_API_BASE_URL=https://service.hzmaijie.com:4433 VITE_WECHAT_DEV_AUTH=0 \
  npm --prefix apps/after-sales/miniapp run build:mp-weixin
rg -n -a "localhost|wechat-mini/dev-login|http://" \
  apps/after-sales/miniapp/dist/build/mp-weixin
```

最后一条命令必须无输出。然后用微信开发者工具导入 `miniapp/dist/build/mp-weixin/`：

1. 上传体验版并使用真机验证登录、注册、附件上传下载、待审核、派单、完工和注销。
2. 在微信公众平台确认服务类目、用户协议、隐私保护指引和权限用途与代码一致。
3. 提交微信审核；审核通过后发布正式版。

开发版和体验版只能供指定成员使用。只有发布正式版后，普通微信用户才能搜索或扫码使用。

## 5. 回滚原则

- 应用部署失败时，`app-deploy.sh` 会尽量恢复上一版镜像和容器，但不会逆转已经执行的数据库迁移。
- 代码回滚与数据库回滚必须匹配同一版本。数据库恢复前先停止写入，并使用 `restore_app_db.py` 的验证模式确认归档。
- 附件卷单独恢复，避免数据库里的附件记录与文件内容不一致。
- 微信正式版出现阻断问题时，可先在微信公众平台回退版本，同时保留服务器日志、Auth dump、售后 dump 和附件卷备份供排查。
