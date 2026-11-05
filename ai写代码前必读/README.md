# 每次运行必读

平台开发的统一入口已汇总为 [mj-platform-standards skill](../skills/mj-platform-standards/SKILL.md)。先读取 skill，再按任务读取其中的参考；下列文档继续提供接口和操作细节。新应用以 skill 和应用模板为基准，既有业务例外见 skill 的系统差异表。

## 协作执行约束

- 需要并行思考时，可使用 Luna 或特大 Terra 子线程。
- 不使用 agent 工具；除非用户明确改口，不启动 agent 协作。

开始开发前，根据任务范围阅读对应规范：

- Auth、统一登录、代理、白名单和组织接口：[Auth 内部接口说明](./auth内部接口说明.md)
- 使用 Auth 部门/员工分配业务权限：[统一组织权限页面与接口规范](./统一组织权限页面与接口规范.md)
- 查询我司主体、省市区及新增平台基础数据：[平台基础数据查询接口](../docs/PLATFORM_BASE_DATA_API.md)；各应用统一调用权威维护服务，管理页与查询接口使用相同来源。
- 内部应用统一发送机器人通知：[内部应用机器人通知接口](../docs/ROBOT_NOTIFICATIONS_INTERNAL_API.md)；包含服务鉴权、发送/查结果/查群、幂等编号、来源追溯和共享 Python 客户端。
- 接入钉钉群通知或员工私聊：[钉钉群消息与私聊接入指南](../docs/DINGTALK_GROUP_MESSAGING.md)；包含已验证的机器人/群 ID、群聊及私聊发送接口、后端代码和新群接入步骤。
- 页面、弹窗、抽屉、遮罩点击、未保存提醒和交互样式：[页面设计风格规范](./页面设计风格规范.md)
- 新增或维护独立 App：[标准 App 开发规范](./标准App开发规范/README.md)
- 查询脚手架、部署、打包、导入和数据库命令：[脚手架命令与影响范围](./标准App开发规范/脚手架命令与影响范围.md)

## 弹窗、抽屉和遮罩交互（所有系统通用）

全应用改造范围和验证记录：[遮罩检查记录](../docs/BACKDROP_DISMISS_AUDIT.md)。

- 遮罩关闭必须来自一次完整的遮罩点击：同一指针在遮罩上按下，并且仍在遮罩上松开。
- 在弹窗或抽屉内容中按下后移动到遮罩再松开，不得关闭浮层；不得使用单独的 `mouseup`/`pointerup` 或 `@click.self` 关闭。
- 弹窗内容必须阻止点击冒泡到遮罩；关闭按钮、取消按钮和 `Escape` 等显式关闭方式可以独立处理。
- 自制 Vue 遮罩统一导入 `backdropDismiss as vBackdropDismiss`（来自 `@platform-ui/backdrop-dismiss.js`），在实际遮罩节点使用 `v-backdrop-dismiss="requestClose"`；内联表达式写成函数，例如 `v-backdrop-dismiss="() => { open = false }"`。不要再叠加直接关闭的 `@click`。
- 关闭仍走原来的未保存确认、提交中保护等业务逻辑；原本不可通过遮罩关闭的窗口继续保留该策略。
- 第三方弹窗需验证其完整点击校验；小程序触摸遮罩需同时记录触点，并校验松开坐标仍落在遮罩上。

修改遮罩后，从仓库根目录执行静态检查及浏览器回归：

```bash
node scripts/check-backdrop-dismiss.cjs
node --test packages/platform-ui/tests/backdrop-dismiss.browser.test.mjs
node --test apps/crm/frontend/tests/backdrop.browser.test.mjs
node --test scripts/test-app-backdrop-dismiss.browser.mjs
node apps/maijie-mall/frontend/scripts/backdrop-browser-test.mjs
```

浏览器回归需要安装 Playwright 和 Chromium；商城测试可用 `PLAYWRIGHT_MODULE` 指定共享 Playwright 模块路径。操作规则和实现示例见[页面设计风格规范](./页面设计风格规范.md#10-弹窗抽屉和确认框)。

新增 App 时必须先阅读“标准 App 开发规范”。正常情况下，只修改 `apps/<app-id>/`，不得手工修改 Auth、门户、CRM、根 Compose 或网关配置。
