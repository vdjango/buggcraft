"""Identify loaders from launch metadata, never from an instance's display name."""


def metadata_loader(metadata):
    arguments = metadata.get('arguments', {}).get('game', [])
    options = {key: arguments[index + 1] for index, key in enumerate(arguments[:-1])
               if isinstance(key, str) and key.startswith('--')
               and isinstance(arguments[index + 1], str)}
    libraries = [item.get('name', '') for item in metadata.get('libraries', [])
                 if isinstance(item, dict) and isinstance(item.get('name'), str)]
    # NeoForge 1.20.1 still uses forgeVersion, forgeclient and some Forge
    # libraries. Its Maven group, not those compatibility names, identifies it.
    neo = next((name for name in libraries if name.startswith(
        ('net.neoforged:neoforge:', 'net.neoforged:forge:'))), '')
    if neo or (options.get('--fml.neoForgeVersion') and any(
            name.startswith('net.neoforged') for name in libraries)) or (
            options.get('--fml.forgeGroup') == 'net.neoforged' and any(
                name.startswith(('net.neoforged:', 'net.minecraftforge:fmlloader:')) for name in libraries)):
        version = options.get('--fml.neoForgeVersion') or options.get('--fml.forgeVersion') or (neo.split(':')[2] if neo else '')
        mc = options.get('--fml.mcVersion', '')
        if mc and version.startswith(mc + '-'):
            version = version[len(mc) + 1:]
        return 'neoforge', version
    for prefix, loader in [('net.fabricmc:fabric-loader:', 'fabric'),
                           ('org.quiltmc:quilt-loader:', 'quilt'),
                           ('net.minecraftforge:forge:', 'forge'),
                           ('net.minecraftforge:fmlloader:', 'forge'),
                           ('net.minecraftforge:fmlcore:', 'forge')]:
        name = next((name for name in libraries if name.startswith(prefix)), '')
        if name:
            version = name.split(':')[2]
            return loader, options.get('--fml.forgeVersion', version) if loader == 'forge' else version
    return 'vanilla', ''
