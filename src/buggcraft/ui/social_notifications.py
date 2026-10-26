"""Read markers for social notifications, independent of polling and windows."""


class SocialNotifications:
    def __init__(self):
        self.seen = set()
        self.home_seen = set()
        self.read = set()

    @staticmethod
    def keys(state):
        groups = {
            'requests': [r for r in state.get('friendRequests', []) if r.get('incoming')],
            'invitations': state.get('friendInvitations', []),
            'joinRequests': [r for r in state.get('joinRequests', []) if r.get('incoming')],
        }
        return {kind: {(kind, r['id']) for r in items if isinstance(r.get('id'), str)}
                for kind, items in groups.items()}

    def update(self, state):
        groups = self.keys(state)
        new = set().union(*groups.values()) - self.seen
        self.seen.update(new)
        if any(kind in ('invitations', 'joinRequests') for kind, _ in new):
            return 'invite'
        return 'request' if new else ''

    def acknowledge_home(self, state):
        self.home_seen.update(set().union(*self.keys(state).values()))

    def mark_read(self, state, kind):
        keys = self.keys(state).get(kind, set())
        changed = bool(keys - self.read)
        self.read.update(keys)
        self.home_seen.update(keys)
        return changed

    def view(self, state):
        groups = self.keys(state)
        unread = {kind: len(keys - self.read) for kind, keys in groups.items()}
        pending = set().union(*groups.values())
        return dict(unread, total=len(pending), homeAttention=bool(pending - self.home_seen),
                    urgent=bool((groups['invitations'] | groups['joinRequests']) - self.read))
