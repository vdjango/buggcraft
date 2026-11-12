#include <QCoreApplication>
#include <QCryptographicHash>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QRegularExpression>
#include <algorithm>

#include "bugg/dependency_check.h"
#include "contracts/dependency_decision.h"
#include "modules/game_install/application/game_operations.h"
#include "modules/game_install/application/modpack_plan.h"
#include "modules/game_install/infrastructure/dependency_facts.h"

namespace bugg {
namespace {
QJsonObject evaluate(const QJsonObject& input, bool solve = false) {
  const auto raw = QJsonDocument(input).toJson(QJsonDocument::Compact).toStdString();
  return QJsonDocument::fromJson(QByteArray::fromStdString(solve ? dependency::solve_json(raw)
                                                                 : dependency::check_json(raw)))
      .object();
}
QString combination_fingerprint(const QJsonObject& input, const QJsonObject& checked) {
  QJsonArray files;
  for (const auto& value : input["artifacts"].toArray()) {
    const auto artifact = value.toObject();
    files.append(QJsonObject{{"path", artifact["path"]},
                             {"sha256", artifact["sha256"]},
                             {"parser_version", artifact["facts"].toObject()["parser_version"]}});
  }
  const QJsonObject identity{{"environment", input["environment"]},
                             {"files", files},
                             {"issues", checked["issues"]},
                             {"checker", "bugg-dependency-core-v1"}};
  return QString::fromLatin1(
      QCryptographicHash::hash(QJsonDocument(identity).toJson(QJsonDocument::Compact),
                               QCryptographicHash::Sha256)
          .toHex());
}
QJsonArray artifact_lock(const QJsonArray& artifacts) {
  QJsonArray result;
  for (const auto& value : artifacts) {
    const auto artifact = value.toObject();
    result.append(QJsonObject{{"path", artifact["path"]},
                              {"sha256", artifact["sha256"]},
                              {"parser_version", artifact["facts"].toObject()["parser_version"]}});
  }
  return result;
}
QString issue_text(const QJsonObject& issue) {
  const QMap<QString, QString> labels{
      {"missing_dependency", QCoreApplication::translate("Bugg", "缺少依赖")},
      {"version_constraint", QCoreApplication::translate("Bugg", "版本要求不满足")},
      {"incompatible_dependency", QCoreApplication::translate("Bugg", "模组声明不兼容")},
      {"duplicate_provider", QCoreApplication::translate("Bugg", "重复模组")},
      {"known_runtime_failure", QCoreApplication::translate("Bugg", "已知运行问题")},
      {"incomplete_metadata", QCoreApplication::translate("Bugg", "元数据未完整解析")},
      {"no_active_loader_metadata", QCoreApplication::translate("Bugg", "未识别当前加载器的声明")},
      {"unknown_version_expression", QCoreApplication::translate("Bugg", "版本表达式尚不能核验")},
      {"load_order_cycle", QCoreApplication::translate("Bugg", "加载顺序存在循环")}};
  const auto range =
      issue["required"].isString() ? issue["required"].toString()
      : issue["required"].isArray()
          ? QString::fromUtf8(
                QJsonDocument(issue["required"].toArray()).toJson(QJsonDocument::Compact))
          : QString{};
  return QStringList{labels.value(issue["code"].toString(), issue["code"].toString()),
                     issue["mod_id"].toString(), issue["target_id"].toString(), range,
                     issue["reason"].toString()}
      .filter(QRegularExpression(".+"))
      .join(" · ");
}
}  // namespace
void GameOperations::set_dependency_context(QVariantMap specification, ContentRequest request) {
  dependency_context_ = std::move(specification);
  dependency_request_ = std::move(request);
}
QJsonObject GameOperations::check_dependencies(const QString& directory, const QString& overlay,
                                               QStringList& remove, QJsonArray& records,
                                               const QJsonObject& metadata, const QString& intent) {
  QMap<QString, QString> paths;
  const auto scan = [&](const QString& root, bool original) {
    const QDir mods(safe_path(root, "mods"));
    for (const auto& file :
         mods.entryInfoList({"*.jar"}, QDir::Files | QDir::NoSymLinks, QDir::Name)) {
      check_cancelled(cancelled_);
      const auto relative = "mods/" + file.fileName();
      if (!original || !remove.contains(relative)) paths[relative] = file.absoluteFilePath();
      if (paths.size() > 4096) throw std::runtime_error("dependency_artifact_budget");
    }
  };
  if (directory != overlay) scan(directory, true);
  scan(overlay, false);
  if (paths.isEmpty()) return {};
  report(-1, QCoreApplication::translate("Bugg", "核对模组的实际依赖与版本要求"), true);
  DependencyFacts facts(portable_cache_root(portable_), resources_, facts_base_, cancelled_);
  const auto descriptor = instance_descriptor(metadata);
  QJsonObject environment{{"minecraft", descriptor.value("version").toString()},
                          {"loader", descriptor.value("loader").toString().toLower()},
                          {"loader_version", descriptor.value("loaderVersion").toString()}};
  const auto java = metadata["javaVersion"].toObject()["majorVersion"].toInt();
  if (java > 0) environment["java"] = QString::number(java);
  QJsonObject input{{"environment", environment}, {"artifacts", facts.collect(paths)}};
  auto checked = evaluate(input);
  const auto fingerprint = combination_fingerprint(input, checked);
  QJsonObject receipt{{"schema", "bugg-dependency-decision-v1"},
                      {"fingerprint", fingerprint},
                      {"intent", intent},
                      {"environment", environment},
                      {"check", checked},
                      {"artifacts", artifact_lock(input["artifacts"].toArray())}};
  if (checked["issues"].toArray().isEmpty()) {
    receipt["choice"] = "satisfied_declared";
    return receipt;
  }
  QStringList messages;
  for (const auto& issue : checked["issues"].toArray())
    messages.append(issue_text(issue.toObject()));
  auto decision =
      QVariantMap{{"fingerprint", fingerprint},
                  {"intent", intent},
                  {"issues", checked["issues"].toArray().toVariantList()},
                  {"summary", messages.mid(0, 20).join('\n')},
                  {"canRepair", intent != "room_manifest" && bool(dependency_request_)}};
  const bool confirmed =
      dependency_context_.value("dependencyFingerprint").toString() == fingerprint;
  const auto stored = metadata["buggDependencyDecision"].toObject();
  const auto choice = confirmed ? dependency_context_.value("dependencyChoice").toString()
                      : stored["fingerprint"] == fingerprint ? stored["choice"].toString()
                                                             : QString{};
  if (choice == "keep") {
    receipt["choice"] = "keep";
    return receipt;
  }
  const auto issues = checked["issues"].toArray();
  const bool automatic = choice.isEmpty() && intent == "requested_content" &&
                         std::all_of(issues.begin(), issues.end(), [](const QJsonValue& value) {
                           return value.toObject()["code"] == "missing_dependency";
                         });
  if ((choice != "repair" && !automatic) || !decision.value("canRepair").toBool())
    throw DependencyDecision(decision);
  report(-1, QCoreApplication::translate("Bugg", "查找满足整组依赖的候选文件"), true);
  QMap<QString, QJsonObject> known;
  for (const auto& value : metadata["buggcraftModpack"].toObject()["resources"].toArray()) {
    auto record = value.toObject();
    known[record["path"].toString()] = record;
  }
  for (const auto& value : records) {
    auto record = value.toObject();
    known[record["path"].toString()] = record;
  }
  QSet<QString> affected;
  for (const auto& value : checked["issues"].toArray()) {
    const auto issue = value.toObject();
    affected.insert(issue["artifact"].toString());
    affected.insert(issue["provider_artifact"].toString());
  }
  QJsonArray candidates;
  QMap<QString, QJsonObject> candidate_records;
  QMap<QString, QString> candidate_paths;
  qint64 candidate_bytes = 0;
  QString repair_error;
  struct Search {
    QString publisher, project, pinned, replaces;
    int depth;
  };
  QList<Search> searches;
  QMap<QString, QString> project_artifacts;
  for (const auto& value : input["artifacts"].toArray()) {
    const auto artifact = value.toObject();
    const auto record = known.value(artifact["path"].toString());
    const auto publisher = record["publisher"].toString();
    const auto project = record["projectId"].toString();
    const auto digest = artifact["sha256"].toString();
    if (!project.isEmpty()) project_artifacts[publisher + "/" + project] = digest;
    if (affected.contains(digest) && !publisher.isEmpty() && !project.isEmpty())
      searches.append({publisher, project, {}, digest, 0});
  }
  const auto discover = [&](const QJsonObject& record, int depth) {
    if (depth >= 8) return;
    for (const auto& value : record["publisherDependencies"].toArray()) {
      const auto dep = value.toObject();
      if (dep["type"] != "required") continue;
      const auto publisher = dep["publisher"].toString(record["publisher"].toString());
      const auto project = dep["projectId"].toString();
      const auto pinned = dep["versionId"].toString();
      if (project.isEmpty() && pinned.isEmpty()) continue;
      const auto replaces = project_artifacts.value(publisher + "/" + project);
      searches.append({publisher, project, pinned, replaces, depth + 1});
    }
  };
  for (const auto& record : known) discover(record, 0);
  QStringList targets;
  for (const auto& value : issues) {
    const auto issue = value.toObject();
    if (issue["code"] == "missing_dependency" && !issue["target_id"].toString().isEmpty())
      targets.append(issue["target_id"].toString());
  }
  targets.removeDuplicates();
  if (!targets.isEmpty()) {
    try {
      const auto bindings =
          dependency_request_({{"operation", "bindings"},
                               {"targets", targets.mid(0, 32)},
                               {"gameVersion", environment["minecraft"].toString()},
                               {"loader", environment["loader"].toString()}},
                              cancelled_)
              .value("items")
              .toList();
      for (const auto& value : bindings) {
        const auto binding = value.toMap();
        const auto provider = binding.value("provider").toString();
        if (!targets.contains(binding.value("mod_id").toString()) ||
            !QStringList{"modrinth", "curseforge"}.contains(provider) ||
            binding.value("sha256").toString().size() != 64)
          continue;
        searches.append({provider == "modrinth" ? QString("Modrinth") : QString("CurseForge"),
                         binding.value("project_id").toString(),
                         {},
                         {},
                         0});
      }
    } catch (const std::exception& error) {
      check_cancelled(cancelled_);
      repair_error = QString::fromUtf8(error.what());
    }
  }
  QSet<QString> searched, downloaded;
  QElapsedTimer deadline;
  deadline.start();
  while (!searches.isEmpty() && candidates.size() < 64 && searched.size() < 64 &&
         deadline.elapsed() < 120000) {
    const auto search = searches.takeFirst();
    const auto search_key = search.publisher + "/" + search.project + "/" + search.pinned;
    if (searched.contains(search_key)) continue;
    searched.insert(search_key);
    QVariantMap query{{"operation", "versions"},
                      {"kind", "mod"},
                      {"publisher", search.publisher},
                      {"projectId", search.project},
                      {"gameVersion", environment["minecraft"].toString()},
                      {"loader", environment["loader"].toString()},
                      {"loaderVersion", environment["loader_version"].toString()}};
    QVariantList versions;
    try {
      if (!search.pinned.isEmpty()) versions.append(QVariantMap{{"id", search.pinned}});
      if (!search.project.isEmpty()) {
        const auto listed = dependency_request_(query, cancelled_).value("versions").toList();
        for (const auto& version : listed.mid(0, 8))
          if (version.toMap().value("id").toString() != search.pinned) versions.append(version);
      }
    } catch (const std::exception& error) {
      check_cancelled(cancelled_);
      repair_error = QString::fromUtf8(error.what());
    }
    for (const auto& version : versions) {
      check_cancelled(cancelled_);
      if (candidates.size() >= 64 || deadline.elapsed() >= 120000) break;
      try {
        auto candidate_query = query;
        candidate_query["operation"] = "artifact";
        candidate_query["versionId"] = version.toMap().value("id");
        const auto plan = dependency_request_(candidate_query, cancelled_);
        const auto options = content_records(plan);
        if (options.size() != 1) continue;
        auto selected = options.first().toObject();
        // A candidate must belong to the project and release we requested;
        // otherwise its replacement target could be attached to another mod.
        if (selected["publisher"].toString() != search.publisher ||
            (!search.project.isEmpty() && selected["projectId"].toString() != search.project) ||
            selected["versionId"].toString() != version.toMap().value("id").toString())
          continue;
        const auto key = QString::fromLatin1(
            QCryptographicHash::hash(QJsonDocument(selected).toJson(QJsonDocument::Compact),
                                     QCryptographicHash::Sha256)
                .toHex());
        if (downloaded.contains(key)) continue;
        downloaded.insert(key);
        const auto size = selected["fileSize"].toInteger();
        if (size <= 0 || candidate_bytes + size > 128 * 1024 * 1024) continue;
        candidate_bytes += size;
        const auto path = safe_path(overlay, ".dependency-candidates/" + key + ".jar");
        resources_.fetch({{QUrl(selected["downloads"].toArray().first().toString()), path,
                           selected["hashes"].toObject()["sha1"].toString().toLatin1(), size}});
        verify_content_file(path, selected, cancelled_);
        const auto parsed = facts.collect({{selected["path"].toString(), path}});
        auto candidate = parsed.first().toObject();
        const auto digest = candidate["sha256"].toString();
        if (!search.replaces.isEmpty()) candidate["replaces"] = search.replaces;
        candidate["releaseType"] = version.toMap().value("channel").toString();
        if (!candidate_records.contains(digest)) candidates.append(candidate);
        candidate_records[digest] = selected;
        candidate_paths[digest] = path;
        discover(selected, search.depth);
      } catch (const std::exception& error) {
        check_cancelled(cancelled_);
        repair_error = QString::fromUtf8(error.what());
      }
    }
  }
  input["candidates"] = candidates;
  input["allow_locked_changes"] = !automatic;
  if (automatic) {
    QJsonArray additions;
    for (const auto& value : candidates)
      if (value.toObject()["replaces"].toString().isEmpty()) additions.append(value);
    input["candidates"] = additions;
  }
  const auto solution = evaluate(input, true);
  if (solution["state"] != "resolved_declared") {
    decision["repairError"] =
        QCoreApplication::translate(
            "Bugg", "暂未找到可完整核验的组合。已保留原文件，可继续保留原版本或取消。") +
        repair_error.left(200);
    throw DependencyDecision(decision);
  }
  QJsonArray changed;
  for (const auto& value : solution["artifacts"].toArray()) {
    const auto artifact = value.toObject();
    const auto digest = artifact["sha256"].toString();
    if (!candidate_records.contains(digest)) continue;
    const auto replacement = candidate_records[digest];
    const auto old_digest = artifact["replaces"].toString();
    for (const auto& original : input["artifacts"].toArray()) {
      const auto old = original.toObject();
      if (old["sha256"] != old_digest) continue;
      const auto old_path = old["path"].toString();
      remove.append(old_path);
      for (int index = int(records.size()) - 1; index >= 0; --index)
        if (records[index].toObject()["path"] == old_path) records.removeAt(index);
      if (directory == overlay && QFileInfo::exists(safe_path(overlay, old_path)))
        QFile::remove(safe_path(overlay, old_path));  // hidden pack staging only
      changed.append(QJsonObject{{"from", old_digest},
                                 {"to", digest},
                                 {"path", replacement["path"]},
                                 {"releaseType", artifact["releaseType"]}});
    }
    const auto target = safe_path(overlay, replacement["path"].toString());
    if (QFileInfo::exists(target)) QFile::remove(target);
    copy_file(candidate_paths[digest], target, cancelled_);
    records.append(replacement);
  }
  remove.removeDuplicates();
  auto final_input = input;
  final_input["artifacts"] = solution["artifacts"];
  receipt["choice"] = "repair";
  receipt["changes"] = changed;
  receipt["check"] = evaluate(final_input);
  receipt["artifacts"] = artifact_lock(solution["artifacts"].toArray());
  return receipt;
}
}  // namespace bugg
