#ifndef BUGG_MODULES_GAME_INSTALL_APPLICATION_GAME_RUNTIME_H_
#define BUGG_MODULES_GAME_INSTALL_APPLICATION_GAME_RUNTIME_H_
#include <QFileSystemWatcher>
#include <QTimer>
#include <QVariantList>

#include "contracts/content_catalog.h"
#include "contracts/download_sources.h"
#include "contracts/game_runtime.h"
#include "contracts/room_content.h"
#include "platform/files/game_files.h"
#include "platform/runtime/game_process.h"
namespace bugg {
/// 应用级真实任务/实例快照；页面销毁不结束任务。仅此处调度共享 GameOperations。
class GameRuntime : public GameRuntimePort {
  Q_OBJECT
  Q_PROPERTY(QVariantList instances READ instances NOTIFY instances_changed)
  Q_PROPERTY(QVariantList tasks READ tasks NOTIFY tasks_changed)
  Q_PROPERTY(QVariantMap environment READ environment NOTIFY environment_changed)
  Q_PROPERTY(QVariantMap launch_status READ launch_status NOTIFY status_changed)
  Q_PROPERTY(QVariantMap activity READ activity NOTIFY tasks_changed)
  Q_PROPERTY(QString game_root READ game_root NOTIFY instances_changed)
  Q_PROPERTY(bool loading_instances READ loading_instances NOTIFY instances_changed)
  Q_PROPERTY(QVariantMap preferences READ preferences NOTIFY settings_changed)
  Q_PROPERTY(QString cache_root READ cache_root NOTIFY cache_root_changed)
  Q_PROPERTY(QVariantMap pack_preview READ pack_preview NOTIFY pack_preview_changed)
  Q_PROPERTY(QVariantMap content READ content NOTIFY content_changed)
  Q_PROPERTY(QVariantMap diagnostics_status READ diagnostics_status NOTIFY diagnostics_changed)
  Q_PROPERTY(QVariantMap content_installation READ content_installation NOTIFY
                 content_installation_changed)
 public:
  GameRuntime(QString portable_root, QString game_root, AccountPort* account,
              QObject* parent = nullptr);
  QVariantList instances() const { return instances_; }
  QVariantList tasks() const { return tasks_; }
  QVariantMap environment() const { return environment_; }
  QVariantMap launch_status() const { return launch_status_; }
  QVariantMap activity() const;
  QString game_root() const { return game_root_; }
  bool loading_instances() const { return initializing_; }
  QVariantMap preferences() const;
  QString cache_root() const { return cache_root_; }
  QVariantMap pack_preview() const { return pack_preview_; }
  QVariantMap content() const { return content_; }
  QVariantMap diagnostics_status() const { return diagnostics_status_; }
  Q_PROPERTY(QVariantMap debug_log READ debug_log NOTIFY debug_log_changed)
  QVariantMap debug_log() const { return debug_log_; }
  /// Bounded worker snapshot; module/level/search are filters, never file paths.
  Q_INVOKABLE void refresh_debug_log(const QString& module = {}, const QString& level = {},
                                     const QString& search = {}, const QString& logger = {});
  /// GUI command; bounded, redacted ZIP in the existing cancellable file worker.
  /// Existing destination is refused; diagnostics_changed publishes path/error.
  Q_INVOKABLE void export_diagnostics(const QString& url);
  QVariantMap content_installation() const { return content_installation_; }
  bool busy() const { return workers_ > 0; }
  /// GUI 调度环境/配置/实例工作；initialized(error) 在真实扫描完成后发出。
  void initialize();
  /// GUI 幂等拒绝新任务并取消 worker；drained 异步确认，自有游戏保持运行。
  void shutdown();
  void select_sources(const QStringList& order, const QUrl& bugg_base = {}) {
    source_order_ = order;
    if (!bugg_base.isEmpty()) bugg_base_ = bugg_base;
  }
  /// GUI 注入内容来源值快照；worker 自动补齐/重试依赖，不访问页面或服务 QObject。
  void set_content_request(ContentRequest request) { content_request_ = std::move(request); }
  /// GUI 装配唯一房间文件端口，工作线程仅捕获该值；不对 QML 暴露 RPC。
  void set_room_content_request(RoomContentRequest request) {
    room_content_request_ = std::move(request);
  }
  Q_INVOKABLE void refresh_instances();
  Q_INVOKABLE void install(const QVariantMap& specification) override;
  Q_INVOKABLE void cancel_task(const QString& id) override;
  Q_INVOKABLE void retry_task(const QString& id);
  /// Exact pending task choice; worker rechecks its file-set fingerprint before committing.
  Q_INVOKABLE void resolve_dependencies(const QString& id, const QString& choice);
  /// GUI 清除已结束的任务记录及重试规格，返回移除数量；保留活动/排队任务，不删文件。
  Q_INVOKABLE int clear_task_history();
  /// GUI 调度房间配置只读核对；文件工作复用生命周期任务，结果由房间检查代数裁决。
  void check_room(const QString& session, quint64 revision, const QString& instance_id,
                  const QVariantMap& game);
  /// GUI 取消该房间任务，清理待发布结果；不影响其他安装/运行中的游戏。
  void cancel_room(const QString& session);
  /// GUI 只读策略快照；automatic 默认 true，自动结果属于本次环境，不持久化。
  Q_INVOKABLE QVariantMap instance_settings(const QString& id) const;
  /// GUI 兼容入口，委托逐项设置校验并后台合并保存；仅失败提示，退出汇聚写入。
  Q_INVOKABLE void save_instance_settings(const QString& id, bool automatic, int memory_mb);
  /// GUI 更新全局（空 id）或实例覆盖；true 表示命令接受，false 表示非法/不可用。
  /// 未探测的 Java 在 worker 验证后才保存；新选择/恢复默认使旧验证失效，失败发 notice。
  /// 普通值即时更新并串行保存；只影响下一次游戏启动，退出汇聚自有验证工作。
  Q_INVOKABLE bool set_game_setting(const QString& id, const QString& key, const QVariant& value);
  Q_INVOKABLE void reset_instance_settings(const QString& id);
  /// GUI 通用设置唯一入口：language / concurrency / afterLaunch；同值不重复保存。
  Q_INVOKABLE bool set_preference(const QString& key, const QVariant& value);
  Q_INVOKABLE void select_game_root(const QString& path);
  Q_INVOKABLE void open_directory(const QString& id);
  /// GUI 提交归档只读检查，结果 pack_preview；不会自动安装。
  Q_INVOKABLE void inspect_pack(const QString& url);
  Q_INVOKABLE void import_pack(const QString& name);
  Q_INVOKABLE void export_pack(const QString& id, const QString& url, bool compact, bool saves);
  /// GUI 接受删除/隐藏后返回 true；文件工作在后台执行，不写入下载历史。
  Q_INVOKABLE bool remove_instance(const QString& id, bool permanent);
  /// GUI 发起内容扫描/修改；工作线程限制 mods/resourcepacks/shaderpacks，状态归 content。
  Q_INVOKABLE void refresh_content(const QString& id, const QString& category);
  Q_INVOKABLE void change_content(const QString& id, const QString& category, const QString& name,
                                  const QString& action);
  Q_INVOKABLE void add_content(const QString& id, const QString& category,
                               const QVariantList& urls);
  /// GUI schedules read-only compatibility/conflict checks in the existing
  /// file worker; a newer selection supersedes late results. No download.
  Q_INVOKABLE void inspect_content_install(const QString& id, const QVariantMap& plan);
  Q_INVOKABLE void refresh_environment();
  /// GUI 发起便携目录迁移；复制与定位提交在 worker，完成通知 app 重定向其余服务。
  Q_INVOKABLE void select_cache_root(const QString& url);
  void launch(const QString& instance_id, const QString& profile_id,
              const QVariantMap& contributions = {}) override;
  void cancel_launch() override;
  void stop_game() override;
 signals:
  void instances_changed();
  void tasks_changed();
  /// GUI: successful complete game installation/import only; failures stay in tasks.
  void installation_finished(const QString& task, const QString& instance);
  void environment_changed();
  void status_changed();
  void initialized(const QString& error);
  void drained();
  void notice(const QString& message);
  void settings_changed();
  void cache_root_changed();
  void pack_preview_changed();
  void content_changed();
  void diagnostics_changed();
  void debug_log_changed();
  void content_installation_changed();
  /// GUI 成功结果带原会话 ID，接收方忽略已经离开的房间。
  void room_prepared(const QString& session, const QString& instance_id, const QString& config);
  void room_checked(const QString& session, quint64 revision, const QString& instance_id,
                    const QVariantMap& result);
  /// 真实房间任务进度；GUI 信号，任务与房间 ID 隔离迟到结果，不推算虚假阶段。
  void room_progress(const QString& session, const QString& task, const QString& state,
                     double progress, const QString& config);

