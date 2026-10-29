"""Player-facing network summary backed by bounded probes and native journals."""
import asyncio
from pathlib import Path
import time


def classify_network(probe):
    """Return a cautious category; a server probe is not proof of peer reachability."""
    if not isinstance(probe, dict) or not isinstance(probe.get('ipv4'), dict):
        return 'unknown'
    ipv4 = probe['ipv4']
    mapping = (ipv4.get('mapping') or {}).get('behavior')
    if ipv4.get('udp') != 'reachable':
        return 'unknown'
    if mapping == 'endpoint-independent':
        return 'direct_easier'
    if mapping in ('destination-dependent', 'destination-dependent-or-multiple-egress'):
        return 'relay_likely'
    return 'unknown'


def successful_session_counts(summary):
    direct = relay = 0
    for session in summary.get('sessions', []) if isinstance(summary, dict) else []:
        if not isinstance(session, dict):
            continue
        direct += bool(session.get('p2p_data_observed'))
        relay += any(isinstance(stream, dict) and stream.get('data_observed')
                     for stream in session.get('relay_streams', []))
    return {'direct_successes': direct, 'relay_successes': relay}


async def collect_network_profile():
    """Run bounded network detection and local evidence scans off the UI thread."""
    def collect():
        from utils.diagnostics import connection_session_directory
        from utils.nat_probe import probe_network
        from utils.p2p_evidence import summarize_player_logs

        directory = connection_session_directory()
        result = {'type': 'unknown', 'direct_successes': 0, 'relay_successes': 0}
        try:
            result['type'] = classify_network(probe_network(budget=8.0))
        except Exception:
            pass
        if directory:
            try:
                players = Path(directory).parent / 'players'
                cutoff = time.time() - 7 * 86400
                paths = sorted((path for path in players.glob('*/*.jsonl')
                                if path.stat().st_mtime >= cutoff), key=lambda path: path.stat().st_mtime,
                               reverse=True)[:128]
                result.update(successful_session_counts(summarize_player_logs(paths)))
            except (OSError, ValueError):
                pass
        return result

    return await asyncio.to_thread(collect)
