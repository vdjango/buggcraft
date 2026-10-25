"""Public translation protocol client. No model credentials belong in a launcher."""
from __future__ import annotations

import hashlib
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import time
from urllib.parse import urlsplit
import uuid

import requests

SOURCES = {'Buggcraft': 'https://translate.bugg.icu/v1'}


def text_hash(text, field, format='plain', source_language='und'):
    value = dict(schema='mc-text-v1', field=field, source_language=source_language, format=format,
                 text=text.replace('\r\n', '\n').replace('\r', '\n'))
    return 'sha256:' + hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                                separators=(',', ':')).encode('utf-8')).hexdigest()


def endpoint(source='Buggcraft'):
    value = os.environ.get('BUGGCRAFT_TRANSLATION_URL') or SOURCES.get(source, SOURCES['Buggcraft'])
    parsed = urlsplit(value)
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost', '::1')):
        raise ValueError('翻译服务需要 HTTPS')
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('翻译服务地址无效')
    return value.rstrip('/')


def lookup_items(rows, detail=False):
    items = []
    for index, row in enumerate(rows):
        provider = {'Modrinth':'modrinth', 'CurseForge':'curseforge'}.get(row.get('source'))
        identity = str(row.get('project_id') or row.get('id') or '')
        if not provider or not identity:
            continue
        fields = []
        if isinstance(row.get('description'), str):
            fields.append(dict(field='summary', source_hash=text_hash(row['description'], 'summary')))
        # Hash raw HTML/Markdown before the UI's image removal and clipping.
        if detail and isinstance(row.get('body'), str):
            fields.append(dict(field='body', source_hash=text_hash(row['body'], 'body', 'html' if row.get('body_html') else 'markdown')))
        if fields:
            items.append(dict(request_id=str(index), resource=dict(provider=provider, project_id=identity,
                         entity_type='project', entity_id=identity), fields=fields))
    return items