 private:
  void run_operation(const QString& task_id, const QVariantMap& specification, bool launching,
                     const GameIdentity& identity = {}, const QVariantMap& contributions = {});
  void update_task(const QString& id, const QString& state, double progress, const QString& detail);
  void update_content_item(const QString& id, const QVariantMap& item);
  void publish_launch(const QString& state, const QString& detail = {}, double progress = -1);
  void save_settings();
  // GUI 串行派发已入队任务；取消/失败不丢掉其他任务。
  void dispatch_next();
  void persist_tasks();
  // GUI 调度可取消文件工作，统一归入生命周期；result/error 仅在 GUI 线程交付。
  void run_file_work(std::function<QVariantMap(const Cancellation&)> work,
                     std::function<void(const QVariantMap&)> complete);
  QString portable_, game_root_, cache_root_;
  AccountPort* account_;
  GameProcess process_;
  QFileSystemWatcher directory_watcher_;
  QTimer rescan_timer_;
  QVariantList instances_, tasks_;
  QVariantMap environment_, settings_, launch_status_{{"state", "idle"}};
  QVariantMap pack_preview_, content_;
  QVariantMap diagnostics_status_;
  QVariantMap debug_log_;
  QVariantMap content_installation_;
  quint64 content_install_generation_ = 0;
  quint64 content_generation_ = 0, pack_generation_ = 0;
  QHash<QString, QVariantMap> specifications_;
  QHash<QString, quint64> java_selection_generations_;
  QStringList source_order_ = supported_download_sources();
  QUrl bugg_base_ = default_bugg_source();
  Cancellation cancelled_;
  Cancellation launch_cancelled_;
  RoomContentRequest room_content_request_;
  ContentRequest content_request_;
  // 同步完成后，等实例扫描发布才允许房间启动；旧会话由接收服务拒绝。
  QVariantList prepared_rooms_;
  Cancellation initialization_cancelled_;
  QString task_id_, launch_id_, launch_task_id_;
  QVariantMap pending_launch_;
  QString launch_paused_task_;
  quint64 generation_ = 0;
  int workers_ = 0;
  bool closing_ = false;
  bool scan_pending_ = false;
  bool settings_writing_ = false;
  bool settings_dirty_ = false;
  bool initializing_ = true;
  bool initialization_started_ = false;
  bool rescan_requested_ = false;
  bool storage_migrating_ = false;
  QMetaObject::Connection credentials_connection_;
};
}  // namespace bugg
#endif
