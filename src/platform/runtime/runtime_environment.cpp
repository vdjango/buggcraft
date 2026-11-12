#include "platform/runtime/runtime_environment.h"

#include <QCoreApplication>
#include <QDir>
#include <QDirIterator>
#include <QElapsedTimer>
#include <QProcess>
#include <QRegularExpression>
#include <QStandardPaths>
#include <stdexcept>
#ifdef Q_OS_WIN
#define NOMINMAX
#include <windows.h>
#elif defined(Q_OS_MACOS)
#include <mach/mach.h>
#include <sys/sysctl.h>
#include <unistd.h>
#else
#include <unistd.h>
#endif
namespace bugg {
QVariantMap memory_snapshot() {
  qint64 total = 0, available = 0;
#ifdef Q_OS_WIN
  MEMORYSTATUSEX status{};
  status.dwLength = sizeof(status);
  if (GlobalMemoryStatusEx(&status)) {
    total = status.ullTotalPhys;
    available = status.ullAvailPhys;
  }
#elif defined(Q_OS_MACOS)
  uint64_t bytes = 0;
  size_t size = sizeof(bytes);
  sysctlbyname("hw.memsize", &bytes, &size, nullptr, 0);
  total = bytes;
  vm_statistics64_data_t statistics{};
  mach_msg_type_number_t count = HOST_VM_INFO64_COUNT;
  if (host_statistics64(mach_host_self(), HOST_VM_INFO64,
                        reinterpret_cast<host_info64_t>(&statistics), &count) == KERN_SUCCESS)
    available = (statistics.free_count + statistics.inactive_count) * sysconf(_SC_PAGESIZE);
#else
  total = sysconf(_SC_PHYS_PAGES) * sysconf(_SC_PAGESIZE);
  available = sysconf(_SC_AVPHYS_PAGES) * sysconf(_SC_PAGESIZE);
#endif
  return {{"totalMB", total / 1048576}, {"availableMB", available / 1048576}};
}
int memory_limit_mb(const QVariantMap& snapshot) {
  const int total = snapshot.value("totalMB").toInt();
  const int available = snapshot.value("availableMB").toInt();
  if (total <= 0 || available <= 0) return 1024;
  const int reserve = qBound(1024, total / 8, 4096);
  return qMax(512, qMin(total - reserve, available - reserve) / 256 * 256);
}
int automatic_memory_mb(const QVariantMap& snapshot, int mod_count, int hosted_players) {
  if (snapshot.value("totalMB").toInt() <= 0 || snapshot.value("availableMB").toInt() <= 0)
    return 1024;
  const int mods = qBound(0, mod_count, 10000);
  const int players = qBound(1, hosted_players, 32);
  const int estimated = kMinimumAutomaticMemoryMB + mods * 20 + (players - 1) * 256;
  const int rounded = ((estimated + 511) / 512) * 512;
  return qMax(512, qMin(qMin(rounded, memory_limit_mb(snapshot)), 16384));
}
QStringList java_candidates(const QString& portable_root, const Cancellation& cancelled) {
#ifdef Q_OS_WIN
  const QString executable = "java.exe";
#else
  const QString executable = "java";
#endif
  QStringList result;
  const auto from_path = QStandardPaths::findExecutable(executable);
  if (!from_path.isEmpty()) result.append(from_path);
  const auto java_home = qEnvironmentVariable("JAVA_HOME");
  if (!java_home.isEmpty()) result.append(java_home + "/bin/" + executable);
  QStringList roots{portable_cache_root(portable_root) + "/runtime",
                    portable_root + "/.minecraft/runtime"};
#ifdef Q_OS_WIN
  for (const auto& name : {"Java", "Eclipse Adoptium", "Microsoft", "BellSoft", "Zulu"})
    roots.append(qEnvironmentVariable("ProgramFiles") + '/' + name);
#elif defined(Q_OS_MACOS)
  roots.append("/Library/Java/JavaVirtualMachines");
#else
  roots.append("/usr/lib/jvm");
#endif
  for (const auto& root : roots) {
    QDirIterator iterator(root, {executable}, QDir::Files | QDir::NoSymLinks,
                          QDirIterator::Subdirectories);
    int count = 0;
    while (iterator.hasNext() && ++count < 100) {
      check_cancelled(cancelled);
      result.append(iterator.next());
    }
  }
  result.removeDuplicates();
  return result;
}
int java_major(const QString& executable, const Cancellation& cancelled) {
  if (!QFileInfo::exists(executable)) return 0;
  QProcess process;
  process.setProcessChannelMode(QProcess::MergedChannels);
  process.start(executable, {"-version"});
  QElapsedTimer timer;
  timer.start();
  while (!process.waitForFinished(50)) {
    if (cancelled->load() || timer.elapsed() > 6000 || process.state() == QProcess::NotRunning) {
      process.kill();
      process.waitForFinished(1000);
      check_cancelled(cancelled);
      return 0;
    }
  }
  if (process.exitStatus() != QProcess::NormalExit || process.exitCode() != 0) return 0;
  const auto text = QString::fromUtf8(process.readAll());
  const auto match =
      QRegularExpression("(?:version|openjdk)\\s+\"?(\\d+)(?:\\.(\\d+))?").match(text);
  if (!match.hasMatch()) return 0;
  return match.captured(1) == "1" ? match.captured(2).toInt() : match.captured(1).toInt();
}
QVariantMap environment_snapshot(const QString& portable_root, const Cancellation& cancelled) {
  auto snapshot = memory_snapshot();
  snapshot["automaticMemoryMB"] = automatic_memory_mb(snapshot);
  snapshot["maximumMemoryMB"] = memory_limit_mb(snapshot);
  QVariantList entries;
  const auto paths = java_candidates(portable_root, cancelled);
  for (const auto& path : paths) {
    check_cancelled(cancelled);
    const int major = java_major(path, cancelled);
    if (major)
      entries.append(QVariantMap{{"id", path},
                                 {"name", QString("Java %1").arg(major)},
                                 {"caption", QDir::toNativeSeparators(path)},
                                 {"major", major}});
  }
  snapshot["javaPaths"] = paths;
  snapshot["javaEntries"] = entries;
  return snapshot;
}
void run_java_tool(const QString& executable, const QStringList& arguments,
                   const QString& directory, const QString& log_path,
                   const Cancellation& cancelled) {
  QDir().mkpath(QFileInfo(log_path).absolutePath());
  QProcess process;
  process.setWorkingDirectory(directory);
  process.setStandardOutputFile(log_path, QIODevice::Append);
  process.setStandardErrorFile(log_path, QIODevice::Append);
  process.start(executable, arguments);
  QElapsedTimer timer;
  timer.start();
  while (!process.waitForFinished(50)) {
    if (cancelled->load() || timer.elapsed() > 10 * 60 * 1000) {
      process.kill();
      process.waitForFinished(1000);
      check_cancelled(cancelled);
      throw std::runtime_error(
          QCoreApplication::translate("Bugg", "加载器处理器超时，请查看安装日志").toStdString());
    }
    if (process.state() == QProcess::NotRunning) break;
  }
  if (process.error() == QProcess::FailedToStart || process.exitStatus() != QProcess::NormalExit ||
      process.exitCode() != 0)
    throw std::runtime_error(
        QCoreApplication::translate("Bugg", "加载器处理器运行失败，请查看安装日志").toStdString());
}
}  // namespace bugg
