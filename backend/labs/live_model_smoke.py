"""由 config.yaml/.env 显式驱动的真实模型工具、usage 与流式检查。"""

import asyncio
import sys

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage

from agentloom.agents.factory import create_loom_agent
from agentloom.config import ConfigurationError, load_config


def _usage(messages) -> tuple[int, int, int]:
    attempts = 0
    input_tokens = 0
    output_tokens = 0
    for message in messages:
        if not isinstance(message, AIMessage):
            continue
        usage = message.usage_metadata
        if usage:
            attempts += 1
            input_tokens += int(usage.get("input_tokens", 0))
            output_tokens += int(usage.get("output_tokens", 0))
    return attempts, input_tokens, output_tokens


async def _run_live() -> tuple[dict, int, int]:
    agent = create_loom_agent()
    final_state = None
    model_stream_items = 0
    incremental_chunks = 0
    async for mode, payload in agent.astream(
        {"messages": [HumanMessage(content="请使用 add 工具计算 2 + 3。")]},
        stream_mode=["messages", "values"],
    ):
        if mode == "values":
            final_state = payload
            continue
        message, _metadata = payload
        if isinstance(message, AIMessage | AIMessageChunk):
            model_stream_items += 1
        if isinstance(message, AIMessageChunk):
            incremental_chunks += 1
    if final_state is None:
        raise RuntimeError("Agent 流结束但没有最终 State")
    return final_state, model_stream_items, incremental_chunks


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    config = load_config()
    selected = config.models.default
    print(f"provider: {selected.provider}")
    print(f"model: {selected.model}")
    if selected.provider == "fake":
        print("LIVE: NOT_RUN（config.yaml 的 provider 仍是 fake）")
        return 2
    try:
        result, model_stream_items, incremental_chunks = asyncio.run(_run_live())
    except ConfigurationError as exc:
        print(f"LIVE: NOT_RUN（{exc}）")
        return 2
    except Exception as exc:
        print(f"LIVE: FAIL（{type(exc).__name__}: {exc}）")
        return 1

    tool_results = [message for message in result["messages"] if isinstance(message, ToolMessage)]
    if len(tool_results) != 1 or tool_results[0].name != "add" or tool_results[0].content != "5":
        print(f"LIVE: FAIL（工具轨迹不符合预期：{tool_results}）")
        return 1
    print(f"tool: name={tool_results[0].name} result={tool_results[0].content}")
    print(f"answer: {result['messages'][-1].content}")
    attempts, input_tokens, output_tokens = _usage(result["messages"])
    if attempts:
        print(f"usage: available attempts={attempts} input_tokens={input_tokens} output_tokens={output_tokens}")
    else:
        print("usage: provider limitation（最终消息未报告 token usage）")
    if incremental_chunks:
        print(f"stream: available model_items={model_stream_items} incremental_chunks={incremental_chunks}")
    elif model_stream_items:
        print(f"stream: graph messages available；provider returned complete messages ({model_stream_items} items)")
    else:
        print("stream: provider limitation（没有模型消息流条目）")
    print("LIVE: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
