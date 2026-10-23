"""Choose a verified configured Java without changing a player's preferences."""
import os
from dataclasses import dataclass

from config.javafinder import JavaPathFinder
from core.launch_options import required_java


class JavaRuntimeUnavailable(ValueError):
    def __init__(self, version, required, current, path):
        self.version, self.required = version, required or 0
        requirement = f'Java {required} 或更高版本' if required else '可用的 Java'
        super().__init__(f'Minecraft {version} 需要 {requirement}。\n'
                         f'当前 Java：{current or "未安装或无法识别"}\n'
                         f'当前路径：{path or "未设置"}\n'
                         '已配置的 Java 中未找到满足要求的版本，游戏未启动。请下载并在设置中添加 Java。')


@dataclass(frozen=True)
class JavaSelection:
    path: str
    major: int
    required: int
    switched: bool


def select_java(settings, directory, version):
    required = required_java(directory, version) or 0
    current = settings.get_version_setting('java.path') or ''
    finder = JavaPathFinder()

    def inspect(path):
        if not isinstance(path, str) or not os.path.isfile(path):
            return '', 0
        raw, parsed = finder._get_java_version(path)
        major = (parsed[1] if parsed[0] == 1 else parsed[0]) if parsed else 0
        return raw, major

    raw, major = inspect(current)
    if major and major >= required:
        return JavaSelection(current, major, required, False)
    entries = settings.get_setting('java.installations', []) or []
    # Prefer the nearest sufficient major over an unnecessarily newer runtime.
    candidates = []
    for entry in entries:
        if not isinstance(entry, (list, tuple)) or not entry or entry[0] == current:
            continue
        path = entry[0]
        _, actual = inspect(path)
        if actual and actual >= required:
            candidates.append((actual, path))
    if candidates:
        major, path = min(candidates)
        return JavaSelection(path, major, required, True)
    raise JavaRuntimeUnavailable(version, required, raw, current)
