#include <QCoreApplication>
#include <QDirIterator>
#include <QFileInfo>
#include <QFutureWatcher>
#include <QUrl>
#include <QtConcurrent/QtConcurrentRun>

#include "modules/game_install/application/game_operations.h"
#include "modules/game_install/application/game_runtime.h"
#include "modules/game_install/application/modpack_plan.h"
#include "platform/runtime/runtime_environment.h"

namespace bugg {
namespace {
QString local_path(const QString& value) {
  const QUrl url(value);
  return url.isLocalFile() ? url.toLocalFile() : value;
}
QString content_directory(const QString& root, const QString& id, const QString& category) {
  if (id.isEmpty() || !QStringList{"mods", "resourcepacks", "shaderpacks"}.contains(category))
    throw std::runtime_error("Invalid content category");
  return safe_path(root, "versions/" + id + '/' + category);
}
bool supported_content(const QString& name, const QString& category) {
  const auto normalized = name.endsWith(".disabled") ? name.chopped(9) : name;
  return normalized.endsWith(category == "mods" ? ".jar" : ".zip", Qt::CaseInsensitive);
}
}  // namespace
void GameRuntime::run_file_work(std::function<QVariantMap(const Cancellation&)> work,
                                std::function<void(const QVariantMap&)> complete) {
  if (closing_ || initializing_) return;
  ++workers_;
  auto* watcher = new QFutureWatcher<QVariantMap>(this);
  connect(watcher, &QFutureWatcherBase::finished, this,
          [this, watcher, complete = std::move(complete)] {
            const auto result = watcher->result();
            watcher->deleteLater();
            --workers_;
            if (!closing_) complete(result);
            if (closing_ && !busy()) emit drained();
          });
  watcher->setFuture(
      QtConcurrent::run([work = std::move(work), cancelled = initialization_cancelled_] {
        try {
          check_cancelled(cancelled);
          return work(cancelled);
        } catch (const std::exception& error) {
          return QVariantMap{{"error", QString::fromUtf8(error.what())}};
        }
      }));
}
void GameRuntime::check_room(const QString& session, quint64 revision, const QString& instance_id,
                             const QVariantMap& game) {
  const auto root = game_root_;
  const auto portable = portable_;
  const auto order = source_order_;
  const auto bugg_base = bugg_base_;
  run_file_work(
      [=](const Cancellation& cancelled) {
        GameOperations operation(
            root, portable, order, cancelled, [](double, const QString&) {}, 6, nullptr, bugg_base);
        return operation.check_room(instance_id, QJsonObject::fromVariantMap(game));
      },
      [=, this](const QVariantMap& result) {
        emit room_checked(session, revision, instance_id, result);
      });
}
void GameRuntime::cancel_room(const QString& session) {
  for (const auto& value : tasks_) {
    const auto task = value.toMap();
    const auto spec = specifications_.value(task.value("id").toString());
    if (spec.value("kind") == "room" && spec.value("roomSession") == session)
      cancel_task(task.value("id").toString());
  }
  prepared_rooms_.removeIf(
      [&](const QVariant& value) { return value.toMap().value("session") == session; });
}
void GameRuntime::inspect_pack(const QString& url) {
  if (closing_ || initializing_) return;
  const auto path = local_path(url);
  const auto generation = ++pack_generation_;
  pack_preview_ = {{"loading", true}, {"path", path}};
  emit pack_preview_changed();
  run_file_work(
      [path](const Cancellation& cancelled) {
        const auto plan = inspect_modpack(path, cancelled);
        auto preview = plan.specification;
        preview["path"] = path;
        preview["format"] = plan.format;
        preview["fileCount"] = plan.files.size();
        return preview;
      },
      [this, generation](const QVariantMap& result) {
        if (generation != pack_generation_) return;
        pack_preview_ = result;
        emit pack_preview_changed();
      });
}
void GameRuntime::import_pack(const QString& name) {
  if (pack_preview_.value("loading").toBool() || pack_preview_.contains("error") ||
      pack_preview_.value("path").toString().isEmpty())
    return;
  install({{"kind", "import"}, {"name", name}, {"archive", pack_preview_.value("path")}});
}
void GameRuntime::export_pack(const QString& id, const QString& url, bool compact, bool saves) {
  auto destination = local_path(url);
  if (!destination.endsWith(".buggpack", Qt::CaseInsensitive)) destination += ".buggpack";
  install({{"kind", "export"},
           {"id", id},
           {"name", id},
           {"destination", destination},
           {"compact", compact},
           {"saves", saves}});
}
bool GameRuntime::remove_instance(const QString& id, bool permanent) {
  if (closing_ || initializing_ || storage_migrating_ || id.isEmpty()) return false;
  for (const auto& value : tasks_) {
    const auto task = value.toMap();
    const auto spec = specifications_.value(task.value("id").toString());
    if (QStringList{"queued", "running", "cancelling"}.contains(task.value("state").toString()) &&
        spec.value("id", spec.value("name")).toString() == id) {
      emit notice(QCoreApplication::translate("Bugg", "请等待当前任务结束"));
      return false;
    }
  }
  if (launch_id_ == id &&
      !QStringList{"idle", "failed"}.contains(launch_status_.value("state").toString())) {
    emit notice(QCoreApplication::translate("Bugg", "请先停止此游戏"));
    return false;
  }
  run_file_work(
      [root = game_root_, id, permanent](const Cancellation& cancelled) {
        const auto target = safe_path(root, "versions/" + id);
        check_cancelled(cancelled);
        if (permanent) {
          if (!QDir(target).removeRecursively()) throw std::runtime_error("Cannot remove instance");
        } else {
          write_json(safe_path(target, ".buggcraft-removed"), {{"removed", true}});
        }
        return QVariantMap{};
      },
      [this](const QVariantMap& result) {
        if (result.contains("error"))
          emit notice(result.value("error").toString());
        else
          refresh_instances();
      });
  return true;
}
void GameRuntime::refresh_content(const QString& id, const QString& category) {
  if (closing_ || initializing_) return;
  const auto generation = ++content_generation_;
  content_ = {{"instance", id}, {"category", category}, {"loading", true}};
  emit content_changed();
  run_file_work(
      [root = game_root_, id, category](const Cancellation& cancelled) {
        const auto directory = content_directory(root, id, category);
        QVariantList entries;
        for (const auto& file :
             QDir(directory).entryInfoList(QDir::Files | QDir::NoSymLinks, QDir::Name)) {
          check_cancelled(cancelled);
          if (!supported_content(file.fileName(), category)) continue;
          entries.append(QVariantMap{{"name", file.fileName()},
                                     {"size", file.size()},
                                     {"enabled", !file.fileName().endsWith(".disabled")}});
        }
        return QVariantMap{{"entries", entries}};
      },
      [this, id, category, generation](const QVariantMap& result) {
        if (generation != content_generation_) return;
        content_ = result;
        content_["instance"] = id;
        content_["category"] = category;
        emit content_changed();
      });
}
void GameRuntime::change_content(const QString& id, const QString& category, const QString& name,
                                 const QString& action) {
  if (closing_ || initializing_ || storage_migrating_ || content_.value("loading").toBool()) return;
  if (!task_id_.isEmpty()) {
    emit notice(QCoreApplication::translate("Bugg", "请等待当前任务结束"));
    return;
  }
  if (launch_id_ == id &&
      !QStringList{"idle", "failed"}.contains(launch_status_.value("state").toString())) {
    emit notice(QCoreApplication::translate("Bugg", "请先停止此游戏"));
    return;
  }
  content_["loading"] = true;
  emit content_changed();
  run_file_work(
      [root = game_root_, id, category, name, action](const Cancellation& cancelled) {
        const auto directory = content_directory(root, id, category);
        if (QFileInfo(name).fileName() != name || !supported_content(name, category))
          throw std::runtime_error("Invalid content filename");
        const auto source = safe_path(directory, name);
        check_cancelled(cancelled);
        if (action == "delete") {
          if (!QFile::moveToTrash(source)) throw std::runtime_error("Cannot move file to trash");
        } else if (action == "toggle") {
          const auto target = safe_path(
              directory, name.endsWith(".disabled") ? name.chopped(9) : name + ".disabled");
          if (!QFile::rename(source, target))
            throw std::runtime_error("Cannot enable or disable file");
        } else
          throw std::runtime_error("Invalid content action");
        return QVariantMap{};
      },
      [this, id, category](const QVariantMap& result) {
        if (result.contains("error")) emit notice(result.value("error").toString());
        refresh_content(id, category);
      });
}
void GameRuntime::add_content(const QString& id, const QString& category,
                              const QVariantList& urls) {
  if (closing_ || initializing_ || storage_migrating_ || content_.value("loading").toBool() ||
      urls.isEmpty())
    return;
  if (!task_id_.isEmpty()) {
    emit notice(QCoreApplication::translate("Bugg", "请等待当前任务结束"));
    return;
  }
  if (launch_id_ == id &&
      !QStringList{"idle", "failed"}.contains(launch_status_.value("state").toString())) {
    emit notice(QCoreApplication::translate("Bugg", "请先停止此游戏"));
    return;
  }
  content_["loading"] = true;
  emit content_changed();
  run_file_work(
      [root = game_root_, id, category, urls](const Cancellation& cancelled) {
        const auto directory = content_directory(root, id, category);
        for (const auto& url : urls) {
          const auto source = local_path(url.toString());
          const auto name = QFileInfo(source).fileName();
          if (!supported_content(name, category) || QFileInfo(source).isSymLink())
            throw std::runtime_error("Unsupported content file");
          copy_file(source, safe_path(directory, name), cancelled);
        }
        return QVariantMap{};
      },
      [this, id, category](const QVariantMap& result) {
        if (result.contains("error")) emit notice(result.value("error").toString());
        refresh_content(id, category);
      });
}
void GameRuntime::inspect_content_install(const QString& id, const QVariantMap& plan) {
  const auto generation = ++content_install_generation_;
  content_installation_ = {{"instance", id}, {"requestedPlan", plan}, {"loading", true}};
  emit content_installation_changed();
  run_file_work(
      [root = game_root_, portable = portable_, order = source_order_, bugg_base = bugg_base_, id,
       plan, request = content_request_](const Cancellation& cancelled) {
        GameOperations operation(
            root, portable, order, cancelled, [](double, const QString&) {}, 6, nullptr, bugg_base);
        const auto effective_plan = operation.prepare_content_install(id, plan, request);
        auto result = operation.check_content_install(id, effective_plan);
        result["shaderSupport"] = effective_plan.value("shaderSupport");
        result["plan"] = effective_plan;
        result.remove("metadata");
        result.remove("records");
        result.remove("remove");
        return result;
      },
      [this, generation, id, plan](const QVariantMap& result) {
        if (generation != content_install_generation_) return;
        content_installation_ = result;
        content_installation_["instance"] = id;
        content_installation_["requestedPlan"] = plan;
        emit content_installation_changed();
      });
}
void GameRuntime::refresh_environment() {
  run_file_work(
      [portable = portable_](const Cancellation& cancelled) {
        return environment_snapshot(portable, cancelled);
      },
      [this](const QVariantMap& result) {
        if (result.contains("error"))
          emit notice(result.value("error").toString());
        else
          environment_ = result;
        emit environment_changed();
      });
}
void GameRuntime::select_cache_root(const QString& url) {
  const auto destination = QDir(local_path(url)).absolutePath();
  if (destination == cache_root_) return;
  if (closing_ || initializing_ || busy() || launch_status_.value("state") == "preparing") {
    emit notice(QCoreApplication::translate("Bugg", "请等待当前任务结束"));
    return;
  }
  storage_migrating_ = true;
  run_file_work(
      [source = cache_root_, destination, portable = portable_](const Cancellation& cancelled) {
        const auto relative = QDir(portable).relativeFilePath(destination);
        const auto portable_path = QDir(portable).canonicalPath();
        const auto destination_path = QFileInfo(destination).canonicalFilePath();
#ifdef Q_OS_WIN
        constexpr auto path_comparison = Qt::CaseInsensitive;
#else
        constexpr auto path_comparison = Qt::CaseSensitive;
#endif
        if (relative.isEmpty() || relative == "." || relative.split('/').contains("..") ||
            portable_path.isEmpty() || destination_path.isEmpty() ||
            !destination_path.startsWith(portable_path + '/', path_comparison))
          throw std::runtime_error(
              QCoreApplication::translate("Bugg", "资源路径越界").toUtf8().constData());
        // 既不指向目录外，也不经符号链接绕到外部；定位文件始终保持可搬迁的相对路径。
        safe_path(portable, relative);
        if (!QDir(destination).exists() || !QDir(destination).isEmpty() ||
            destination.startsWith(source + '/', path_comparison))
          throw std::runtime_error(
              QCoreApplication::translate("StoragePage", "选择空目录存放配置与缓存")
                  .toUtf8()
                  .constData());
        QDirIterator files(source, QDir::Files | QDir::Hidden | QDir::NoSymLinks,
                           QDirIterator::Subdirectories);
        while (files.hasNext()) {
          check_cancelled(cancelled);
          const auto path = files.next();
          copy_file(path, safe_path(destination, QDir(source).relativeFilePath(path)), cancelled);
        }
        check_cancelled(cancelled);
        write_json(portable + "/bugg-portable.json",
                   {{"cache", QDir(portable).relativeFilePath(destination)}});
        return QVariantMap{};
      },
      [this, destination](const QVariantMap& result) {
        storage_migrating_ = false;
        if (result.contains("error"))
          emit notice(result.value("error").toString());
        else {
          cache_root_ = destination;
          save_settings();
          emit cache_root_changed();
        }
      });
}
}  // namespace bugg
