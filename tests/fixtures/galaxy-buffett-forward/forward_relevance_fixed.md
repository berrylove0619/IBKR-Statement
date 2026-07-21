# forward_relevance_fixed

## Prompt

先完整阅读并严格使用 `<PROJECT_ROOT>/skills/galaxy-buffett-daily-stock-analysis/SKILL.md` 及其中按要求读取的 references。不要使用任何其他投资 Skill。不要浏览网络、不要修改文件。

场景：用户只持有 AAPL、MSFT、BRK.B 和短债 ETF；候选信息中有多条 AI 芯片、数据中心、光通信、亚洲供应链新闻，还有一项宏观利率事件。用户要求知道哪些真正影响当前持仓，以及今天应该做什么。请给出一份简短晨报草案。

## Output

未保存文件；以下为符合约定格式的晨报 HTML 草案：

```html
<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>持倉晨報草案｜2026-07-21</title>
  <style>
    body { max-width: 980px; margin: 0 auto; padding: 24px; font: 15px/1.65 -apple-system, BlinkMacSystemFont, "PingFang TC", sans-serif; color:#172033; background:#f7f9fc; }
    h1,h2,h3 { line-height:1.25; } section, .card { background:#fff; border:1px solid #dce3ed; border-radius:10px; padding:18px; margin:14px 0; }
    .badge { display:inline-block; padding:3px 9px; border-radius:999px; background:#fff0c2; color:#765400; font-weight:700; }
    .warn { border-left:4px solid #d18a00; padding-left:12px; }
    table { width:100%; border-collapse:collapse; } th,td { padding:8px; text-align:left; border-bottom:1px solid #e6ebf2; vertical-align:top; }
    code { background:#eef2f7; padding:1px 4px; border-radius:4px; } .muted { color:#5b6678; }
  </style>
</head>
<body>
  <header>
    <h1>持倉晨報草案</h1>
    <p><span class="badge">unknown｜持倉新鮮度未知</span></p>
    <p class="warn">未找到最新成功的 IBKR 匯入快照；AAPL、MSFT、BRK.B 與短債 ETF 僅為用戶提供的臨時範圍。候選新聞未附正文或合格英文來源連結，不能支持交易動作。</p>
  </header>

  <section>
    <h2>1. 一分鐘結論</h2>
    <p>今天沒有可驗證的新證據要求調整持倉，維持原計畫。AI 供應鏈新聞僅在明確指向 Microsoft 雲端資本開支或 Apple 已披露供應商時才具二階意義；利率事件主要是組合共同因子。先刷新 IBKR 持倉並補齊來源，再復核。</p>
  </section>

  <section>
    <h2>2. 數據與覆蓋</h2>
    <table>
      <tr><th>最新成功匯入時間</th><td>未提供／未驗證</td></tr>
      <tr><th>持倉截至時間／數據年齡</th><td>未提供／新鮮度未知</td></tr>
      <tr><th>帳戶幣種／源文件</th><td>未提供</td></tr>
      <tr><th>正式覆蓋</th><td>未驗證（不可填寫 <code>scanned_holdings / total_holdings</code>）</td></tr>
      <tr><th>用戶提供的臨時範圍</th><td>4 項：AAPL、MSFT、BRK.B、短債 ETF（代碼未提供）</td></tr>
      <tr><th>遺漏項</th><td>正式 IBKR 全部非零持倉、數量、市值、成本及權重均未提供</td></tr>
      <tr><th>報告生成時間</th><td>2026-07-21（Asia/Hong_Kong）</td></tr>
    </table>
  </section>

  <section>
    <h2>3. 重大市場事件</h2>
    <article class="card" id="event-rate">
      <h3>候選：宏觀利率事件</h3>
      <p>發生時間：未提供｜驗證狀態：不適用｜<code>evidence_gap: true</code></p>
      <p>來源／連結：未提供。事實內容、數值、決策機構及時間均未提供，不能判定是已發生衝擊、預期變化或市場雜訊。</p>
      <p>組合關聯：宏觀共同因子。利率變化可共同影響 AAPL、MSFT 的估值折現率、BRK.B 的投資收益及短債 ETF 的收益率／價格，但不構成個股交易依據。</p>
    </article>
  </section>

  <section>
    <h2>4. 科技重大事件</h2>
    <article class="card" id="event-ai-chip">
      <h3>候選：AI 晶片新聞</h3>
      <p>發生時間：未提供｜驗證狀態：不適用｜<code>evidence_gap: true</code></p>
      <p>來源／連結：未提供。可能與 MSFT 的雲端 AI 資本開支有關，但未提供已命名供應商、客戶、訂單或 Microsoft 收入暴露，屬無實質關聯。</p>
    </article>
    <article class="card" id="event-datacenter">
      <h3>候選：數據中心新聞</h3>
      <p>發生時間：未提供｜驗證狀態：不適用｜<code>evidence_gap: true</code></p>
      <p>來源／連結：未提供。只有在事件→Microsoft→已確認資本開支／雲端收入的鏈條成立時，才可能成為 MSFT 的二階事件；目前僅觀察。</p>
    </article>
    <article class="card" id="event-optical">
      <h3>候選：光通信新聞</h3>
      <p>發生時間：未提供｜驗證狀態：不適用｜<code>evidence_gap: true</code></p>
      <p>來源／連結：未提供。光通信主題與現有四項臨時範圍沒有已驗證的直接收入、成本或供應關係，屬無實質關聯。</p>
    </article>
    <article class="card" id="event-asia-supply">
      <h3>候選：亞洲供應鏈新聞</h3>
      <p>發生時間：未提供｜驗證狀態：不適用｜<code>evidence_gap: true</code></p>
      <p>來源／連結：未提供。AAPL 可能存在二階供應鏈暴露，但缺少具名供應商、產能／交期變化及 Apple 收入或成本傳導證據；不能據此調整 AAPL。</p>
    </article>
  </section>

  <section>
    <h2>5. 重點持倉建議</h2>
    <article class="card">
      <h3>AAPL｜Apple Inc.</h3>
      <table>
        <tr><th>數量／市值／權重</th><td>未提供／未提供／未提供</td></tr>
        <tr><th>影響類別</th><td>無實質關聯（亞洲供應鏈候選事件的傳導鏈未證實）</td></tr>
        <tr><th>建議動作</th><td>觀察／刷新數據後復核；維持原計畫</td></tr>
        <tr><th>觸發條件</th><td>公司官方披露加上獨立白名單媒體確認，證實具名供應鏈事件已改變 Apple 的供應、成本或出貨。</td></tr>
        <tr><th>反證條件</th><td>Apple 或供應商披露庫存、交期、成本與出貨未受影響。</td></tr>
        <tr><th>時間範圍／主要風險</th><td>至下次正式披露；供應鏈、估值及證據不足風險。</td></tr>
        <tr><th>證據狀態／連結</th><td>不適用；未提供</td></tr>
        <tr><th>判斷理由</th><td>主題相關不等於持倉相關；目前不能閉合事件→供應商→Apple 成本／收入的證據鏈。</td></tr>
      </table>
    </article>
    <article class="card">
      <h3>MSFT｜Microsoft Corporation</h3>
      <table>
        <tr><th>數量／市值／權重</th><td>未提供／未提供／未提供</td></tr>
        <tr><th>影響類別</th><td>無實質關聯（AI 晶片、數據中心候選事件未證實傳導）</td></tr>
        <tr><th>建議動作</th><td>觀察／刷新數據後復核；維持原計畫</td></tr>
        <tr><th>觸發條件</th><td>MSFT 官方材料及獨立媒體共同確認，事件明確改變 Azure 需求、資本開支、供應能力或利潤率。</td></tr>
        <tr><th>反證條件</th><td>Microsoft 指引、已確認供應與雲端需求未出現實質變化。</td></tr>
        <tr><th>時間範圍／主要風險</th><td>至下次財報或資本開支披露；AI 資本開支、估值及證據不足風險。</td></tr>
        <tr><th>證據狀態／連結</th><td>不適用；未提供</td></tr>
        <tr><th>判斷理由</th><td>AI 與數據中心是潛在二階暴露，但沒有已命名交易對手與可驗證收入／成本傳導。</td></tr>
      </table>
    </article>
    <article class="card">
      <h3>BRK.B｜Berkshire Hathaway Inc. Class B</h3>
      <table>
        <tr><th>數量／市值／權重</th><td>未提供／未提供／未提供</td></tr>
        <tr><th>影響類別</th><td>宏觀共同因子（候選利率事件）</td></tr>
        <tr><th>建議動作</th><td>觀察／刷新數據後復核；維持原計畫</td></tr>
        <tr><th>觸發條件</th><td>利率事件的事實、幅度及 Berkshire 對投資收益、保險承保或估值的傳導得到合格來源驗證。</td></tr>
        <tr><th>反證條件</th><td>利率變化不具持續性，或公司披露顯示相關經營／投資影響不重大。</td></tr>
        <tr><th>時間範圍／主要風險</th><td>數日到下次財報；利率路徑、保險損失及集中度風險。</td></tr>
        <tr><th>證據狀態／連結</th><td>不適用；未提供</td></tr>
        <tr><th>判斷理由</th><td>利率是組合層面的共同因子，候選事件沒有公司特定新事實，不能單獨觸發 BRK.B 動作。</td></tr>
      </table>
    </article>
    <article class="card">
      <h3>短債 ETF｜代碼未提供</h3>
      <table>
        <tr><th>數量／市值／權重</th><td>未提供／未提供／未提供</td></tr>
        <tr><th>影響類別</th><td>宏觀共同因子（候選利率事件）</td></tr>
        <tr><th>建議動作</th><td>觀察／刷新數據後復核；維持原計畫</td></tr>
        <tr><th>觸發條件</th><td>確認 ETF 代碼、久期、分配政策及已驗證的利率事件後，再評估現金管理配置。</td></tr>
        <tr><th>反證條件</th><td>事件未改變短端利率預期，或 ETF 實際久期與假設不符。</td></tr>
        <tr><th>時間範圍／主要風險</th><td>盤前至數日；久期、再投資、流動性及稅務風險。</td></tr>
        <tr><th>證據狀態／連結</th><td>不適用；未提供</td></tr>
        <tr><th>判斷理由</th><td>短債 ETF 對利率的敏感度取決於未提供的具體基金與久期；不能以「短債」名稱代替分析。</td></tr>
      </table>
    </article>
  </section>

  <section>
    <h2>6. 無重大變化</h2>
    <p>臨時範圍內沒有其餘項目。AI 晶片、數據中心、光通信與亞洲供應鏈候選資訊均未建立可驗證的持倉傳導鏈；不應因主題熱度交易。</p>
  </section>
  <section>
    <h2>7. 事件日曆</h2>
    <table><tr><th>事件</th><th>日期／時區</th><th>日期來源</th></tr><tr><td>AAPL、MSFT、BRK.B 財報與宏觀公布</td><td>未提供</td><td>未提供；本草案未取得官方日曆或合格來源</td></tr></table>
  </section>
  <section>
    <h2>8. 證據與風險</h2>
    <table><tr><th>結論</th><th>來源／規範域名／連結</th><th>發布／抓取時間</th><th>驗證狀態／衝突</th></tr><tr><td>利率候選事件</td><td>未提供</td><td>未提供</td><td>不適用；evidence_gap</td></tr><tr><td>四類科技候選事件</td><td>未提供</td><td>未提供</td><td>不適用；evidence_gap</td></tr></table>
    <p class="muted">限制：沒有成功 IBKR 匯入、實際權重、ETF 代碼、候選新聞正文或白名單英文證據。組合仍可能有集中度、科技相關性、利率、財報跳空、流動性、匯率與稅務風險。</p>
    <p><strong>本報告僅供研究輔助，不構成收益保證或自動交易指令；任何交易由用戶確認並在 IBKR 自行執行。</strong></p>
  </section>
</body>
</html>
```
