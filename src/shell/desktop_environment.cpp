#include "shell/desktop_environment.h"

#include <QCursor>
#include <QGuiApplication>
#include <QScreen>
#include <QWindow>

#ifdef Q_OS_WIN
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#endif

namespace bugg {

DesktopEnvironment::DesktopEnvironment(QObject* parent) : QObject(parent) {
  for (QScreen* screen : QGuiApplication::screens()) {
    watch_screen(screen);
  }
  connect(qGuiApp, &QGuiApplication::screenAdded, this, [this](QScreen* screen) {
    watch_screen(screen);
    emit available_geometry_changed();
  });
  connect(qGuiApp, &QGuiApplication::screenRemoved, this,
          [this](QScreen*) { emit available_geometry_changed(); });
}

QRect DesktopEnvironment::available_geometry(QWindow* window) const {
  QScreen* screen = window ? window->screen() : nullptr;
  if (!screen) {
    screen = QGuiApplication::primaryScreen();
  }
  return screen ? screen->availableGeometry() : QRect();
}

bool DesktopEnvironment::left_button_pressed() const {
#ifdef Q_OS_WIN
  return (GetAsyncKeyState(VK_LBUTTON) & 0x8000) != 0;
#else
  return QGuiApplication::mouseButtons().testFlag(Qt::LeftButton);
#endif
}

bool DesktopEnvironment::pointer_inside(QWindow* window) const {
  return window && window->isVisible() && window->geometry().contains(QCursor::pos());
}

bool DesktopEnvironment::fullscreen_foreground(QWindow* window) const {
  if (!window) return false;
#ifdef Q_OS_WIN
  const auto foreground = GetForegroundWindow();
  const auto own = reinterpret_cast<HWND>(window->winId());
  if (!foreground || foreground == own || foreground == GetShellWindow() ||
      foreground == GetDesktopWindow() || !IsWindowVisible(foreground) || IsIconic(foreground))
    return false;
  const auto monitor = MonitorFromWindow(own, MONITOR_DEFAULTTONEAREST);
  if (monitor != MonitorFromWindow(foreground, MONITOR_DEFAULTTONEAREST)) return false;
  MONITORINFO info{};
  info.cbSize = sizeof(info);
  RECT rectangle{};
  if (!GetMonitorInfoW(monitor, &info) || !GetClientRect(foreground, &rectangle)) return false;
  POINT origin{rectangle.left, rectangle.top};
  if (!ClientToScreen(foreground, &origin)) return false;
  // Client bounds distinguish a maximized decorated window from fullscreen.
  return origin.x <= info.rcMonitor.left && origin.y <= info.rcMonitor.top &&
         origin.x + rectangle.right >= info.rcMonitor.right &&
         origin.y + rectangle.bottom >= info.rcMonitor.bottom;
#else
  for (const auto* candidate : QGuiApplication::topLevelWindows())
    if (candidate != window && candidate->isActive() && candidate->isVisible() &&
        candidate->screen() == window->screen() && candidate->windowState() == Qt::WindowFullScreen)
      return true;
  return false;
#endif
}

void DesktopEnvironment::watch_screen(QScreen* screen) {
  connect(screen, &QScreen::availableGeometryChanged, this,
          [this](const QRect&) { emit available_geometry_changed(); });
}

}  // namespace bugg
