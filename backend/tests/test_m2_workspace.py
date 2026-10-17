from uuid import uuid4

import pytest

from agentloom.sandbox import FileContentMismatch, PathOutOfScope, WorkspaceError, WorkspaceService


def test_workspace_scopes_paths_and_uses_hash_guarded_replace(tmp_path) -> None:
    workspace = WorkspaceService(tmp_path / "threads")
    first_thread = str(uuid4())
    second_thread = str(uuid4())
    path = "/mnt/user-data/workspace/nested/note.txt"

    created = workspace.write_text(first_thread, path, "第一版")
    assert workspace.read_text(first_thread, path) == created
    assert workspace.list_dir(first_thread, "/mnt/user-data/workspace/nested") == [
        {"name": "note.txt", "type": "file", "size_bytes": len("第一版".encode())}
    ]

    # 相同虚拟路径按 thread_id 解析；第二个线程不能读到第一个线程的文件。
    with pytest.raises(WorkspaceError, match="文件不存在"):
        workspace.read_text(second_thread, path)

    for escaped in (
        "/mnt/user-data/workspace/../uploads/secret.txt",
        "/mnt/user-data/workspace//secret.txt",
        "C:/Windows/System32/drivers/etc/hosts",
        "/etc/passwd",
    ):
        with pytest.raises(PathOutOfScope):
            workspace.read_text(first_thread, escaped)

    with pytest.raises(FileContentMismatch, match="旧前置条件失效"):
        workspace.replace_text(first_thread, path, old="第一版", new="第二版", expected_sha256="0" * 64)

    replaced = workspace.replace_text(
        first_thread,
        path,
        old="第一版",
        new="第二版",
        expected_sha256=created.sha256,
    )
    assert replaced.content == "第二版"


def test_workspace_rejects_symlink_escape_when_platform_supports_it(tmp_path) -> None:
    workspace = WorkspaceService(tmp_path / "threads")
    thread_id = str(uuid4())
    outside = tmp_path / "outside.txt"
    outside.write_text("不能泄漏", encoding="utf-8")
    link = workspace.ensure_thread(thread_id) / "workspace" / "escape.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("当前 Windows 权限不允许创建符号链接")

    with pytest.raises(PathOutOfScope, match="符号链接"):
        workspace.read_text(thread_id, "/mnt/user-data/workspace/escape.txt")
