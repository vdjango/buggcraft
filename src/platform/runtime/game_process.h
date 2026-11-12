#ifndef BUGG_PLATFORM_RUNTIME_GAME_PROCESS_H_
#define BUGG_PLATFORM_RUNTIME_GAME_PROCESS_H_
#include <QObject>
#include <QTimer>

#include "modules/launch/domain/minecraft_metadata.h"
namespace bugg {
/// 工作线程创建独立游戏进程，标准流直接写游戏日志，启动器退出不杀游戏。
qint64 start_game_process(const LaunchCommand& command);
/// GUI 线程只监视本启动器创建的 PID；停止为异步，退出时解除监视即可。
class GameProcess : public QObject {
  Q_OBJECT
 public:
  explicit GameProcess(QObject* parent = nullptr);
  ~GameProcess() override;
  void watch(qint64 pid);
  void stop();
  void release();
 signals:
  void exited(int code);

 private:
  qint64 pid_ = 0;
  void* handle_ = nullptr;
  QObject* notifier_ = nullptr;
  QTimer timer_;
};
}  // namespace bugg
#endif
