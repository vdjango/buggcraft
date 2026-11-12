#ifndef BUGG_SHELL_DESKTOP_ENVIRONMENT_H_
#define BUGG_SHELL_DESKTOP_ENVIRONMENT_H_

#include <QObject>
#include <QRect>

class QScreen;
class QWindow;

namespace bugg {

/// GUI 线程只读系统工作区/鼠标状态；无磁盘或网络 I/O，位置策略归 EdgeDock.qml。
class DesktopEnvironment : public QObject {
  Q_OBJECT

 public:
  explicit DesktopEnvironment(QObject* parent = nullptr);

  /// window 无屏幕时回退主屏，无屏幕返回空矩形；排除任务栏占用区。
  Q_INVOKABLE QRect available_geometry(QWindow* window) const;
  /// 原生拖动期间轮询实时左键，不阻塞等待松开。
  Q_INVOKABLE bool left_button_pressed() const;
  /// 系统指针是否在可见窗口内；补偿原生拖动/窗口缩放遗漏的悬停事件。
  Q_INVOKABLE bool pointer_inside(QWindow* window) const;
  /// GUI, bounded native probe; only same-monitor foreground fullscreen counts.
  /// Windows supports external applications; other platforms inspect Qt windows.
  Q_INVOKABLE bool fullscreen_foreground(QWindow* window) const;

 signals:
  void available_geometry_changed();

 private:
  void watch_screen(QScreen* screen);
};

}  // namespace bugg

#endif  // BUGG_SHELL_DESKTOP_ENVIRONMENT_H_
