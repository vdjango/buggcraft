#ifndef BUGG_MODULES_GAME_INSTALL_UI_INSTALL_CATALOG_SESSION_H_
#define BUGG_MODULES_GAME_INSTALL_UI_INSTALL_CATALOG_SESSION_H_

#include <QtQml/qqmlregistration.h>

#include <QHash>
#include <QPointer>
#include <QVariantMap>

#include "bugg_presentation_export.h"
#include "contracts/game_catalog.h"

namespace bugg {

/// 窗口级安装选择模型；service 由应用注入，同一份选择供两种主题使用。
/// GUI 线程，无阻塞 I/O；只选择元数据，不创建安装任务或伪造安装完成。
class BUGG_PRESENTATION_EXPORT InstallCatalogSession : public QObject {
  Q_OBJECT
  QML_ELEMENT
  Q_PROPERTY(QObject* service READ service WRITE set_service NOTIFY service_changed)
  Q_PROPERTY(QVariantMap status READ status NOTIFY status_changed)
 public:
  explicit InstallCatalogSession(QObject* parent = nullptr);
  ~InstallCatalogSession() override;
  QObject* service() const { return service_; }
  /// 仅接受 GameCatalogPort，替换时取消旧请求、清除旧结果；nullptr 表示未接入。
  void set_service(QObject* service);
  QVariantMap status() const;
  /// 进入时复用缓存并按服务有效期更新；refresh 显式重新取最新目录。
  Q_INVOKABLE void ensure_loaded();
  Q_INVOKABLE void refresh();
  Q_INVOKABLE void retry_loaders();
  /// 仅接受当前结果 ID/支持的加载器种类；无效输入不改变状态。
  /// 切换复用组合结果和在途请求；迟到结果只更新它所属组合。
  Q_INVOKABLE void select_game(const QString& id);
  /// Content installation guide; remembers a requested game until async metadata
  /// arrives and validates it against that catalogue. GUI, no installation I/O.
  Q_INVOKABLE void prepare_selection(const QString& game, const QString& loader);
  Q_INVOKABLE void select_loader(const QString& kind);
  Q_INVOKABLE void select_loader_version(const QString& id);
  /// 手动名称保留；等于建议名时恢复自动命名：游戏版本-加载器-加载器版本。
  Q_INVOKABLE void set_instance_name(const QString& name);
  /// 取消请求后保留已成功列表；不因页面隐藏或回首页调用。
  Q_INVOKABLE void cancel();
 signals:
  void status_changed();
  void service_changed();

 private:
  void load_games(bool refresh);
  void load_loaders(bool refresh = false);
  void accept(quint64 request_id, const CatalogResult& result);
  void apply(quint64 request_id, const CatalogResult& result, bool final);
  void report_source(quint64 request_id, const QString& source);
  QString suggested_name() const;
  QPointer<GameCatalogPort> service_;
  CatalogResult games_;
  CatalogResult loaders_;
  struct LoaderSelection {
    CatalogResult result;
    QString version;
    bool custom_version = false;
  };
  QHash<QString, LoaderSelection> loader_catalogs_;
  QHash<quint64, CatalogQuery> loader_requests_;
  QString game_;
  QString pending_game_;
  QString loader_ = "vanilla";
  QString loader_version_;
  QString instance_name_;
  QString error_;
  QString loader_error_;
  quint64 sequence_ = 0;
  quint64 game_request_ = 0;
  quint64 loader_request_ = 0;
  bool attempted_ = false;
  bool custom_name_ = false;
  bool custom_game_ = false;
};

}  // namespace bugg
#endif  // BUGG_MODULES_GAME_INSTALL_UI_INSTALL_CATALOG_SESSION_H_
