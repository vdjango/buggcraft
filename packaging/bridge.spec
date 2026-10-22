from pathlib import Path

root = Path(SPECPATH).parent
assets = [(str(root / 'src/buggcraft/hookup' / name), 'hookup') for name in
          ('chat_protocols.json', 'legacy_packets.json', 'THIRD_PARTY_NOTICES.txt')]
assets.append((str(root / 'dist/bridge-build/bridge_build.json'), 'hookup'))
a = Analysis([str(root / 'packaging/bridge_entry.py')],
             pathex=[str(root / 'src/buggcraft')], binaries=[], datas=assets,
             hiddenimports=['aiortc'], hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=['PySide6', 'tkinter', 'pytest', 'unittest', 'numpy', 'IPython',
                       'minecraft_launcher_lib', 'plyer', 'notifypy'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='buggcraft-bridge',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='buggcraft-bridge')
