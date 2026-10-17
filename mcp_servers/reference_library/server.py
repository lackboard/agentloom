"""AgentLoom 演示用只读参考资料 MCP Server。"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

SERVER = FastMCP("agentloom-reference-library")

REFERENCES = (
    {
        "id": "mcp-protocol",
        "title": "Model Context Protocol",
        "topics": ["mcp", "protocol", "tools"],
        "summary": "MCP 用统一协议连接模型应用与外部工具或资料服务；工具仍由宿主应用决定是否暴露和执行。",
        "source": "local://reference-library/mcp-protocol",
    },
    {
        "id": "deerflow-agent-runtime",
        "title": "DeerFlow Agent Runtime",
        "topics": ["deerflow", "agent", "runtime"],
        "summary": "DeerFlow 将模型、工具、中间件和状态组装为 Agent，并为 MCP、子 Agent 和运行生命周期提供工程化管理。",
        "source": "local://reference-library/deerflow-agent-runtime",
    },
    {
        "id": "sqlite-wal",
        "title": "SQLite WAL 与短事务",
        "topics": ["sqlite", "wal", "transaction"],
        "summary": "WAL 改善读写并发，但 SQLite 仍只有一个写者；网络和模型调用不应放在数据库事务内。",
        "source": "local://reference-library/sqlite-wal",
    },
)


@SERVER.tool(description="在受控的本地参考资料中按关键词检索，返回来源明确的简短结果。")
def search_references(query: str, limit: int = 3) -> dict:
    """只读取进程内固定资料，不访问网络或工作区文件。"""
    normalized = query.strip().casefold()
    bounded_limit = min(max(limit, 1), 5)
    matches = []
    for item in REFERENCES:
        haystack = " ".join([item["id"], item["title"], *item["topics"], item["summary"]]).casefold()
        if normalized and normalized not in haystack:
            continue
        matches.append(item)
        if len(matches) >= bounded_limit:
            break
    return {
        "ok": True,
        "query": query,
        "count": len(matches),
        "items": matches,
    }


@SERVER.tool(description="按稳定 ID 读取一条本地参考资料。")
def get_reference(reference_id: str) -> dict:
    for item in REFERENCES:
        if item["id"] == reference_id:
            return {"ok": True, "item": item}
    return {
        "ok": False,
        "error": {
            "code": "REFERENCE_NOT_FOUND",
            "message": f"未找到参考资料：{reference_id}",
        },
    }


if __name__ == "__main__":
    SERVER.run(transport="stdio")
