"""Read the installed version and compare it with the latest public GitHub release."""
from .i18n import tr
from dataclasses import dataclass
from http.client import HTTPException
import json
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from time import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def version_tuple(tag: str) -> tuple[int, int, int]:
    number = r"(0|[1-9][0-9]{0,8})"
    match = re.fullmatch(rf"v?{number}\.{number}(?:\.{number})?", tag)
    if match is None:
        raise ValueError("版本号应为 X.Y.Z，例如 0.1.0")
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch or "0")


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    repository: str
    check_on_startup: bool
    repository_name: str = ""

    @classmethod
    def load(cls, app_root):
        data = json.loads((app_root / "config/release.json").read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError("发布配置应为 JSON 对象")
        version, repo = data.get("version"), data.get("github_repository", "")
        automatic = data.get("check_on_startup", True)
        if not isinstance(version, str) or not isinstance(repo, str) or not isinstance(automatic, bool):
            raise ValueError("发布配置字段类型有误")
        repo_name = r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}"
        owner_pattern = r"[A-Za-z0-9-]{1,39}"
        if repo and not re.fullmatch(rf"(?:{owner_pattern}/)?{repo_name}", repo):
            raise ValueError("GitHub 仓库应填写 owner/repo")
        normalized_version = ".".join(map(str, version_tuple(version)))
        return cls(normalized_version, repo if "/" in repo else "", automatic, repo.rsplit("/", 1)[-1])


@dataclass(frozen=True)
class ReleaseResult:
    message: str
    update_available: bool = False
    page: str | None = None


def check_latest(info: ReleaseInfo) -> ReleaseResult:
    if not info.repository:
        return ReleaseResult(tr("尚未配置 GitHub 发布仓库。"))
    request = Request(
        f"https://github.com/{info.repository}/releases/latest",
        method="HEAD",
        headers={"User-Agent": "SomePhylloscopus-ReleaseCheck"},
    )
    try:
        with urlopen(request, timeout=5) as response:
            url = urlsplit(response.geturl())
        path = url.path.split("/")
        if (url.scheme != "https" or url.netloc.lower() != "github.com" or len(path) != 6
                or "/".join(path[1:3]).lower() != info.repository.lower() or path[3:5] != ["releases", "tag"]):
            return ReleaseResult(tr("GitHub 未返回可识别的正式版。"))
        tag = path[5]
        latest = version_tuple(tag)
    except HTTPError as error:
        if error.code == 404:
            return ReleaseResult(tr("未找到公开的正式版。请检查仓库地址和 Releases。"))
        if error.code in (403, 429):
            return ReleaseResult(tr("GitHub 暂时拒绝查询，请稍后再试。"))
        return ReleaseResult(tr("GitHub 查询失败（HTTP {0}）。").format(error.code))
    except (URLError, OSError, HTTPException):
        return ReleaseResult(tr("暂时无法连接 GitHub。联网后可重试。"))
    except ValueError:
        return ReleaseResult(tr("GitHub 发布链接或版本号格式有误。"))

    current = version_tuple(info.version)
    if latest > current:
        return ReleaseResult(tr("发现正式版 {0}。").format(tag), True,
                             f"https://github.com/{info.repository}/releases/tag/{tag}")
    if latest < current:
        return ReleaseResult(tr("GitHub 最新正式版为 {0}，当前安装版本更新。").format(tag))
    return ReleaseResult(tr("当前已是最新正式版（{0}）。").format(tag))


def automatic_check_due(cache_path, info: ReleaseInfo) -> bool:
    try:
        record = json.loads(cache_path.read_text(encoding="utf-8"))
        elapsed = time() - float(record["checked_at"])
        return not (record["repository"] == info.repository and record["version"] == info.version
                    and 0 <= elapsed < 24 * 60 * 60)
    except (OSError, ValueError, KeyError, TypeError):
        return True


def remember_check(cache_path, info: ReleaseInfo):
    """An advisory cache. A read-only install can still check manually."""
    pending = None
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=cache_path.parent, suffix=".tmp", delete=False, mode="w", encoding="utf-8") as stream:
            pending = Path(stream.name)
            json.dump(dict(repository=info.repository, version=info.version, checked_at=time()), stream)
        pending.replace(cache_path)
    except OSError:
        if pending is not None:
            try:
                pending.unlink(missing_ok=True)
            except OSError:
                pass
