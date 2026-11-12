#include "platform/files/game_files.h"

#include <QCoreApplication>
#include <QCryptographicHash>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QSaveFile>
#include <QSet>
#include <stdexcept>
#include <vector>

#include "miniz.h"

namespace bugg {
void copy_file(const QString& source, const QString& destination, const Cancellation& cancelled) {
  if (QFileInfo::exists(destination)) throw std::runtime_error("Destination already exists");
  QFile input(source);
  QSaveFile output(destination);
  QDir().mkpath(QFileInfo(destination).absolutePath());
  if (!input.open(QIODevice::ReadOnly) || !output.open(QIODevice::WriteOnly))
    throw std::runtime_error("Cannot open file");
  while (!input.atEnd()) {
    check_cancelled(cancelled);
    const auto block = input.read(1024 * 1024);
    if ((block.isEmpty() && input.error() != QFile::NoError) || output.write(block) != block.size())
      throw std::runtime_error("Cannot copy file");
  }
  check_cancelled(cancelled);
  if (!output.commit()) throw std::runtime_error("Cannot commit file");
}
namespace {
[[noreturn]] void fail(const QString& text) { throw std::runtime_error(text.toUtf8().constData()); }
class Archive {
 public:
  explicit Archive(const QString& path) {
    file.setFileName(path);
    if (!file.open(QIODevice::ReadOnly))
      fail(QCoreApplication::translate("Bugg", "无法打开压缩文件"));
    zip.m_pIO_opaque = &file;
    zip.m_pRead = [](void* value, mz_uint64 offset, void* buffer, size_t bytes) -> size_t {
      auto* input = static_cast<QFile*>(value);
      return input->seek(offset) ? qMax<qint64>(0, input->read(static_cast<char*>(buffer), bytes))
                                 : 0;
    };
    if (!mz_zip_reader_init(&zip, file.size(), 0))
      fail(QCoreApplication::translate("Bugg", "压缩文件损坏"));
  }
  ~Archive() { mz_zip_reader_end(&zip); }
  QFile file;
  mz_zip_archive zip{};
};
}  // namespace
QString portable_cache_root(const QString& portable) {
  QFile locator(QDir(portable).filePath("bugg-portable.json"));
  if (locator.open(QIODevice::ReadOnly) && locator.size() <= 16384) {
    const auto value = QJsonDocument::fromJson(locator.readAll()).object()["cache"].toString();
    if (!value.isEmpty()) return QDir::cleanPath(QDir(portable).absoluteFilePath(value));
  }
  return QDir(portable).filePath(".buggcraft");
}
QString safe_path(const QString& root, const QString& relative) {
  QString normalized = relative;
  normalized.replace('\\', '/');
  if (normalized.isEmpty() || QDir::isAbsolutePath(normalized) || normalized.contains(':') ||
      normalized.split('/').contains("..") || normalized.contains(QChar::Null))
    fail(QCoreApplication::translate("Bugg", "资源包含不安全路径"));
  const auto base = QDir(root).absolutePath();
  const auto target = QDir::cleanPath(base + '/' + normalized);
  if (!target.startsWith(base + '/')) fail(QCoreApplication::translate("Bugg", "资源路径越界"));
  auto parent = QFileInfo(target);
  while (parent.absoluteFilePath().startsWith(base + '/')) {
    if (parent.isSymLink()) fail(QCoreApplication::translate("Bugg", "资源路径包含符号链接"));
    parent = QFileInfo(parent.absolutePath());
  }
  return target;
}
QJsonObject read_json(const QString& path) {
  QFile file(path);
  if (!file.open(QIODevice::ReadOnly) || file.size() > 32 * 1024 * 1024)
    fail(QCoreApplication::translate("Bugg", "无法读取版本/配置文件：") +
         QFileInfo(path).fileName());
  QJsonParseError error;
  const auto document = QJsonDocument::fromJson(file.readAll(), &error);
  if (error.error != QJsonParseError::NoError || !document.isObject())
    fail(QCoreApplication::translate("Bugg", "版本/配置 JSON 无效"));
  return document.object();
}
void write_json(const QString& path, const QJsonObject& object) {
  QDir().mkpath(QFileInfo(path).absolutePath());
  QSaveFile file(path);
  const auto data = QJsonDocument(object).toJson();
  if (!file.open(QIODevice::WriteOnly) || file.write(data) != data.size() || !file.commit())
    fail(QCoreApplication::translate("Bugg", "无法保存版本/配置文件"));
}
void check_cancelled(const Cancellation& cancelled) {
  if (cancelled && cancelled->load()) fail(QCoreApplication::translate("Bugg", "已取消"));
}
bool valid_file(const QString& path, const QByteArray& sha1, qint64 size,
                const Cancellation& cancelled) {
  QFile file(path);
  if (!file.open(QIODevice::ReadOnly) || file.size() <= 0 || (size >= 0 && size != file.size()))
    return false;
  if (sha1.isEmpty()) return true;
  QCryptographicHash hash(QCryptographicHash::Sha1);
  while (!file.atEnd()) {
    check_cancelled(cancelled);
    hash.addData(file.read(1024 * 1024));
  }
  return hash.result().toHex() == sha1.toLower();
}
QByteArray archive_read(const QString& path, const QString& entry, qint64 limit,
                       const Cancellation& cancelled) {
  check_cancelled(cancelled);
  Archive archive(path);
  const int index = mz_zip_reader_locate_file(&archive.zip, entry.toUtf8().constData(), nullptr, 0);
  mz_zip_archive_file_stat info;
  if (index < 0 || !mz_zip_reader_file_stat(&archive.zip, index, &info) ||
      limit < 0 || info.m_uncomp_size > quint64(limit))
    fail(QCoreApplication::translate("Bugg", "安装器缺少有效的 ") + entry);
  QByteArray bytes(info.m_uncomp_size, Qt::Uninitialized);
  if (!mz_zip_reader_extract_to_mem(&archive.zip, index, bytes.data(), bytes.size(), 0))
    fail(QCoreApplication::translate("Bugg", "读取压缩内容失败"));
  check_cancelled(cancelled);
  return bytes;
}
void archive_extract(const QString& path, const QString& destination, const QString& prefix,
                     const QStringList& excludes, const Cancellation& cancelled,
                     bool preserve_executable) {
  Archive archive(path);
  quint64 total = 0;
  const auto count = mz_zip_reader_get_num_files(&archive.zip);
  if (count > 100000) fail(QCoreApplication::translate("Bugg", "压缩文件条目过多"));
  for (mz_uint index = 0; index < count; ++index) {
    check_cancelled(cancelled);
    mz_zip_archive_file_stat info;
    if (!mz_zip_reader_file_stat(&archive.zip, index, &info))
      fail(QCoreApplication::translate("Bugg", "压缩目录损坏"));
    const auto name = QString::fromUtf8(info.m_filename);
    if (!name.startsWith(prefix) || info.m_is_directory) continue;
    const auto relative = name.mid(prefix.size());
    if (relative.isEmpty()) continue;
    bool skip = false;
    for (const auto& exclude : excludes) skip |= relative.startsWith(exclude);
    if (skip) continue;
    if (((info.m_external_attr >> 16) & 0170000) == 0120000)
      fail(QCoreApplication::translate("Bugg", "压缩内容不允许符号链接"));
    total += info.m_uncomp_size;
    if (info.m_uncomp_size > 1024ULL * 1024 * 1024 || total > 8ULL * 1024 * 1024 * 1024)
      fail(QCoreApplication::translate("Bugg", "解压内容超过大小限制"));
    const auto target = safe_path(destination, relative);
    QDir().mkpath(QFileInfo(target).absolutePath());
    QSaveFile output(target);
    if (!output.open(QIODevice::WriteOnly))
      fail(QCoreApplication::translate("Bugg", "无法创建解压文件"));
    struct Context {
      QSaveFile* file;
      Cancellation cancelled;
    } context{&output, cancelled};
    const auto callback = [](void* opaque, mz_uint64, const void* buffer, size_t size) -> size_t {
      const auto* value = static_cast<Context*>(opaque);
      if (value->cancelled && value->cancelled->load()) return 0;
      return qMax<qint64>(0, value->file->write(static_cast<const char*>(buffer), size));
    };
    const bool extracted =
        mz_zip_reader_extract_to_callback(&archive.zip, index, callback, &context, 0);
    check_cancelled(cancelled);
    if (!extracted) {
      const auto error = output.errorString();
      fail(output.error() != QFileDevice::NoError
               ? QCoreApplication::translate("Bugg", "解压写入失败，请检查磁盘空间：") + relative +
                     " · " + error
               : QCoreApplication::translate("Bugg", "归档解压/CRC 校验失败：") + relative);
    }
    if (!output.commit())
      fail(QCoreApplication::translate("Bugg", "无法保存解压文件，请检查磁盘空间：") + relative +
           " · " + output.errorString());
#ifndef Q_OS_WIN
    if (preserve_executable) {
      auto permissions = QFile::permissions(target);
      const auto mode = info.m_external_attr >> 16;
      if (mode & 0100) permissions |= QFile::ExeOwner;
      if (mode & 0010) permissions |= QFile::ExeGroup;
      if (mode & 0001) permissions |= QFile::ExeOther;
      if (!QFile::setPermissions(target, permissions))
        fail(QCoreApplication::translate("Bugg", "无法保留程序执行权限"));
    }
#else
    Q_UNUSED(preserve_executable);
#endif
  }
}
QByteArray file_digest(const QString& path, const QByteArray& algorithm,
                       const Cancellation& cancelled) {
  return file_digests(path, {algorithm}, cancelled).value(algorithm);
}
QMap<QByteArray, QByteArray> file_digests(const QString& path, const QList<QByteArray>& algorithms,
                                          const Cancellation& cancelled) {
  QMap<QByteArray, QByteArray> result;
  std::vector<std::pair<QByteArray, std::unique_ptr<QCryptographicHash>>> hashes;
  if (algorithms.isEmpty()) fail(QCoreApplication::translate("Bugg", "不支持的摘要算法"));
  for (const auto& algorithm : algorithms) {
    if (result.contains(algorithm)) continue;
    QCryptographicHash::Algorithm type;
    if (algorithm == "sha1")
      type = QCryptographicHash::Sha1;
    else if (algorithm == "sha256")
      type = QCryptographicHash::Sha256;
    else if (algorithm == "sha512")
      type = QCryptographicHash::Sha512;
    else
      fail(QCoreApplication::translate("Bugg", "不支持的摘要算法"));
    result.insert(algorithm, {});
    hashes.emplace_back(algorithm, std::make_unique<QCryptographicHash>(type));
  }
  check_cancelled(cancelled);
  QFile input(path);
  if (!input.open(QIODevice::ReadOnly)) fail(QCoreApplication::translate("Bugg", "无法读取文件"));
  QByteArray block(1024 * 1024, Qt::Uninitialized);
  while (true) {
    check_cancelled(cancelled);
    const auto count = input.read(block.data(), block.size());
    if (count < 0) fail(input.errorString());
    if (!count) break;
    for (const auto& [algorithm, hash] : hashes) hash->addData(QByteArrayView(block.data(), count));
  }
  check_cancelled(cancelled);
  for (const auto& [algorithm, hash] : hashes) result[algorithm] = hash->result().toHex();
  return result;
}
QStringList archive_entries(const QString& path, const Cancellation& cancelled) {
  Archive archive(path);
  QStringList result;
  QSet<QString> seen;
  quint64 total = 0;
  const auto count = mz_zip_reader_get_num_files(&archive.zip);
  if (count > 50000) fail(QCoreApplication::translate("Bugg", "压缩文件条目过多"));
  for (mz_uint index = 0; index < count; ++index) {
    check_cancelled(cancelled);
    mz_zip_archive_file_stat info;
    if (!mz_zip_reader_file_stat(&archive.zip, index, &info))
      fail(QCoreApplication::translate("Bugg", "压缩目录损坏"));
    auto name = QString::fromUtf8(info.m_filename);
    name.replace('\\', '/');
    if (name.endsWith('/')) name.chop(1);
    safe_path(QDir::tempPath(), name);
    const auto key = QDir::cleanPath(name).toCaseFolded();
    if (seen.contains(key) || info.m_is_encrypted ||
        ((info.m_external_attr >> 16) & 0170000) == 0120000)
      fail(QCoreApplication::translate("Bugg", "归档包含重复、加密或链接文件"));
    seen.insert(key);
    total += info.m_uncomp_size;
    if (info.m_uncomp_size > 1024ULL * 1024 * 1024 || total > 8ULL * 1024 * 1024 * 1024)
      fail(QCoreApplication::translate("Bugg", "解压内容超过大小限制"));
    if (!info.m_is_directory) result.append(name);
  }
  return result;
}
void archive_write(const QString& path, const QMap<QString, QString>& files,
                   const QMap<QString, QByteArray>& entries, const Cancellation& cancelled,
                   const std::function<void(int, int)>& progress) {
  if (QFileInfo::exists(path))
    fail(QCoreApplication::translate("Bugg", "导出文件已存在，请更换名称"));
  QDir().mkpath(QFileInfo(path).absolutePath());
  QSaveFile output(path);
  if (!output.open(QIODevice::WriteOnly)) fail(output.errorString());
  mz_zip_archive zip{};
  zip.m_pIO_opaque = &output;
  zip.m_pWrite = [](void* value, mz_uint64 offset, const void* bytes, size_t size) -> size_t {
    auto* file = static_cast<QSaveFile*>(value);
    return file->seek(offset) ? qMax<qint64>(0, file->write(static_cast<const char*>(bytes), size))
                              : 0;
  };
  if (!mz_zip_writer_init_v2(&zip, 0, MZ_ZIP_FLAG_WRITE_ZIP64))
    fail(QCoreApplication::translate("Bugg", "无法创建整合包"));
  bool finalized = false;
  try {
    int done = 0;
    QSet<QString> seen;
    for (auto it = files.begin(); it != files.end(); ++it) {
      check_cancelled(cancelled);
      safe_path(QDir::tempPath(), it.key());
      if (seen.contains(it.key().toCaseFolded()))
        fail(QCoreApplication::translate("Bugg", "导出路径重复"));
      seen.insert(it.key().toCaseFolded());
      QFile input(it.value());
      if (!input.open(QIODevice::ReadOnly)) fail(input.errorString());
      struct Context {
        QFile* input;
        Cancellation cancelled;
      } context{&input, cancelled};
      const auto reader = [](void* opaque, mz_uint64 offset, void* buffer, size_t size) -> size_t {
        const auto* value = static_cast<Context*>(opaque);
        if (value->cancelled && value->cancelled->load()) return 0;
        return value->input->seek(offset)
                   ? qMax<qint64>(0, value->input->read(static_cast<char*>(buffer), size))
                   : 0;
      };
      const bool added = mz_zip_writer_add_read_buf_callback(
          &zip, it.key().toUtf8().constData(), reader, &context, input.size(), nullptr, nullptr, 0,
          MZ_BEST_SPEED, nullptr, 0, nullptr, 0);
      check_cancelled(cancelled);
      if (!added) fail(QCoreApplication::translate("Bugg", "写入整合包失败"));
      if (progress) progress(++done, files.size());
    }
    for (auto it = entries.begin(); it != entries.end(); ++it) {
      check_cancelled(cancelled);
      safe_path(QDir::tempPath(), it.key());
      if (!mz_zip_writer_add_mem(&zip, it.key().toUtf8().constData(), it.value().constData(),
                                 it.value().size(), MZ_BEST_SPEED))
        fail(QCoreApplication::translate("Bugg", "写入整合包清单失败"));
    }
    if (!mz_zip_writer_finalize_archive(&zip))
      fail(QCoreApplication::translate("Bugg", "整合包提交失败"));
    mz_zip_writer_end(&zip);
    finalized = true;
    check_cancelled(cancelled);
    if (!output.commit()) fail(output.errorString());
  } catch (...) {
    if (!finalized) mz_zip_writer_end(&zip);
    throw;
  }
}
}  // namespace bugg
