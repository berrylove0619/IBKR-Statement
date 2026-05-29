"""
run_trace 摘要构建器。

将完整的 Agent 运行轨迹转换为可展示的摘要，不返回完整 observation。
Handles both ToolCallingRuntime traces (tool_start/tool_finish events) and
LangGraph node traces (node_success/node_completed with tools_called arrays).
"""

from typing import Any


def build_run_trace_summary(run_trace: list[dict]) -> dict:
    """
    将完整 run_trace 转换为可展示的摘要。

    Args:
        run_trace: Agent 运行轨迹列表

    Returns:
        可读摘要字典，不包含完整 observation 内容
    """
    if not run_trace:
        return {
            "tool_call_count": 0,
            "tool_success_count": 0,
            "tool_error_count": 0,
            "llm_rounds": 0,
            "truncated_observations": 0,
            "tools": [],
            "llm_started": None,
            "llm_finished": None,
        }

    tool_calls = 0
    tool_success = 0
    tool_error = 0
    truncated_obs = 0
    llm_rounds = 0
    llm_started = None
    llm_finished = None
    tool_summaries = []
    # Track unique MCP tools from node traces to avoid double-counting
    node_mcp_tools: dict[str, dict] = {}  # node_name -> tool metadata

    for event in run_trace:
        evt = event.get("event", "")

        # ToolCallingRuntime events
        if evt == "llm_start":
            llm_rounds += 1
            if llm_started is None:
                llm_started = event.get("created_at_ms")

        if evt == "llm_finish":
            llm_finished = event.get("created_at_ms")

        if evt == "tool_start":
            tool_calls += 1

        if evt == "tool_finish":
            ok = event.get("ok", False)
            if ok:
                tool_success += 1
            else:
                tool_error += 1

            obs = event.get("observation") or {}
            if obs.get("truncated"):
                truncated_obs += 1

            tool_summaries.append({
                "tool": event.get("tool", ""),
                "ok": ok,
                "summary": event.get("summary", ""),
                "truncated": obs.get("truncated", False),
                "original_size": obs.get("original_size"),
                "final_size": obs.get("final_size"),
            })

        if evt == "tool_error":
            tool_calls += 1
            tool_error += 1
            tool_summaries.append({
                "tool": event.get("tool", ""),
                "ok": False,
                "summary": event.get("summary", ""),
                "truncated": False,
                "original_size": None,
                "final_size": None,
            })

        # LangGraph node trace events — extract MCP tool calls
        if evt in ("node_success", "node_completed", "node_fallback", "node_failed"):
            node_name = event.get("node_name", "")
            tools_called = event.get("tools_called") or []
            if tools_called:
                node_mcp_tools[node_name] = {
                    "tools_called": tools_called,
                    "tool_call_count": event.get("tool_call_count"),
                    "tool_calls": event.get("tool_calls") or [],
                }

    # Count MCP tools from LangGraph node traces.
    # Each node's tools_called lists the tools that node used.
    # We count each unique (node, tool) pair as one tool call.
    for node_name, info in node_mcp_tools.items():
        tools = info.get("tools_called") or []
        records = info.get("tool_calls") or []
        counted_records = records if records else [{"tool_name": tool_name, "success": True} for tool_name in tools]
        if not records and info.get("tool_call_count") and info.get("tool_call_count") > len(tools):
            counted_records.extend(
                {"tool_name": "unknown_mcp_tool", "success": True}
                for _ in range(int(info.get("tool_call_count")) - len(tools))
            )
        for record in counted_records:
            tool_name = record.get("tool_name") or record.get("tool") or "unknown_mcp_tool"
            tool_calls += 1
            ok = record.get("success", True)
            if ok:
                tool_success += 1
            else:
                tool_error += 1
            tool_summaries.append({
                "tool": tool_name,
                "ok": ok,
                "summary": f"called by {node_name}",
                "truncated": False,
                "original_size": None,
                "final_size": None,
            })

    return {
        "tool_call_count": tool_calls,
        "tool_success_count": tool_success,
        "tool_error_count": tool_error,
        "llm_rounds": llm_rounds,
        "truncated_observations": truncated_obs,
        "tools": tool_summaries,
        "llm_started": llm_started,
        "llm_finished": llm_finished,
    }
