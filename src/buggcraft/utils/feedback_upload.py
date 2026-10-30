"""Submit a diagnostics archive only after an explicit user action."""
import json
from pathlib import Path
import tempfile

MAX_ARCHIVE = 20 * 1024 * 1024


async def submit_diagnostics(profile, title, description, *, consent):
    if consent is not True:
        raise ValueError('未确认上传诊断日志')
    title, description = str(title).strip(), str(description).strip()
    if not title or len(title) > 120 or not description or len(description) > 4000:
        raise ValueError('请填写问题标题和描述')
    if len(json.dumps({'title': title, 'description': description}, ensure_ascii=False).encode('utf-8')) > 6500:
        raise ValueError('标题和描述合计超过 6500 UTF-8 字节，请缩短后提交')
    from utils.diagnostics import export_connection_diagnostics
    from utils.http_identity import LAUNCHER_VERSION
    from hookup.native_routes import NativeRoutes
    import platform

    from utils.storage_paths import temporary_directory
    with tempfile.TemporaryDirectory(prefix='feedback-', dir=temporary_directory()) as temporary:
        archive = Path(temporary) / 'diagnostics.zip'
        await export_connection_diagnostics(archive)
        size = archive.stat().st_size
        if not 0 < size <= MAX_ARCHIVE:
            raise ValueError('诊断包超过节点 20 MiB 限制，请先单独导出后检查')
        from zipfile import ZipFile, BadZipFile
        game_version = '未选择'
        try:
            with ZipFile(archive) as bundle:
                manifest = json.loads(bundle.read('diagnostics.json'))
                selected = manifest.get('selected_game', {}).get('version')
                if isinstance(selected, str) and selected.strip():
                    game_version = selected[:120]
        except (BadZipFile, KeyError, ValueError, AttributeError):
            pass
        metadata = {'title': title, 'description': description,
                    'game_version': game_version, 'launcher_version': LAUNCHER_VERSION,
                    'system': platform.platform()[:120], 'loader': ''}
        routes = NativeRoutes(force_process=True)
        try:
            node = await routes.handle(profile)
            if not routes.feedback_support:
                raise ValueError('原生联机桥尚不支持诊断上传，请更新完整启动器；可先使用“导出日志”')
            return await routes.request('feedback.submit', {
                'node': node, 'consent': True, 'archive': str(archive),
                'metadata': metadata})
        finally:
            await routes.close()
