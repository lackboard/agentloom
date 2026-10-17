"""在当前盘的隔离副本中验证 README 的干净安装路径。"""

import argparse
import os
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = (ROOT / "output" / "clean-install").resolve()
CACHE_ROOT = (ROOT / "output" / "clean-cache").resolve()
IGNORED_DIRECTORIES = {
    ".agentloom",
    ".git",
    ".playwright-cli",
    ".venv",
    ".vscode",
    "__pycache__",
    "dist",
    "node_modules",
    "output",
}
IGNORED_FILES = {".env", "config.yaml"}


def _ignore(_directory: str, names: list[str]) -> set[str]:
    ignored = {name for name in names if name in IGNORED_DIRECTORIES or name in IGNORED_FILES}
    ignored.update(name for name in names if name.endswith((".pyc", ".tsbuildinfo")))
    return ignored


def _run(command: list[str], *, cwd: Path, env: dict[str, str], timeout: float = 300) -> None:
    print(f"CLEAN> ({cwd.name}) {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True, timeout=timeout)


def _verify_api_start(*, backend: Path, env: dict[str, str]) -> None:
    """用干净环境的真实 uvicorn 进程启动应用，并等待 lifespan 完成。"""
    uvicorn = backend / ".venv" / "Scripts" / "uvicorn.exe"
    log_path = backend.parent / "clean-api.log"
    command = [
        str(uvicorn),
        "agentloom.api:create_app",
        "--factory",
        "--host",
        "127.0.0.1",
        "--port",
        "18765",
    ]
    print(f"CLEAN> (backend) {' '.join(command)}", flush=True)
    with log_path.open("w", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            command,
            cwd=backend,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        try:
            deadline = time.monotonic() + 300
            last_error: Exception | None = None
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    log_file.flush()
                    output = log_path.read_text(encoding="utf-8", errors="replace")
                    raise RuntimeError(f"uvicorn 提前退出：\n{output[-4000:]}")
                try:
                    with urllib.request.urlopen("http://127.0.0.1:18765/api/threads", timeout=1) as response:
                        if response.status == 200:
                            print("CLEAN> API GET /api/threads: 200", flush=True)
                            return
                except Exception as exc:
                    last_error = exc
                    time.sleep(0.2)
            log_file.flush()
            output = log_path.read_text(encoding="utf-8", errors="replace")
            raise TimeoutError(f"uvicorn 300 秒内未就绪：{last_error}\n{output[-4000:]}")
        finally:
            process.terminate()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


def main() -> None:
    parser = argparse.ArgumentParser(description="在隔离副本中验证 AgentLoom 的干净安装和启动")
    parser.add_argument("--reuse", action="store_true", help="复用上次保留的隔离副本继续验证")
    args = parser.parse_args()
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    candidates = sorted(
        (path for path in OUTPUT_ROOT.glob("workspace*") if path.is_dir()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if args.reuse:
        if not candidates:
            raise RuntimeError("--reuse 需要 output/clean-install 下存在隔离副本")
        target = candidates[0].resolve()
    else:
        target = (OUTPUT_ROOT / f"workspace-{int(time.time())}").resolve()
    if not target.is_relative_to(OUTPUT_ROOT):
        raise RuntimeError("干净安装目录越过 output/clean-install 边界")
    if not args.reuse:
        shutil.copytree(ROOT, target, ignore=_ignore)
    try:
        env = os.environ.copy()
        env.pop("VIRTUAL_ENV", None)
        env.update(
            {
                "AGENTLOOM_CONFIG": "config.example.yaml",
                "PYTHONUNBUFFERED": "1",
                "UV_CACHE_DIR": str(CACHE_ROOT / "uv"),
                "npm_config_cache": str(CACHE_ROOT / "npm"),
            }
        )
        uv = shutil.which("uv")
        npx = shutil.which("npx")
        if uv is None or npx is None:
            raise RuntimeError("干净安装验证需要 PATH 中存在 uv 和 npx")

        backend = target / "backend"
        _run([uv, "sync", "--locked"], cwd=backend, env=env)
        scripts = backend / ".venv" / "Scripts"
        _run([str(scripts / "alembic.exe"), "upgrade", "head"], cwd=backend, env=env)
        _run(
            [
                str(scripts / "python.exe"),
                "-c",
                "import agentloom.api; print('CLEAN> import agentloom.api: PASS')",
            ],
            cwd=backend,
            env=env,
            timeout=900,
        )
        _verify_api_start(backend=backend, env=env)
        _run(
            [str(scripts / "pytest.exe"), "-m", "not live and not docker", "-q"],
            cwd=backend,
            env=env,
        )

        frontend = target / "frontend"
        pnpm = [npx, "--yes", "pnpm@12.11.2"]
        _run(
            [*pnpm, "install", "--frozen-lockfile", "--store-dir", str(CACHE_ROOT / "pnpm")],
            cwd=frontend,
            env=env,
            timeout=900,
        )
        _run([*pnpm, "check"], cwd=frontend, env=env, timeout=900)
    except Exception:
        print(f"CLEAN INSTALL: FAIL；失败现场保留在 {target}", flush=True)
        raise
    print(f"CLEAN INSTALL: PASS；隔离副本保留在 {target}", flush=True)


if __name__ == "__main__":
    main()
