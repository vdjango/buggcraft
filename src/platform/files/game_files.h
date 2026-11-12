#ifndef BUGG_PLATFORM_FILES_GAME_FILES_H_
#define BUGG_PLATFORM_FILES_GAME_FILES_H_
#include <QJsonObject>
#include <QMap>
#include <QStringList>
#include <atomic>
#include <functional>
#include <memory>

namespace bugg {
using Cancellation = std::shared_ptr<std::atomic_bool>;
/// 工作线程文件基础机制；所有路径从受控根构造，拒绝绝对子路径、穿越和符号链接逃逸。
QString safe_path(const QString& root, const QString& relative);
/// Worker-only cancellable atomic copy; refuses an existing destination.
void copy_file(const QString& source, const QString& destination, const Cancellation& cancelled);
QJsonObject read_json(const QString& path);
void write_json(const QString& path, const QJsonObject& object);
void check_cancelled(const Cancellation& cancelled);
bool valid_file(const QString& path, const QByteArray& sha1, qint64 size,
                const Cancellation& cancelled);
/// ZIP/JAR 只读取/解压；限定单文件/总大小、拒绝穿越与符号链接。均在工作线程调用。
QByteArray archive_read(const QString& path, const QString& entry,
                       qint64 limit = 32 * 1024 * 1024, const Cancellation& cancelled = {});
/// preserve_executable 仅原生更新开启，保留 UNIX 可执行位，不恢复特权位。
void archive_extract(const QString& path, const QString& destination, const QString& prefix,
                     const QStringList& excludes, const Cancellation& cancelled,
                     bool preserve_executable = false);
/// 工作线程预检整个归档；拒绝重复、加密、链接、穿越与超限，再返回文件名。
QStringList archive_entries(const QString& path, const Cancellation& cancelled);
/// 工作线程流式、原子写 ZIP；files 为归档名→磁盘文件，entries 为少量清单内容。
/// 不覆盖已有文件；失败/取消不留下可见输出。进度输出已完成文件数/总数。
void archive_write(const QString& path, const QMap<QString, QString>& files,
                   const QMap<QString, QByteArray>& entries, const Cancellation& cancelled,
                   const std::function<void(int, int)>& progress);
/// 流式摘要共用入口；工作线程，取消按块检查。
QByteArray file_digest(const QString& path, const QByteArray& algorithm,
                       const Cancellation& cancelled);
/// 同一文件单次读取计算 SHA-1/256/512；算法列表非空，重复项只计算一次。
/// 工作线程、1 MiB 有界缓冲；读错/未知算法/取消抛错，不返回部分摘要。
QMap<QByteArray, QByteArray> file_digests(const QString& path, const QList<QByteArray>& algorithms,
                                          const Cancellation& cancelled);
/// 便携入口定位（最多 16 KiB）；缺省为程序旁 .buggcraft，相对路径随整包搬迁。
QString portable_cache_root(const QString& portable);
}  // namespace bugg
#endif
