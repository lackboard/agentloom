"""单用户、单进程版本的线程工作目录服务。"""

import hashlib
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from uuid import UUID, uuid4

VIRTUAL_ROOT = PurePosixPath("/mnt/user-data")
VISIBLE_NAMESPACES = {"workspace", "uploads", "outputs", "tool-results"}
WRITABLE_NAMESPACES = {"workspace", "outputs"}
SNAPSHOT_NAMESPACES = {"artifacts", "uploads"}
DEFAULT_MAX_FILE_BYTES = 1024 * 1024
MAX_TOOL_RESULT_BYTES = 10 * 1024 * 1024
DEFAULT_MAX_LIST_ENTRIES = 500
INVALID_WINDOWS_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


class WorkspaceError(RuntimeError):
    """带稳定错误码的工作目录错误。"""

    code = "WORKSPACE_ERROR"


class PathOutOfScope(WorkspaceError):
    code = "PATH_OUT_OF_SCOPE"


class WorkspaceFileNotFound(WorkspaceError):
    code = "FILE_NOT_FOUND"


class FileAlreadyExists(WorkspaceError):
    code = "FILE_ALREADY_EXISTS"


class FileTooLarge(WorkspaceError):
    code = "FILE_TOO_LARGE"


class FileContentMismatch(WorkspaceError):
    code = "FILE_CONTENT_MISMATCH"


class BinaryFileRejected(WorkspaceError):
    code = "BINARY_FILE_REJECTED"


@dataclass(frozen=True)
class WorkspaceFile:
    """读取或写入后可公开给工具的文件事实。"""

    virtual_path: str
    content: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class StableFile:
    """产物快照前读取到的稳定字节和元数据。"""

    virtual_path: str
    name: str
    content: bytes
    sha256: str
    size_bytes: int


