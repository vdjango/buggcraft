"""Installation choices; see docs/guides/整合包导入与兼容.md."""

LOADERS = ('Forge', 'NeoForge', 'Fabric', 'Quilt')
COMPONENTS = (*LOADERS, 'OptiFine', 'Fabric API', 'QSL/QFAPI')


def incompatibility(component, selected_loader):
    """Return the reason a component is blocked by the committed loader."""
    if not selected_loader or component == selected_loader:
        return ''
    allowed = {
        'Forge': {'Forge', 'OptiFine'},
        'NeoForge': {'NeoForge'},
        'Fabric': {'Fabric', 'Fabric API'},
        'Quilt': {'Quilt', 'Fabric API', 'QSL/QFAPI'},
    }
    if component not in allowed.get(selected_loader, set()):
        return f'与 {selected_loader} 不兼容'
    return ''


def validate_loaders(names):
    names = list(names)
    if any(name not in LOADERS for name in names):
        raise ValueError('整合包包含暂不支持的加载器')
    if len(names) != len(set(names)) or len(names) > 1:
        raise ValueError('Forge、NeoForge、Fabric、Quilt 互斥，不能在同一实例中安装多个加载器')
