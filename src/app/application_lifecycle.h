#ifndef BUGG_APP_APPLICATION_LIFECYCLE_H_
#define BUGG_APP_APPLICATION_LIFECYCLE_H_
#include <QObject>
#include <QTimer>
#include <QUrl>
#include <QVariantMap>
namespace bugg {
class GameRuntime;
class MultiplayerService;
class MicrosoftAccount;
class SourceSettings;
class ContentCatalogService;
class LauncherUpdateService;
class LanguageService;
class HttpClient;
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
  /// Optional anonymous startup event after consent/ready; cancelled on shutdown, no timer.
  void attach_usage(HttpClient* http,
                    const QUrl& endpoint = QUrl("https://node.bugg.icu/v1/usage/launcher"));
  QString phase() const { return phase_; }
  QVariantMap status() const;
  /// GUI 装配完成、创建 QML 前调用；只发布 setup/before_mount，不执行重工作。
  void before_mount();
  /// 首帧后幂等一次，后台初始化账号/运行时；各所有者完成后 ready。
  Q_INVOKABLE void mounted();
  /// GUI explicit consent; persists the current agreement revision before starting
  /// identity/network owners. Ignored outside awaiting_consent; shutdown drains saves.
  Q_INVOKABLE void accept_agreement();
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
  void initialize_services();
  void drain();
  void report_usage();
  GameRuntime* runtime_;
  MultiplayerService* multiplayer_ = nullptr;
  ContentCatalogService* content_catalog_ = nullptr;
  LauncherUpdateService* updates_ = nullptr;
  LanguageService* languages_ = nullptr;
  HttpClient* usage_http_ = nullptr;
  QUrl usage_endpoint_;
  quint64 usage_request_ = 0;
  bool usage_reported_ = false;
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
