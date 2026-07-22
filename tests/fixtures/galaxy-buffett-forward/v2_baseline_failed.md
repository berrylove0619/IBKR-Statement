# v2_baseline_failed

## Prompt

Use $galaxy-buffett-daily-stock-analysis at /Users/galaxyimac/Melo DEV/Melo Stock/IBKR-Statement/skills/galaxy-buffett-daily-stock-analysis to draft a complete offline morning-report HTML for a portfolio with AAPL, MSFT, BRK.B and a short-duration Treasury ETF. Use the skill's own missing-data rules. Do not browse, call a broker, or modify files. Return the complete response you would give the user.

## Output

未保存文件。由于本次明确为离线场景，且未调用 IBKR 或新闻来源，以下证券仅列为用户提供的临时范围，不能视为正式持仓；报告不会推算数量、权重，也不会给出持仓动作。

```html
<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>每日美股晨报｜2026-07-22</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4f6f8;
      --card: #ffffff;
      --text: #17202a;
      --muted: #5f6b76;
      --line: #dce2e7;
      --warning-bg: #fff4d6;
      --warning-text: #775500;
      --neutral-bg: #e9edf1;
      --neutral-text: #394550;
      --danger-bg: #fde9e7;
      --danger-text: #8a241d;
      --accent: #205493;
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
        "Noto Sans TC", "PingFang TC", Arial, sans-serif;
      line-height: 1.6;
    }

    main {
      width: min(1100px, calc(100% - 28px));
      margin: 28px auto 48px;
    }

    header, section {
      margin-bottom: 18px;
      padding: 22px;
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 12px;
    }

    h1, h2, h3 { margin-top: 0; }

    h1 { margin-bottom: 10px; font-size: 1.8rem; }

    h2 {
      padding-bottom: 8px;
      border-bottom: 1px solid var(--line);
      font-size: 1.25rem;
    }

    p:last-child { margin-bottom: 0; }

    .meta, .badges {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }

    .badge {
      display: inline-block;
      padding: 4px 9px;
      border-radius: 999px;
      font-size: 0.84rem;
      font-weight: 650;
    }

    .unknown {
      color: var(--warning-text);
      background: var(--warning-bg);
    }

    .unavailable {
      color: var(--danger-text);
      background: var(--danger-bg);
    }

    .neutral {
      color: var(--neutral-text);
      background: var(--neutral-bg);
    }

    .notice {
      padding: 12px 14px;
      background: var(--warning-bg);
      border-left: 4px solid #d6a300;
      border-radius: 6px;
    }

    .empty {
      color: var(--muted);
      font-style: italic;
    }

    .table-wrap {
      overflow-x: auto;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.93rem;
    }

    th, td {
      padding: 10px;
      border: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
    }

    th {
      background: #f7f9fb;
      white-space: nowrap;
    }

    code {
      padding: 2px 5px;
      background: #eef1f4;
      border-radius: 4px;
    }

    a { color: var(--accent); }

    footer {
      padding: 18px 4px;
      color: var(--muted);
      font-size: 0.9rem;
    }

    @media (max-width: 640px) {
      main {
        width: min(100% - 16px, 1100px);
        margin-top: 8px;
      }

      header, section {
        padding: 16px;
        border-radius: 8px;
      }

      h1 { font-size: 1.45rem; }
    }
  </style>
</head>
<body>
  <main>
    <header>
      <h1>每日美股晨报</h1>
      <div class="badges" aria-label="报告状态">
        <span class="badge unknown">新鲜度：unknown</span>
        <span class="badge unavailable">账户状态：source_unavailable</span>
        <span class="badge neutral">正式覆盖：未验证</span>
      </div>
      <p class="meta">
        <span>插件查询时间：未提供</span>
        <span>报告生成时间：2026-07-22 12:14:23 HKT</span>
      </p>
    </header>

    <section id="summary">
      <h2>1. 一分钟结论</h2>
      <p>
        今日不应据此采取交易行动。IBKR 账户快照、新闻证据及事件日历均未验证，组合权重、现金与集中度无法判断；维持原计划，待刷新插件数据并完成双源取证后复核。
      </p>
    </section>

    <section id="coverage">
      <h2>2. 数据与覆盖</h2>
      <div class="notice">
        本报告按离线约束生成，未调用券商或互联网来源。用户列出的证券仅为临时范围，不属于 IBKR 正式持仓覆盖。
      </div>

      <div class="table-wrap">
        <table>
          <tbody>
            <tr>
              <th>指定正式数据源</th>
              <td>Interactive Brokers (IBKR) plugin（本次未调用）</td>
            </tr>
            <tr>
              <th>插件查询时间</th>
              <td>未提供</td>
            </tr>
            <tr>
              <th>账户状态</th>
              <td><code>source_unavailable</code>（本次离线约束）</td>
            </tr>
            <tr>
              <th>新鲜度</th>
              <td><code>unknown</code></td>
            </tr>
            <tr>
              <th>正式已扫描／总持仓</th>
              <td>未验证／未验证</td>
            </tr>
            <tr>
              <th>缺失组件</th>
              <td>全部未平仓持仓、账户财务指标、分币种余额</td>
            </tr>
            <tr>
              <th>新闻覆盖</th>
              <td>未验证；未执行候选元数据扫描或事件簇深读</td>
            </tr>
            <tr>
              <th>证据缺口</th>
              <td><code>evidence_gap: true</code></td>
            </tr>
            <tr>
              <th>报告生成时间</th>
              <td>2026-07-22 12:14:23 HKT（Asia/Hong_Kong）</td>
            </tr>
          </tbody>
        </table>
      </div>

      <h3>用户提供的临时范围</h3>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>证券</th>
              <th>数量</th>
              <th>市值</th>
              <th>组合权重</th>
              <th>正式持仓状态</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>AAPL</td>
              <td>未提供</td>
              <td>未提供</td>
              <td>未验证</td>
              <td>未通过 IBKR 验证</td>
            </tr>
            <tr>
              <td>MSFT</td>
              <td>未提供</td>
              <td>未提供</td>
              <td>未验证</td>
              <td>未通过 IBKR 验证</td>
            </tr>
            <tr>
              <td>BRK.B</td>
              <td>未提供</td>
              <td>未提供</td>
              <td>未验证</td>
              <td>未通过 IBKR 验证</td>
            </tr>
            <tr>
              <td>短久期美国国债 ETF（代码未提供）</td>
              <td>未提供</td>
              <td>未提供</td>
              <td>未验证</td>
              <td>具体证券及正式持仓均未验证</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section id="market-events">
      <h2>3. 重大市场事件</h2>
      <p class="empty">无已验证项目。</p>
      <p>
        未提供任何候选 URL 或来源；<code>evidence_gap: true</code>，
        验证状态为“不适用”，不得作为动作依据。
      </p>
    </section>

    <section id="technology-events">
      <h2>4. 科技重大事件</h2>
      <p class="empty">无已验证项目。</p>
      <p>
        未对 AAPL、MSFT 或相关科技供应链执行新闻取证；来源与链接均为“未提供”，不得据此推断公司事件。
      </p>
    </section>

    <section id="holding-actions">
      <h2>5. 重点持仓建议</h2>
      <p class="empty">无已验证项目。</p>
      <div class="notice">
        账户状态为 <code>source_unavailable</code>，正式持仓覆盖未验证。依照动作门槛，本报告不得生成持仓建议、条件式加减仓或集中度再平衡动作。
      </div>

      <div class="table-wrap">
        <table>
          <tbody>
            <tr>
              <th>建议动作</th>
              <td>不适用；刷新插件数据后复核</td>
            </tr>
            <tr>
              <th>触发条件</th>
              <td>IBKR 三项固定读取成功，数据为 fresh，并取得达到双源门槛的直接或清晰二阶事件证据</td>
            </tr>
            <tr>
              <th>反证条件</th>
              <td>插件数据仍不可用、数据 stale／unknown，或事件证据存在未解决冲突</td>
            </tr>
            <tr>
              <th>时间范围</th>
              <td>取得有效账户快照及合格证据后</td>
            </tr>
            <tr>
              <th>主要风险</th>
              <td>账户数据、证据、集中度、利率、汇率、税务及执行风险均未验证</td>
            </tr>
            <tr>
              <th>证据状态</th>
              <td>不适用；<code>evidence_gap: true</code></td>
            </tr>
            <tr>
              <th>影响类别</th>
              <td>不适用</td>
            </tr>
            <tr>
              <th>证据链接</th>
              <td>未提供</td>
            </tr>
            <tr>
              <th>判断理由</th>
              <td>缺少唯一正式持仓来源及可追溯英文证据，无法判断证券是否实际持有、仓位大小或事件传导路径。</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section id="no-material-change">
      <h2>6. 无重大变化</h2>
      <p class="empty">无已验证项目。</p>
      <p>
        无法确认任何正式持仓“无重大变化”，因为本次未完成 IBKR 全持仓扫描。AAPL、MSFT、BRK.B 与代码未提供的短久期美国国债 ETF 仅属于临时范围，未计入正式覆盖。
      </p>
      <p>
        <strong>遗漏原因：</strong>全部正式持仓未知；券商连接器未调用，无法枚举、匹配事件或确认遗漏数量。
      </p>
    </section>

    <section id="calendar">
      <h2>7. 事件日历</h2>
      <p class="empty">无已验证项目。</p>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>日期</th>
              <th>事件</th>
              <th>时区</th>
              <th>日期来源</th>
              <th>验证状态</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>未提供</td>
              <td>持仓财报、宏观公布及关键日期均未离线验证</td>
              <td>未提供</td>
              <td>未提供</td>
              <td>不适用；evidence_gap</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section id="evidence-risk">
      <h2>8. 证据与风险</h2>

      <h3>证据审计</h3>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>证据标识</th>
              <th>来源</th>
              <th>canonical_domain</th>
              <th>原始链接</th>
              <th>发布时间</th>
              <th>抓取时间</th>
              <th>验证状态</th>
              <th>冲突／更正</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>EVID-GAP-01</td>
              <td>未提供</td>
              <td>未提供</td>
              <td>未提供</td>
              <td>未提供</td>
              <td>未提供</td>
              <td>不适用；evidence_gap</td>
              <td>未执行取证，无法检查冲突或更正</td>
            </tr>
          </tbody>
        </table>
      </div>

      <h3>账户与组合限制</h3>
      <ul>
        <li>未验证证券数量、市值、平均成本、当日盈亏、未实现盈亏或币种。</li>
        <li>未验证净清算值、现金、可用资金、购买力、保证金或杠杆。</li>
        <li>不得计算组合权重、现金比例、前五大集中度或主题相关性。</li>
        <li>短久期美国国债 ETF 的证券代码、久期、费用及流动性均未提供。</li>
        <li>AAPL、MSFT、BRK.B 的公司事件、财报日期及新闻证据均未验证。</li>
        <li>利率、汇率、税务、财报跳空、流动性及执行风险仍需后续核实。</li>
      </ul>

      <h3>恢复正式分析所需条件</h3>
      <ol>
        <li>只读获取 IBKR 全部未平仓持仓、账户财务指标及分币种余额。</li>
        <li>确认插件查询时间，并确保报告在最后一次固定调用后 15 分钟内生成。</li>
        <li>完整扫描所有非零正式持仓后，再选择最多 6 个重点持仓。</li>
        <li>只使用合格英文白名单来源，并按双源门槛验证可影响仓位的事件。</li>
      </ol>
    </section>

    <footer>
      本报告仅供研究辅助，不构成收益保证或自动交易指令；任何交易由用户确认并在 IBKR 自行执行。
    </footer>
  </main>
</body>
</html>
```
