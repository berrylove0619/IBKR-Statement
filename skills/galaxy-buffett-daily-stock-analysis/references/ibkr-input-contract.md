# IBKR 持仓输入合同

## 唯一读取入口

每次晨报先执行 `scripts/read_ibkr_snapshot.py`。它只读本机 loopback Elasticsearch，输出脱敏 JSON；不得改用新闻、历史回答、用户口述或猜测补齐正式持仓。

仓库根目录按以下顺序发现：显式 `--repo-root`；当前目录及父目录；这些目录的直接子目录 `IBKR-Statement`。候选目录必须同时包含 `ibkr_show_backend/` 和 `ibkr_show_worker/`，否则返回 `source_unavailable`。

```bash
python3 IBKR-Statement/skills/galaxy-buffett-daily-stock-analysis/scripts/read_ibkr_snapshot.py
```

若索引含多个账户，必须用 `--account-id` 或既有 `IBKR_ACCOUNT_ID` 环境变量显式选择。没有 selector 且账户候选不唯一时返回 `incomplete`。selector 值只用于 Elasticsearch 精确过滤，绝不输出或写入日志。

脚本可安全读取既有 `ES_USERNAME`、`ES_PASSWORD` 和 `ES_VERIFY_CERTS`。用户名和密码必须同时存在；凭证不得出现在 URL、输出或错误信息中。即使配置认证，`ES_HOST` 仍只允许 `localhost`、`127.0.0.1` 或 `::1` 的 HTTP(S)，拒绝远端主机。

## 已验证的真实数据链与成功语义

- 导入链：Flex CSV → `worker.parsers.transformers` → `worker.jobs.import_daily_snapshot` → Elasticsearch bulk upsert。
- 账户索引：`ibkr_account_daily_snapshot_v1`。
- 持仓索引：`ibkr_position_daily_snapshot_v1`。
- 后端现有服务读取相同索引；本脚本直接只读索引，是取得 `ingested_at` 且不修改公共 API／schema 的最小入口。

当前 schema **没有持久化的 import success 状态或独立导入日志**。禁止使用“最新成功导入”描述数据，也不得伪造 `status=success` 过滤。正式分析只能使用“最新可用且可证明同批的快照”；输出的 `document_batch_time` 是文档批次时间，不是导入成功审计时间。

## 严格连接与同批证明

账户候选按 `report_date desc, ingested_at desc` 排序。选定候选后，以下四个连接键必须全部为非空字符串：

`account_id + report_date + source_query_type + source_file_name`

任一缺失即返回 `incomplete`，绝不减少 position query 的过滤条件。position query 必须同时包含四个精确 `term` filters；每个返回文档还要逐项后验验证四键完全相等，错账户、错日期、错 query type 或错文件均返回 `incomplete`。

真实 transformer 先生成账户文档，再在同一次内存转换中逐个生成持仓文档，并分别调用 `utc_now_iso()`。因此同批证明还要求账户与全部持仓均有可解析、带时区的 `ingested_at`，且每个持仓时间不得早于账户时间，也不得晚于账户时间超过 5 分钟。这样可拒绝“新账户文档已写入、持仓 bulk 尚未完成而旧持仓仍残留”的 partial import。只靠相同日期或文件名、时间缺失／倒序／跨度过大都不能证明同批，必须返回 `incomplete`，不得生成正式覆盖或仓位动作。

账户或持仓候选超过 reader 上限而被截断时同样返回 `incomplete`。不存在精确匹配的持仓文档是连接不完整，不得降成可用空仓，也不得回退旧文档冒充当前批次。

## 持仓字段映射

| 输出字段 | Elasticsearch 字段 |
|---|---|
| `symbol` | `symbol` |
| `name` | `description` |
| `asset_class` | `asset_class` |
| `quantity` | `quantity` |
| `mark_price` | `mark_price` |
| `market_value` | `position_value` |
| `average_cost` | `average_cost_price` |
| `cost_basis` | `cost_basis_money` |
| `portfolio_weight` | `percent_of_nav` |
| `currency` | `currency` |

只保留 `quantity != 0` 或 `position_value != 0` 的同批文档；按绝对市值降序、代码升序输出。字段为空时保留 `null`，不得推算。输出不包含 `account_id`、原始文件名、文件名哈希、Flex 配置、ES 凭证或其他密钥；只输出 `source_identifier_present: true/false` 表示连接键中是否存在非空源标识。

## 状态分支

- `ready`：存在最新可用且可证明同批的快照；使用 `document_batch_time`、`holdings_as_of` 与 `holdings` 判断新鲜度并开始正式全持仓扫描。
- `empty`：没有账户文档，或已证明同批的快照没有非零持仓。正式覆盖写“未验证”，停止仓位动作。
- `incomplete`：账户选择歧义、连接键缺失／错配、候选截断、无精确持仓连接或时间不能证明同批。正式覆盖写“未验证”，停止仓位动作。
- `source_unavailable`：仓库根、索引或本机 Elasticsearch 不可用。披露错误类别，不展示底层响应、账户 selector、配置或凭证。

脚本 exit 0 仅代表 `ready`；`empty/incomplete` 为 exit 3，`source_unavailable` 为 exit 2。任何非零 exit 都进入临时范围分支，不得把用户提供的证券写成正式持仓。
