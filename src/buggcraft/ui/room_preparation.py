"""Preparation presentation: bounded local logs and authenticated member state."""
import time
import re
from datetime import datetime

from PySide6.QtCore import QTimer


def shared_log_text(text):
    """Remove private paths, URLs and credentials before transmitting a log."""
    from utils.diagnostics import redact
    text = redact(str(text))
    text = re.sub(r'(?i)(?:buggnode1-|bugg1-|acct1\.)[^\s]+', '[credential]', text)
    text = re.sub(r'(?i)[a-z]:[\\/][^\s]*|/(?:home|Users|tmp|var|opt)/[^\s]*', '[local path]', text)
    text = re.sub(r'https?://[^\s]+', '[download address]', text)
    return ''.join(c for c in text if c.isprintable())[:500]


class RoomPreparation:
    def init_preparation(self):
        self.room_reports = {}
        self.room_report_timer = QTimer(self)
        self.room_report_timer.setInterval(1600)
        self.room_report_timer.timeout.connect(self.flush_room_reports)
        self.room_report_timer.start()

    def apply_members(self, name, snapshot):
        record = self.records.get(name)
        if not record or not isinstance(snapshot, dict):
            return
        old = record.get('lobby', {})
        if snapshot.get('revision', -1) < old.get('revision', -1):
            return
        if snapshot.get('offset', 0):
            if snapshot.get('revision') != old.get('revision'):
                return
            rows = {row['id']: row for row in old.get('members', [])}
            rows.update({row['id']: row for row in snapshot.get('members', [])})
            snapshot = dict(snapshot, members=list(rows.values()), offset=0)
        elif snapshot.get('revision') == old.get('revision') and len(old.get('members', [])) > len(snapshot.get('members', [])):
            rows = {row['id']: row for row in snapshot.get('members', [])}
            rows.update({row['id']: row for row in old['members'] if row['id'] not in rows})
            snapshot = dict(snapshot, members=list(rows.values()), next=old.get('next'))
        previous = {row['id']: row for row in old.get('members', [])}
        record['lobby'] = snapshot
        record['isManager'] = snapshot.get('self_id') == snapshot.get('manager_id')
        logs = snapshot.get('logs', {})
        if record.get('remoteLogMember') not in logs.get('allowed', []):
            record['remoteLogs'] = []
            record['remoteLogMember'] = ''
        sharing = logs.get('sharing', False)
        if sharing != old.get('logs', {}).get('sharing', False):
            record['_logUploadCursor'] = 0
        if record['isManager'] and old:
            for row in snapshot.get('members', []):
                prior = previous.get(row['id'])
                if (row['id'] != snapshot.get('self_id') and prior and
                        row.get('state') in ('ready', 'failed', 'cancelled') and
                        (prior.get('state'), prior.get('task')) != (row.get('state'), row.get('task'))):
                    label = {'ready': '已准备好', 'failed': '准备失败', 'cancelled': '取消了准备'}[row['state']]
                    text = row.get('name', '玩家') + ' ' + label
                    results = record.setdefault('roomResults', [])
                    results.append(dict(text=text, time=datetime.now().strftime('%H:%M:%S')))
                    del results[:-30]
                    self.patch(notice=text)
                    self.room_notification.emit(text)
        if old.get('config_id') and old.get('config_id') != snapshot.get('config_id'):
            cancel = self.preparations.get(name)
            if cancel:
                cancel.set()
            record['preparedSource'] = None
            record.pop('preparedGame', None)
            record['prepareStatus'] = '房间配置已更新，请重新同步。'
            if snapshot.get('self_id') == snapshot.get('provider_id'):
                self.report_room_state(name, 'ready', 'verify')
        self.publish_connections()

    def more_members(self):
        name = self._state['selected']
        record = self.records.get(name, {})
        offset = record.get('lobby', {}).get('next')
        endpoint = self.service.endpoints.get(name)
        key = 'roommembers:' + name
        if endpoint and type(offset) is int and key not in self.jobs:
            self.job(key, endpoint.lobby_request('members', offset=offset))

    def add_prepare_log(self, record, message, category='game', level='info'):
        message = str(message)[:500]
        rows = record.setdefault('prepareLogs', [])
        if rows and rows[-1]['text'] == message:
            return
        record['_logSequence'] = record.get('_logSequence', 0) + 1
        rows.append(dict(seq=record['_logSequence'], time=datetime.now().strftime('%H:%M:%S'), text=message,
                         category=category, level=level))
        del rows[:-600]

    def report_room_state(self, name, state, stage='waiting', **counters):
        record = self.records.get(name)
        if not record or not record.get('lobby', {}).get('config_id'):
            return
        self.room_reports[name] = dict(state=state, stage=stage,
            config_id=record['lobby']['config_id'], task=record.get('prepareTask', ''),
            seq=time.monotonic_ns() // 1000, **counters)

    def flush_room_reports(self):
        for name, fields in list(self.room_reports.items()):
            endpoint = self.service.endpoints.get(name)
            key = 'roomstate:' + name
            if endpoint and hasattr(endpoint, 'lobby_request') and key not in self.jobs:
                self.room_reports.pop(name, None)
                self.job(key, endpoint.lobby_request('member_update', **fields))
        for name, record in list(self.records.items()):
            if not record.get('lobby', {}).get('logs', {}).get('sharing'):
                continue
            endpoint = self.service.endpoints.get(name)
            key = 'roomlogupload:' + name
            if not endpoint or key in self.jobs:
                continue
            rows = [row for row in record.get('prepareLogs', []) if row.get('seq', 0) > record.get('_logUploadCursor', 0)][:10]
            if rows:
                entries = [dict(seq=row['seq'], text=shared_log_text(row['text']), category=row['category'], level=row['level']) for row in rows]
                self.job(key, endpoint.lobby_request('logs_append', entries=entries))

    def log_action(self, action, data):
        name = self._state['selected']
        record = self.records.get(name, {})
        endpoint = self.service.endpoints.get(name)
        if not endpoint:
            raise ValueError('房间尚未连接。')
        if action == 'viewMemberLogs':
            target = data.get('member') or record.get('remoteLogMember')
            if not target:
                raise ValueError('玩家尚未授权或已撤回授权。')
            if target != record.get('remoteLogMember'):
                record.update(remoteLogs=[], remoteLogMember=target)
            record['remoteLogName'] = next((row['name'] for row in record.get('lobby', {}).get('members', []) if row['id'] == target), '玩家')
            offset = record['remoteLogs'][-1]['seq'] + 1 if record.get('remoteLogs') else 0
            key = 'roomlogread:' + name
            if key not in self.jobs:
                self.job(key, endpoint.lobby_request('logs_read', member=target, offset=offset))
            return
        op = {'requestMemberLogs': 'logs_request', 'answerLogRequest': 'logs_answer', 'revokeLogAccess': 'logs_revoke'}[action]
        fields = dict(member=data.get('member')) if action == 'requestMemberLogs' else dict(request=data.get('request'), allow=data.get('allow')) if action == 'answerLogRequest' else {}
        async def perform():
            await endpoint.lobby_request(op, **fields)
            return await endpoint.lobby_request('members')
        self.job('roommanage:' + name, perform())

    def member_action(self, action, data):
        name = self._state['selected']
        record = self.records.get(name, {})
        endpoint = self.service.endpoints.get(name)
        if not endpoint or record.get('state') != 'online':
            raise ValueError('请先连接房间。')
        operations = {'kickMember': 'member_kick', 'unblockMember': 'member_unblock',
                      'offerOwner': 'owner_offer', 'cancelOwner': 'owner_cancel', 'answerOwner': 'owner_answer'}
        if action != 'answerOwner' and not record.get('isManager'):
            raise ValueError('只有房主可以管理成员。')
        fields = {'offer': data.get('offer'), 'accept': data.get('accept')} if action == 'answerOwner' else {'member': data.get('member')}
        async def perform():
            await endpoint.lobby_request(operations[action], **fields)
            return await endpoint.lobby_request('members')
        self.job('roommanage:' + name, perform())

    def finish_room_action(self, key, value, error):
        if key.startswith('roommembers:'):
            if error:
                self.patch(error='成员列表暂时无法更新，请稍后重试。')
            else:
                self.apply_members(key.split(':', 1)[1], value)
            return True
        if key.startswith('roomlogupload:'):
            record = self.records.get(key.split(':', 1)[1])
            if record and not error:
                record['_logUploadCursor'] = value['next'] - 1
            return True
        if key.startswith('roomlogread:'):
            record = self.records.get(key.split(':', 1)[1])
            if record:
                if error:
                    record['remoteLogs'] = []
                    self.patch(error='无法读取日志，玩家可能已撤回授权。')
                elif value.get('member') == record.get('remoteLogMember'):
                    rows = record.setdefault('remoteLogs', [])
                    for row in value.get('entries', []):
                        if not rows or row['seq'] > rows[-1]['seq']:
                            rows.append(dict(row, time=datetime.fromtimestamp(row['time']).strftime('%H:%M:%S')))
                    del rows[:-200]
                self.publish_connections()
            return True
        if key.startswith('roommanage:'):
            if error:
                self.patch(error='操作未完成：' + str(error))
            else:
                self.apply_members(key.split(':', 1)[1], value)
                self.patch(error='')
            return True
        if key.startswith('roomstate:'):
            # An old configuration's final update can legitimately be rejected.
            return True
        return False
