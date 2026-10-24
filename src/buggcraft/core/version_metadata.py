"""Minecraft release identity independent of a custom instance's display name."""


def base_version(metadata, fallback):
    modpack = metadata.get('buggcraftModpack')
    room = metadata.get('buggcraftRoom')
    for value in (metadata.get('clientVersion'),
                  modpack.get('minecraft') if isinstance(modpack, dict) else None,
                  room.get('version') if isinstance(room, dict) else None):
        if isinstance(value, str) and value:
            return value
    return fallback
