"""只通过 Docker CLI 执行 Bash，不在宿主机回退执行命令。"""

import asyncio
import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path

from agentloom.config import SandboxConfig

MANAGED_LABEL = "agentloom.managed=true"


class DockerSandboxError(RuntimeError):
    """带稳定错误码的容器执行错误。"""

    code = "DOCKER_EXECUTION_FAILED"


class DockerUnavailable(DockerSandboxError):
    code = "DOCKER_UNAVAILABLE"


class DockerCommandTimeout(DockerSandboxError):
    code = "DOCKER_TIMEOUT"


@dataclass(frozen=True)
class DockerCommandResult:
    """一次容器命令的确定结果。"""

    exit_code: int
    stdout: str
    stderr: str
    truncated: bool


async def _read_limited(stream: asyncio.StreamReader | None, limit: int) -> tuple[bytes, bool]:
    if stream is None:
        return b"", False
    # kept：用 bytearray 而不是 bytes，因为它是可变的，可以高效 extend 追加。
    kept = bytearray()
    truncated = False
    while chunk := await stream.read(8192):
        room = max(0, limit - len(kept))
        kept.extend(chunk[:room])
        if len(chunk) > room:
            truncated = True
    return bytes(kept), truncated


class DockerCommandService:
    """为每次 Bash 调用创建一个受限容器，并跟踪 Run 所属容器以便取消。"""

    def __init__(self, threads_root: Path, config: SandboxConfig, *, executable: str | None = None) -> None:
        self.threads_root = threads_root.resolve()
        self.config = config
        self.executable = executable or shutil.which("docker")
        self._active: dict[str, set[str]] = {}
        self._lock = asyncio.Lock()

    @property
    def available(self) -> bool:
        return self.executable is not None

    @staticmethod
    def _container_name(run_id: str, tool_call_id: str) -> str:
        digest = hashlib.sha256(f"{run_id}:{tool_call_id}".encode()).hexdigest()[:20]
        return f"agentloom-{digest}"

    def _create_args(
        self,
        *,
        thread_root: Path,
        run_id: str,
        container_name: str,
        command: str,
    ) -> list[str]:
        """生成固定安全边界；模型只能提供容器内执行的 command。"""
        if self.executable is None:
            raise DockerUnavailable("未找到 docker 命令；AgentLoom 不会回退到宿主机 Bash")
        workspace = (thread_root / "workspace").resolve()
        uploads = (thread_root / "uploads").resolve()
        outputs = (thread_root / "outputs").resolve()
        tool_results = (thread_root / "tool-results").resolve()
        for directory in (workspace, uploads, outputs, tool_results):
            try:
                directory.relative_to(thread_root)
            except ValueError as exc:
                raise DockerSandboxError("Docker 挂载目录通过链接逃出了当前线程") from exc
            directory.mkdir(parents=True, exist_ok=True)
        return [
            self.executable,
            "create",
            "--name",
            container_name,
            "--label",
            MANAGED_LABEL,
            "--label",
            f"agentloom.run_id={run_id}",
            "--network",
            self.config.network,
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            str(self.config.pids_limit),
            "--memory",
            f"{self.config.memory_mb}m",
            "--cpus",
            str(self.config.cpu_limit),
            "--user",
            "1000:1000",
            "--tmpfs",
            f"/tmp:rw,noexec,nosuid,size={self.config.tmpfs_mb}m",
            "--env",
            "HOME=/tmp",
            "--env",
            "PYTHONUNBUFFERED=1",
            "--workdir",
            "/mnt/user-data/workspace",
            "--mount",
            f"type=bind,src={workspace},dst=/mnt/user-data/workspace",
            "--mount",
            f"type=bind,src={uploads},dst=/mnt/user-data/uploads,readonly",
            "--mount",
            f"type=bind,src={outputs},dst=/mnt/user-data/outputs",
            "--mount",
            f"type=bind,src={tool_results},dst=/mnt/user-data/tool-results,readonly",
            self.config.image,
            "/bin/bash",
            "-lc",
            command,
        ]

    async def _run(self, args: list[str], *, timeout: float = 10) -> tuple[int, str, str, bool]:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out_task = asyncio.create_task(_read_limited(process.stdout, self.config.output_max_bytes))
        err_task = asyncio.create_task(_read_limited(process.stderr, self.config.output_max_bytes))
        try:
            await asyncio.wait_for(process.wait(), timeout=timeout)
        except BaseException:
            if process.returncode is None:
                process.kill()
                await process.wait()
            await asyncio.gather(out_task, err_task, return_exceptions=True)
            raise
        """ stdout：stdout 的 bytes。
            out_cut：stdout 是否截断。
            stderr：stderr 的 bytes。
            err_cut：stderr 是否截断。"""
        (stdout, out_cut), (stderr, err_cut) = await asyncio.gather(out_task, err_task)
        return (
            int(process.returncode or 0),
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
            out_cut or err_cut,
        )

    async def _register(self, run_id: str, container_name: str) -> None:
        async with self._lock:
            self._active.setdefault(run_id, set()).add(container_name)

    async def _forget(self, run_id: str, container_name: str) -> None:
        async with self._lock:
            names = self._active.get(run_id)
            if names is not None:
                # 从集合移除容器名。
                names.discard(container_name)
                # 集合空了,把整个 run_id 键删掉。
                if not names:
                    self._active.pop(run_id, None)

    async def _remove(self, container_name: str) -> None:
        if self.executable is None:
            return
        try:
            await self._run([self.executable, "rm", "-f", container_name], timeout=10)
        except (OSError, TimeoutError):
            return

    async def execute(
        self,
        *,
        thread_id: str,
        run_id: str,
        tool_call_id: str,
        command: str,
    ) -> DockerCommandResult:
        if not self.available:
            raise DockerUnavailable("未找到 docker 命令；请安装并启动 Docker 后再执行 Bash")
        thread_root = (self.threads_root / thread_id).resolve()
        try:
            thread_root.relative_to(self.threads_root)
        except ValueError as exc:
            raise DockerSandboxError("线程目录超出受控根目录") from exc
        container_name = self._container_name(run_id, tool_call_id)
        create_args = self._create_args(
            thread_root=thread_root,
            run_id=run_id,
            container_name=container_name,
            command=command,
        )
        await self._register(run_id, container_name)
        try:
            code, _stdout, stderr, _cut = await self._run(create_args, timeout=30)
            if code != 0:
                raise DockerSandboxError(f"创建容器失败：{stderr.strip() or 'docker create failed'}")
            try:
                code, stdout, stderr, cut = await self._run(
                    [self.executable, "start", "--attach", container_name],
                    timeout=self.config.timeout_seconds,
                )
            except TimeoutError as exc:
                # shield 保护 _remove 不被外部取消。
                await asyncio.shield(self._remove(container_name))
                raise DockerCommandTimeout(f"命令超过 {self.config.timeout_seconds} 秒，容器已停止") from exc
            return DockerCommandResult(code, stdout, stderr, cut)
        except asyncio.CancelledError:
            await asyncio.shield(self._remove(container_name))
            raise
        finally:
            await asyncio.shield(self._remove(container_name))
            await self._forget(run_id, container_name)

    async def execute_task(
        self,
        *,
        parent_thread_id: str,
        task_id: str,
        run_id: str,
        command: str,
    ) -> DockerCommandResult:
        """在 Coder 私有任务目录验证，不把父工作区挂进容器。"""
        task_threads_root = (self.threads_root / parent_thread_id / "tasks").resolve()
        try:
            task_threads_root.relative_to(self.threads_root)
        except ValueError as exc:
            raise DockerSandboxError("Coder 任务目录超出受控根目录") from exc
        verifier = DockerCommandService(task_threads_root, self.config, executable=self.executable)
        return await verifier.execute(
            thread_id=task_id,
            run_id=run_id,
            tool_call_id=f"coder-verify:{task_id}",
            command=command,
        )

    async def cancel_run(self, run_id: str) -> None:
        """强制删除该 Run 的容器；返回时 Docker 已确认清理命令结束。"""
        async with self._lock:
            names = tuple(self._active.get(run_id, ()))
        await asyncio.gather(*(self._remove(name) for name in names))

    async def cleanup_orphans(self) -> int:
        """启动时仅清理带 AgentLoom 标签的遗留容器。"""
        if self.executable is None:
            return 0
        code, stdout, _stderr, _cut = await self._run(
            [self.executable, "ps", "--all", "--quiet", "--filter", f"label={MANAGED_LABEL}"],
            timeout=10,
        )
        if code != 0:
            return 0
        ids = [line.strip() for line in stdout.splitlines() if line.strip()]
        if ids:
            await self._run([self.executable, "rm", "-f", *ids], timeout=30)
        return len(ids)
