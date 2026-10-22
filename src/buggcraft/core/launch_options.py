"""Pure argument handling shared by launch configuration and validation."""
import shlex
import json
from pathlib import Path


def split_arguments(value):
    if not isinstance(value, str):
        raise ValueError('启动参数必须是文本')
    parser = shlex.shlex(value, posix=True)
    parser.whitespace_split = True
    parser.commenters = ''
    parser.escape = ''
    return list(parser)


def redacted_command(command, token=None):
    result = list(command)
    for index, argument in enumerate(result):
        if argument in ('--accessToken', '--clientToken', '--xuid') and index + 1 < len(result):
            result[index + 1] = '<redacted>'
        elif token and isinstance(argument, str) and token in argument:
            result[index] = argument.replace(token, '<redacted>')
    return result


def configure_room_join(options, address, directory, version):
    """Use the installed version's Quick Play feature or legacy server/port."""
    host, separator, port = str(address).rpartition(':')
    if not separator or host != '127.0.0.1' or not port.isdigit() or not 1 <= int(port) <= 65535:
        raise ValueError('房间游戏地址无效')
    current, seen = version, set()
    quick_play = False
    while current and current not in seen:
        seen.add(current)
        metadata = json.loads((Path(directory) / 'versions' / current / (current + '.json')).read_text(encoding='utf8'))
        quick_play = quick_play or any(isinstance(item, dict) and any(
            rule.get('features', {}).get('is_quick_play_multiplayer') is True
            for rule in item.get('rules', [])) for item in metadata.get('arguments', {}).get('game', []))
        current = metadata.get('inheritsFrom')
    if quick_play:
        options['quickPlayMultiplayer'] = address
        options['quickPlayPath'] = str(Path(options['gameDirectory']) / 'quickPlay' / 'buggcraft.json')
    else:
        options['server'], options['port'] = host, port
