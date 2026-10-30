"""Fast local memory checks immediately before starting Minecraft."""

from pathlib import Path
import re


_HEAP = re.compile(r'^-Xmx(\d+)([kKmMgG]?)$')


class LaunchMemoryWarning(ValueError):
    """A launch risk which the user may explicitly accept."""


def enabled_mod_count(game_directory):
    """Count installed, enabled JARs in this instance's mods directory."""
    if not game_directory:
        return 0
    mods = Path(game_directory) / 'mods'
    if not mods.is_dir():
        return 0
    return sum(entry.is_file() and entry.suffix.lower() == '.jar'
               for entry in mods.iterdir())


def minimum_heap_mib(mod_count):
    """Conservative advisory floor, not a guarantee of smooth gameplay."""
    if mod_count >= 80:
        return 6144
    if mod_count >= 40:
        return 4096
    if mod_count >= 10:
        return 3072
    if mod_count:
        return 2048
    return 0


def effective_heap_mib(command, configured_arguments):
    """Use the last effective JVM -Xmx flag, including advanced overrides."""
    flags = [arg for arg in command if isinstance(arg, str) and arg.startswith('-Xmx')]
    if not flags:
        flags = [arg for arg in configured_arguments
                 if isinstance(arg, str) and arg.startswith('-Xmx')]
    if not flags:
        raise ValueError('启动前检查失败：未找到游戏最大内存参数 -Xmx。')
    match = _HEAP.fullmatch(flags[-1])
    if not match:
        raise ValueError('启动前检查失败：无法识别游戏最大内存参数 ' + flags[-1][:40])
    amount, unit = int(match[1]), match[2].lower()
    mib = amount * 1024 if unit == 'g' else amount / 1024 if unit == 'k' else amount / 1048576 if not unit else amount
    return int(mib)


def check_launch_memory(game_directory, command, configured_arguments, available_mib=None):
    """Return the effective heap or raise an overridable memory warning."""
    count = enabled_mod_count(game_directory)
    allocated = effective_heap_mib(command, configured_arguments)
    required = minimum_heap_mib(count)
    warnings = []
    if allocated < required:
        warnings.append(
            f'当前实例有 {count} 个已启用模组，实际分配 {allocated} MiB；'
            f'按模组数量建议至少 {required} MiB。'
            '可在实例设置中提高游戏内存；自动分配或高级 JVM 参数中的 -Xmx 也会影响实际值。')
    if available_mib is not None and allocated > max(0, available_mib - 1024):
        warnings.append(
            f'游戏最大内存 {allocated} MiB，系统当前可用约 {available_mib} MiB；'
            '建议至少为系统保留 1024 MiB，可关闭其他程序或降低分配。')
    if warnings:
        raise LaunchMemoryWarning((chr(10) * 2).join(warnings))
    return count, allocated, required
