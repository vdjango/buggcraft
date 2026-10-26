"""Language names from Mojang assets, filtered by the selected game's index."""
from functools import lru_cache
import json
from pathlib import Path
import re


@lru_cache(maxsize=1)
def language_names():
    for parent in Path(__file__).resolve().parents:
        path = parent / 'resources' / 'minecraft-languages.json'
        if path.is_file():
            return json.loads(path.read_text(encoding='utf-8'))
    return {'zh_cn': {'name': '简体中文', 'region': '中国大陆'},
            'en_us': {'name': 'English', 'region': 'United States'}}


def normalize_language(value):
    aliases = {'English': 'en_us', '简体中文': 'zh_cn', '繁體中文': 'zh_tw',
               'Français': 'fr_fr', 'Deutsch': 'de_de', 'Español': 'es_es',
               '日本語': 'ja_jp', '한국어': 'ko_kr', 'Русский': 'ru_ru'}
    value = aliases.get(value, str(value).lower())
    return value if value in language_names() or re.fullmatch(r'[a-z]{2,3}_[a-z0-9_]{2,16}', value) else 'zh_cn'


def available_languages(directory=None, version=None):
    names = language_names()
    codes = set(names)
    if directory and version:
        try:
            from core.launch_preparation import version_chain
            chain = version_chain(directory, version)
            index = next((metadata.get('assetIndex', {}).get('id') or metadata.get('assets')
                          for _, metadata in chain if metadata.get('assetIndex') or metadata.get('assets')), None)
            if index and Path(index).name == index and not any(c in index for c in '/\\:'):
                data = json.loads((Path(directory) / 'assets/indexes' / (index + '.json')).read_text(encoding='utf-8'))
                found = {Path(key).stem.lower() for key in data['objects']
                         if key.startswith('minecraft/lang/') and key.endswith(('.json', '.lang'))
                         and Path(key).stem != 'deprecated'}
                if found:
                    codes = found | {'en_us'}
        except (OSError, ValueError, TypeError, KeyError):
            pass
    preferred = {'zh_cn': 0, 'zh_tw': 1, 'zh_hk': 2, 'en_us': 3}
    def title(code):
        entry = names.get(code, {})
        return entry.get('name', code) + ('（' + entry['region'] + '）' if entry.get('region') else '')
    return [dict(value=code, title=title(code), description='')
            for code in sorted(codes, key=lambda code: (preferred.get(code, 4), title(code).casefold()))]
