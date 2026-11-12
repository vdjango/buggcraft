#ifndef BUGG_MODULES_UPDATE_APPLICATION_LAUNCHER_UPDATE_SERVICE_H_
#define BUGG_MODULES_UPDATE_APPLICATION_LAUNCHER_UPDATE_SERVICE_H_
#include <QVariantMap>

#include "modules/game_install/infrastructure/resource_client.h"

namespace bugg {
/// Application-owned update feed and staged native bundle. HTTP is asynchronous;
/// download/hash/extraction run in one cancellable worker using existing file mechanisms.
class LauncherUpdateService : public QObject {
  Q_OBJECT
  Q_PROPERTY(QVariantMap status READ status NOTIFY changed)
 public:
  LauncherUpdateService(HttpClient* http, QString cache, QObject* parent = nullptr,
                        QUrl endpoint = QUrl("https://download.bugg.icu/api/launcher/update"));
  QVariantMap status() const;
  static QString platform_id();
  void relocate_storage(const QString& cache) { cache_ = cache; }
  Q_INVOKABLE void check();
  Q_INVOKABLE void download();
  /// Starts the isolated helper, then asks the existing lifecycle to quit.
  Q_INVOKABLE void install();
  Q_INVOKABLE void cancel();
  void shutdown();
  bool busy() const { return working_; }
  /// Dedicated native helper entry, before constructing the GUI application.
  static int apply_staged(const QString& plan_path);
 signals:
  void changed();
  void drained();
  void restart_requested();
  void update_available(const QString& version);

 private:
  HttpClient* http_;
  QString cache_, plan_path_, helper_;
  QUrl endpoint_;
  QVariantMap state_{{"state", "idle"}}, release_;
  quint64 request_ = 0;
  Cancellation cancelled_;
  bool working_ = false, closing_ = false;
};
}  // namespace bugg
#endif