class TranslationClient:
    def __init__(self, cache_directory):
        self.path = Path(cache_directory) / 'translations.sqlite3'
        self.session = requests.Session()
        self.session.headers['User-Agent'] = 'Buggcraft-Launcher-Translation/1.0'
        self.token, self.expires, self.token_source = '', 0, ''
        self.ensured = {}

    def close(self):
        self.session.close()

    def _request(self, url, *, data=None, headers=None):
        response = self.session.request('POST' if data is not None else 'GET', url,
            json=data, headers=headers, timeout=(3, 8), allow_redirects=False, stream=True)
        with response:
            if response.status_code >= 400:
                if response.status_code == 401:
                    self.expires = 0
                delay = min(3600, max(15, int(response.headers.get('Retry-After', '30'))))
                raise TranslationUnavailable('翻译服务暂不可用，继续显示原文', delay)
            raw = bytearray()
            for chunk in response.iter_content(65536):
                raw.extend(chunk)
                if len(raw) > 1048576:
                    raise TranslationUnavailable('翻译内容超过大小限制', 60)
            return json.loads(raw), bytes(raw)

    def _auth(self, source):
        # Optional developer credential belongs only to its configured origin.
        # Never ship the model/admin credential or a shared privileged key.
        key = os.environ.get('BUGGCRAFT_TRANSLATION_KEY', '').strip()
        if key and source.rstrip('/') == endpoint().rstrip('/'):
            return {'Authorization': 'Bearer ' + key}
        if source != self.token_source or time.monotonic() >= self.expires:
            data, _ = self._request(source+'/sessions/anonymous', data={'client_id':'buggcraft-launcher'})
            self.token, self.token_source = data['access_token'], source
            self.expires = time.monotonic() + min(3600, int(data['expires_in'])) - 60
        return {'Authorization':'Bearer '+self.token}

    @staticmethod
    def cache_key(source, item, field):
        return json.dumps([source, 'zh-Hans', 'minecraft-v1', item['resource'], field], sort_keys=True)

    def resolve(self, source, rows, detail=False):
        items = lookup_items(rows, detail)
        result = dict(translations={}, pending=False, status='', retry=2)
        if not items:
            return result
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=3, isolation_level=None)) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS cache(key TEXT PRIMARY KEY, text TEXT NOT NULL, format TEXT NOT NULL, accessed REAL NOT NULL)')
            missing = []
            for item in items:
                fields = []
                for field in item['fields']:
                    key = self.cache_key(source, item, field)
                    cached = db.execute('SELECT text,format FROM cache WHERE key=?', (key,)).fetchone()
                    if cached:
                        result['translations'].setdefault(item['request_id'], {})[field['field']] = dict(text=cached[0], format=cached[1])
                    else:
                        fields.append(field)
                if fields:
                    missing.append(dict(item, fields=fields))
            # Keep the disk cache bounded, independently of API availability.
            db.execute('DELETE FROM cache WHERE key IN (SELECT key FROM cache ORDER BY accessed DESC LIMIT -1 OFFSET 5000)')
            try:
                # Bound each worker round to one batch. Newly appended visible
                # rows take priority; older pending rows are revisited as cached
                # work completes. Never hold a write transaction during HTTP.
                result['pending'] = len(missing)>20
                for batch in ([missing[-20:]] if missing else []):
                    payload = dict(target_language='zh-Hans', profile='minecraft-v1', items=batch)
                    response, _ = self._request(source+'/translations:resolve', data=payload)
                    if len(response['results']) != len(batch):
                        raise ValueError('Incomplete translation response')
                    needed = []
                    for item, resolved in zip(batch, response['results']):
                        if resolved.get('request_id') != item['request_id'] or resolved.get('resource') != item['resource']:
                            raise ValueError('Invalid translation response identity')
                        by_name = {f['field']:f for f in item['fields']}
                        if len(resolved['fields']) != len(by_name) or {f['field'] for f in resolved['fields']} != set(by_name):
                            raise ValueError('Incomplete translation fields')
                        unresolved = []
                        for field in resolved['fields']:
                            expected = by_name.get(field['field'])
                            if not expected or field['requested_source_hash'] != expected['source_hash']:
                                raise ValueError('Invalid translation response hash')
                            update = field.get('update', {})
                            if update.get('notice'):
                                result['status'] = update['notice']
                            if update.get('action') == 'refresh_source' or field.get('is_current') is False:
                                result['status'] = update.get('notice') or '原文已更新，正在准备新版本译文'
                                continue
                            if field['state']=='ready' and field.get('matches_request') is True and field.get('is_current') is True:
                                translated = field['translation']
                                if 'text' not in translated:
                                    artifact_hash = translated['artifact']['artifact_sha256']
                                    # Construct URL ourselves; never follow arbitrary artifact URLs.
                                    artifact, raw = self._request(source+'/artifacts/'+artifact_hash)
                                    if hashlib.sha256(raw).hexdigest() != artifact_hash or artifact.get('source_hash') != expected['source_hash'] or artifact.get('resource') != item['resource'] or artifact.get('field') != field['field'] or artifact.get('target_language') != 'zh-Hans' or artifact.get('profile') != 'minecraft-v1':
                                        raise ValueError('Invalid translation artifact')
                                    translated = artifact
                                text, format = translated['text'], translated['format']
                                if not isinstance(text,str) or format not in ('plain','markdown','html'):
                                    raise ValueError('Invalid translation text')
                                result['translations'].setdefault(item['request_id'], {})[field['field']] = dict(text=text,format=format)
                                db.execute('INSERT OR REPLACE INTO cache VALUES(?,?,?,?)', (self.cache_key(source,item,expected),text,format,time.time()))
                            elif field.get('error',{}).get('code') == 'source_mismatch':
                                result['status'] = '原文版本已变化，刷新资源后自动更新翻译'
                            elif field['state'] not in ('failed','blocked'):
                                unresolved.append(expected)
                                result['pending'] = True
                            else:
                                result['status'] = update.get('notice') or '译文暂不可用，继续显示原文'
                        if unresolved:
                            needed.append(dict(item,fields=unresolved))
                    # Idempotency plus a local cooldown prevents repeated ensure
                    # submissions on every UI polling tick.
                    to_ensure = []
                    for item in needed:
                        key = self.cache_key(source,item,item['fields'])
                        if self.ensured.get(key,0) < time.monotonic():
                            to_ensure.append(item)
                    if to_ensure:
                        headers=self._auth(source)
                        headers['Idempotency-Key']=uuid.uuid4().hex
                        self._request(source+'/translations:ensure', data=dict(payload,items=to_ensure,purpose='detail' if detail else 'visible_list'), headers=headers)
                        for item in to_ensure:
                            self.ensured[self.cache_key(source,item,item['fields'])] = time.monotonic()+300
                if len(self.ensured)>2000:
                    self.ensured={k:v for k,v in self.ensured.items() if v>time.monotonic()}
                if result['pending'] and not result['status']:
                    result['status']='正在自动翻译，完成后显示中文 · 可继续浏览和下载'
            except TranslationUnavailable as exc:
                result.update(status=str(exc),retry=exc.retry,pending=True)
            except (requests.RequestException, ValueError, KeyError, TypeError):
                result.update(status='翻译服务暂不可用，继续显示原文',retry=30,pending=True)
        return result


class TranslationUnavailable(Exception):
    def __init__(self, message, retry=30):
        super().__init__(message)
        self.retry=retry
