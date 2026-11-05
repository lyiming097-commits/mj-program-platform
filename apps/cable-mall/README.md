# Cable Mall App

Cable mall owns:

- `frontend/`: `/cable-mall` and external cable mall pages
- `backend/`: cable mall APIs and the local sales catalog mirror
- `cable-mall-postgres`: cable mall data only

Cable product master data comes only from the product archive `线材` domain. The backend reads
`http://product-archive-backend:8000/api/internal/product-catalog/` over the private `mj_services`
network with the `cable-mall-backend` Auth service credential, then stores a local mirror for carts,
external users and order snapshots. It does not connect to an external product database.
Cached catalog images are exposed only through the app-owned `/cable-mall-media/` route.

Internal cable-mall access follows the same centralized permission contract as CRM. Platform system
administrators are identified by Auth's `canUseSystemAdmin` capability. Permission departments and
employees come from a revision-consistent Auth organization snapshot and are materialized only in the
cable-mall database for local authorization checks. Permission reads return `revision`, directory reads
return `orgRevision`, and saves require both values to prevent stale configuration or organization data
from overwriting newer changes.

This app now builds from its own `frontend/` and `backend/` folders.

<!-- software-suggestions-rollout -->
## 本软件优化建议（桌面）

桌面工作台新增「本软件优化建议」，地址为 `/cable-mall/suggestions/`；共用应用模板的 `PlatformSoftwareSuggestions`。建议按 App ID 隔离，经 `/api/feedback/apps/cable-mall/suggestions` 正式接口读写，保留本应用原有访问与业务权限；建议服务仍独立校验我要提议的使用权限。原型版本管理沿用原建议和附件记录。

支持状态表格、关注/未读提醒、富文本与图片、视频附件、讨论意见弹窗、编辑、软删除、转为任务及真实任务抽屉；建议不提供分类或阶段字段。宿主导航、浏览器返回和门户提醒深链接入草稿/提交保护。手机菜单保持原有入口；桌面专用系统仍按原终端范围使用。
