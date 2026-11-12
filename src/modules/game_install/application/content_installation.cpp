#include <QCoreApplication>
#include <QCryptographicHash>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>

#include "modules/game_install/application/game_operations.h"
#include "modules/game_install/application/modpack_plan.h"

namespace bugg {
namespace {
[[noreturn]] void invalid_content(const QString& error) {
  throw std::runtime_error(error.toStdString());
}
QString content_folder(const QString& kind) {
  return QMap<QString, QString>{{"mod", "mods"},
                                {"resourcepack", "resourcepacks"},
                                {"shader", "shaderpacks"},
                                {"modpack", "modpacks"}}
      .value(kind);
}
QVariantMap content_subset(const QVariantMap& plan, bool dependencies) {
  auto result = plan;
  QVariantList files;
  for (const auto& value : plan.value("files").toList())
    if (value.toMap().value("dependency").toBool() == dependencies) files.append(value);
  result["files"] = files;
  return result;
}
// One worker operation owns the directory/size index and digest memo. Names
// are hints only: a renamed archive must match all supplied content hashes.
class LocalContentIndex {
 public:
  LocalContentIndex(QString directory, Cancellation cancelled)
      : directory_(std::move(directory)), cancelled_(std::move(cancelled)) {}
  QString locate(const QJsonObject& record) {
    const auto relative = record["path"].toString();
    if (matches(relative, record)) return relative;
    const auto folder = QFileInfo(relative).path();
    if (!folders_.contains(folder)) {
      QMap<qint64, QStringList> sizes;
      const QDir directory(safe_path(directory_, folder));
      const auto entries = directory.entryInfoList(QDir::Files | QDir::NoSymLinks, QDir::Name);
      for (const auto& entry : entries) {
        check_cancelled(cancelled_);
        if (entry.suffix().compare("jar", Qt::CaseInsensitive) == 0 ||
            entry.suffix().compare("zip", Qt::CaseInsensitive) == 0)
          sizes[entry.size()].append(folder + '/' + entry.fileName());
      }
      folders_.insert(folder, sizes);
    }
    for (const auto& candidate : folders_.value(folder).value(record["fileSize"].toInteger()))
      if (candidate != relative && matches(candidate, record)) return candidate;
    return {};
  }

