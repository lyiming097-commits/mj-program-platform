# 迈杰现场服务微信小程序

现场端与钉钉管理端共用统一 Auth、`after-sales` API 和业务数据库。小程序不保存微信 AppSecret，也不使用姓名或手机号猜测账号关系。

## 本地运行

```powershell
npm install
npm run type-check
npm run build:mp-weixin:local
& 'D:\Program Files (x86)\Tencent\微信web开发者工具\cli.bat' open `
  --project 'D:\maiteng project\jsj\mj_program_platform\apps\after-sales\miniapp\dist\build\mp-weixin' `
  --lang zh
```

服务器构建目录映射为 Windows `W:` 后，可启动受限调试桥接：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File 'W:\.mj-devtools\Start-MjWechatBridge.ps1' `
  -ShareRoot 'W:\' `
  -ProjectPath "$env:USERPROFILE\Desktop\mj-after-sales-miniapp"
```

桥接只处理环境探测、打开或编译项目、小程序组件检查、微信开发者工具窗口内点击、窗口截图和桥接自更新，不支持上传、发布或任意命令执行。保持桥接窗口打开即可；每次小程序构建会自动把脚本补回构建目录，并从上传包中排除 `.mj-devtools`。

本地测试包使用 Auth 独立的微信受限开发登录，不依赖真实 AppID。`auth-backend` 必须启用 `WECHAT_MINI_DEV_LOGIN_ENABLED=1`，小程序构建环境必须设置 `VITE_WECHAT_DEV_AUTH=1`，且请求必须通过本机来源校验。不要为此打开钉钉 Web 登录使用的 `AUTH_DEV_LOGIN_ENABLED`。

真机调试和正式发布使用正式构建，必须显式关闭开发认证并指向已备案的 HTTPS 域名：

```bash
VITE_API_BASE_URL=https://service.hzmaijie.com:4433 VITE_WECHAT_DEV_AUTH=0 \
  npm run build:mp-weixin
```

## 联动测试

1. 在微信开发者工具左上角确认账号已登录；登录态过期时先重新扫码。
2. 编译本地测试包，首次进入填写姓名、联系电话、城市和服务角色并提交。
3. 用钉钉管理账号打开 `http://localhost:8080/after-sales/team/`，在“服务团队”的“待审核”状态中找到刚注册的人员。
4. 打开该人员详情并点击“审核通过”。小程序最多 5 秒后自动进入任务列表。
5. 在售中或售后项目节点中把该人员加入项目人员并确认开始，小程序会自动出现对应任务。售前人员始终从钉钉通讯录选择，不会进入服务人员小程序任务。
6. 小程序填写现场数据并确认完工，管理端节点会显示已上传内容，再由管理端执行节点通过。

## 微信配置

1. 确认 `src/manifest.json` 中的 AppID 归属于公司；如不属于，替换为正式小程序 AppID。
2. 在平台环境设置 `WECHAT_MINI_APP_ID` 为同一个 AppID。
3. 将 AppSecret 写入 `secrets/apps/auth/wechat-mini-app.secret`，不要写入仓库。
4. 重新生成运行配置并重启 `auth-backend`。

首次登录时填写服务人员资料。注册成功后会立即出现在管理端“服务团队”的待审核列表；管理员审核通过后，小程序自动进入任务列表。

正式发布前还必须在微信公众平台配置 `https://service.hzmaijie.com:4433` 为 request、uploadFile 和 downloadFile 合法域名，完成 ICP/小程序备案和隐私保护指引，真机验收后提交审核并发布正式版。体验版不能满足“所有微信用户可用”。
