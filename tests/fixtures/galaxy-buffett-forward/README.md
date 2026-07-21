# Galaxy Buffett 前向测试 Fixtures

本目录保存 2026-07-21 前向测试的脱敏 prompt 与原始输出，供非 LLM 校验器重放。绝对用户路径统一替换为 `<PROJECT_ROOT>`；未保存账户号、凭证或配置值。

- `forward_breadth.md`：资源与覆盖压力输出。
- `forward_conflict.md`：财报冲突输出。
- `forward_relevance_failed.md`：修复前失败输出。
- `forward_relevance_fixed.md`：修复后的 fresh rerun 输出。
- `ibkr-es-responses.json`：由仓库既有 `daily_sample.csv` 字段构造的脱敏 Elasticsearch 代表性响应。
- `ibkr-es-empty.json`：无快照分支响应。

这些 fixtures 只由项目验证脚本读取，不属于 Skill 每次运行上下文。
