"""Finish the trimmed runtime before Nuitka 4.3.1 embeds its onefile payload."""
import importlib.util
import json
import os
from pathlib import Path

from nuitka.plugins.PluginBase import NuitkaPluginBase


class LauncherPayload(NuitkaPluginBase):
    plugin_name = 'launcher'
    plugin_desc = 'Include the native multiplayer install tree and trim unused Qt DLLs.'

    @classmethod
    def addPluginCommandLineOptions(cls, group):
        group.add_option('--launcher-native', dest='launcher_native', action='store',
                         help='Complete CMake install tree to embed in the launcher.')

    def __init__(self, launcher_native=None):
        self.native = launcher_native

    def onStandaloneDistributionFinished(self, dist_dir):
        if not self.native:
            self.sysexit('A complete native install tree is required for the single-file launcher.')
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location('_launcher_build', root / 'build.py')
        build = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build)
        runtime = Path(dist_dir).resolve()
        build.stage_native_bridge(runtime, Path(self.native))
        removed = (build.trim_qt_libraries(runtime, runtime.parent / 'qt-unused')
                   if os.name == 'nt' else build.trim_unix_qt_libraries(runtime, runtime.parent / 'qt-unused'))
        build.validate_runtime_inventory(runtime)
        (runtime.parent / 'qt-trim-report.json').write_text(json.dumps(removed, indent=2), encoding='utf-8')
        self.info('Prepared complete native multiplayer runtime and removed %d unused Qt DLLs.' % len(removed))
