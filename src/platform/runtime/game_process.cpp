#include "platform/runtime/game_process.h"

#include <QCoreApplication>
#include <QDir>
#include <QFileInfo>
#include <QProcess>
#include <stdexcept>
#ifdef Q_OS_WIN
#define NOMINMAX
#include <windows.h>

#include <QWinEventNotifier>
#else
#include <errno.h>
#include <signal.h>
#endif
namespace bugg {
qint64 start_game_process(const LaunchCommand& command) {
  QDir().mkpath(command.directory);
  QDir().mkpath(QFileInfo(command.log_path).absolutePath());
  QProcess process;
  process.setProgram(command.java);
  process.setArguments(command.arguments);
  process.setWorkingDirectory(command.directory);
  process.setProcessChannelMode(QProcess::MergedChannels);
  process.setStandardOutputFile(command.log_path);
  qint64 pid = 0;
  if (!process.startDetached(&pid))
    throw std::runtime_error(
        QCoreApplication::translate("Bugg", "无法创建游戏进程，请检查 Java 和游戏目录权限")
            .toStdString());
  return pid;
}
GameProcess::GameProcess(QObject* parent) : QObject(parent) {
#ifndef Q_OS_WIN
  connect(&timer_, &QTimer::timeout, this, [this] {
    if (::kill(pid_, 0) != 0 && errno == ESRCH) {
      release();
      emit exited(0);
    }
  });
#endif
}
GameProcess::~GameProcess() { release(); }
void GameProcess::release() {
  timer_.stop();
  if (notifier_) {
#ifdef Q_OS_WIN
    static_cast<QWinEventNotifier*>(notifier_)->setEnabled(false);
#endif
    notifier_->deleteLater();
  }
  notifier_ = nullptr;
#ifdef Q_OS_WIN
  if (handle_) CloseHandle(static_cast<HANDLE>(handle_));
#endif
  handle_ = nullptr;
  pid_ = 0;
}
void GameProcess::watch(qint64 pid) {
  release();
  pid_ = pid;
#ifdef Q_OS_WIN
  handle_ = OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_TERMINATE, FALSE,
                        DWORD(pid));
  if (!handle_) {
    QTimer::singleShot(0, this, [this] {
      release();
      emit exited(-1);
    });
    return;
  }
  auto* notifier = new QWinEventNotifier(static_cast<HANDLE>(handle_), this);
  notifier_ = notifier;
  connect(notifier, &QWinEventNotifier::activated, this, [this] {
    DWORD code = 0;
    GetExitCodeProcess(static_cast<HANDLE>(handle_), &code);
    release();
    emit exited(int(code));
  });
#else
  timer_.start(500);
#endif
}
void GameProcess::stop() {
  if (!pid_) return;
#ifdef Q_OS_WIN
  const auto pid = DWORD(pid_);
  EnumWindows(
      [](HWND window, LPARAM value) -> BOOL {
        DWORD owner = 0;
        GetWindowThreadProcessId(window, &owner);
        if (owner == DWORD(value)) PostMessageW(window, WM_CLOSE, 0, 0);
        return TRUE;
      },
      LPARAM(pid));
  QTimer::singleShot(5000, this, [this, pid] {
    if (pid_ == pid && handle_) TerminateProcess(static_cast<HANDLE>(handle_), 0);
  });
#else
  ::kill(pid_, SIGTERM);
#endif
}
}  // namespace bugg
