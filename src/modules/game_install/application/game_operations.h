#ifndef BUGG_MODULES_GAME_INSTALL_APPLICATION_GAME_OPERATIONS_H_
#define BUGG_MODULES_GAME_INSTALL_APPLICATION_GAME_OPERATIONS_H_
#include <QElapsedTimer>

#include "contracts/content_catalog.h"
#include "contracts/room_content.h"
#include "modules/game_install/infrastructure/resource_client.h"
#include "modules/launch/domain/minecraft_metadata.h"
namespace bugg {
/// 所有入口共用的工作线程流水线；页面/房间不得自行下载库或拼启动参数。
class GameOperations {
 public:
  using Progress = ResourceClient::Progress;
  using ContentProgress = std::function<void(const QVariantMap&)>;
  GameOperations(QString game_root, QString portable_root, QStringList source_order,
                 Cancellation cancelled, Progress progress, int concurrency = 6,
                 HttpClient* transport = nullptr, QUrl bugg_base = default_bugg_source());
  /// Worker-only value callback for bounded per-content task details. Uses the
  /// same cancellation and throttled transfer progress; no additional worker.
  void set_content_progress(ContentProgress progress) { content_progress_ = std::move(progress); }
  /// Installation intent/decision stays with this worker. A keep/repair choice
  /// is valid only for the check fingerprint returned by this exact task.
  void set_dependency_context(QVariantMap specification, ContentRequest request = {});
  /// Worker: version/loader specification → atomic instance JSON. updateExisting
  /// adds a loader to the given vanilla id, preserving its client, worlds and settings.
  /// Errors/cancellation throw and preserve the previous instance JSON.
  QString install(const QVariantMap& specification);
  /// 工作线程：规范化清单 → 共用 install/下载 → 隐藏目录原子提交；失败保留可重试文件。
  QString import_pack(const QString& archive, const QString& name);
  /// Worker preview and execution share compatibility/path/hash checks. Preview
  /// reads files only; execution stages downloads before committing. Existing
  /// different files require specification.replace=true, and are rolled back on failure.
  QVariantMap check_content_install(const QString& id, const QVariantMap& plan);
  /// Worker-only preflight: bind mod plans to the actual loader build; for shaders inspect active
  /// JAR identities, verify an installed core through the existing metadata port and reuse it. No
  /// game is started; cancellation/errors throw, unknown cores are not overwritten.
  QVariantMap prepare_content_install(const QString& id, const QVariantMap& plan,
                                      const ContentRequest& request);
  /// 整组文件先暂存并核对实际依赖，再一次提交；依赖冲突进入明确选择，
  /// 未确认、失败或取消均保留原实例。request 仅供 worker 使用。
  QVariantMap install_content(const QVariantMap& specification, const ContentRequest& request = {});
  /// Worker: an existing id adds shader support in place; otherwise reuse the
  /// hidden game creation transaction. Core/dependency failure never commits a
  /// shader. An installed loader remains usable for retry; cancellation throws.
  QVariantMap install_with_content(const QVariantMap& specification,
                                   const ContentRequest& request = {});
  /// 工作线程：完整清单校验、公共源优先/P2P 补齐，共用 install/原子提交。
  /// request 绑定当前会话；失败/取消保留隐藏缓存，不发布半成品。
  QString sync_room(const QVariantMap& specification, const RoomContentRequest& request);
  /// 工作线程只读核对，返回 compatible/canSupplement/detail/warning；复用版本解析及摘要。
  /// 加载器版本差异仅提示，版本/加载器类型/必需模组不符不可直接启动。
  QVariantMap check_room(const QString& instance_id, const QJsonObject& game);
  /// 工作线程：Buggcraft v1 .buggpack；明确引用或嵌入，未知来源文件始终嵌入。
  void export_pack(const QString& id, const QString& destination, bool compact, bool saves);
  /// 同一准备流程修复依赖、资源、Java/natives，最终生成语义去重的命令。
  /// memory_mb 是当前环境与活动模组估算出的堆上限；不固定初始堆，身份和参数仅本次启动使用。
  LaunchCommand prepare(const QString& instance_id, int memory_mb, const GameIdentity& identity,
                        const QVariantMap& contributions = {});
  QJsonObject load_version(const QString& id);

 private:
  /// 唯一文件事务：校验、暂存、替换、回滚。上层为主内容/单个依赖复用。
  QVariantMap prepare_content_files(const QVariantMap& specification);
  static QJsonArray content_records(const QVariantMap& plan);
  void install_content_files(const QVariantMap& specification, const QVariantMap& prepared = {});
  /// Stage overlay + existing active JARs -> one shared check/solver. May throw
  /// DependencyDecision before publication. Returns a receipt and updates only
  /// worker-owned staging records when explicitly authorized to repair.
  QJsonObject check_dependencies(const QString& directory, const QString& overlay,
                                 QStringList& remove, QJsonArray& records,
                                 const QJsonObject& metadata, const QString& intent);
  QJsonObject base_version(const QString& version);
  QString ensure_java(const QJsonObject& metadata, const QString& preferred = {});
  void prepare_files(const QJsonObject& metadata, const QString& instance_id);
  void fetch_libraries(const QJsonArray& libraries);
  /// Worker-only descriptor collection; all callers use the same rules/native mapping.
  QList<GameResource> library_resources(const QJsonArray& libraries);
  void validate_libraries(const QJsonObject& metadata);
  void run_processors(const QJsonObject& profile, const QString& installer,
                      const QString& extracted, const QString& java);
  void report(double progress, const QString& detail, bool immediate = false);
  void content_update(const QVariantMap& file, const QString& state, double progress = -1,
                      const QString& detail = {});
  QString commit_content(const QString& staging_id, const QString& name, QJsonObject metadata,
                         const QJsonArray& records, const QString& source);
  QString root_;
  QString portable_;
  Cancellation cancelled_;
  Progress progress_;
  ContentProgress content_progress_;
  QVariantMap content_item_;
  QHash<QString, QVariantMap> content_transfers_;
  QElapsedTimer progress_clock_;
  double reported_progress_ = -1;
  QString reported_detail_;
  ResourceClient resources_;
  QUrl facts_base_;
  QVariantMap dependency_context_;
  ContentRequest dependency_request_;
  QList<GameResource> pack_resources_;
  QSet<QString> resolving_;
};
}  // namespace bugg
#endif
