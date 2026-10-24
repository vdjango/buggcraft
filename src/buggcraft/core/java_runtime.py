"""Choose a verified configured Java without changing a player's preferences."""
import os
import json
import re
from pathlib import Path
from dataclasses import dataclass

from config.javafinder import JavaPathFinder
from core.launch_options import required_java


class JavaRuntimeUnavailable(ValueError):
    def __init__(self, version, required, current, path, maximum=None, reason=''):
        self.version, self.required = version, required or 0
        self.maximum = maximum
        requirement = (f'Java {required}' if maximum == required else
                       f'Java {required}–{maximum}' if maximum else f'Java {required} 或更高版本')
        super().__init__(f'Minecraft {version} 需要 {requirement}。\n'
                         f'当前 Java：{current or "未安装或无法识别"}\n'
                         f'当前路径：{path or "未设置"}\n'
                         f'{reason}\n已配置的 Java 中未找到适合此实例的版本，游戏尚未启动。')


@dataclass(frozen=True)
class JavaPolicy:
    minimum: int
    maximum: int
    recommended: int
    reason: str

    def accepts(self, major):
        return self.minimum <= major <= self.maximum


def java_policy(directory, version):
    """Use inherited metadata and conservative loader compatibility boundaries.

    These upper bounds are launcher defaults, not claims that all newer JVMs
    cannot run vanilla. Legacy Forge/LaunchWrapper must never be upgraded to 9+.
    """
    minimum = required_java(directory, version) or 8
    current, seen, release, modded, legacy = version, set(), None, False, False
    while current and current not in seen:
        seen.add(current)
        match = re.fullmatch(r'(\d+)\.(\d+)(?:\.(\d+))?(?:[- ].*)?', current)
        if match:
            release = tuple(int(part or 0) for part in match.groups())
        path = Path(directory) / 'versions' / current / (current + '.json')
        if not path.is_file():
            break
        data = json.loads(path.read_text(encoding='utf-8'))
        from core.version_metadata import base_version
        match = re.fullmatch(r'(\d+)\.(\d+)(?:\.(\d+))?(?:[- ].*)?', base_version(data, current))
        if match:
            release = tuple(int(part or 0) for part in match.groups())
        names = [lib.get('name', '') for lib in data.get('libraries', []) if isinstance(lib, dict)]
        modded |= any(name.startswith(('net.minecraftforge:', 'net.neoforged:',
                        'net.fabricmc:fabric-loader:', 'org.quiltmc:quilt-loader:')) for name in names)
        legacy |= (any(name.startswith(('net.minecraftforge:', 'net.minecraft:launchwrapper:')) for name in names)
                   or data.get('mainClass') == 'net.minecraft.launchwrapper.Launch')
        current = data.get('inheritsFrom')
    if legacy and release and release <= (1, 12, 2):
        return JavaPolicy(minimum, 8, 8, '此旧版 Forge / LaunchWrapper 仅使用 Java 8，Java 9 起的类加载器变化会导致启动失败。')
    if release and release < (1, 17, 0) and minimum <= 8:
        return JavaPolicy(8, 8, 8, '旧版游戏与模组优先使用 Java 8，避免新 JVM 的兼容性变化。')
    if release and release < (1, 18, 0) and minimum <= 17:
        return JavaPolicy(minimum, 17, 17, 'Minecraft 1.17 至少需要 Java 16，自动安装使用兼容的 Java 17。')
    if minimum <= 17:
        maximum = 17 if modded else 21
        return JavaPolicy(minimum, maximum, 17, '模组实例保守使用 Java 17；不会自动跨大版本升级 JVM。')
    return JavaPolicy(minimum, minimum, minimum, '使用此 Minecraft 版本声明的 Java 大版本及其最新稳定补丁。')


@dataclass(frozen=True)
class JavaSelection:
    path: str
    major: int
    required: int
    switched: bool


def select_java(settings, directory, version):
    policy = java_policy(directory, version)
    required = policy.minimum
    current = settings.get_version_setting('java.path') or ''
    finder = JavaPathFinder()

    def inspect(path):
        if not isinstance(path, str) or not os.path.isfile(path):
            return '', 0
        raw, parsed = finder._get_java_version(path)
        major = (parsed[1] if parsed[0] == 1 else parsed[0]) if parsed else 0
        return raw, major

    raw, major = inspect(current)
    if major and policy.accepts(major):
        return JavaSelection(current, major, required, False)
    entries = settings.get_setting('java.installations', []) or []
    # Choose the newest configured runtime inside this instance's supported range.
    candidates = []
    for entry in entries:
        if not isinstance(entry, (list, tuple)) or not entry or entry[0] == current:
            continue
        path = entry[0]
        _, actual = inspect(path)
        if actual and policy.accepts(actual):
            candidates.append((actual, path))
    if candidates:
        major, path = max(candidates)
        return JavaSelection(path, major, required, True)
    raise JavaRuntimeUnavailable(version, required, raw, current, policy.maximum, policy.reason)
