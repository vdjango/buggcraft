"""Prepare inherited instances without installing their alias as a vanilla version."""
import json
import copy
import os
from pathlib import Path

import minecraft_launcher_lib

from core.downloads import MinecraftDownloader, verified_installation


def deduplicate_classpath(command):
    """Keep the first occurrence of each JAR in JVM class and module paths.

    BootstrapLauncher scans every classpath entry as a module. A repeated JAR
    can therefore abort NeoForge before Minecraft starts, even when both
    entries point to the exact same shared library file.
    """
    result = list(command)
    for index, argument in enumerate(result):
        if not isinstance(argument, str):
            continue
        if index and result[index - 1] in ('-cp', '-classpath', '--class-path', '-p', '--module-path'):
            classpath, prefix = argument, ''
        elif argument.startswith(('--class-path=', '--module-path=', '-DlegacyClassPath=')):
            prefix, classpath = argument.split('=', 1)
            prefix += '='
        else:
            continue
        entries, seen = [], set()
        for entry in classpath.split(os.pathsep):
            key = os.path.normcase(os.path.normpath(entry)) if entry else ''
            if key not in seen:
                seen.add(key)
                entries.append(entry)
        result[index] = prefix + os.pathsep.join(entries)
    return result


def version_chain(directory, version):
    root, seen, result = Path(directory), set(), []
    while version:
        if (not isinstance(version, str) or version in ('.', '..') or
                any(c in version for c in '/\\:') or not version):
            raise ValueError('游戏版本标识无效')
        if version in seen or len(seen) >= 32:
            raise ValueError('游戏版本继承存在循环或层数过多')
        seen.add(version)
        path = root / 'versions' / version / (version + '.json')
        metadata = json.loads(path.read_text(encoding='utf-8'))
        result.append((version, metadata))
        version = metadata.get('inheritsFrom')
    return result


def prepare_inherited(directory, version, callback, source='自动'):
    """Return the actual client JAR owner, or None for an ordinary version.

    launcher-lib's generic installer copies a missing child JAR in the wrong
    direction. A modpack alias intentionally has no JAR. Prepare its vanilla
    ancestor, then install only each loader layer's libraries and natives.
    """
    chain = version_chain(directory, version)
    if len(chain) == 1:
        return None
    root = Path(directory)
    base = chain[-1][0]
    if not verified_installation(directory, base):
        MinecraftDownloader(directory, source=source, status=callback.get('setStatus'),
                            file_event=callback.get('fileEvent'),
                            progress=lambda current, maximum: (
                                callback.get('setMax', lambda _: None)(maximum),
                                callback.get('setProgress', lambda _: None)(current))).install(base)
    # Import locally: the loader module also uses MinecraftDownloader.
    from core.loaders import _use_download_source
    with _use_download_source(source):
        minecraft_launcher_lib.install.install_libraries(
            version, resolved_metadata(chain).get('libraries', []), str(root), callback)
    jar_owner = next((metadata['jar'] for _, metadata in chain if metadata.get('jar')), None)
    if jar_owner is None:
        jar_owner = next((name for name, _ in chain
                          if (root / 'versions' / name / (name + '.jar')).is_file()), base)
    if (not isinstance(jar_owner, str) or jar_owner in ('.', '..') or
            not jar_owner or any(c in jar_owner for c in '/\\:')):
        raise ValueError('游戏核心版本标识无效')
    jar = root / 'versions' / jar_owner / (jar_owner + '.jar')
    if not jar.is_file():
        raise FileNotFoundError(f'缺少游戏核心：{jar}。请修复对应的基础游戏版本。')
    callback.get('setStatus', lambda _: None)(f'使用继承的游戏核心：{jar_owner}')
    return jar_owner


