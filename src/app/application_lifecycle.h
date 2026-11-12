#ifndef BUGG_APP_APPLICATION_LIFECYCLE_H_
#define BUGG_APP_APPLICATION_LIFECYCLE_H_
#include <QObject>
#include <QTimer>
#include <QVariantMap>
namespace bugg {
class GameRuntime;
class MultiplayerService;
class MicrosoftAccount;
class SourceSettings;
class ContentCatalogService;
class LauncherUpdateService;
class LanguageService;
/// 应用寿命的唯一协调器。钩子类似组合式 UI 生命周期；首帧后初始化，退出异步汇聚。
class ApplicationLifecycle : public QObject {
  Q_OBJECT
  Q_PROPERTY(QString phase READ phase NOTIFY changed)
  Q_PROPERTY(QVariantMap status READ status NOTIFY changed)
 public:
  ApplicationLifecycle(GameRuntime* runtime, MicrosoftAccount* account, SourceSettings* sources,
                       QObject* parent = nullptr);
  void attach_multiplayer(MultiplayerService* service);
  /// App-owned content metadata worker participates in the same async drain.
  void attach_content_catalog(ContentCatalogService* service);
  /// Same startup and drain as other app-owned services.
  void attach_updates(LauncherUpdateService* service);
  /// Optional language downloads share application cancellation/drain.
  void attach_languages(LanguageService* service);
  QString phase() const { return phase_; }
  QVariantMap status() const;
  /// GUI 装配完成、创建 QML 前调用；只发布 setup/before_mount，不执行重工作。
  void before_mount();
  /// 首帧后幂等一次，后台初始化账号/运行时；各所有者完成后 ready。
  Q_INVOKABLE void mounted();
  /// GUI 输入路由/主题/工具键，hook 携带旧/新上下文；相同键无操作。
  Q_INVOKABLE void update_view(const QString& key);
  /// GUI 视图激活/失活；只改变呈现寿命，不取消业务。
  Q_INVOKABLE void set_presented(bool presented);
  Q_INVOKABLE void capture_error(const QString& owner, const QString& error);
  /// GUI 幂等卸载；无同步等待，quit_ready 在所有自有工作及保存结束后发出。
  Q_INVOKABLE void shutdown();
 signals:
  void changed();
  void hook(const QString& name, const QVariantMap& context);
  void quit_ready();

 private:
  void notify(const QString& name, const QVariantMap& context = {});
  void complete(const QString& owner, const QString& error);
  void drain();
  GameRuntime* runtime_;
  MultiplayerService* multiplayer_ = nullptr;
  ContentCatalogService* content_catalog_ = nullptr;
  LauncherUpdateService* updates_ = nullptr;
  LanguageService* languages_ = nullptr;
  MicrosoftAccount* account_;
  SourceSettings* sources_;
  QString phase_ = "setup";
  QString view_;
  QStringList pending_, errors_;
  QTimer draining_;
  bool presented_ = true;
  bool mounted_ = false;
};
}  // namespace bugg
#endif
