"""Plain-text room messages and explicit virtual-player identities."""
import re


def bridge_player_name(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{2,15}', value):
        raise ValueError('虚拟玩家名称须为 3–16 位，以英文字母开头，只能包含英文字母、数字和下划线。')
    return value

def chat_text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('请输入聊天内容。')
    value = value.strip()
    if len(value.encode('utf-16-le')) > 512:
        raise ValueError('聊天内容不能超过 256 个字符。')
    if any(not ch.isprintable() or ch == '\u00a7' for ch in value):
        raise ValueError('聊天内容只能使用单行普通文字。')
    return value