class WorkspaceService:
    """把虚拟路径限制在线程自己的 workspace/uploads/outputs 中。"""

    def __init__(
        self,
        root: Path,
        *,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
        max_list_entries: int = DEFAULT_MAX_LIST_ENTRIES,
    ) -> None:
        self.root = root.resolve()
        self.max_file_bytes = max_file_bytes
        self.max_list_entries = max_list_entries
        # 同一进程内把普通写入、替换和多文件接纳放进同一临界区。
        self._mutation_lock = threading.RLock()
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _thread_key(thread_id: str) -> str:
        try:
            return str(UUID(thread_id))
        except ValueError as exc:
            raise PathOutOfScope("无效的线程 ID") from exc

    def thread_root(self, thread_id: str) -> Path:
        return self.root / self._thread_key(thread_id)

    def ensure_thread(self, thread_id: str) -> Path:
        thread_root = self.thread_root(thread_id)
        for name in (*sorted(VISIBLE_NAMESPACES), "artifacts"):
            (thread_root / name).mkdir(parents=True, exist_ok=True)
        return thread_root

    # 判断单个路径是不是链接/junction
    @staticmethod
    def _is_link_or_junction(path: Path) -> bool:
        # 判断是不是符号链接。
        if path.is_symlink():
            return True
        # Junction 是 Windows 特有的目录链接（mklink /J），类似 symlink 但机制不同。
        is_junction = getattr(path, "is_junction", None)
        return bool(is_junction and is_junction())

    # _reject_link_components 先把目标限制在 root 之下，
    # 再逐段检查路径中是否有链接，一旦发现就抛 PathOutOfScope，防止通过链接绕过工作目录限制。
    def _reject_link_components(self, root: Path, target: Path) -> None:
        current = root
        try:
            # 求 target 相对于 root 的路径。
            parts = target.relative_to(root).parts
        except ValueError as exc:
            raise PathOutOfScope("路径超出当前线程工作目录") from exc
        for part in parts:
            current /= part
            if current.exists() and self._is_link_or_junction(current):
                raise PathOutOfScope("不允许通过符号链接或 junction 访问文件")

    @staticmethod
    def _virtual_parts(path: str) -> tuple[str, tuple[str, ...]]:
        if not isinstance(path, str) or not path or "\x00" in path or "\\" in path:
            raise PathOutOfScope("文件工具只接受规范的 POSIX 虚拟路径")
        prefix = f"{VIRTUAL_ROOT.as_posix()}/"
        if not path.startswith(prefix):
            raise PathOutOfScope(f"路径必须位于 {VIRTUAL_ROOT.as_posix()}/ 下")
        # 去掉前缀，得到相对部分
        raw_parts = path[len(prefix) :].split("/")
        if not raw_parts or raw_parts[0] not in VISIBLE_NAMESPACES:
            raise PathOutOfScope("路径必须位于 workspace、uploads、outputs 或 tool-results 中")
        if any(part in {"", ".", ".."} for part in raw_parts):
            raise PathOutOfScope("路径包含空段、. 或 ..")

        for part in raw_parts[1:]:
            stem = part.split(".", 1)[0].upper()
            if INVALID_WINDOWS_CHARS.search(part) or part.endswith((".", " ")) or stem in WINDOWS_RESERVED_NAMES:
                raise PathOutOfScope(f"路径段在当前平台不安全：{part}")
        return raw_parts[0], tuple(raw_parts[1:])

    # 把用户传入的虚拟路径，经过多重校验后，映射成真实文件系统上的绝对路径。
    def _resolve_virtual(
        self,
        thread_id: str,
        virtual_path: str,
        *,
        writable: bool = False,
        must_exist: bool = True,
    ) -> tuple[str, Path]:
        namespace, relative = self._virtual_parts(virtual_path)
        if writable and namespace not in WRITABLE_NAMESPACES:
            raise PathOutOfScope("uploads 和 tool-results 是只读目录，文件只能写入 workspace 或 outputs")
        thread_root = self.ensure_thread(thread_id)
        namespace_root = (thread_root / namespace).resolve(strict=True)
        lexical = namespace_root.joinpath(*relative)
        self._reject_link_components(namespace_root, lexical)
        try:
            resolved = lexical.resolve(strict=must_exist)
            resolved.relative_to(namespace_root)
        except (FileNotFoundError, ValueError) as exc:
            if isinstance(exc, FileNotFoundError):
                raise WorkspaceFileNotFound(f"文件不存在：{virtual_path}") from exc
            raise PathOutOfScope("解析后的路径超出当前线程目录") from exc
        return namespace, resolved

    # 把虚拟路径解析成真实目录，然后安全地列出里面的条目，跳过链接、限制数量、排序稳定。
    def list_dir(self, thread_id: str, virtual_path: str) -> list[dict]:
        _, directory = self._resolve_virtual(thread_id, virtual_path)
        if not directory.is_dir():
            raise WorkspaceFileNotFound(f"不是目录：{virtual_path}")
        entries = []
        for child in sorted(directory.iterdir(), key=lambda item: item.name.casefold()):
            if self._is_link_or_junction(child):
                continue
            kind = "directory" if child.is_dir() else "file"
            entries.append(
                {
                    "name": child.name,
                    "type": kind,
                    "size_bytes": child.stat().st_size if kind == "file" else None,
                }
            )
            if len(entries) >= self.max_list_entries:
                break
        return entries

    def _read_stable_bytes(self, path: Path, public_path: str, *, max_bytes: int | None = None) -> bytes:
        if not path.is_file():
            raise WorkspaceFileNotFound(f"不是普通文件：{public_path}")
        limit = self.max_file_bytes if max_bytes is None else max_bytes
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            if before.st_size > limit:
                raise FileTooLarge(f"文件超过 {limit} 字节限制：{public_path}")
            content = handle.read(limit + 1)
            after = os.fstat(handle.fileno())
        if len(content) > limit:
            raise FileTooLarge(f"文件超过 {limit} 字节限制：{public_path}")
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise FileContentMismatch(f"读取期间文件发生变化：{public_path}")
        return content

    def read_text(self, thread_id: str, virtual_path: str) -> WorkspaceFile:
        namespace, path = self._resolve_virtual(thread_id, virtual_path)
        limit = MAX_TOOL_RESULT_BYTES if namespace == "tool-results" else self.max_file_bytes
        content = self._read_stable_bytes(path, virtual_path, max_bytes=limit)
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise BinaryFileRejected(f"只支持读取 UTF-8 文本：{virtual_path}") from exc
        return WorkspaceFile(
            virtual_path=virtual_path,
            content=text,
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
        )

    def store_tool_result(self, thread_id: str, run_id: str, tool_call_id: str, content: str) -> WorkspaceFile:
        """把完整工具文本写入服务端控制的只读目录；相同内容可幂等复用。"""
        try:
            run_key = str(UUID(run_id))
        except ValueError as exc:
            raise PathOutOfScope("无效的 Run ID") from exc
        encoded = content.encode("utf-8")
        if len(encoded) > MAX_TOOL_RESULT_BYTES:
            raise FileTooLarge(f"工具结果超过 {MAX_TOOL_RESULT_BYTES} 字节限制")
        call_key = hashlib.sha256(tool_call_id.encode("utf-8")).hexdigest()[:20]
        digest = hashlib.sha256(encoded).hexdigest()
        filename = f"{call_key}-{digest[:20]}.txt"
        virtual_path = f"{VIRTUAL_ROOT.as_posix()}/tool-results/{run_key}/{filename}"
        _, target = self._resolve_virtual(thread_id, virtual_path, must_exist=False)
        try:
            self._write_new_bytes(target, encoded)
        except FileAlreadyExists:
            existing = self._read_stable_bytes(target, virtual_path, max_bytes=MAX_TOOL_RESULT_BYTES)
            if existing != encoded:
                raise FileContentMismatch("同一工具结果引用对应了不同内容") from None
        return WorkspaceFile(
            virtual_path=virtual_path,
            content=content,
            sha256=digest,
            size_bytes=len(encoded),
        )

    def validate_evidence_path(self, virtual_path: str) -> None:
        """验证待生成文件的虚拟路径；文件此时可以尚不存在。"""
        namespace, _parts = self._virtual_parts(virtual_path)
        if namespace not in WRITABLE_NAMESPACES:
            raise PathOutOfScope("执行证据只能位于 workspace 或 outputs")

    def inspect_file(self, thread_id: str, virtual_path: str) -> StableFile:
        """读取任意受控普通文件的稳定字节事实，供故障后的证据核验使用。"""
        _, path = self._resolve_virtual(thread_id, virtual_path)
        content = self._read_stable_bytes(path, virtual_path)
        return StableFile(
            virtual_path=virtual_path,
            name=path.name,
            content=content,
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
        )

    # 原子地写入一个新文件
    @staticmethod
    def _write_new_bytes(target: Path, content: bytes) -> None:
        # 确保父目录存在（parents=True 递归创建，exist_ok=True 已存在不报错）
        target.parent.mkdir(parents=True, exist_ok=True)

        # 临时名不重复目标文件名，避免 Windows 上因路径过长而创建失败。
        # 放在同目录是为了后面 os.link 能在同一文件系统内完成（跨设备会失败）。
        temporary = target.parent / f".tmp-{uuid4().hex}"

        try:
            # "xb" = 独占创建 + 二进制写入：文件已存在则抛 FileExistsError
            with temporary.open("xb") as handle:
                handle.write(content)
                handle.flush()  # 把 Python 缓冲刷到 OS
                os.fsync(handle.fileno())  # 把 OS 缓冲刷到磁盘，保证落盘

            # 用硬链接把临时文件“发布”为目标文件
            # 关键：如果 target 已存在，os.link 抛 FileExistsError，
            # 从而保证“只创建新文件、绝不覆盖已有文件”的语义
            os.link(temporary, target)

        except FileExistsError as exc:
            # 目标已存在：拒绝覆盖，交给后续审批单元处理
            raise FileAlreadyExists(f"文件已存在：{target.name}；覆盖需要后续审批单元") from exc

        finally:
            # 无论成功失败，都清理临时文件（missing_ok=True 避免二次报错）
            # 成功时：target 已通过硬链接指向同一 inode，删除临时名不影响内容
            # 失败时：清理残留
            temporary.unlink(missing_ok=True)

    # 写入新文本文件
    def write_text(self, thread_id: str, virtual_path: str, content: str) -> WorkspaceFile:
        # 统一按 UTF-8 编码，后续大小、hash 都基于编码后的字节
        encoded = content.encode("utf-8")

        # 大小限制：防止写入超大文件耗尽磁盘/内存
        if len(encoded) > self.max_file_bytes:
            raise FileTooLarge(f"写入内容超过 {self.max_file_bytes} 字节限制")

        # 解析虚拟路径：
        #   writable=True  → 检查是否在可写命名空间（非 uploads）
        #   must_exist=False → 允许目标不存在（新建文件场景）
        _, target = self._resolve_virtual(thread_id, virtual_path, writable=True, must_exist=False)

        # 再对父目录到目标做一次链接检查：
        # 因为 must_exist=False 时目标本身可能不存在，_resolve_virtual 里的
        # 链接检查主要覆盖已存在部分；这里显式再查一遍父路径，防止父目录是链接
        self._reject_link_components(target.parent, target)

        # 原子写入新文件（不覆盖已有文件）
        with self._mutation_lock:
            self._write_new_bytes(target, encoded)

        # 返回写入结果描述：虚拟路径、内容、sha256、字节数
        return WorkspaceFile(
            virtual_path=virtual_path,
            content=content,
            sha256=hashlib.sha256(encoded).hexdigest(),
            size_bytes=len(encoded),
        )

    # 带内容 hash 前置条件的文本替换
    def replace_text(
        self,
        thread_id: str,
        virtual_path: str,
        *,
        old: str,
        new: str,
        expected_sha256: str,
    ) -> WorkspaceFile:
        """执行带内容 hash 的底层替换；M2.4 再由审批层调用。"""
        with self._mutation_lock:
            _, target = self._resolve_virtual(thread_id, virtual_path, writable=True)
            current = self.read_text(thread_id, virtual_path)
            if current.sha256 != expected_sha256:
                raise FileContentMismatch("文件内容已变化，旧前置条件失效")
            if current.content.count(old) != 1:
                raise FileContentMismatch("旧文本必须且只能出现一次")
            encoded = current.content.replace(old, new, 1).encode("utf-8")
            if len(encoded) > self.max_file_bytes:
                raise FileTooLarge(f"替换结果超过 {self.max_file_bytes} 字节限制")
            temporary = target.parent / f".{target.name}.{uuid4().hex}.tmp"
            try:
                with temporary.open("xb") as handle:
                    handle.write(encoded)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        return WorkspaceFile(
            virtual_path=virtual_path,
            content=encoded.decode("utf-8"),
            sha256=hashlib.sha256(encoded).hexdigest(),
            size_bytes=len(encoded),
        )

    def apply_file_set(self, thread_id: str, changes: list[dict]) -> list[WorkspaceFile]:
        """按旧 hash 接纳一组文件；任一发布失败时恢复本次已发布文件。"""
        prepared: list[tuple[str, Path, bytes, str | None, bytes | None]] = []
        with self._mutation_lock:
            for change in changes:
                virtual_path = str(change["path"])
                content = bytes(change["content"])
                expected = change.get("base_sha256")
                namespace, target = self._resolve_virtual(thread_id, virtual_path, writable=True, must_exist=False)
                if namespace != "workspace":
                    raise PathOutOfScope("Coder 变更只能接纳到父 workspace")
                old_content = None
                if target.exists():
                    old_content = self._read_stable_bytes(target, virtual_path)
                    current_hash = hashlib.sha256(old_content).hexdigest()
                    if expected is None or current_hash != expected:
                        raise FileContentMismatch(f"父文件已变化：{virtual_path}")
                elif expected is not None:
                    raise FileContentMismatch(f"父文件已被删除：{virtual_path}")
                prepared.append((virtual_path, target, content, expected, old_content))

            published: list[tuple[Path, bytes | None]] = []
            try:
                for _virtual_path, target, content, _expected, old_content in prepared:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    temporary = target.parent / f".{target.name}.{uuid4().hex}.accept"
                    try:
                        with temporary.open("xb") as handle:
                            handle.write(content)
                            handle.flush()
                            os.fsync(handle.fileno())
                        os.replace(temporary, target)
                    finally:
                        temporary.unlink(missing_ok=True)
                    published.append((target, old_content))
            except BaseException:
                # 回滚也使用同目录临时文件，避免把半写文件暴露给后续工具。
                for target, old_content in reversed(published):
                    if old_content is None:
                        target.unlink(missing_ok=True)
                    else:
                        rollback = target.parent / f".{target.name}.{uuid4().hex}.rollback"
                        rollback.write_bytes(old_content)
                        os.replace(rollback, target)
                raise

        return [
            WorkspaceFile(path, content.decode("utf-8"), hashlib.sha256(content).hexdigest(), len(content))
            for path, _target, content, _expected, _old in prepared
        ]

    # 从 outputs 读取产物源文件
    def read_output_snapshot_source(self, thread_id: str, virtual_path: str) -> StableFile:
        namespace, path = self._resolve_virtual(thread_id, virtual_path)
        if namespace != "outputs":
            raise PathOutOfScope("只有 outputs 中的文件可以登记为生成产物")
        content = self._read_stable_bytes(path, virtual_path)
        return StableFile(
            virtual_path=virtual_path,
            name=path.name,
            content=content,
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
        )

    # 写入产物快照
    def store_snapshot(self, thread_id: str, relative_path: str, content: bytes) -> Path:
        parts = PurePosixPath(relative_path).parts
        if not parts or parts[0] not in SNAPSHOT_NAMESPACES or any(part in {"", ".", ".."} for part in parts):
            raise PathOutOfScope("无效的快照相对路径")
        thread_root = self.ensure_thread(thread_id)
        target = thread_root.joinpath(*parts)
        self._reject_link_components(thread_root, target)
        self._write_new_bytes(target, content)
        return target

    # 读取产物快照
    def read_snapshot(self, thread_id: str, relative_path: str) -> bytes:
        parts = PurePosixPath(relative_path).parts
        if not parts or parts[0] not in SNAPSHOT_NAMESPACES or any(part in {"", ".", ".."} for part in parts):
            raise PathOutOfScope("无效的产物相对路径")
        thread_root = self.ensure_thread(thread_id).resolve(strict=True)
        lexical = thread_root.joinpath(*parts)
        self._reject_link_components(thread_root, lexical)
        try:
            resolved = lexical.resolve(strict=True)
            resolved.relative_to(thread_root)
        except (FileNotFoundError, ValueError) as exc:
            raise WorkspaceFileNotFound("产物快照不存在") from exc
        return self._read_stable_bytes(resolved, relative_path)

    #
    def delete_snapshot(self, thread_id: str, relative_path: str) -> None:
        try:
            parts = PurePosixPath(relative_path).parts
            target = self.thread_root(thread_id).joinpath(*parts)
            target.unlink(missing_ok=True)
            target.parent.rmdir()
        except OSError:
            return