def prepare_standalone(directory, version, callback, source='自动'):
    """Keep a combined modpack self-contained when repairing libraries or JARs."""
    metadata = version_chain(directory, version)[0][1]
    from core.loaders import _use_download_source
    with _use_download_source(source):
        minecraft_launcher_lib.install.install_libraries(
            version, metadata.get('libraries', []), str(directory), callback)
    if not verified_installation(directory, version):
        MinecraftDownloader(directory, source=source, status=callback.get('setStatus'),
                            file_event=callback.get('fileEvent'),
                            progress=lambda current, maximum: (
                                callback.get('setMax', lambda _: None)(maximum),
                                callback.get('setProgress', lambda _: None)(current))).install_metadata(
                                    version, metadata, preserve_client=True)


def resolved_metadata(chain):
    """Resolve all ancestors; launcher-lib 7.x merges only one parent level."""
    def merge(parent, child):
        result = copy.deepcopy(parent)
        for key, value in child.items():
            if key == 'inheritsFrom':
                continue
            if key == 'libraries':
                def coordinate(item):
                    parts = item['name'].split(':')
                    return tuple(parts[:2] + parts[3:])
                overrides = {coordinate(item) for item in value}
                result[key] = copy.deepcopy(value) + [item for item in result.get(key, [])
                                                      if coordinate(item) not in overrides]
            elif isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = merge(result[key], value)
            elif isinstance(value, list) and isinstance(result.get(key), list):
                result[key] += copy.deepcopy(value)
            else:
                result[key] = copy.deepcopy(value)
        return result
    result = {}
    for name, metadata in reversed(chain):
        result = merge(result, metadata)
    return result


def exclude_version_jar_from_bootstrap_scan(metadata, version):
    """Keep Forge's ignoreList aligned with a standalone version JAR name."""
    arguments = metadata.get('arguments')
    if not isinstance(arguments, dict) or not isinstance(arguments.get('jvm'), list):
        return
    jar_name = version + '.jar'
    jvm = []
    for argument in arguments['jvm']:
        if isinstance(argument, str) and argument.startswith('-DignoreList='):
            key, names = argument.split('=', 1)
            if jar_name not in names.split(','):
                argument = key + '=' + names + ',' + jar_name
        jvm.append(argument)
    metadata['arguments'] = dict(arguments, jvm=jvm)


def inherited_command(directory, version, options, jar_owner):
    """Use launcher-lib argument helpers with fully resolved metadata in memory."""
    helper = minecraft_launcher_lib.command
    path = str(directory)
    data = resolved_metadata(version_chain(directory, version))
    data['jar'] = jar_owner
    options = dict(options)
    options.setdefault('nativesDirectory', str(Path(directory) / 'versions' / version / 'natives'))
    classpath = helper.get_libraries(data, path)
    command = [options.get('executablePath', 'java'), *options.get('jvmArguments', [])]
    arguments = data.get('arguments', {})
    if 'jvm' in arguments:
        command += helper.get_arguments(arguments['jvm'], data, path, options, classpath)
    else:
        command += ['-Djava.library.path=' + options['nativesDirectory'], '-cp', classpath]
    if data['mainClass'] == 'cpw.mods.bootstraplauncher.BootstrapLauncher':
        # Forge excludes ${version_name}.jar from its module scan. Aliases use
        # another owner's JAR, which must also be excluded to avoid loading both
        # vanilla and Forge's patched Minecraft module (duplicate packages).
        command = [argument + ',' + jar_owner + '.jar'
                   if argument.startswith('-DignoreList=') and jar_owner + '.jar' not in argument.split('=', 1)[1].split(',')
                   else argument for argument in command]
    if options.get('enableLoggingConfig') and data.get('logging', {}).get('client'):
        config = data['logging']['client']
        command.append(config['argument'].replace('${path}', str(Path(directory) / 'assets/log_configs' / config['file']['id'])))
    command.append(data['mainClass'])
    if 'minecraftArguments' in data:
        command += helper.get_arguments_string(data, path, options, classpath)
    else:
        command += helper.get_arguments(arguments.get('game', []), data, path, options, classpath)
    if 'server' in options:
        command += ['--server', options['server']]
        if 'port' in options:
            command += ['--port', options['port']]
    for key, flag in [('disableMultiplayer', '--disableMultiplayer'), ('disableChat', '--disableChat')]:
        if options.get(key):
            command.append(flag)
    return command
