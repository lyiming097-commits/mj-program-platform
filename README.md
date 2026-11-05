# 迈杰平台项目

当前工作目录的源码快照，包含 `apps/` 下的平台应用、开发规范及表单审批管理交互原型。

## 表单设计与审批

- 应用代码及功能说明：[apps/form-designer](apps/form-designer/README.md)。
- 交互原型：[审批管理原型](apps/form-designer/prototypes/approval-management.html)。
- 已实现的提交结果窗口位于表单设计前端源码；原型中的流程分级授权、人员排查与批量替换为设计演示，尚未接入真实业务。

原型沿用统一流程树：箭头展开审批，点击审批进入申请填写页；管理员点击流程名称进入管理页，“全部流程”支持查看权限范围内的全部审批。

## 运行边界

本目录是平台应用源码，并非完整平台发行包。正式运行需要公司的共享 `platform-ui`、`platform_auth`、部署脚本和各应用所需服务，具体见应用 README。原有本机的独立验证启动工具位于此仓库之外，未包含在本次源码快照中。

原完整平台 CI 配置保存在 [.github/workflow-reference/auth-portal-checks.yml](.github/workflow-reference/auth-portal-checks.yml)，供参考，不作为本仓库的自动运行工作流。本机原 `.github/workflows/auth-portal-checks.yml` 保留；当前 GitHub 登录权限不包含上传工作流所需的 `workflow` scope，且此配置依赖本快照缺失的平台目录。

原型是用于 Codex 会话预览的 HTML 片段；图标、状态持久化和设计选项依赖会话环境，不能作为已接入后端的产品页面使用。

不包含本地依赖目录、虚拟环境、数据库、上传附件、日志或运行时密钥；环境变量示例见 `.env.docker.example`。请勿将生产密钥或业务数据库提交到仓库。
