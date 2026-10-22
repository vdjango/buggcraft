"""Atomic per-device nodes and local friend bookmarks. No account passwords."""
import json
import os
from pathlib import Path
import tempfile


class LobbyStore:
    def __init__(self, path):
        self.path = Path(path)
        self.data = {'nodes': [], 'contacts': [], 'node_names': {}}
        if self.path.exists():
            loaded = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(loaded, dict) or any(not isinstance(loaded.get(key, []), list) for key in ('nodes', 'contacts')):
                raise ValueError('联机配置格式错误')
            if any(not isinstance(item, str) for item in loaded.get('nodes', [])):
                raise ValueError('节点列表格式错误')
            for contact in loaded.get('contacts', []):
                if not isinstance(contact, dict) or any(not isinstance(contact.get(key), str)
                        for key in ('name', 'invite', 'node')):
                    raise ValueError('联系人列表格式错误')
                if not isinstance(contact.get('account', ''), str):
                    raise ValueError('好友账号格式错误')
            names = loaded.get('node_names', {})
            if not isinstance(names, dict) or any(not isinstance(k, str) or not isinstance(v, str) or
                                                 not 1 <= len(v) <= 80 for k, v in names.items()):
                raise ValueError('节点名称格式错误')
            self.data.update({key: loaded.get(key, []) for key in ('nodes', 'contacts')})
            self.data['node_names'] = names

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix='.lobby-', dir=self.path.parent)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as target:
                json.dump(self.data, target, ensure_ascii=False, indent=2)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def add_node(self, path):
        path = str(Path(path).expanduser().resolve())
        if path not in self.data['nodes']:
            self.data['nodes'].append(path)
            self.save()

    def add_contact(self, name, invite, node, account=''):
        name = name.strip()
        if not name or len(name) > 64:
            raise ValueError('好友昵称需要 1–64 个字符')
        contact = {'name': name, 'invite': invite, 'node': node, 'account': account}
        for index, previous in enumerate(self.data['contacts']):
            if (account and previous.get('account') == account) or (
                    not account and not previous.get('account') and previous['name'] == name):
                self.data['contacts'][index] = contact
                break
        else:
            self.data['contacts'].append(contact)
        self.save()
