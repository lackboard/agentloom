"""从开发者维护的本地目录发现并按需加载 Skill。"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import ValidationError

from agentloom.skills.schema import SkillMetadata, SkillSnapshot

MAX_SKILL_BYTES = 256 * 1024
_FRONTMATTER = re.compile(r"\A---\s*\r?\n(.*?)\r?\n---\s*(?:\r?\n|\Z)(.*)\Z", re.DOTALL)


class SkillError(RuntimeError):
    """Skill 发现或加载失败。"""

    code = "SKILL_ERROR"


class SkillNotFound(SkillError):
    code = "SKILL_NOT_FOUND"


class SkillValidationError(SkillError):
    code = "SKILL_INVALID"


class SkillActivationDisabled(SkillError):
    code = "SKILL_ACTIVATION_DISABLED"


@dataclass(frozen=True)
class _CatalogEntry:
    metadata: SkillMetadata
    path: Path


@dataclass(frozen=True)
class _ParsedSkill:
    metadata: SkillMetadata
    content: str
    raw_bytes: bytes


def _allowed_tools(value: object, path: Path) -> tuple[str, ...]:
    if isinstance(value, str):
        values = value.split()
    elif isinstance(value, list):
        values = value
    else:
        raise SkillValidationError(f"{path} 的 allowed-tools 必须是字符串列表或空格分隔字符串")
    if any(not isinstance(item, str) or not item.strip() for item in values):
        raise SkillValidationError(f"{path} 的 allowed-tools 只能包含非空字符串")
    return tuple(dict.fromkeys(item.strip() for item in values))


def parse_skill_file(path: Path) -> _ParsedSkill:
    """解析一个 UTF-8 `SKILL.md`，正文与 frontmatter 分开返回。"""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise SkillValidationError(f"无法读取 Skill：{path}") from exc
    if len(raw) > MAX_SKILL_BYTES:
        raise SkillValidationError(f"Skill 超过 {MAX_SKILL_BYTES} 字节限制：{path}")
    try:
        source = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SkillValidationError(f"Skill 必须使用 UTF-8：{path}") from exc
    match = _FRONTMATTER.match(source)
    if match is None:
        raise SkillValidationError(f"Skill 缺少由 --- 包围的 YAML frontmatter：{path}")
    try:
        frontmatter = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        raise SkillValidationError(f"Skill frontmatter 不是有效 YAML：{path}: {exc}") from exc
    if not isinstance(frontmatter, dict):
        raise SkillValidationError(f"Skill frontmatter 必须是对象：{path}")
    try:
        metadata = SkillMetadata(
            name=frontmatter.get("name"),
            description=frontmatter.get("description"),
            allowed_tools=_allowed_tools(frontmatter.get("allowed-tools"), path),
        )
    except ValidationError as exc:
        raise SkillValidationError(f"Skill 元数据无效：{path}: {exc}") from exc
    content = match.group(2).strip()
    if not content:
        raise SkillValidationError(f"Skill 正文不能为空：{path}")
    return _ParsedSkill(metadata=metadata, content=content, raw_bytes=raw)


class SkillLoader:
    """固定一个启动时目录清单，加载时才把指定正文做成 Run 快照。"""

    def __init__(self, root: Path, *, max_active: int = 1) -> None:
        self.root = root.resolve()
        self.max_active = max_active
        self._entries = self._scan()

    def _scan(self) -> dict[str, _CatalogEntry]:
        if not self.root.exists():
            return {}
        if not self.root.is_dir():
            raise SkillValidationError(f"Skills 路径不是目录：{self.root}")
        entries: dict[str, _CatalogEntry] = {}
        for skill_file in sorted(self.root.glob("*/SKILL.md"), key=lambda item: item.as_posix().casefold()):
            resolved = skill_file.resolve()
            try:
                resolved.relative_to(self.root)
            except ValueError as exc:
                raise SkillValidationError(f"Skill 路径越过配置目录：{skill_file}") from exc
            parsed = parse_skill_file(resolved)
            if parsed.metadata.name != resolved.parent.name:
                raise SkillValidationError(f"Skill 名称必须与目录名一致：{resolved}")
            if parsed.metadata.name in entries:
                raise SkillValidationError(f"Skill 名称重复：{parsed.metadata.name}")
            entries[parsed.metadata.name] = _CatalogEntry(parsed.metadata, resolved)
        return entries

    def list_skills(self) -> tuple[SkillMetadata, ...]:
        """只返回可发现元数据，不返回任何正文。"""
        return tuple(entry.metadata for entry in self._entries.values())

    def load(self, name: str, *, activation: str, run_id: str) -> SkillSnapshot:
        """读取指定 Skill 的当前字节并冻结正文、权限和内容 hash。"""
        if self.max_active == 0:
            raise SkillActivationDisabled("当前配置已禁用 Skill 激活")
        entry = self._entries.get(name)
        if entry is None:
            raise SkillNotFound(f"未找到 Skill：{name}")
        parsed = parse_skill_file(entry.path)
        if parsed.metadata.name != name:
            raise SkillValidationError(f"Skill 加载期间名称发生变化：{name}")
        digest = hashlib.sha256(parsed.raw_bytes).hexdigest()
        return SkillSnapshot(
            **parsed.metadata.model_dump(),
            content=parsed.content,
            content_hash=digest,
            snapshot_ref=f"skill://{name}@sha256:{digest}",
            activation=activation,
            run_id=run_id,
        )