 private:
  bool matches(const QString& relative, const QJsonObject& record) {
    check_cancelled(cancelled_);
    const auto path = safe_path(directory_, relative);
    const QFileInfo file(path);
    if (!file.isFile() || file.isSymLink() || file.size() != record["fileSize"].toInteger())
      return false;
    const auto hashes = record["hashes"].toObject();
    if (hashes.isEmpty()) return false;
    QList<QByteArray> missing;
    auto& known = digests_[relative];
    for (auto it = hashes.begin(); it != hashes.end(); ++it)
      if (!known.contains(it.key().toLatin1())) missing.append(it.key().toLatin1());
    if (!missing.isEmpty()) {
      const auto computed = file_digests(path, missing, cancelled_);
      for (auto it = computed.begin(); it != computed.end(); ++it) known[it.key()] = it.value();
    }
    for (auto it = hashes.begin(); it != hashes.end(); ++it)
      if (known.value(it.key().toLatin1()) != it.value().toString().toLatin1().toLower())
        return false;
    return true;
  }
  QString directory_;
  Cancellation cancelled_;
  QHash<QString, QMap<qint64, QStringList>> folders_;
  QHash<QString, QMap<QByteArray, QByteArray>> digests_;
};
QList<GameResource> content_downloads(const QVariantMap& prepared) {
  QList<GameResource> downloads;
  for (const auto& value : prepared.value("records").toList()) {
    const auto record = value.toMap();
    downloads.append({QUrl(record.value("downloads").toList().value(0).toString()),
                      safe_path(prepared.value("staging").toString(),
                                "files/" + record.value("path").toString()),
                      record.value("hashes").toMap().value("sha1").toString().toLatin1(),
                      record.value("fileSize").toLongLong()});
  }
  return downloads;
}
}  // namespace
QJsonArray GameOperations::content_records(const QVariantMap& plan) {
  const auto files = plan.value("files").toList();
  if (files.isEmpty() || files.size() > 128)
    invalid_content(QCoreApplication::translate("Bugg", "内容安装计划无效"));
  QJsonArray records;
  QSet<QString> names;
  for (const auto& value : files) {
    const auto file = value.toMap();
    const auto kind = file.value("kind").toString();
    const auto folder = content_folder(kind);
    const auto name = file.value("filename").toString();
    const auto suffix = QFileInfo(name).suffix().toLower();
    if (folder.isEmpty() || name != QFileInfo(name).fileName() || name.isEmpty() ||
        (kind == "mod"       ? suffix != "jar"
         : kind == "modpack" ? !QStringList{"zip", "mrpack", "buggpack"}.contains(suffix)
                             : suffix != "zip"))
      invalid_content(QCoreApplication::translate("Bugg", "内容文件名称或类型无效"));
    QJsonObject record{{"path", folder + '/' + name},
                       {"fileSize", QJsonValue::fromVariant(file.value("size"))},
                       {"hashes", QJsonObject::fromVariantMap(file.value("hashes").toMap())},
                       {"downloads", QJsonArray{file.value("url").toString()}},
                       {"embedded", false},
                       {"publisher", file.value("publisher").toString()},
                       {"projectId", file.value("projectId").toString()},
                       {"versionId", file.value("versionId").toString()},
                       {"versionName", file.value("versionName").toString()},
                       {"title", file.value("title").toString()}};
    if (!file.value("dependencies").toList().isEmpty())
      record["publisherDependencies"] =
          QJsonArray::fromVariantList(file.value("dependencies").toList());
    validate_content_record(record, names);
    if (record["fileSize"].toDouble() <= 0)
      invalid_content(QCoreApplication::translate("Bugg", "内容文件大小无效"));
    records.append(record);
  }
  return records;
}
QVariantMap GameOperations::prepare_content_install(const QString& id, const QVariantMap& plan,
                                                    const ContentRequest& request) {
  const bool shader = plan.value("kind") == "shader";
  if (!shader && (plan.value("kind") != "mod" || plan.value("query").toMap().isEmpty()))
    return plan;
  auto support = plan.value("shaderSupport").toMap();
  if (shader && support.value("runtimes").toList().isEmpty())
    invalid_content(
        QCoreApplication::translate("Bugg", "缺少光影核心兼容信息，请重新选择光影版本"));
  const auto directory = safe_path(root_, "versions/" + id);
  const auto metadata = load_version(id);
  const auto descriptor = instance_descriptor(metadata);
  auto query = plan.value("query").toMap();
  query["gameVersion"] = descriptor.value("version");
  query["loader"] = descriptor.value("loader").toString().toLower();
  query["loaderVersion"] = descriptor.value("loaderVersion");
  auto result = plan;
  if ((shader && support.value("loader") != query.value("loader")) ||
      plan.value("query").toMap().value("loader").toString() != query.value("loader").toString() ||
      plan.value("query").toMap().value("loaderVersion").toString() !=
          query.value("loaderVersion").toString() ||
      plan.value("query").toMap().value("gameVersion") != query.value("gameVersion")) {
    if (!request)
      invalid_content(QCoreApplication::translate("Bugg", "目标游戏已变化，请重新匹配内容与依赖"));
    result = request(query, cancelled_);
    support = result.value("shaderSupport").toMap();
  }
  if (!shader) return result;
  for (const auto& library : metadata["libraries"].toArray())
    if (library.toObject()["name"].toString().startsWith("optifine:"))
      invalid_content(QCoreApplication::translate(
          "Bugg", "此游戏已有 OptiFine，不能叠加 Iris/Oculus。请使用其他目标游戏"));
  QSet<QString> markers;
  for (const auto& value : support.value("runtimes").toList())
    for (const auto& marker : value.toMap().value("markers").toStringList()) markers.insert(marker);
  QString found;
  QStringList disabled;
  for (const auto& file : QDir(safe_path(directory, "mods"))
                              .entryInfoList({"*.jar", "*.jar.disabled"},
                                             QDir::Files | QDir::NoSymLinks, QDir::Name)) {
    check_cancelled(cancelled_);
    QStringList entries;
    try {
      entries = archive_entries(file.absoluteFilePath(), cancelled_);
    } catch (const std::exception&) {
      check_cancelled(cancelled_);
      continue;
    }
    bool core = false;
    for (const auto& marker : markers) core |= entries.contains(marker);
    if (!core) continue;
    if (file.fileName().endsWith(".disabled", Qt::CaseInsensitive)) {
      disabled.append(file.fileName());
      continue;
    }
    if (!found.isEmpty())
      invalid_content(QCoreApplication::translate("Bugg", "检测到多个光影核心，请先禁用重复核心"));
    found = file.absoluteFilePath();
  }
  if (found.isEmpty()) {
    if (!disabled.isEmpty())
      invalid_content(QCoreApplication::translate("Bugg",
                                                  "光影核心已禁用：%"
                                                  "1。请先在游戏的模组管理中检查冲突并启用需要的核"
                                                  "心，再安装光影；不会自动替换或启用它。")
                          .arg(disabled.join(", ")));
    return result;
  }
  if (!request)
    invalid_content(QCoreApplication::translate("Bugg", "无法核验已有光影核心，请重试"));
  query["shaderRuntimeHash"] = QString::fromLatin1(file_digest(found, "sha1", cancelled_));
  for (const auto& value : metadata["buggcraftModpack"].toObject()["resources"].toArray()) {
    const auto record = value.toObject();
    if (record["publisher"] == "CurseForge" &&
        record["hashes"].toObject()["sha1"] == query.value("shaderRuntimeHash").toString() &&
        !record["projectId"].toString().isEmpty() && !record["versionId"].toString().isEmpty()) {
      query["shaderRuntimeCurseForgeProject"] = record["projectId"].toString();
      query["shaderRuntimeCurseForgeVersion"] = record["versionId"].toString();
      break;
    }
  }
  result = request(query, cancelled_);
  auto installed = result.value("shaderSupport").toMap();
  if (!installed.value("installed").toBool())
    invalid_content(
        QCoreApplication::translate("Bugg", "已有光影核心未通过兼容核验，请检查后重试"));
  installed["path"] = "mods/" + QFileInfo(found).fileName();
  result["shaderSupport"] = installed;
  return result;
}
QVariantMap GameOperations::check_content_install(const QString& id, const QVariantMap& plan) {
  const auto dependencies = content_subset(plan, true).value("files").toList();
  if (!dependencies.isEmpty()) {
    auto result = check_content_install(id, content_subset(plan, false));
    QStringList conflicts;
    for (const auto& value : dependencies) {
      auto dependency = plan;
      auto file = value.toMap();
      file["dependency"] = false;
      dependency["files"] = QVariantList{file};
      try {
        conflicts.append(check_content_install(id, dependency).value("conflicts").toStringList());
      } catch (const std::exception&) {
        check_cancelled(cancelled_);
        if (plan.value("kind") == "shader") throw;
      }
    }
    conflicts.removeDuplicates();
    result["dependencyConflicts"] = conflicts;
    return result;
  }
  const auto records = content_records(plan);
  const auto directory = safe_path(root_, "versions/" + id);
  LocalContentIndex local_content(directory, cancelled_);
  const auto metadata = load_version(id);
  const auto descriptor = instance_descriptor(metadata);
  for (const auto& value : plan.value("files").toList()) {
    check_cancelled(cancelled_);
    const auto file = value.toMap();
    if (!file.value("gameVersions")
             .toStringList()
             .contains(descriptor.value("version").toString()) ||
        file.value("kind") == "mod" && !file.value("loaders").toStringList().contains(
                                           descriptor.value("loader").toString().toLower()))
      invalid_content(QCoreApplication::translate("Bugg", "内容与所选游戏版本或加载器不兼容"));
  }
  const auto old_records = metadata["buggcraftModpack"].toObject()["resources"].toArray();
  for (const auto& value : plan.value("files").toList()) {
    const auto file = value.toMap();
    for (const auto& dependency_value : file.value("dependencies").toList()) {
      const auto dependency = dependency_value.toMap();
      if (dependency.value("type") != "incompatible") continue;
      for (const auto& old : old_records) {
        const auto record = old.toObject();
        if (record["publisher"].toString() == file.value("publisher").toString() &&
            record["projectId"].toString() == dependency.value("projectId").toString() &&
            !local_content.locate(record).isEmpty())
          invalid_content(QCoreApplication::translate("Bugg", "目标游戏中已有不兼容的内容：") +
                          record["path"].toString());
      }
    }
  }
  QStringList conflicts, remove;
  QVariantList installed;
  QJsonArray resolved_records;
  for (const auto& value : records) {
    auto record = value.toObject();
    const auto original = record["path"].toString();
    const auto found = local_content.locate(record);
    // A different file at the requested destination still requires consent.
    if (!found.isEmpty() &&
        (found == original || !QFileInfo::exists(safe_path(directory, original))))
      record["path"] = found;
    resolved_records.append(record);
    const auto relative = record["path"].toString();
    const auto path = safe_path(directory, relative);
    const bool exists = QFileInfo::exists(path);
    const bool matches = exists && relative == found;
    if (exists) {
      installed.append(QVariantMap{
          {"path", relative},
          {"versionName", matches ? record["versionName"].toString() : QFileInfo(path).fileName()},
          {"versionId", matches ? record["versionId"].toString() : ""},
          {"matchesSelected", matches}});
      if (!matches) conflicts.append(relative);
    }
    if (QFileInfo::exists(path + ".disabled")) {
      conflicts.append(relative + ".disabled");
      remove.append(relative + ".disabled");
    }
    for (const auto& old : old_records) {
      auto previous = old.toObject();
      if (record["projectId"].toString().isEmpty() ||
          previous["publisher"] != record["publisher"] ||
          previous["projectId"] != record["projectId"])
        continue;
      const auto old_path = previous["path"].toString();
      if (!QFileInfo::exists(safe_path(directory, old_path))) {
        const auto renamed = local_content.locate(previous);
        if (!renamed.isEmpty()) previous["path"] = renamed;
      }
      if (previous["publisher"] == record["publisher"] &&
          previous["projectId"] == record["projectId"] &&
          !record["projectId"].toString().isEmpty() &&
          QFileInfo::exists(safe_path(directory, previous["path"].toString()))) {
        QVariantMap local{{"path", previous["path"].toString()},
                          {"versionName", previous["versionName"].toString().isEmpty()
                                              ? QFileInfo(previous["path"].toString()).fileName()
                                              : previous["versionName"].toString()},
                          {"versionId", previous["versionId"].toString()},
                          {"matchesSelected", matches && previous["path"] == record["path"]}};
        if (previous["path"] != record["path"])
          installed.append(local);
        else if (exists && !matches)
          installed.last() = local;
      }
      if (previous["publisher"] == record["publisher"] &&
          previous["projectId"] == record["projectId"] && previous["path"] != record["path"] &&
          !record["projectId"].toString().isEmpty()) {
        const auto old_path = previous["path"].toString();
        if (QFileInfo::exists(safe_path(directory, old_path))) {
          conflicts.append(old_path);
          remove.append(old_path);
        }
      }
    }
  }
  conflicts.removeDuplicates();
  remove.removeDuplicates();
  return {{"conflicts", conflicts},
          {"installed", installed},
          {"remove", remove},
          {"records", resolved_records.toVariantList()},
          {"metadata", metadata.toVariantMap()}};
}
QVariantMap GameOperations::install_with_content(const QVariantMap& specification,
                                                 const ContentRequest& request) {
  const auto existing = specification.value("id").toString();
  if (!existing.isEmpty()) {
    if (specification.value("plan").toMap().value("kind") != "shader")
      invalid_content(QCoreApplication::translate("Bugg", "当前游戏补装仅用于光影支持"));
    auto installation = specification;
    installation["name"] = existing;
    installation["updateExisting"] = true;
    install(installation);
    auto result = install_content(specification, request);
    result["instance"] = existing;
    return result;
  }
  const auto name = specification.value("name").toString();
  const auto destination = safe_path(root_, "versions/" + name);
  if (name.isEmpty() || name.contains('/') || name.contains('\\') || QFileInfo::exists(destination))
    invalid_content(QCoreApplication::translate("Bugg", "实例名称无效或已存在"));
  const auto fingerprint =
      QCryptographicHash::hash(
          QJsonDocument::fromVariant(specification).toJson(QJsonDocument::Compact),
          QCryptographicHash::Sha256)
          .toHex()
          .left(20);
  const auto staging_id = ".content-game-" + QString::fromLatin1(fingerprint);
  const auto staging = safe_path(root_, "versions/" + staging_id);
  auto installation = specification;
  installation["name"] = staging_id;
  if (!QFileInfo::exists(safe_path(staging, staging_id + ".json"))) install(installation);
  auto content_specification = specification;
  content_specification["id"] = staging_id;
  auto result = install_content(content_specification, request);
  const auto metadata = load_version(staging_id);
  result["instance"] = commit_content(
      staging_id, name, metadata, metadata["buggcraftModpack"].toObject()["resources"].toArray(),
      "Online content");
  return result;
}
QVariantMap GameOperations::install_content(const QVariantMap& specification,
                                            const ContentRequest& request) {
  set_dependency_context(specification, request);
  auto complete = specification;
  complete["plan"] = prepare_content_install(specification.value("id").toString(),
                                             specification.value("plan").toMap(), request);
  const auto plan = complete.value("plan").toMap();
  for (const auto& file : plan.value("files").toList()) content_update(file.toMap(), "queued");
  if (!plan.value("missingDependencies").toList().isEmpty())
    invalid_content(QCoreApplication::translate("Bugg", "必要依赖的发布信息尚未取得，请重试"));
  install_content_files(complete);
  return {{"instance", specification.value("id")}};
}
QVariantMap GameOperations::prepare_content_files(const QVariantMap& specification) {
  const auto plan = specification.value("plan").toMap();
  const auto id = specification.value("id").toString();
  for (const auto& value : plan.value("files").toList()) {
    auto file = value.toMap();
    file["dependency"] = specification.value("dependency", file.value("dependency"));
    content_update(file, "checking", -1, QCoreApplication::translate("Bugg", "检查本地文件"));
  }
  auto transaction_plan = plan;
  auto transaction_files = plan.value("files").toList();
  for (auto& value : transaction_files) {
    auto file = value.toMap();
    file["dependency"] = false;
    value = file;
  }
  transaction_plan["files"] = transaction_files;
  const auto prepared = check_content_install(id, transaction_plan);
  const auto records = QJsonArray::fromVariantList(prepared.value("records").toList());
  if (!prepared.value("conflicts").toStringList().isEmpty() &&
      !specification.value("replace").toBool())
    invalid_content(QCoreApplication::translate("Bugg", "存在不同版本文件，请确认替换后重试"));
  const auto directory = safe_path(root_, "versions/" + id);
  const auto fingerprint =
      QCryptographicHash::hash(QJsonDocument(records).toJson(QJsonDocument::Compact),
                               QCryptographicHash::Sha256)
          .toHex()
          .left(24);
  const auto staging = safe_path(directory, ".content-" + QString::fromLatin1(fingerprint));
  QSet<QString> reused;
  for (const auto& value : prepared.value("installed").toList()) {
    const auto item = value.toMap();
    if (item.value("matchesSelected").toBool()) reused.insert(item.value("path").toString());
  }
  int index = 0;
  for (const auto& value : records) {
    const auto record = value.toObject();
    const auto relative = record["path"].toString();
    const auto target = safe_path(staging, "files/" + relative);
    const auto existing = safe_path(directory, relative);
    const bool local = reused.contains(relative);
    if (local) {
      if (!QFileInfo::exists(target)) copy_file(existing, target, cancelled_);
    }
    auto file = plan.value("files").toList().value(index++).toMap();
    file["dependency"] = specification.value("dependency", file.value("dependency"));
    content_transfers_[target] = file;
    content_update(file, local ? "checking" : "downloading", -1,
                   local ? QCoreApplication::translate("Bugg", "本地已有，校验通过")
                         : QCoreApplication::translate("Bugg", "下载并校验"));
  }
  auto result = prepared;
  result["directory"] = directory;
  result["staging"] = staging;
  result["reused"] = QStringList(reused.begin(), reused.end());
  return result;
}
void GameOperations::install_content_files(const QVariantMap& specification,
                                           const QVariantMap& preparation) {
  const auto plan = specification.value("plan").toMap();
  auto records = content_records(plan);
  if (specification.value("kind") == "onlinePack") {
    if (records.size() != 1 || plan.value("kind") != "modpack")
      invalid_content(QCoreApplication::translate("Bugg", "整合包安装计划无效"));
    const auto record = records.first().toObject();
    const auto file = plan.value("files").toList().first().toMap();
    const auto archive = safe_path(portable_cache_root(portable_),
                                   "content/" + record["hashes"].toObject()["sha1"].toString() +
                                       '/' + QFileInfo(record["path"].toString()).fileName());
    content_update(file, "downloading", -1, QCoreApplication::translate("Bugg", "下载整合包"));
    content_transfers_[archive] = file;
    resources_.fetch({{QUrl(record["downloads"].toArray().first().toString()), archive,
                       record["hashes"].toObject()["sha1"].toString().toLatin1(),
                       record["fileSize"].toInteger()}});
    content_transfers_.remove(archive);
    verify_content_file(archive, record, cancelled_);
    content_update(file, "installing", -1, QCoreApplication::translate("Bugg", "安装整合包"));
    import_pack(archive, specification.value("instanceName").toString());
    content_update(file, "done", 1, QCoreApplication::translate("Bugg", "安装完成"));
    return;
  }
  const auto prepared = preparation.isEmpty() ? prepare_content_files(specification) : preparation;
  records = QJsonArray::fromVariantList(prepared.value("records").toList());
  const auto id = specification.value("id").toString();
  const auto directory = prepared.value("directory").toString();
  const auto staging = prepared.value("staging").toString();
  const auto reused_list = prepared.value("reused").toStringList();
  const QSet<QString> reused(reused_list.begin(), reused_list.end());
  if (preparation.isEmpty()) resources_.fetch(content_downloads(prepared));
  for (const auto& value : records)
    content_transfers_.remove(safe_path(staging, "files/" + value.toObject()["path"].toString()));
  for (const auto& value : records)
    verify_content_file(safe_path(staging, "files/" + value.toObject()["path"].toString()),
                        value.toObject(), cancelled_);
  for (const auto& value : plan.value("files").toList()) {
    auto file = value.toMap();
    file["dependency"] = specification.value("dependency", file.value("dependency"));
    content_update(file, "installing", 1, QCoreApplication::translate("Bugg", "提交已校验文件"));
  }
  auto metadata = load_version(id);
  auto remove = prepared.value("remove").toStringList();
  const auto dependency_receipt = check_dependencies(directory, safe_path(staging, "files"), remove,
                                                     records, metadata, "requested_content");
  if (!dependency_receipt.isEmpty()) metadata["buggDependencyDecision"] = dependency_receipt;
  auto info = metadata["buggcraftModpack"].toObject();
  QJsonArray merged;

  QSet<QString> replaced;
  for (const auto& value : records) replaced.insert(value.toObject()["path"].toString());
  for (const auto& old : info["resources"].toArray()) {
    const auto previous = old.toObject();
    bool same_project = false;
    for (const auto& value : records) {
      const auto record = value.toObject();
      same_project |= !record["projectId"].toString().isEmpty() &&
                      previous["publisher"] == record["publisher"] &&
                      previous["projectId"] == record["projectId"];
    }
    if (!same_project && !replaced.contains(previous["path"].toString()) &&
        !remove.contains(previous["path"].toString()))
      merged.append(old);
  }
  for (const auto& value : records) merged.append(value);
  info["resources"] = merged;
  metadata["buggcraftModpack"] = info;
  QStringList published;
  QMap<QString, QString> backups;
  try {
    QStringList targets = remove;
    for (const auto& value : records) targets.append(value.toObject()["path"].toString());
    targets.removeDuplicates();
    for (const auto& relative : targets) {
      check_cancelled(cancelled_);
      const auto path = safe_path(directory, relative);
      if (!QFileInfo::exists(path)) continue;
      const auto backup = safe_path(staging, "backup/" + relative);
      QDir().mkpath(QFileInfo(backup).absolutePath());
      if (!QFile::rename(path, backup))
        invalid_content(QCoreApplication::translate("Bugg", "无法替换正在使用的内容文件"));
      backups[path] = backup;
    }
    for (const auto& value : records) {
      check_cancelled(cancelled_);
      const auto relative = value.toObject()["path"].toString();
      const auto target = safe_path(directory, relative);
      copy_file(safe_path(staging, "files/" + relative), target, cancelled_);
      published.append(target);
    }
    check_cancelled(cancelled_);
    write_json(safe_path(directory, id + ".json"), metadata);
  } catch (...) {
    for (const auto& path : published) QFile::remove(path);
    for (auto it = backups.begin(); it != backups.end(); ++it) QFile::rename(it.value(), it.key());
    throw;
  }
  for (const auto& path : backups) QFile::remove(path);
  QDir(staging).removeRecursively();
  int index = 0;
  for (const auto& value : records) {
    auto file = plan.value("files").toList().value(index++).toMap();
    file["dependency"] = specification.value("dependency", file.value("dependency"));
    const bool local = reused.contains(value.toObject()["path"].toString());
    content_update(file, local ? "installed" : "done", 1,
                   local ? QCoreApplication::translate("Bugg", "已安装 · 已校验，未重复下载")
                         : QCoreApplication::translate("Bugg", "安装完成"));
  }
  content_item_.clear();
  report(1, QCoreApplication::translate("Bugg", "内容安装完成"));
}
}  // namespace bugg
