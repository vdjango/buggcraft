"""Verified Minecraft downloads without UI dependencies or global HTTP patches."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlsplit

import requests

from utils.archives import extract_zip


MANIFEST_URL = "https://launchermeta.mojang.com/mc/game/version_manifest_v2.json"
MIRROR = "https://bmclapi2.bangbang93.com"


class _DownloadSession(requests.Session):
    def rebuild_auth(self, prepared_request, response):
        super().rebuild_auth(prepared_request, response)
        if not (urlsplit(prepared_request.url).hostname or '').endswith('.forgecdn.net'):
            prepared_request.headers.pop('x-api-key', None)


class DownloadCancelled(Exception):
    pass


def _resolved(path):
    value = str(Path(path).resolve())
    # Windows can retain the extended prefix when another worker creates a parent.
    if os.name == 'nt' and value.startswith('\\\\?\\'):
        value = '\\\\' + value[8:] if value.startswith('\\\\?\\UNC\\') else value[4:]
    return Path(value)


def _sha1(path):
    digest = hashlib.sha1()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verified_installation(directory, version):
    """Check the local installation receipt without needing an Internet connection."""
    root = _resolved(directory)
    try:
        receipt = json.loads((root / 'versions' / version / '.buggcraft-complete.json').read_text(encoding='utf-8'))
        if receipt.get('version') != version or not receipt.get('files'):
            return False
        for item in receipt['files']:
            target = _resolved(root / item['path'])
            if not target.is_relative_to(root) or not target.is_file():
                return False
            if item.get('sha1') and _sha1(target) != item['sha1']:
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


class MinecraftDownloader:
    def __init__(self, directory, source="自动", cancel=None, status=None, progress=None):
        self.root = _resolved(directory)
        self.source = source
        self.cancel = cancel if cancel is not None else threading.Event()
        self.status = status or (lambda message: None)
        self.progress = progress or (lambda current, maximum: None)
        self._sessions = threading.local()
        self._verified = {}
        self._verified_lock = threading.Lock()
        self.system = {"Windows": "windows", "Darwin": "osx"}.get(platform.system(), "linux")

    def check_cancelled(self):
        if self.cancel.is_set():
            raise DownloadCancelled("下载已取消，已校验文件会保留，重试时继续使用")

    def urls(self, original):
        parsed = urlsplit(original)
        replacements = {
            "launchermeta.mojang.com": "",
            "piston-meta.mojang.com": "",
            "launcher.mojang.com": "",
            "piston-data.mojang.com": "",
            "resources.download.minecraft.net": "/assets",
            "libraries.minecraft.net": "/maven",
        }
        if parsed.hostname not in replacements or self.source == "官方":
            return [original]
        mirror = MIRROR + replacements[parsed.hostname] + parsed.path
        if parsed.query:
            mirror += "?" + parsed.query
        return [mirror, original] if self.source == "BMCLAPI" else [original, mirror]

    def inside(self, relative):
        target = _resolved(self.root / relative)
        if target == self.root or not target.is_relative_to(self.root):
            raise ValueError(f"下载路径超出游戏目录：{relative} ({target!s}; root={self.root!s})")
        return target

    def fetch(self, url, relative, sha1=None, size=None):
        """Download into a temporary file; never publish truncated files."""
        target = self.inside(relative)
        self.check_cancelled()
        if target.is_file() and sha1 and _sha1(target) == sha1:
            with self._verified_lock:
                self._verified[str(target.relative_to(self.root))] = sha1
            return target
        errors = []
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".buggcraft-part")
        for candidate in self.urls(url):
            for attempt in range(3):
                self.check_cancelled()
                try:
                    session = getattr(self._sessions, 'session', None)
                    if session is None:
                        session = _DownloadSession()
                        self._sessions.session = session
                    with session.get(candidate, stream=True, timeout=(8, 20),
                                      headers={"User-Agent": "Buggcraft/1.0", **getattr(self, 'request_headers', {})}) as response:
                        response.raise_for_status()
                        digest = hashlib.sha1()
                        downloaded = 0
                        with temporary.open("wb") as output:
                            for chunk in response.iter_content(128 * 1024):
                                self.check_cancelled()
                                if chunk:
                                    output.write(chunk)
                                    digest.update(chunk)
                                    downloaded += len(chunk)
                        if sha1 and digest.hexdigest() != sha1:
                            raise ValueError(f"文件校验失败：{target.name}")
                        expected = size if size is not None else response.headers.get("Content-Length")
                        if expected is not None and downloaded != int(expected):
                            raise ValueError(f"文件长度不完整：{target.name}")
                    os.replace(temporary, target)
                    with self._verified_lock:
                        self._verified[str(target.relative_to(self.root))] = sha1
                    return target
                except DownloadCancelled:
                    raise
                except (requests.RequestException, OSError, ValueError) as exc:
                    errors.append(str(exc))
                    self.check_cancelled()
                    if attempt < 2 and self.cancel.wait(0.5 * (attempt + 1)):
                        self.check_cancelled()
                finally:
                    temporary.unlink(missing_ok=True)
        raise RuntimeError(f"下载 {target.name} 失败：{errors[-1] if errors else url}")

    def manifest(self):
        self.status("正在获取 Minecraft 版本列表…")
        # Fetch to a per-request name so opening a list cannot race an install.
        import uuid
        path = self.fetch(MANIFEST_URL, f".buggcraft-downloads/manifest-{uuid.uuid4().hex}.json")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data.get("versions"), list):
                raise ValueError("版本列表格式不正确")
            return data
        finally:
            path.unlink(missing_ok=True)

    def allowed(self, rules):
        if not rules:
            return True
        allowed = False
        for rule in rules:
            os_rule = rule.get("os", {})
            if os_rule.get("name", self.system) != self.system:
                continue
            if "version" in os_rule and not re.search(os_rule["version"], platform.version()):
                continue
            if "arch" in os_rule and not re.search(os_rule["arch"], platform.machine()):
                continue
            if any(value is not False for value in rule.get("features", {}).values()):
                continue
            allowed = rule.get("action") == "allow"
        return allowed

    def _batch(self, jobs, label):
        # Dedupe shared objects before scheduling to avoid competing file writers.
        jobs = list({str(job[1]): job for job in jobs}.values())
        self.status(label)
        self.progress(0, len(jobs))
        if not jobs:
            return
        with ThreadPoolExecutor(max_workers=8, thread_name_prefix="minecraft-download") as pool:
            futures = [pool.submit(self.fetch, *job) for job in jobs]
            try:
                for completed, future in enumerate(as_completed(futures), 1):
                    future.result()
                    self.check_cancelled()
                    self.progress(completed, len(jobs))
            except BaseException:
                for future in futures:
                    future.cancel()
                self.cancel.set()
                raise

    def install(self, version):
        if not version or version in (".", "..") or any(c in version for c in '/\\:'):
            raise ValueError("无效的游戏版本")
        self.status(f"正在准备 Minecraft {version}…")
        manifest = self.manifest()
        entry = next((item for item in manifest["versions"] if item["id"] == version), None)
        if entry is None:
            raise ValueError(f"未找到 Minecraft {version}")
        metadata_path = self.fetch(entry["url"], f".buggcraft-downloads/{version}.json", entry.get("sha1"))
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("id") != version:
            raise ValueError("版本元数据与所选版本不一致")

        jobs, natives = [], []
        for library in metadata.get("libraries", []):
            if not self.allowed(library.get("rules")):
                continue
            downloads = library.get("downloads", {})
            artifact = downloads.get("artifact")
            if artifact and artifact.get("url"):
                jobs.append((artifact["url"], "libraries/" + artifact["path"], artifact.get("sha1"), artifact.get("size")))
            classifier = library.get("natives", {}).get(self.system)
            if classifier:
                classifier = classifier.replace("${arch}", "64" if platform.architecture()[0] == "64bit" else "32")
                native = downloads.get("classifiers", {}).get(classifier)
                if not native:
                    raise ValueError(f"缺少本机依赖：{library.get('name')}")
                relative = "libraries/" + native["path"]
                jobs.append((native["url"], relative, native.get("sha1"), native.get("size")))
                natives.append(relative)
        client = metadata["downloads"]["client"]
        jobs.append((client["url"], f"versions/{version}/{version}.jar", client.get("sha1"), client.get("size")))
        logging = metadata.get("logging", {}).get("client", {}).get("file")
        if logging:
            jobs.append((logging["url"], "assets/log_configs/" + logging["id"], logging.get("sha1"), logging.get("size")))
        self._batch(jobs, "正在下载游戏客户端和依赖库…")

        index = metadata.get("assetIndex")
        if index:
            index_path = self.fetch(index["url"], "assets/indexes/" + index["id"] + ".json", index.get("sha1"), index.get("size"))
            assets = json.loads(index_path.read_text(encoding="utf-8"))
            objects = assets["objects"]
            self._batch([
                (f"https://resources.download.minecraft.net/{obj['hash'][:2]}/{obj['hash']}",
                 f"assets/objects/{obj['hash'][:2]}/{obj['hash']}", obj["hash"], obj.get("size"))
                for obj in objects.values()
            ], "正在下载游戏资源…")
            # Early Minecraft versions look up assets by their logical names.
            if assets.get("virtual") or assets.get("map_to_resources"):
                import shutil
                for name, obj in objects.items():
                    self.check_cancelled()
                    source = self.inside(f"assets/objects/{obj['hash'][:2]}/{obj['hash']}")
                    roots = []
                    if assets.get("virtual"):
                        roots.append("assets/virtual/" + index["id"])
                    if assets.get("map_to_resources"):
                        roots.append("resources")
                    for root in roots:
                        destination = self.inside(root + "/" + name)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(source, destination)

        self.status("正在完成安装并校验本机依赖…")
        for relative in natives:
            self.check_cancelled()
            with zipfile.ZipFile(self.inside(relative)) as archive:
                extract_zip(archive, self.inside(f"versions/{version}/natives"))
        natives_root = self.inside(f"versions/{version}/natives")
        if natives_root.is_dir():
            for path in natives_root.rglob('*'):
                if path.is_file():
                    self._verified[str(path.relative_to(self.root))] = _sha1(path)
        self.check_cancelled()
        # Publish the version only after every required file has passed validation.
        destination = self.inside(f"versions/{version}/{version}.json")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".json.buggcraft-part")
        temporary.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, destination)
        receipt = {
            'version': version,
            'files': [{'path': relative, 'sha1': sha1} for relative, sha1 in self._verified.items()
                      if not relative.startswith('.buggcraft-downloads')],
        }
        receipt['files'].append({'path': str(destination.relative_to(self.root)), 'sha1': _sha1(destination)})
        receipt_path = destination.parent / '.buggcraft-complete.json'
        receipt_tmp = receipt_path.with_suffix('.tmp')
        receipt_tmp.write_text(json.dumps(receipt), encoding='utf-8')
        os.replace(receipt_tmp, receipt_path)
        self.status("安装完成")
