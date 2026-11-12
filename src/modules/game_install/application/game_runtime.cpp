#include "modules/game_install/application/game_runtime.h"

#include <QCoreApplication>
#include <QDesktopServices>
#include <QDir>
#include <QFileInfo>
#include <QFutureWatcher>
#include <QJSValue>
#include <QJsonObject>
#include <QUrl>
#include <QUuid>
#include <QtConcurrent/QtConcurrentRun>
#include <algorithm>
#include <utility>

#include "modules/game_install/application/game_operations.h"
#include "contracts/dependency_decision.h"
#include "modules/settings/application/language_service.h"
#include "platform/diagnostics/diagnostic_log.h"
#include "platform/runtime/runtime_environment.h"

namespace bugg {
namespace {
QVariantMap scan_instances(const QString& root) {
  QVariantList result;
  // Variants of one game share an asset index; keep only its language codes
  // for this scan, so the next scan still observes changed files/directories.
  QHash<QString, QStringList> language_indexes;
  const QDir versions(root + "/versions");
  QStringList watch_paths;
  auto ancestor = QDir(root);
  while (!ancestor.exists() && ancestor.cdUp()) {
  }
  if (ancestor.exists()) watch_paths.append(ancestor.absolutePath());
  if (versions.exists()) watch_paths.append(versions.absolutePath());
  for (const auto& id : versions.entryList(QDir::Dirs | QDir::NoDotAndDotDot, QDir::Name)) {
    watch_paths.append(versions.filePath(id));
    try {
      if (id.startsWith('.') || QFileInfo::exists(versions.filePath(id + "/.buggcraft-removed")))
        continue;
      const auto metadata = read_json(safe_path(root, "versions/" + id + '/' + id + ".json"));
      const auto descriptor = instance_descriptor(metadata);
      const QDir mods_directory(versions.filePath(id + "/mods"));
      if (mods_directory.exists()) watch_paths.append(mods_directory.absolutePath());
      const int mod_count =
          mods_directory.entryList({"*.jar"}, QDir::Files | QDir::NoSymLinks, QDir::Name).size();
      watch_paths.append(versions.filePath(id + '/' + id + ".json"));
      QStringList languages;
      try {
        languages = game_language_codes(root, metadata, &language_indexes);
      } catch (...) {
      }
      result.append(QVariantMap{{"id", id},
                                {"name", id},
                                {"version", descriptor.value("version")},
                                {"loader", descriptor.value("loader")},
                                {"loaderVersion", descriptor.value("loaderVersion")},
                                {"modCount", mod_count},
                                {"directory", versions.filePath(id)},
                                {"languages", languages}});
    } catch (...) { /* 单个坏 JSON 不隐藏其他真实实例。 */
    }
  }
  return {{"instances", result}, {"watchPaths", watch_paths}};
}
struct OperationResult {
  QString error;
  qint64 pid = 0;
  QVariantMap content;
};
}  // namespace
GameRuntime::GameRuntime(QString portable_root, QString game_root, AccountPort* account,
                         QObject* parent)
    : GameRuntimePort(parent),
      portable_(std::move(portable_root)),
      game_root_(std::move(game_root)),
      cache_root_(portable_cache_root(portable_)),
      account_(account) {
  rescan_timer_.setInterval(180);
  rescan_timer_.setSingleShot(true);
  connect(&rescan_timer_, &QTimer::timeout, this, &GameRuntime::refresh_instances);
  connect(&directory_watcher_, &QFileSystemWatcher::directoryChanged, &rescan_timer_,
          qOverload<>(&QTimer::start));
  connect(&directory_watcher_, &QFileSystemWatcher::fileChanged, &rescan_timer_,
          qOverload<>(&QTimer::start));
  connect(&process_, &GameProcess::exited, this, [this](int code) {
    publish_launch(
        code == 0 ? "idle" : "failed",
        code == 0 ? QString()
                  : QString(QCoreApplication::translate(
                                "Bugg", "游戏已退出（%1），可查看实例目录 logs/launcher-game.log"))
                        .arg(code));
    dispatch_next();
  });
}
QVariantMap GameRuntime::activity() const {
  if (launch_status_.value("state") == "preparing")
    return {{"active", true},
            {"progress", launch_status_.value("progress", -1)},
            {"label", launch_status_.value("detail")}};
  for (const auto& value : tasks_) {
    const auto task = value.toMap();
    if (task.value("kind") != "launch" &&
        (task.value("state") == "running" || task.value("state") == "cancelling"))
      return {{"active", true},
              {"progress", task.value("progress", -1)},
              {"label", task.value("detail")}};
  }
  return {{"active", false}, {"progress", 0}};
}
void GameRuntime::initialize() {
  if (initialization_started_ || closing_) return;
  initialization_started_ = true;
  initializing_ = true;
  initialization_cancelled_ = std::make_shared<std::atomic_bool>(false);
  ++workers_;
  auto* watcher = new QFutureWatcher<QPair<QVariantMap, QVariantMap>>(this);
  connect(watcher, &QFutureWatcherBase::finished, this, [this, watcher] {
    const auto [environment, settings] = watcher->result();
    watcher->deleteLater();
    --workers_;
    if (!closing_) {
      environment_ = environment;
      settings_ = settings;
      emit settings_changed();
      const auto configured = settings_.value("gameRoot").toString();
      if (!configured.isEmpty()) game_root_ = QDir(portable_).absoluteFilePath(configured);
      for (const auto& item : settings_.value("tasks").toList()) {
        auto task = item.toMap();
        if (task.value("kind") == "launch" || task.value("kind") == "remove") continue;
        if (QStringList{"queued", "running", "cancelling"}.contains(
                task.value("state").toString())) {
          task["state"] = "interrupted";
          task["detail"] = QCoreApplication::translate("Bugg", "上次未完成，可重试");
          auto items = task.value("contentItems").toList();
          for (auto& value : items) {
            auto entry = value.toMap();
            if (!QStringList{"done", "installed", "failed"}.contains(
                    entry.value("state").toString()))
              entry["state"] = "interrupted";
            value = entry;
          }
          task["contentItems"] = items;
        }
        specifications_[task.value("id").toString()] = task.take("specification").toMap();
        tasks_.append(task);
      }
      emit tasks_changed();
      emit environment_changed();
      refresh_instances();
    } else if (!busy())
      emit drained();
  });
  watcher->setFuture(QtConcurrent::run(
      [portable = portable_, cache = cache_root_, cancelled = initialization_cancelled_] {
        QVariantMap environment;
        try {
          environment = environment_snapshot(portable, cancelled);
        } catch (const std::exception& error) {
          environment["error"] = QString::fromUtf8(error.what());
        }
        QVariantMap settings;
        const auto path = cache + "/instance-settings.json";
        if (QFileInfo::exists(path)) {
          try {
            settings = read_json(path).toVariantMap();
          } catch (...) {
          }
        }
        return qMakePair(environment, settings);
      }));
}
void GameRuntime::refresh_instances() {
  if (closing_ || storage_migrating_) return;
  if (scan_pending_) {
    rescan_requested_ = true;
    return;
  }
  scan_pending_ = true;
  ++workers_;
  const auto root = game_root_;
  auto* watcher = new QFutureWatcher<QVariantMap>(this);
  connect(watcher, &QFutureWatcherBase::finished, this, [this, watcher, root] {
    const auto instances = watcher->result();
    watcher->deleteLater();
    --workers_;
    scan_pending_ = false;
    if (!closing_ && root == game_root_) {
      instances_ = instances.value("instances").toList();
      const auto old_paths = directory_watcher_.directories() + directory_watcher_.files();
      if (!old_paths.isEmpty()) directory_watcher_.removePaths(old_paths);
      const auto paths = instances.value("watchPaths").toStringList();
      if (!paths.isEmpty()) directory_watcher_.addPaths(paths);
      const bool initialized_now = initializing_;
      initializing_ = false;
      emit instances_changed();
      for (auto it = prepared_rooms_.begin(); it != prepared_rooms_.end();) {
        const auto instance = it->toMap().value("instance").toString();
        if (std::any_of(instances_.begin(), instances_.end(), [&instance](const auto& item) {
              return item.toMap().value("id").toString() == instance;
            })) {
          const auto ready = it->toMap();
          it = prepared_rooms_.erase(it);
          emit room_prepared(ready.value("session").toString(), instance,
                             ready.value("config").toString());
        } else {
          ++it;
        }
      }
      if (initialized_now) {
        emit initialized(environment_.value("error").toString());
      }
    } else if (!closing_)
      refresh_instances();
    if (rescan_requested_ && !closing_) {
      rescan_requested_ = false;
      rescan_timer_.start();
    }
    if (closing_ && !busy()) emit drained();
  });
  watcher->setFuture(QtConcurrent::run([root] { return scan_instances(root); }));
}
void GameRuntime::install(const QVariantMap& specification) {
  if (closing_ || storage_migrating_) return;
  if (initializing_) {
    emit notice(QCoreApplication::translate("Bugg", "游戏目录正在初始化，请稍后重试"));
    return;
  }
  if (QStringList{"content", "installWithContent"}.contains(
          specification.value("kind").toString()) &&
      !specification.value("id").toString().isEmpty() && launch_id_ == specification.value("id") &&
      !QStringList{"idle", "failed"}.contains(launch_status_.value("state").toString())) {
    emit notice(QCoreApplication::translate("Bugg", "请先停止此游戏再安装内容"));
    return;
  }
  for (const auto& value : tasks_) {
    const auto task = value.toMap();
    if (QStringList{"queued", "running", "cancelling"}.contains(task.value("state").toString()) &&
        specifications_.value(task.value("id").toString()) == specification) {
      emit notice(QCoreApplication::translate("Bugg", "该任务已在队列中"));
      return;
    }
  }
  const auto id = QUuid::createUuid().toString(QUuid::WithoutBraces);
  specifications_[id] = specification;
  tasks_.prepend(QVariantMap{{"id", id},
                             {"name", specification.value("name")},
                             {"kind", specification.value("kind", "install")},
                             {"state", "queued"},
                             {"progress", -1},
                             {"detail", QCoreApplication::translate("Bugg", "排队中")}});
  persist_tasks();
  emit tasks_changed();
  dispatch_next();
}
void GameRuntime::dispatch_next() {
  if (closing_ || initializing_ || !task_id_.isEmpty() ||
      launch_status_.value("state") == "preparing")
    return;
  for (auto it = tasks_.crbegin(); it != tasks_.crend(); ++it) {
    const auto task = it->toMap();
    if (task.value("state") == "queued") {
      const auto id = task.value("id").toString();
      const auto spec = specifications_.value(id);
      if (QStringList{"content", "installWithContent"}.contains(spec.value("kind").toString()) &&
          !spec.value("id").toString().isEmpty() && launch_id_ == spec.value("id").toString() &&
          !QStringList{"idle", "failed"}.contains(launch_status_.value("state").toString())) {
        continue;  // Resume this instance's queued mutations after its game exits.
      }
      run_operation(id, specifications_.value(id), false);
      return;
    }
  }
}
void GameRuntime::persist_tasks() {
  QVariantList stored;
  for (const auto& value : tasks_) {
    auto task = value.toMap();
    if (task.value("kind") == "launch") continue;
    task["specification"] = specifications_.value(task.value("id").toString());
    stored.append(task);
    if (stored.size() >= 100) break;
  }
  settings_["tasks"] = stored;
  save_settings();
}
void GameRuntime::update_task(const QString& id, const QString& state, double progress,
                              const QString& detail) {
  if (state != "running")
    record_diagnostic("task.state",
                      {{"task", id}, {"state", state}, {"detail", redact_diagnostic(detail)}});
  for (auto& value : tasks_) {
    auto task = value.toMap();
    if (task.value("id") != id) continue;
    task["state"] = state;
    task["progress"] = progress;
    task["detail"] = detail;
    value = task;
    break;
  }
  emit tasks_changed();
  if (state != "running") persist_tasks();
  const auto specification = specifications_.value(id);
  if (specification.value("kind") == "room" && state != "done")
    emit room_progress(specification.value("roomSession").toString(), id,
                       state == "running"      ? (progress < 0 ? "checking" : "downloading")
                       : state == "queued"     ? "idle"
                       : state == "cancelling" ? "cancelled"
                                               : state,
                       progress, specification.value("roomConfig").toString());
}
void GameRuntime::update_content_item(const QString& id, const QVariantMap& item) {
  for (auto& value : tasks_) {
    auto task = value.toMap();
    if (task.value("id") != id) continue;
    auto items = task.value("contentItems").toList();
    bool replaced = false;
    for (auto& entry : items) {
      if (entry.toMap().value("key") != item.value("key")) continue;
      entry = item;
      replaced = true;
      break;
    }
    if (!replaced && items.size() < 128) items.append(item);
    task["contentItems"] = items;
    if (item.contains("aggregateSpeedText") && !item.value("aggregateSpeedText").isNull()) {
      task["downloadSpeed"] = item.value("aggregateSpeedText");
      task["activeTransfers"] = item.value("activeTransfers");
    }
    value = task;
    emit tasks_changed();
    return;
  }
}
void GameRuntime::run_operation(const QString& id, const QVariantMap& specification, bool launching,
                                const GameIdentity& identity, const QVariantMap& contributions) {
  const auto kind = specification.value("kind", "install").toString();
  (launching ? launch_task_id_ : task_id_) = id;
  auto& cancellation = launching ? launch_cancelled_ : cancelled_;
  cancellation = std::make_shared<std::atomic_bool>(false);
  const auto cancelled = cancellation;
  for (auto& value : tasks_) {
    auto task = value.toMap();
    if (task.value("id") != id) continue;
    task.remove("contentItems");
    value = task;
    break;
  }
  ++workers_;
  update_task(id, "running", -1,
              launching ? QCoreApplication::translate("Bugg", "准备游戏文件与 Java")
                        : QCoreApplication::translate("Bugg", "准备安装"));
  auto* watcher = new QFutureWatcher<OperationResult>(this);
  // 工作 lambda 只捕获值；进度使用仍存活的 watcher 作 queued 回传上下文。
  const auto progress = [this, watcher, id, cancelled, launching](double value,
                                                                  const QString& detail) {
    QMetaObject::invokeMethod(
        watcher,
        [this, id, cancelled, launching, value, detail] {
          if (closing_ || cancelled->load() || (launching ? launch_task_id_ : task_id_) != id)
            return;
          update_task(id, "running", value, detail);
          if (launching) publish_launch("preparing", detail, value);
        },
        Qt::QueuedConnection);
  };
  const auto content_progress = [this, watcher, id, cancelled, launching](const QVariantMap& item) {
    QMetaObject::invokeMethod(
        watcher,
        [this, id, cancelled, item, launching] {
          if (closing_ || cancelled->load() || (launching ? launch_task_id_ : task_id_) != id)
            return;
          update_content_item(id, item);
        },
        Qt::QueuedConnection);
  };
  connect(
      watcher, &QFutureWatcherBase::finished, this,
      [this, watcher, id, cancelled, launching, kind, specification] {
        const auto result = watcher->result();
        watcher->deleteLater();
        --workers_;
        auto& current = launching ? launch_task_id_ : task_id_;
        if (current == id) current.clear();
        const bool aborted = cancelled->load();
        const auto dependency_decision = result.content.value("dependencyDecision").toMap();
        if (!aborted && !dependency_decision.isEmpty()) {
          for (auto& value : tasks_) {
            auto task = value.toMap();
            if (task.value("id") != id) continue;
            task["dependencyDecision"] = dependency_decision;
            value = task;
            break;
          }
          update_task(id, "needs_dependency_decision", -1,
                      QCoreApplication::translate("Bugg", "依赖检查需要选择；已下载文件保留，尚未提交安装"));
          persist_tasks();
          dispatch_next();
          if (closing_ && !busy()) emit drained();
          return;
        }
        const auto missing = result.content.value("missingDependencies").toList();
        for (auto& value : tasks_) {
          auto task = value.toMap();
          if (task.value("id") != id) continue;
          task["missingDependencies"] = missing;
          auto items = task.value("contentItems").toList();
          for (auto& entry : items) {
            auto item = entry.toMap();
            if (!QStringList{"done", "installed", "failed"}.contains(
                    item.value("state").toString())) {
              item["state"] = aborted ? "cancelled" : result.error.isEmpty() ? "done" : "failed";
              item["detail"] =
                  aborted ? QCoreApplication::translate("Bugg", "已取消") : result.error;
            }
            entry = item;
          }
          task["contentItems"] = items;
          value = task;
          break;
        }
        if (!missing.isEmpty() && !aborted && result.error.isEmpty()) {
          auto retry = specification;
          retry["kind"] = "content";
          retry["id"] = result.content.value("instance");
          retry["retryDependencies"] = true;
          specifications_[id] = retry;
          if (!closing_)
            emit notice(QCoreApplication::translate(
                            "Bugg", "所选内容已安装，%1 项必要依赖未补齐，请在任务中查看并重试")
                            .arg(missing.size()));
        }
        update_task(id,
                    aborted                  ? "cancelled"
                    : result.error.isEmpty() ? "done"
                                             : "failed",
                    result.error.isEmpty() && !aborted ? 1 : -1,
                    aborted ? QCoreApplication::translate("Bugg", "已取消，已校验文件保留供重试")
                    : result.error.isEmpty()
                        ? (launching ? QCoreApplication::translate("Bugg", "游戏进程已启动")
                           : !missing.isEmpty()
                               ? QCoreApplication::translate(
                                     "Bugg", "所选内容已安装；缺少必要依赖，游戏可能无法正常运行")
                           : kind == "export" ? QString()
                                              : QCoreApplication::translate("Bugg", "安装完成"))
                        : result.error);
        if (result.pid) {
          // 创建进程与取消竞争时，PID 已真实存在，不能假报未启动或遗留不可停止进程。
          process_.watch(result.pid);
          publish_launch("running",
                         QCoreApplication::translate("Bugg", "游戏进程已启动，日志保存在实例目录"),
                         1);
          if (aborted && !closing_) stop_game();
        } else if (launching)
          publish_launch(aborted ? "idle" : "failed", result.error);
        if (!launching && result.error.isEmpty() && !aborted && !closing_) {
          if (kind == "room")
            prepared_rooms_.append(QVariantMap{{"session", specification.value("roomSession")},
                                               {"instance", specification.value("name")},
                                               {"config", specification.value("roomConfig")}});
          refresh_instances();
          if (missing.isEmpty() &&
              QStringList{"install", "installWithContent", "import"}.contains(kind)) {
            const auto instance = result.content.value("instance").toString();
            if (!instance.isEmpty()) set_preference("selectedInstance", instance);
            emit installation_finished(id, instance);
          }
          if (kind == "content" && content_.value("instance") == specification.value("id"))
            refresh_content(specification.value("id").toString(),
                            content_.value("category").toString());
        }
        if (!launching && id == launch_paused_task_) {
          launch_paused_task_.clear();
          if (aborted)
            update_task(id, "queued", -1,
                        QCoreApplication::translate("Bugg", "游戏退出后继续安装"));
          const auto intent = std::exchange(pending_launch_, {});
          if (!closing_ && !intent.isEmpty()) {
            publish_launch("idle");
            launch(intent.value("instance").toString(), intent.value("profile").toString(),
                   intent.value("contributions").toMap());
          }
        }
        persist_tasks();
        dispatch_next();
        if (closing_ && !busy()) emit drained();
      });
  const auto game_root = game_root_;
  const auto portable = portable_;
  const auto order = source_order_;
  const auto bugg_base = bugg_base_;
  const auto room_request = room_content_request_;
  const auto content_request = content_request_;
  const auto settings = instance_settings(specification.value("id").toString());
  auto launch_options = settings;
  for (auto it = contributions.begin(); it != contributions.end(); ++it)
    launch_options[it.key()] = it.value();
  launch_options["language"] = preferences().value("language");
  launch_options["concurrency"] = preferences().value("concurrency");
  launch_options["javaPath"] = settings.value("javaPath");
  watcher->setFuture(QtConcurrent::run([=] {
    try {
      GameOperations operation(game_root, portable, order, cancelled, progress,
                               launch_options.value("concurrency").toInt(), nullptr, bugg_base);
      operation.set_content_progress(content_progress);
      operation.set_dependency_context(specification, content_request);
      if (!launching) {
        const auto kind = specification.value("kind", "install").toString();
        if (kind == "room")
          operation.sync_room(specification, room_request);
        else if (kind == "content" || kind == "onlinePack")
          return OperationResult{{}, 0, operation.install_content(specification, content_request)};
        else if (kind == "import")
          return OperationResult{
              {},
              0,
              {{"instance", operation.import_pack(specification.value("archive").toString(),
                                                  specification.value("name").toString())}}};
        else if (kind == "export")
          operation.export_pack(
              specification.value("id").toString(), specification.value("destination").toString(),
              specification.value("compact").toBool(), specification.value("saves").toBool());
        else if (kind == "installWithContent")
          return OperationResult{
              {}, 0, operation.install_with_content(specification, content_request)};
        else
          return OperationResult{{}, 0, {{"instance", operation.install(specification)}}};
        return OperationResult{};
      }
      const auto snapshot = memory_snapshot();
      const QDir mods_directory(
          safe_path(game_root, "versions/" + specification.value("id").toString() + "/mods"));
      const int mod_count =
          mods_directory.entryList({"*.jar"}, QDir::Files | QDir::NoSymLinks, QDir::Name).size();
      const int hosted_players = qBound(1, contributions.value("hostPlayerCount", 1).toInt(), 32);
      if (settings.value("automatic", true).toBool() &&
          memory_limit_mb(snapshot) < kMinimumAutomaticMemoryMB)
        throw std::runtime_error(
            (QCoreApplication::translate("Bugg", "可分配上限 %1 GiB")
                 .arg(QString::number(memory_limit_mb(snapshot) / 1024.0, 'f', 1)) +
             " < " + QString::number(kMinimumAutomaticMemoryMB / 1024.0, 'f', 1) + " GiB")
                .toStdString());
      const int memory =
          settings.value("automatic", true).toBool()
              ? automatic_memory_mb(snapshot, mod_count, hosted_players)
              : qBound(512, settings.value("memoryMB", 4096).toInt(), memory_limit_mb(snapshot));
      const auto command =
          operation.prepare(specification.value("id").toString(), memory, identity, launch_options);
      check_cancelled(cancelled);
      return OperationResult{{}, start_game_process(command)};
    } catch (const DependencyDecision& decision) {
      return OperationResult{{}, 0, {{"dependencyDecision", decision.value()}}};
    } catch (const std::exception& error) {
      return OperationResult{QString::fromUtf8(error.what())};
    }
  }));
}
void GameRuntime::publish_launch(const QString& state, const QString& detail, double progress) {
  const QMap<QString, QString> titles{
      {"idle", ""},
      {"preparing", QCoreApplication::translate("Bugg", "正在启动游戏")},
      {"running", QCoreApplication::translate("Bugg", "游戏正在运行")},
      {"stopping", QCoreApplication::translate("Bugg", "正在停止游戏")},
      {"failed", QCoreApplication::translate("Bugg", "启动未完成")}};
  launch_status_ = {{"state", state},       {"title", titles.value(state)}, {"detail", detail},
                    {"progress", progress}, {"instanceName", launch_id_},   {"preview", false}};
  emit launch_changed(launch_status_);
  emit status_changed();
  emit tasks_changed();
}
void GameRuntime::launch(const QString& instance_id, const QString& profile_id,
                         const QVariantMap& contributions) {
  if (closing_ || initializing_ || storage_migrating_ ||
      !QStringList{"idle", "failed"}.contains(launch_status_.value("state").toString()))
    return;
  const auto active = specifications_.value(task_id_);
  if (!task_id_.isEmpty() && active.value("id").toString() == instance_id &&
      QStringList{"content", "installWithContent"}.contains(active.value("kind").toString())) {
    pending_launch_ = {
        {"instance", instance_id}, {"profile", profile_id}, {"contributions", contributions}};
    launch_paused_task_ = task_id_;
    cancel_task(task_id_);
    publish_launch("preparing", QCoreApplication::translate(
                                    "Bugg", "正在暂停此游戏的安装，随后启动；退出游戏后继续安装"));
    return;
  }
  bool found = false;
  for (const auto& instance : instances_) found |= instance.toMap().value("id") == instance_id;
  if (!found) {
    publish_launch("failed", QCoreApplication::translate("Bugg", "找不到所选实例，请刷新游戏列表"));
    return;
  }
  launch_id_ = instance_id;
  publish_launch("preparing", QCoreApplication::translate("Bugg", "正在确认游戏身份"));
  const auto generation = ++generation_;
  disconnect(credentials_connection_);
  credentials_connection_ =
      connect(account_, &AccountPort::credentials_ready, this,
              [this, generation, instance_id, contributions](
                  quint64 operation, const GameIdentity& identity, const QString& error) {
                if (operation != generation) return;
                disconnect(credentials_connection_);
                if (generation != generation_ || closing_) return;
                if (!error.isEmpty()) {
                  publish_launch("failed", error);
                  dispatch_next();
                  return;
                }
                const auto id = QUuid::createUuid().toString(QUuid::WithoutBraces);
                tasks_.prepend(QVariantMap{{"id", id}, {"name", instance_id}, {"kind", "launch"}});
                run_operation(id, {{"id", instance_id}}, true, identity, contributions);
              });
  account_->acquire(generation, profile_id);
}
void GameRuntime::cancel_launch() {
  pending_launch_.clear();
  ++generation_;
  disconnect(credentials_connection_);
  if (launch_status_.value("state") == "preparing") {
    if (launch_cancelled_ && !launch_task_id_.isEmpty())
      cancel_task(launch_task_id_);
    else
      publish_launch("idle");
    dispatch_next();
  } else if (launch_status_.value("state") == "failed")
    publish_launch("idle");
}
void GameRuntime::stop_game() {
  if (launch_status_.value("state") != "running") return;
  publish_launch("stopping", QCoreApplication::translate("Bugg", "等待游戏进程退出"));
  process_.stop();
}
void GameRuntime::cancel_task(const QString& id) {
  for (const auto& value : tasks_) {
    const auto task = value.toMap();
    if (task.value("id") == id && (task.value("state") == "queued" || task.value("state") == "needs_dependency_decision")) {
      update_task(id, "cancelled", -1, QCoreApplication::translate("Bugg", "已取消"));
      return;
    }
  }
  const auto cancellation = id == launch_task_id_ ? launch_cancelled_
                            : id == task_id_      ? cancelled_
                                                  : Cancellation{};
  if (!cancellation) return;
  cancellation->store(true);
  update_task(id, "cancelling", -1, QCoreApplication::translate("Bugg", "正在取消"));
}
void GameRuntime::retry_task(const QString& id) {
  if (closing_ || initializing_ || !specifications_.contains(id)) return;
  for (const auto& value : tasks_) {
    const auto task = value.toMap();
    if (task.value("id") == id &&
        (QStringList{"failed", "cancelled", "interrupted"}.contains(
             task.value("state").toString()) ||
         task.value("state") == "done" && !task.value("missingDependencies").toList().isEmpty())) {
      update_task(id, "queued", -1, QCoreApplication::translate("Bugg", "排队中"));
      dispatch_next();
      return;
    }
  }
}
void GameRuntime::resolve_dependencies(const QString& id, const QString& choice) {
  if (closing_ || initializing_ || !specifications_.contains(id) ||
      !QStringList{"keep", "repair", "cancel"}.contains(choice)) return;
  for (const auto& value : tasks_) {
    const auto task = value.toMap();
    if (task.value("id") != id || task.value("state") != "needs_dependency_decision") continue;
    const auto decision = task.value("dependencyDecision").toMap();
    if (choice == "cancel") { cancel_task(id); persist_tasks(); return; }
    if (choice == "repair" && !decision.value("canRepair").toBool()) return;
    auto specification = specifications_.value(id);
    specification["dependencyChoice"] = choice;
    specification["dependencyFingerprint"] = decision.value("fingerprint");
    specifications_[id] = specification;
    update_task(id, "queued", -1, QCoreApplication::translate("Bugg", "继续核对已下载的文件"));
    persist_tasks();
    dispatch_next();
    return;
  }
}
int GameRuntime::clear_task_history() {
  const auto previous = tasks_.size();
  tasks_.removeIf([this](const QVariant& value) {
    const auto task = value.toMap();
    if (!QStringList{"done", "failed", "cancelled", "interrupted"}.contains(
            task.value("state").toString()))
      return false;
    specifications_.remove(task.value("id").toString());
    return true;
  });
  const auto removed = previous - tasks_.size();
  if (removed) {
    persist_tasks();
    emit tasks_changed();
  }
  return removed;
}
QVariantMap GameRuntime::instance_settings(const QString& id) const {
  auto value = settings_.value("game").toMap();
  const auto overrides = settings_.value("instances").toMap().value(id).toMap();
  for (auto it = overrides.begin(); it != overrides.end(); ++it) value[it.key()] = it.value();
  if (!value.contains("automatic")) value["automatic"] = true;
  if (!value.contains("memoryMB")) value["memoryMB"] = 4096;
  const auto instance = std::find_if(
      instances_.cbegin(), instances_.cend(),
      [&id](const QVariant& item) { return item.toMap().value("id").toString() == id; });
  const int mod_count =
      instance == instances_.cend() ? 0 : instance->toMap().value("modCount").toInt();
  value["automaticMemoryMB"] = automatic_memory_mb(environment_, mod_count);
  if (!value.contains("fullscreen")) value["fullscreen"] = false;
  if (!value.contains("resolution")) value["resolution"] = "1280x720";
  value["overridden"] = !id.isEmpty() && !overrides.isEmpty();
  return value;
}
QVariantMap GameRuntime::preferences() const {
  auto value = settings_.value("preferences").toMap();
  if (!value.contains("language")) value["language"] = "zh_cn";
  if (!value.contains("concurrency")) value["concurrency"] = 6;
  if (!value.contains("afterLaunch")) value["afterLaunch"] = "collapse";
  if (!value.contains("theme")) value["theme"] = "small";
  if (!value.contains("startCollapsed")) value["startCollapsed"] = false;
  if (!value.contains("showOverlayInFullscreen")) value["showOverlayInFullscreen"] = false;
  if (!value.contains("swipeHintSeen")) value["swipeHintSeen"] = false;
  if (!value.contains("contentTranslation")) value["contentTranslation"] = true;
  if (!value.contains("multiplayerOrigin")) value["multiplayerOrigin"] = "";
  return value;
}
bool GameRuntime::set_preference(const QString& key, const QVariant& input) {
  if (closing_ || initializing_) return false;
  const QVariant value = input.metaType() == QMetaType::fromType<QJSValue>()
                             ? input.value<QJSValue>().toVariant()
                             : input;
  if ((key == "language" && !LanguageService::known_language(value.toString())) ||
      (key == "concurrency" && !QList<int>{1, 2, 4, 6, 8, 16, 32}.contains(value.toInt())) ||
      (key == "afterLaunch" && !QStringList{"keep", "collapse"}.contains(value.toString())) ||
      (key == "theme" &&
       !QStringList{"panel", "small", "classic", "large"}.contains(value.toString())) ||
      ((key == "startCollapsed" || key == "showOverlayInFullscreen" || key == "swipeHintSeen" ||
        key == "contentTranslation") &&
       value.metaType().id() != QMetaType::Bool) ||
      (key == "multiplayerOrigin" &&
       (value.metaType().id() != QMetaType::QString || value.toString().size() > 2048)) ||
      (key == "backgrounds" && value.toList().size() > 20) ||
      (key == "identity" && value.metaType().id() != QMetaType::QVariantMap) ||
      !QStringList{"language", "concurrency", "afterLaunch", "theme", "startCollapsed",
                   "backgrounds", "selectedInstance", "identity", "swipeHintSeen",
                   "contentTranslation", "multiplayerOrigin", "showOverlayInFullscreen"}
           .contains(key))
    return false;
  if (preferences().value(key) == value) return true;
  auto values = preferences();
  values[key] = value;
  settings_["preferences"] = values;
  emit settings_changed();
  save_settings();
  return true;
}
bool GameRuntime::set_game_setting(const QString& id, const QString& key, const QVariant& value) {
  if (closing_ || initializing_) return false;
  const QVariant normalized = key == "javaPath" && QUrl(value.toString()).isLocalFile()
                                  ? QVariant(QUrl(value.toString()).toLocalFile())
                                  : value;
  const int maximum = memory_limit_mb(environment_);
  const QFileInfo java_info(normalized.toString());
  const QString java_name = java_info.fileName().toLower();
  if (((key == "automatic" || key == "fullscreen") &&
       normalized.metaType().id() != QMetaType::Bool) ||
      (key == "memoryMB" && (normalized.toInt() < 512 || normalized.toInt() > maximum)) ||
      (key == "javaPath" && !normalized.toString().isEmpty() &&
       (!java_info.isAbsolute() || !java_info.isFile() ||
        (java_name != "java.exe" && java_name != "java"))) ||
      (key == "resolution" &&
       !QStringList{"854x480", "1280x720", "1600x900", "1920x1080", "2560x1440"}.contains(
           normalized.toString())) ||
      !QStringList{"automatic", "memoryMB", "fullscreen", "resolution", "javaPath"}.contains(key))
    return false;
  if (key == "javaPath") {
    const auto generation = ++java_selection_generations_[id];
    const auto entries = environment_.value("javaEntries").toList();
    const bool verified = std::any_of(entries.cbegin(), entries.cend(), [&](const QVariant& entry) {
      return entry.toMap().value("id") == normalized;
    });
    if (!normalized.toString().isEmpty() && !verified) {
      // 添加路径与自动扫描复用同一个 java -version 探测；验证前不落盘、不切换选择。
      run_file_work(
          [path = normalized.toString()](const Cancellation& cancelled) {
            return QVariantMap{{"major", java_major(path, cancelled)}};
          },
          [this, id, normalized, generation](const QVariantMap& result) {
            if (java_selection_generations_.value(id) != generation) return;
            const auto major = result.value("major").toInt();
            if (!major) {
              emit notice(QCoreApplication::translate(
                  "Bugg", "没有适合此平台的 Java，请在 Java 设置中指定已安装的兼容版本"));
              return;
            }
            auto entries = environment_.value("javaEntries").toList();
            if (std::none_of(entries.cbegin(), entries.cend(), [&](const QVariant& entry) {
                  return entry.toMap().value("id") == normalized;
                }))
              entries.append(
                  QVariantMap{{"id", normalized},
                              {"name", QString("Java %1").arg(major)},
                              {"caption", QDir::toNativeSeparators(normalized.toString())},
                              {"major", major}});
            environment_["javaEntries"] = entries;
            emit environment_changed();
            set_game_setting(id, "javaPath", normalized);
          });
      return true;
    }
  }
  if (instance_settings(id).value(key) == normalized) return true;
  if (id.isEmpty()) {
    auto game = settings_.value("game").toMap();
    game[key] = normalized;
    settings_["game"] = game;
  } else {
    auto instances = settings_.value("instances").toMap();
    auto overrides = instances.value(id).toMap();
    overrides[key] = normalized;
    instances[id] = overrides;
    settings_["instances"] = instances;
  }
  emit settings_changed();
  save_settings();
  return true;
}
void GameRuntime::reset_instance_settings(const QString& id) {
  if (closing_ || initializing_ || id.isEmpty()) return;
  ++java_selection_generations_[id];
  auto instances = settings_.value("instances").toMap();
  if (!instances.remove(id)) return;
  settings_["instances"] = instances;
  emit settings_changed();
  save_settings();
}
void GameRuntime::save_instance_settings(const QString& id, bool automatic, int memory_mb) {
  // 兼容早期调用者；校验、合并和持久化只走逐项设置入口。
  if (!id.isEmpty() && set_game_setting(id, "memoryMB", memory_mb))
    set_game_setting(id, "automatic", automatic);
}
void GameRuntime::save_settings() {
  settings_dirty_ = true;
  if (settings_writing_) return;
  settings_dirty_ = false;
  settings_writing_ = true;
  ++workers_;
  auto* watcher = new QFutureWatcher<QString>(this);
  connect(watcher, &QFutureWatcherBase::finished, this, [this, watcher] {
    const auto error = watcher->result();
    watcher->deleteLater();
    --workers_;
    settings_writing_ = false;
    if (!error.isEmpty()) emit notice(error);
    if (settings_dirty_) save_settings();
    if (closing_ && !busy()) emit drained();
  });
  watcher->setFuture(
      QtConcurrent::run([path = cache_root_ + "/instance-settings.json", settings = settings_] {
        try {
          write_json(path, QJsonObject::fromVariantMap(settings));
          checkpoint_diagnostics(QFileInfo(path).absolutePath());
          return QString();
        } catch (const std::exception& error) {
          return QString::fromUtf8(error.what());
        }
      }));
}
void GameRuntime::select_game_root(const QString& path) {
  if (closing_ || initializing_ || storage_migrating_ || !task_id_.isEmpty() ||
      launch_status_.value("state") == "preparing") {
    emit notice(QCoreApplication::translate("Bugg", "请等待当前准备任务结束"));
    return;
  }
  const QUrl url(path);
  const auto local = url.isLocalFile() ? url.toLocalFile() : path;
  if (!QFileInfo(local).isAbsolute() || !QFileInfo(local).isDir()) {
    emit notice(QCoreApplication::translate("Bugg", "请选择已有的 Minecraft 目录"));
    return;
  }
  game_root_ = QDir(local).absolutePath();
  prepared_rooms_.clear();
  settings_["gameRoot"] = QDir(portable_).relativeFilePath(game_root_);
  save_settings();
  refresh_instances();
}
void GameRuntime::open_directory(const QString& id) {
  try {
    QDesktopServices::openUrl(
        QUrl::fromLocalFile(id.isEmpty() ? game_root_ : safe_path(game_root_, "versions/" + id)));
  } catch (const std::exception& error) {
    emit notice(QString::fromUtf8(error.what()));
  }
}
void GameRuntime::shutdown() {
  closing_ = true;
  rescan_timer_.stop();
  ++generation_;
  disconnect(credentials_connection_);
  if (cancelled_) cancelled_->store(true);
  if (launch_cancelled_) launch_cancelled_->store(true);
  if (initialization_cancelled_) initialization_cancelled_->store(true);
  process_.release();
  if (!busy()) emit drained();
}
}  // namespace bugg
