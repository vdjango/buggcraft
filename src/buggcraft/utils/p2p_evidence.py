"""Conservative summary of observed ICE and game paths from native journals."""
import json
from pathlib import Path


def summarize_player_logs(paths):
    sessions, streams, pairs = {}, {}, []
    malformed, read_bytes, truncated = 0, 0, False
    for path in paths:
        if read_bytes >= 64 * 1024 * 1024:
            truncated = True
            break
        try:
            with Path(path).open('rb') as stream:
                for raw in stream:
                    read_bytes += len(raw)
                    if read_bytes > 64 * 1024 * 1024:
                        truncated = True
                        break
                    if len(raw) > 8192:
                        malformed += 1
                        continue
                    try:
                        row = json.loads(raw)
                    except (ValueError, UnicodeDecodeError):
                        malformed += 1
                        continue
                    if not isinstance(row, dict) or not isinstance(row.get('session'), str):
                        continue
                    if row['session'] not in sessions and len(sessions) >= 64:
                        truncated = True
                        continue
                    session = sessions.setdefault(row['session'], {
                        'session': row['session'], 'selected_pair_families': [],
                        'p2p_streams': [], 'relay_streams': [], 'failures': []})
                    event = row.get('event')
                    if event == 'peer_selected_pair':
                        local, remote = row.get('local_endpoint', []), row.get('remote_endpoint', [])
                        if (isinstance(local, list) and isinstance(remote, list) and local and remote
                                and isinstance(local[0], dict) and isinstance(remote[0], dict)
                                and local[0].get('family') == remote[0].get('family')):
                            family = local[0].get('family')
                            if family in (4, 6):
                                session['selected_pair_families'].append(family)
                                if len(pairs) < 256:
                                    pairs.append({'session': row['session'], 'attempt': row.get('attempt'),
                                                  'family': family, 'local': local[0], 'remote': remote[0]})
                    if event in ('peer_failed', 'peer_fallback', 'peer_timeout',
                                 'peer_failure_details', 'peer_heartbeat_timeout'):
                        session['failures'].append({k: row[k] for k in
                            ('event', 'attempt', 'reason', 'ice_state', 'peer_state',
                             'local_endpoints', 'remote_endpoints') if k in row})
                        session['failures'] = session['failures'][-32:]
                    if not isinstance(row.get('stream', ''), str) or not row.get('stream'):
                        continue
                    key = (row['session'], row['stream'])
                    # Journals can write stream_closed before the corresponding game_path
                    # record on shutdown. Keep both records and join them after scanning.
                    if len(streams) < 512 or key in streams:
                        item = streams.setdefault(key, {'session': row['session'], 'stream': row['stream'],
                                                        'paths': set(), 'data_observed': False,
                                                        'closed': False, 'sent_bytes': 0, 'received_bytes': 0})
                        if event == 'game_path' and row.get('path') in ('p2p', 'relay'):
                            item['paths'].add(row['path'])
                        if event in ('stream_sample', 'stream_closed'):
                            if event == 'stream_closed':
                                item['closed'] = True
                            if type(row.get('sent_bytes')) is int and type(row.get('received_bytes')) is int:
                                item['sent_bytes'] = max(item['sent_bytes'], row['sent_bytes'])
                                item['received_bytes'] = max(item['received_bytes'], row['received_bytes'])
                                item['data_observed'] |= row['sent_bytes'] > 0 and row['received_bytes'] > 0
                    else:
                        truncated = True
        except OSError:
            malformed += 1
    for item in streams.values():
        paths = sorted(item.pop('paths'))
        for path in paths:
            item_for_path = dict(item, path=path, mixed_paths=len(paths) > 1,
                                 data_observed=item['data_observed'] and len(paths) == 1)
            sessions[item['session']][path + '_streams'].append(item_for_path)
    for session in sessions.values():
        session['selected_pair_families'] = sorted(set(session['selected_pair_families']))
        session['p2p_data_observed'] = any(s['data_observed'] for s in session['p2p_streams'])
    return {'schema': 1, 'sessions': list(sessions.values()), 'selected_pairs': pairs,
            'malformed_or_unreadable': malformed, 'scanned_bytes': read_bytes, 'truncated': truncated,
            'notice': 'A selected pair proves ICE connectivity; game bytes are separate evidence. '
                      'A host/VM or LAN pair is not proof of WAN NAT traversal. '
                      'Network probes alone do not establish compatibility with another peer.'}
