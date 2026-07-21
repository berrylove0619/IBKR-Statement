# IBKR 持仓输入合同

## 唯一读取入口

每次晨报先执行 `scripts/read_ibkr_snapshot.py`。它只读本机 Elasticsearch，输出脱敏 JSON；不得改用新闻、历史回答、用户口述或猜测补齐正式持仓。

仓库根目录按以下顺序发现：显式 `--repo-root`；当前目录及父目录；这些目录的直接子目录 `IBKR-Statement`。候选目录必须同时包含 `ibkr_show_backend/` 和 `ibkr_show_worker/`，否则返回 `source_unavailable`。

从仓库父目录运行示例：

```bash
python3 IBKR-Statement/skills/galaxy-buffett-daily-stock-analysis/scripts/read_ibkr_snapshot.py
```

## 已验证的真实数据链

- 导入链：Flex CSV → `worker.parsers.transformers` → `worker.jobs.import_daily_snapshot` → Elasticsearch bulk upsert。
- 账户索引：`ibkr_account_daily_snapshot_v1`。
- 持仓索引：`ibkr_position_daily_snapshot_v1`。
- 后端现有 `AccountService` 与 `PositionService` 读取相同索引；本脚本直接只读索引，是取得 `ingested_at` 且不修改公共 API／schema 的最小入口。

当前 schema **没有持久化 import status 或独立导入日志**。不得伪造 `status=success` 过滤。脚本只把“按 `report_date desc, ingested_at desc` 取得的最新账户文档，能够连接同一 `report_date + source_query_type + source_file_name` 的持仓文档”称为可用快照，并在输出中保留 `selection.success_status=not_persisted`。如果最新账户文档无法连接持仓，不得回退到更旧日期冒充最新成功导入。

`imported_at` 来自匹配账户／持仓文档中最大的 `ingested_at`，代表文档写入批次时间，不是独立审计日志。`holdings_as_of` 来自 `report_date`；`base_currency` 来自账户快照 `currency`。

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

只保留 `quantity != 0` 或 `position_value != 0` 的文档；按绝对市值降序、代码升序输出。字段为空时保留 `null`，不得推算。输出不包含 `account_id`、原始文件名、Flex 配置、ES 凭证或其他密钥；源文件只输出不可逆短指纹。

## 状态分支

- `ready`：使用 `snapshot` 与 `holdings`，再判断新鲜度并开始正式全持仓扫描。
- `empty`：没有账户文档，或最新连接快照没有非零持仓。正式覆盖写“未验证”，停止仓位动作。
- `incomplete`：最新账户文档缺关键连接字段。正式覆盖写“未验证”，停止仓位动作。
- `source_unavailable`：仓库根目录、索引或本机 Elasticsearch 不可用。披露错误类别，不展示底层响应或配置。

脚本 exit 0 仅代表 `ready`；`empty/incomplete` 为 exit 3，`source_unavailable` 为 exit 2。任何非零 exit 都进入临时范围分支，不得把用户提供的证券写成正式持仓。
