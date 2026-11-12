#include "modules/game_install/infrastructure/dependency_facts.h"

#include <QCryptographicHash>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QTemporaryDir>

#include "bugg/dependency_check.h"

namespace bugg {
namespace {
constexpr auto kNativeParser = "native-1.1.0";
QJsonObject parsed_json(const std::string& value) {
  const auto result = QJsonDocument::fromJson(QByteArray::fromStdString(value));
  if (!result.isObject()) throw std::runtime_error("invalid_dependency_response");
  return result.object();
}
bool valid_facts(const QJsonObject& facts, const QString& digest, qint64 size) {
  return facts["artifact_sha256"] == digest && facts["size"].toInteger(-1) == size &&
         QStringList{"1.1.0", kNativeParser}.contains(facts["parser_version"].toString()) &&
         QStringList{"complete_declared", "partial", "unsupported"}.contains(
             facts["status"].toString()) &&
         facts["mods"].isArray();
}
}  // namespace
DependencyFacts::DependencyFacts(QString cache, ResourceClient& resources, QUrl source,
                                 Cancellation cancelled)
    : cache_(std::move(cache)),
      resources_(resources),
      source_(std::move(source)),
      cancelled_(std::move(cancelled)) {}
QJsonObject DependencyFacts::parse(const QString& path, const QString& digest, qint64 size) {
  QJsonArray mods, issues, evidence;
  QTemporaryDir temporary;
  if (!temporary.isValid()) throw std::runtime_error("dependency_temporary_directory");
  struct Container {
    QString path, name;
    int depth;
  };
  QList<Container> pending{{path, "root", 0}};
  qint64 consumed = 0;
  int count = 0;
  bool partial = false;
  while (!pending.isEmpty()) {
    check_cancelled(cancelled_);
    const auto container = pending.takeFirst();
    if (++count > 129 || container.depth > 4) throw std::runtime_error("dependency_nested_budget");
    const auto entries = archive_entries(container.path, cancelled_);
    QJsonObject members;
    for (const auto* name : {"fabric.mod.json", "META-INF/mods.toml", "META-INF/neoforge.mods.toml",
                             "META-INF/MANIFEST.MF", "META-INF/jarjar/metadata.json",
                             "quilt.mod.json", "mcmod.info"}) {
      if (!entries.contains(name)) continue;
      const auto bytes = archive_read(container.path, name, 1024 * 1024, cancelled_);
      consumed += bytes.size();
      if (consumed > 128 * 1024 * 1024) throw std::runtime_error("dependency_metadata_budget");
      members[name] = QString::fromUtf8(bytes);
      evidence.append(QJsonObject{
          {"container_path", container.name},
          {"member_path", name},
          {"sha256", QString::fromLatin1(
                         QCryptographicHash::hash(bytes, QCryptographicHash::Sha256).toHex())},
          {"size", bytes.size()}});
    }
    const auto input =
        QJsonDocument(QJsonObject{{"container_path", container.name}, {"members", members}})
            .toJson(QJsonDocument::Compact);
    const auto result = parsed_json(dependency::metadata_json(input.toStdString()));
    for (const auto& mod : result["mods"].toArray()) mods.append(mod);
    for (const auto& issue : result["issues"].toArray()) {
      issues.append(issue);
      partial |= issue.toObject()["code"] == "unsupported_metadata_format";
    }
    if (container.depth == 0 && result["mods"].toArray().isEmpty()) partial = true;
    QSet<QString> seen_nested;
    for (const auto& nested : result["nested"].toArray()) {
      const auto name = nested.toString();
      if (seen_nested.contains(name)) continue;
      seen_nested.insert(name);
      if (container.depth >= 4 || pending.size() + count >= 129)
        throw std::runtime_error("dependency_nested_budget");
      safe_path(temporary.path(), name);
      if (!entries.contains(name)) throw std::runtime_error("dependency_nested_missing");
      const auto bytes =
          archive_read(container.path, name,
                       qMin<qint64>(32 * 1024 * 1024, 128 * 1024 * 1024 - consumed), cancelled_);
      consumed += bytes.size();
      const auto target =
          safe_path(temporary.path(), QString::number(pending.size() + count) + ".jar");
      QFile file(target);
      if (!file.open(QIODevice::WriteOnly) || file.write(bytes) != bytes.size())
        throw std::runtime_error("dependency_nested_write");
      file.close();
      pending.append({target, container.name + "!/" + name, container.depth + 1});
    }
  }
  return {{"artifact_sha256", digest},
          {"size", size},
          {"parser_version", kNativeParser},
          {"status", mods.isEmpty() ? "unsupported"
                     : partial      ? "partial"
                                    : "complete_declared"},
          {"mods", mods},
          {"issues", issues},
          {"evidence", evidence}};
}
QJsonArray DependencyFacts::collect(const QMap<QString, QString>& files) {
  if (files.size() > 4096) throw std::runtime_error("dependency_artifact_budget");
  QMap<QString, QJsonObject> facts;
  QMap<QString, QString> paths, hashes;
  QMap<QString, qint64> sizes;
  for (auto it = files.begin(); it != files.end(); ++it) {
    check_cancelled(cancelled_);
    const QFileInfo info(it.value());
    if (!info.isFile() || info.isSymLink() || info.size() > 256 * 1024 * 1024)
      throw std::runtime_error("dependency_invalid_artifact");
    const auto digest = QString::fromLatin1(file_digest(it.value(), "sha256", cancelled_));
    hashes[it.key()] = digest;
    paths[digest] = it.value();
    sizes[digest] = info.size();
    const auto cached = safe_path(cache_, "dependency-facts/v1/" + digest + ".json");
    if (QFileInfo::exists(cached)) {
      try {
        auto value = read_json(cached);
        if (valid_facts(value, digest, info.size())) facts[digest] = value;
      } catch (const std::exception&) {
        check_cancelled(cancelled_);
      }
    }
  }
  QStringList missing;
  for (auto it = paths.begin(); it != paths.end(); ++it)
    if (!facts.contains(it.key())) missing.append(it.key());
  source_available_ &= source_.isValid() && !source_.isEmpty();
  for (int offset = 0; offset < missing.size() && source_available_; offset += 100) {
    QJsonArray batch;
    for (const auto& digest : missing.mid(offset, 100)) batch.append(digest);
    try {
      const auto response = resources_.json(
          source_.resolved(QUrl("/api/v1/dependency-facts/query")), {{"sha256", batch}});
      if (response["schema"] != "bugg-dependency-facts-v1") {
        source_available_ = false;
        break;
      }
      for (const auto& item : response["items"].toArray()) {
        const auto row = item.toObject();
        const auto digest = row["sha256"].toString();
        const auto value = row["facts"].toObject();
        if (missing.mid(offset, 100).contains(digest) &&
            valid_facts(value, digest, sizes[digest]) && value["status"] == "complete_declared")
          facts[digest] = value;
      }
    } catch (const std::exception&) {
      check_cancelled(cancelled_);
      source_available_ = false;
    }
  }
  QJsonArray result;
  for (auto it = paths.begin(); it != paths.end(); ++it) {
    check_cancelled(cancelled_);
    if (!facts.contains(it.key())) facts[it.key()] = parse(it.value(), it.key(), sizes[it.key()]);
    write_json(safe_path(cache_, "dependency-facts/v1/" + it.key() + ".json"), facts[it.key()]);
  }
  for (auto it = hashes.begin(); it != hashes.end(); ++it)
    result.append(
        QJsonObject{{"path", it.key()}, {"sha256", it.value()}, {"facts", facts[it.value()]}});
  return result;
}
}  // namespace bugg
