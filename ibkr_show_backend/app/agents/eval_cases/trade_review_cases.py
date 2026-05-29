from app.agents.eval_harness import EvalCase


CASES = [
    EvalCase(
        case_id="trade_review_buy_only_open_position_not_zero",
        agent_name="trade_review",
        title="BUY-only 未平仓交易不能因无 SELL 归零",
        tags=["buy_only", "open_position"],
        input={"review_type": "single_trade_review", "trade_id": "sample-buy-only"},
        expected_behavior={"data_missing": False},
        expected_output_fields=["summary", "overall_score", "rating", "data_limitations"],
    ),
    EvalCase(
        case_id="trade_review_profit_but_chase_high_not_excellent",
        agent_name="trade_review",
        title="盈利但追高不能只因赚钱评 excellent",
        tags=["chase_high", "scoring"],
        input={"symbol": "NVDA.US"},
        expected_output_fields=["summary", "overall_score", "rating", "mistake_tags"],
        forbidden_behavior=["赚钱就是好交易"],
    ),
    EvalCase(
        case_id="trade_review_loss_but_disciplined_not_poor",
        agent_name="trade_review",
        title="亏损但纪律正确不能只因亏损评 poor",
        tags=["loss", "discipline"],
        input={"symbol": "AMD.US"},
        expected_output_fields=["summary", "overall_score", "rating", "data_limitations"],
    ),
    EvalCase(
        case_id="trade_review_sold_too_early_avoid_hindsight",
        agent_name="trade_review",
        title="卖飞可以指出机会成本但避免后视镜",
        tags=["opportunity_cost", "hindsight"],
        input={"symbol": "TSLA.US"},
        expected_output_fields=["summary", "mistake_tags", "data_limitations"],
        forbidden_behavior=["完全否定当时卖出"],
    ),
]
