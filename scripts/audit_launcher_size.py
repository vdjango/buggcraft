"""Inventory the delivered ZIP and source resources without changing either."""

import argparse
import csv
import hashlib
import json
import struct
from collections import defaultdict
from pathlib import Path
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]


def category(name):
    if name == "Buggcraft.exe":
        return "application_executable"
    if name.startswith(("av/", "av.libs/", "pylibsrtp/")):
        return "webrtc_media_dependencies"
    if name.startswith(("qt6", "PySide6/", "shiboken6", "pyside6")):
        return "qt_and_bindings"
    if name == "opengl32sw.dll":
        return "software_opengl"
    if name.startswith("resources/fonts/"):
        return "fonts"
    if name.startswith(("resources/images/", "resources/icons/", "resources/settings/")):
        return "images_and_icons"
    if name.startswith("resources/"):
        return "other_resources"
    if name in ("python311.dll", "python3.dll"):
        return "python_runtime_dlls"
    if name.startswith(("cryptography/", "libcrypto", "libssl")):
        return "crypto"
    return "other_dependencies"


def write_csv(path, fields, rows):
    # BOM lets Windows spreadsheet software recognize Chinese paths correctly.
    with path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def audit(archive, resources, output_dir):
    source_files = sorted(p for p in resources.rglob("*") if p.is_file())
    duplicates = defaultdict(list)
    for path in source_files:
        duplicates[hashlib.sha256(path.read_bytes()).digest()].append(path)

    with ZipFile(archive) as package:
        entries = [item for item in package.infolist() if not item.is_dir()]
        by_name = {item.filename: item for item in entries}
        groups = defaultdict(lambda: {"files": 0, "raw_bytes": 0, "zip_payload_bytes": 0})
        package_rows = []
        for item in sorted(entries, key=lambda i: (-i.compress_size, i.filename)):
            group = category(item.filename)
            groups[group]["files"] += 1
            groups[group]["raw_bytes"] += item.file_size
            groups[group]["zip_payload_bytes"] += item.compress_size
            package_rows.append({"path": item.filename, "category": group,
                                 "raw_bytes": item.file_size,
                                 "zip_payload_bytes": item.compress_size})

        resource_rows = []
        for path in sorted(source_files, key=lambda p: (-p.stat().st_size, p.as_posix())):
            data = path.read_bytes()
            name = "resources/" + path.relative_to(resources).as_posix()
            item = by_name.get(name)
            width, height = "", ""
            if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
                width, height = struct.unpack(">II", data[16:24])
            identical = ["resources/" + p.relative_to(resources).as_posix()
                         for p in duplicates[hashlib.sha256(data).digest()] if p != path]
            resource_rows.append({
                "path": name, "source_bytes": len(data), "png_width": width,
                "png_height": height, "in_archive": item is not None,
                "raw_bytes": item.file_size if item else "",
                "zip_payload_bytes": item.compress_size if item else "",
                "same_as_source": package.read(item) == data if item else "",
                "duplicate_source_paths": "; ".join(identical),
            })

    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "launcher-package-inventory.csv",
              ["path", "category", "raw_bytes", "zip_payload_bytes"], package_rows)
    write_csv(output_dir / "launcher-resource-inventory.csv",
              ["path", "source_bytes", "png_width", "png_height", "in_archive",
               "raw_bytes", "zip_payload_bytes", "same_as_source", "duplicate_source_paths"],
              resource_rows)
    payload = sum(item.compress_size for item in entries)
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"archive": archive.name, "sha256": digest, "files": len(entries),
            "archive_bytes": archive.stat().st_size, "zip_payload_bytes": payload,
            "zip_metadata_bytes": archive.stat().st_size - payload,
            "raw_bytes": sum(item.file_size for item in entries),
            "source_resources": len(source_files), "categories": dict(sorted(groups.items()))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path,
                        default=ROOT / "dist/Buggcraft-runtime-windows-x64.zip")
    parser.add_argument("--resources", type=Path, default=ROOT / "resources")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist/size-audit")
    args = parser.parse_args()
    if not args.archive.is_file() or not args.resources.is_dir():
        parser.error("--archive must be a ZIP file and --resources must be a directory")
    print(json.dumps(audit(args.archive, args.resources, args.output_dir),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
