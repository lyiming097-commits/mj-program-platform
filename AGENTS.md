# 平台开发入口

- 开发、修改或评审本平台应用时，先使用并阅读 [mj-platform-standards](skills/mj-platform-standards/SKILL.md)，再按其任务路由读取参考；这是全平台规范的统一入口。
- 同时遵守目标 App 的 `AGENTS.md` 和 README。用户当前要求优先，保留工作树中不属于当前任务的修改。
- 操作/API 细节保留在 [每次运行必读](ai写代码前必读/README.md)，不要把旧实现的差异当成默认规范。
- 不使用 agent 协作工具，除非用户明确改口。
- 用户已授权：后续修改完成并验证通过后直接部署，无需再次询问。按当前主机的实际环境发布本次改动，保留无关工作，完成必要备份、健康检查与上线验证，并报告部署结果。

<!-- CODEGRAPH_START -->
## CodeGraph

In repositories indexed by CodeGraph (a `.codegraph/` directory exists at the repo root), reach for it BEFORE grep/find or reading files when you need to understand or locate code:

- **MCP tool** (when available): `codegraph_explore` answers most code questions in one call — the relevant symbols' verbatim source plus the call paths between them, including dynamic-dispatch hops grep can't follow. Name a file or symbol in the query to read its current line-numbered source. If it's listed but deferred, load it by name via tool search.
- **Shell** (always works): `codegraph explore "<symbol names or question>"` prints the same output.

If there is no `.codegraph/` directory, skip CodeGraph entirely — indexing is the user's decision.
<!-- CODEGRAPH_END -->
