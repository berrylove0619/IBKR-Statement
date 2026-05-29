# ibkr_show_worker

`ibkr_show_worker` 是整个项目的数据入口，负责：

- 从 IBKR Flex Web Service 拉取 `MyDailyData`
- 导入本地历史快照 CSV
- 解析 Flex 多 section 数据
- 写入 Elasticsearch

## 当前会写入的索引

- `ibkr_account_daily_snapshot_v1`
- `ibkr_position_daily_snapshot_v1`
- `ibkr_trade_records_v1`
- `ibkr_cash_flow_records_v1`
- `ibkr_symbol_price_history_v1`

其中：

- `TRNT` section -> 交易记录
- `CTRN` section -> 出入金记录
- `PPPO` section -> 标的历史价格

## 安装

```bash
cd /path/to/ibkr_show/ibkr_show_worker
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## 最小配置

`.env` 中最关键的字段只有：

```env
FLEX_TOKEN=
FLEX_QUERY_ID_DAILY=
ES_HOST=http://localhost:9200
```

其余字段默认值通常可以直接使用。

## CLI 命令

```bash
./.venv/bin/python -m worker.main init-es
./.venv/bin/python -m worker.main es-health
./.venv/bin/python -m worker.main import-daily-file --file /absolute/path/to/file.csv
./.venv/bin/python -m worker.main pull-daily-from-ibkr
./.venv/bin/python -m worker.main run-scheduler
```

## 初始化 Elasticsearch

```bash
./.venv/bin/python -m worker.main init-es
./.venv/bin/python -m worker.main es-health
```

## 导入历史文件

单文件导入：

```bash
./.venv/bin/python -m worker.main import-daily-file --file /absolute/path/to/history.csv
```

目录批量导入：

```bash
find /absolute/path/to/history-folder -name '*.csv' -print0 | while IFS= read -r -d '' file; do
  echo "importing $file"
  ./.venv/bin/python -m worker.main import-daily-file --file "$file"
done
```

如果只想先验证链路，可以用仓库样例：

```bash
./.venv/bin/python -m worker.main import-daily-file --file ./worker/fixtures/daily_sample.csv
```

## 每日增量

手动执行一次：

```bash
./.venv/bin/python -m worker.main pull-daily-from-ibkr
```

持续运行调度器：

```bash
./.venv/bin/python -m worker.main run-scheduler
```

默认规则：

- 每天北京时间 `12:30`
- 拉取一次 `MyDailyData`
- 幂等写入 ES

## 幂等说明

- 每类文档都使用确定性 `_id`
- ES 使用 bulk `update + doc_as_upsert`
- 重复导入同一历史文件不会产生重复数据
