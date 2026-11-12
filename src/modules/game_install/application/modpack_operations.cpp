#include <QCoreApplication>
#include <QCryptographicHash>
#include <QDirIterator>
#include <QElapsedTimer>
#include <QFile>
#include <QJsonDocument>
#include <QRegularExpression>
#include <QSet>
#include <QThread>

#include "modules/game_install/application/game_operations.h"
#include "modules/game_install/application/modpack_plan.h"
#include "modules/room_sync/application/room_content_cache.h"

namespace bugg {
namespace {
[[noreturn]] void invalid_pack(const QString& reason) {
  throw std::runtime_error(reason.toUtf8().constData());
}
bool identifier(const QString& value) {
  static const QRegularExpression valid("\\A[A-Za-z0-9_.+\x2d]{1,64}\\z");
  return valid.match(value).hasMatch();
}
QJsonObject manifest_json(const QString& path, const QString& name) {
  const auto bytes = archive_read(path, name);
  QJsonParseError error;
  const auto document = QJsonDocument::fromJson(bytes, &error);
  if (bytes.size() > 4 * 1024 * 1024 || error.error != QJsonParseError::NoError ||
      !document.isObject())
    invalid_pack(QCoreApplication::translate("Bugg", "整合包清单无效"));
  return document.object();
}
}  // namespace
void verify_content_file(const QString& path, const QJsonObject& record,
                         const Cancellation& cancelled) {
  const auto hashes = record["hashes"].toObject();
  const auto size = record["fileSize"].toVariant().toLongLong();
  if (!QFileInfo::exists(path) || QFileInfo(path).size() != size)
    invalid_pack(QCoreApplication::translate("Bugg", "整合包文件大小不匹配"));
  QList<QByteArray> algorithms;
  for (auto it = hashes.begin(); it != hashes.end(); ++it) algorithms.append(it.key().toLatin1());
  const auto digests = file_digests(path, algorithms, cancelled);
  for (auto it = hashes.begin(); it != hashes.end(); ++it) {
    if (digests.value(it.key().toLatin1()) != it.value().toString().toLatin1().toLower())
      invalid_pack(QCoreApplication::translate("Bugg", "整合包文件摘要不匹配：") +
                   QFileInfo(path).fileName());
  }
}
void validate_content_record(const QJsonObject& record, QSet<QString>& names) {
  const auto relative = record["path"].toString();
  safe_path(QDir::tempPath(), relative);
  const auto parts = relative.toLower().split('/');
  if (parts.first().startsWith('.') || names.contains(relative.toCaseFolded()) ||
      relative.endsWith(".exe", Qt::CaseInsensitive) ||
      relative.endsWith(".dll", Qt::CaseInsensitive) ||
      relative.endsWith(".bat", Qt::CaseInsensitive) ||
      relative.endsWith(".cmd", Qt::CaseInsensitive) || parts.contains("launcher_accounts.json") ||
      parts.contains("launcher_profiles.json"))
    invalid_pack(QCoreApplication::translate("Bugg", "整合包文件路径重复或保留"));
  names.insert(relative.toCaseFolded());
  const auto hashes = record["hashes"].toObject();
  if (hashes.isEmpty() || record["fileSize"].toDouble(-1) < 0)
    invalid_pack(QCoreApplication::translate("Bugg", "整合包文件缺少校验信息"));
  for (auto it = hashes.begin(); it != hashes.end(); ++it) {
    const int length = it.key() == "sha1"     ? 40
                       : it.key() == "sha256" ? 64
                       : it.key() == "sha512" ? 128
                                              : 0;
    if (!length || !QRegularExpression("\\A[0-9a-fA-F]{" + QString::number(length) + "}\\z")
                        .match(it.value().toString())
                        .hasMatch())
      invalid_pack(QCoreApplication::translate("Bugg", "整合包摘要格式无效"));
  }
  if (!record["embedded"].toBool()) {
    const auto urls = record["downloads"].toArray();
    if (urls.isEmpty() || urls.size() > 16 || hashes["sha1"].toString().isEmpty())
      invalid_pack(QCoreApplication::translate("Bugg", "整合包下载信息无效"));
    for (const auto& item : urls) {
      const QUrl url(item.toString());
      const auto host = url.host().toLower();
      const bool trusted =
          QStringList{"cdn.modrinth.com", "github.com",        "raw.githubusercontent.com",
                      "gitlab.com",       "download.bugg.icu", "mirror.bugg.icu"}
              .contains(host) ||
          host.endsWith(".forgecdn.net");
      if (!trusted || url.scheme() != "https" || !url.userInfo().isEmpty() || url.port(443) != 443)
        invalid_pack(QCoreApplication::translate("Bugg", "整合包下载地址不受支持"));
    }
  }
}
ModpackPlan inspect_modpack(const QString& path, const Cancellation& cancelled) {
  const auto entries = archive_entries(path, cancelled);
  QString manifest;
  for (const auto& name : {"buggcraft.pack.json", "modrinth.index.json", "manifest.json"}) {
    if (!entries.contains(name)) continue;
    if (!manifest.isEmpty())
      invalid_pack(QCoreApplication::translate("Bugg", "整合包包含多个清单"));
    manifest = name;
  }
  if (manifest.isEmpty()) {
    const QRegularExpression profile("\\A(\\.minecraft/)?versions/([^/]+)/\\2\\.json\\z");
    QString descriptor;
    QRegularExpressionMatch selected;
    for (const auto& entry : entries) {
      const auto match = profile.match(entry);
      if (!match.hasMatch()) continue;
      if (!descriptor.isEmpty())
        invalid_pack(QCoreApplication::translate("Bugg", "客户端包包含多个实例，请分别导出后导入"));
      descriptor = entry;
      selected = match;
    }
    if (descriptor.isEmpty())
      invalid_pack(QCoreApplication::translate("Bugg", "此归档缺少支持的整合包清单或完整客户端"));
    auto metadata = manifest_json(path, descriptor);
    if (metadata.contains("inheritsFrom") ||
        metadata["downloads"].toObject()["client"].toObject().isEmpty() ||
        metadata["mainClass"].toString().isEmpty())
      invalid_pack(QCoreApplication::translate(
          "Bugg", "客户端包缺少自包含的游戏描述，请从原启动器导出整合包"));
    const auto description = instance_descriptor(metadata);
    const auto game = description.value("version").toString();
    if (!identifier(game))
      invalid_pack(QCoreApplication::translate("Bugg", "客户端包游戏版本无效"));
    ModpackPlan plan;
    plan.format = "Minecraft client";
    plan.client_prefix = selected.captured(1);
    plan.client_id = selected.captured(2);
    plan.client_metadata = metadata;
    plan.specification = {{"name", QFileInfo(path).completeBaseName()},
                          {"game", game},
                          {"loader", description.value("loader").toString() == "Minecraft"
                                         ? "vanilla"
                                         : description.value("loader").toString().toLower()},
                          {"loaderVersion", description.value("loaderVersion")}};
    return plan;
  }
  const auto data = manifest_json(path, manifest);
  ModpackPlan plan;
  plan.specification["name"] = data["name"].toString(QFileInfo(path).completeBaseName());
  plan.specification["loader"] = "vanilla";
  const auto set_loader = [&](const QString& loader, const QString& version) {
    if (plan.specification.value("loader") != "vanilla" || !identifier(version))
      invalid_pack(QCoreApplication::translate("Bugg", "整合包加载器冲突或版本无效"));
    plan.specification["loader"] = loader.toLower();
    plan.specification["loaderVersion"] = version;
  };
  if (manifest == "manifest.json") {
    plan.format = "CurseForge";
    if (data["manifestType"] != "minecraftModpack" || data["manifestVersion"].toInt() != 1)
      invalid_pack(QCoreApplication::translate("Bugg", "不支持的 CurseForge 清单版本"));
    const auto minecraft = data["minecraft"].toObject();
    plan.specification["game"] = minecraft["version"].toString();
    for (const auto& value : minecraft["modLoaders"].toArray()) {
      const auto id = value.toObject()["id"].toString();
      const int at = id.indexOf('-');
      const auto loader = id.left(at);
      if (at < 0 || !QStringList{"forge", "neoforge", "fabric", "quilt"}.contains(loader))
        invalid_pack(QCoreApplication::translate("Bugg", "不支持的整合包加载器"));
      set_loader(loader, id.mid(at + 1));
    }
    plan.overrides = {data["overrides"].toString("overrides") + '/'};
    plan.files = data["files"].toArray();
    for (const auto& value : plan.files) {
      const auto ref = value.toObject();
      if (ref["projectID"].toDouble() <= 0 || ref["fileID"].toDouble() <= 0)
        invalid_pack(QCoreApplication::translate("Bugg", "CurseForge 文件编号无效"));
    }
  } else {
    const bool own = manifest == "buggcraft.pack.json";
    plan.format = own ? "Buggcraft" : "Modrinth";
    if (data["formatVersion"].toInt() != 1 ||
        (own ? data["format"] != "buggcraft" : data["game"] != "minecraft"))
      invalid_pack(QCoreApplication::translate("Bugg", "不支持的整合包清单版本"));
    if (own) {
      plan.specification["game"] = data["minecraft"].toString();
      if (!data["loader"].toString().isEmpty())
        set_loader(data["loader"].toString(), data["loaderVersion"].toString());
      plan.overrides = {"files/"};
    } else {
      const auto dependencies = data["dependencies"].toObject();
      plan.specification["game"] = dependencies["minecraft"].toString();
      for (auto it = dependencies.begin(); it != dependencies.end(); ++it) {
        if (it.key() == "minecraft") continue;
        const auto loader = it.key().split('-').first();
        if (!QStringList{"forge", "neoforge", "fabric", "quilt"}.contains(loader))
          invalid_pack(QCoreApplication::translate("Bugg", "不支持的整合包依赖"));
        set_loader(loader, it.value().toString());
      }
      plan.overrides = {"overrides/", "client-overrides/"};
    }
    QSet<QString> names;
    qint64 total = 0;
    QSet<QString> expected{manifest};
    for (const auto& value : data["files"].toArray()) {
      auto record = value.toObject();
      if (!own && record["env"].toObject()["client"] == "unsupported") continue;
      if (own) {
        QJsonObject hashes;
        for (const auto& key : {"sha1", "sha256", "sha512"})
          if (record.contains(key)) hashes[key] = record[key];
        const auto file_size = record.value("size");
        record["hashes"] = hashes;
        record["fileSize"] = file_size;
        record["embedded"] = record["embedded"].toBool(true);
        if (hashes["sha256"].toString().isEmpty())
          invalid_pack(QCoreApplication::translate("Bugg", "整合包缺少 SHA-256"));
      }
      validate_content_record(record, names);
      total += record["fileSize"].toVariant().toLongLong();
      if (total > 8LL * 1024 * 1024 * 1024)
        invalid_pack(QCoreApplication::translate("Bugg", "整合包文件总量超过限制"));
      if (record["embedded"].toBool()) {
        const auto entry = "files/" + record["path"].toString();
        if (!entries.contains(entry))
          invalid_pack(QCoreApplication::translate("Bugg", "整合包缺少内嵌文件"));
        expected.insert(entry);
      }
      plan.files.append(record);
    }
    if (own && QSet<QString>(entries.begin(), entries.end()) != expected)
      invalid_pack(QCoreApplication::translate("Bugg", "整合包含有清单之外的文件"));
  }
  if (!identifier(plan.specification.value("game").toString()) || plan.files.size() > 10000)
    invalid_pack(QCoreApplication::translate("Bugg", "整合包版本或文件数量无效"));
  for (const auto& prefix : plan.overrides) safe_path(QDir::tempPath(), prefix);
  return plan;
}
QString GameOperations::import_pack(const QString& archive, const QString& name) {
  const auto plan = inspect_modpack(archive, cancelled_);
  const auto destination = safe_path(root_, "versions/" + name);
  if (name.isEmpty() || name.contains('/') || name.contains('\\') || QFileInfo::exists(destination))
    invalid_pack(QCoreApplication::translate("Bugg", "实例名称无效或已存在"));
  const auto fingerprint =
      QCryptographicHash::hash(
          (QFileInfo(archive).absoluteFilePath() + ':' + name + ':' +
           QString::number(QFileInfo(archive).size()) + ':' +
           QString::number(QFileInfo(archive).lastModified().toMSecsSinceEpoch()))
              .toUtf8(),
          QCryptographicHash::Sha256)
          .toHex()
          .left(20);
  const auto staging_id = ".import-" + QString::fromLatin1(fingerprint);
  const auto staging = safe_path(root_, "versions/" + staging_id);
  auto specification = plan.specification;
  specification["name"] = staging_id;
  const auto staging_json = safe_path(staging, staging_id + ".json");
  const QStringList excluded{".buggcraft", "launcher_accounts.json", "launcher_profiles.json",
                             "logs/", "crash-reports/"};
  if (!plan.client_id.isEmpty()) {
    report(-1, QCoreApplication::translate("Bugg", "正在导入完整客户端…"));
    for (const auto* directory : {"assets", "libraries"})
      archive_extract(archive, safe_path(root_, directory), plan.client_prefix + directory + '/',
                      {}, cancelled_);
    archive_extract(archive, staging, plan.client_prefix + "versions/" + plan.client_id + '/',
                    excluded, cancelled_);
    auto metadata = plan.client_metadata;
    metadata["bugg"] =
        QJsonObject{{"version", plan.specification.value("game").toString()},
                    {"loader", plan.specification.value("loader").toString()},
                    {"loaderVersion", plan.specification.value("loaderVersion").toString()}};
    const auto client = safe_path(staging, plan.client_id + ".jar");
    const auto renamed = safe_path(staging, name + ".jar");
    const auto download = metadata["downloads"].toObject()["client"].toObject();
    if (!valid_file(client, download["sha1"].toString().toLatin1(),
                    download["size"].toVariant().toLongLong(), cancelled_))
      invalid_pack(QCoreApplication::translate("Bugg", "客户端包游戏核心校验失败"));
    if (client != renamed && !QFile::rename(client, renamed))
      invalid_pack(QCoreApplication::translate("Bugg", "无法重命名客户端文件"));
    metadata["jar"] = name;
    if (plan.client_id != name) QFile::remove(safe_path(staging, plan.client_id + ".json"));
    return commit_content(staging_id, name, metadata, {}, plan.format);
  }
  for (const auto& prefix : plan.overrides)
    archive_extract(archive, staging, prefix, excluded, cancelled_);
  QList<GameResource> downloads;
  QHash<qint64, QJsonObject> projects, files;
  if (plan.format == "CurseForge") {
    report(-1, QCoreApplication::translate("Bugg", "正在解析整合包文件…"));
    const auto resolve = [&](const QString& manifest_field, const QString& request_field,
                             const QString& route, QHash<qint64, QJsonObject>& target) {
      QJsonArray ids;
      QSet<qint64> seen;
      const auto flush = [&] {
        const auto data = resources_
                              .json(QUrl("https://api.curseforge.com/v1/" + route),
                                    {{request_field, ids}})["data"]
                              .toArray();
        for (const auto& item : data) {
          const auto object = item.toObject();
          const auto id = object["id"].toInteger();
          if (seen.contains(id)) target.insert(id, object);
        }
        ids = {};
      };
      for (const auto& value : plan.files) {
        check_cancelled(cancelled_);
        const auto id = value.toObject()[manifest_field].toInteger();
        if (seen.contains(id)) continue;
        seen.insert(id);
        ids.append(id);
        if (ids.size() == 100) flush();
      }
      if (!ids.isEmpty()) flush();
    };
    resolve("projectID", "modIds", "mods", projects);
    resolve("fileID", "fileIds", "mods/files", files);
  }
  QJsonArray records;
  QSet<QString> names;
  for (const auto& value : plan.files) {
    check_cancelled(cancelled_);
    auto record = value.toObject();
    if (plan.format == "CurseForge") {
      const auto project = QString::number(record["projectID"].toVariant().toLongLong());
      const auto file_id = QString::number(record["fileID"].toVariant().toLongLong());
      const auto project_data = projects.value(project.toLongLong());
      const auto file = files.value(file_id.toLongLong());
      const auto folder =
          QMap<int, QString>{
              {6, "mods"}, {12, "resourcepacks"}, {6552, "shaderpacks"}, {6945, "datapacks"}}
              .value(project_data["classId"].toInt());
      const auto url =
          curseforge_file_url(file["id"].toVariant().toLongLong(), file["fileName"].toString(),
                              file["downloadUrl"].toString());
      const auto filename = file["fileName"].toString();
      if (file["isEarlyAccessContent"].toBool())
        invalid_pack(QCoreApplication::translate("Bugg", "CurseForge 文件尚未公开：") + filename);
      if (folder.isEmpty() || file["modId"].toVariant().toLongLong() != project.toLongLong() ||
          file["id"].toVariant().toLongLong() != file_id.toLongLong() || filename.isEmpty() ||
          filename.contains('/') || filename.contains('\\'))
        invalid_pack(QCoreApplication::translate("Bugg", "CurseForge 文件元数据无效：") + filename);
      QString sha1;
      for (const auto& hash : file["hashes"].toArray())
        if (hash.toObject()["algo"].toInt() == 1) sha1 = hash.toObject()["value"].toString();
      record = {{"path", folder + '/' + file["fileName"].toString()},
                {"fileSize", file["fileLength"]},
                {"hashes", QJsonObject{{"sha1", sha1}}},
                {"downloads", QJsonArray{url}},
                {"embedded", false}};
      validate_content_record(record, names);
    }
    const auto path = safe_path(staging, record["path"].toString());
    if (!record["embedded"].toBool()) {
      QList<QUrl> urls;
      for (const auto& url : record["downloads"].toArray()) urls.append(QUrl(url.toString()));
      downloads.append({urls.takeFirst(), path,
                        record["hashes"].toObject()["sha1"].toString().toLatin1(),
                        record["fileSize"].toVariant().toLongLong(), urls});
    }
    records.append(record);
  }
  // One resource batch lets pack mods/resources run alongside core/libraries/assets.
  // The loader processors still run only after their required files are ready.
  const bool resume = QFileInfo::exists(staging_json);
  pack_resources_ = downloads;
  if (!resume) install(specification);
  pack_resources_.clear();
  auto metadata = load_version(staging_id);
  if (resume) resources_.fetch(downloads);
  for (const auto& value : records) {
    const auto record = value.toObject();
    verify_content_file(safe_path(staging, record["path"].toString()), record, cancelled_);
  }
  return commit_content(staging_id, name, metadata, records, plan.format);
}
QVariantMap GameOperations::check_room(const QString& instance_id, const QJsonObject& game) {
  if (!QFileInfo::exists(safe_path(root_, "versions/" + instance_id + '/' + instance_id + ".json")))
    invalid_pack(QCoreApplication::translate("Bugg", "找不到所选实例，请刷新游戏列表"));
  const auto descriptor = instance_descriptor(load_version(instance_id));
  const auto expected = instance_descriptor(
      {{"bugg", QJsonObject{{"version", game["version"]}, {"loader", game["loader"]}}}});
  QStringList errors;
  if (descriptor.value("version").toString() != game["version"].toString())
    errors.append(QCoreApplication::translate("Bugg", "游戏版本不同"));
  if (descriptor.value("loader").toString() != expected.value("loader").toString())
    errors.append(QCoreApplication::translate("Bugg", "加载器不同"));
  const bool can_supplement = errors.isEmpty();
  QStringList hashes;
  const auto directory = safe_path(root_, "versions/" + instance_id + "/mods");
  for (const auto& name : QDir(directory).entryList({"*.jar"}, QDir::Files, QDir::Name))
    hashes.append(
        QString::fromLatin1(file_digest(safe_path(directory, name), "sha256", cancelled_)));
  hashes.sort();
  const auto digest =
      QCryptographicHash::hash(hashes.join('\n').toUtf8(), QCryptographicHash::Sha256).toHex();
  if (hashes.size() != game["mods_count"].toInt() ||
      (!game["mods_hash"].toString().isEmpty() &&
       digest != game["mods_hash"].toString().toLatin1()))
    errors.append(QCoreApplication::translate("Bugg", "模组内容不同"));
  const auto warning =
      can_supplement && !game["loader_version"].toString().isEmpty() &&
              descriptor.value("loaderVersion").toString() != game["loader_version"].toString()
          ? QCoreApplication::translate("Bugg", "加载器构建不同，类型一致，可以启动")
          : QString();
  return {{"compatible", errors.isEmpty()},
          {"canSupplement", can_supplement},
          {"detail", errors.join(" · ")},
          {"warning", warning},
          {"localMods", hashes.size()}};
}
QString GameOperations::sync_room(const QVariantMap& specification,
                                  const RoomContentRequest& request) {
  if (!request) invalid_pack(QCoreApplication::translate("Bugg", "房间同步服务不可用"));
  const auto session = specification.value("roomSession").toString();
  const auto game = QJsonObject::fromVariantMap(specification.value("roomGame").toMap());
  const auto name = specification.value("name").toString();
  if (session.isEmpty() || name.isEmpty() || name.contains('/') || name.contains('\\'))
    invalid_pack(QCoreApplication::translate("Bugg", "房间同步规格无效"));
  RoomContentCache content(request, session, cancelled_);
  QJsonArray records;
  QSet<QString> names;
  for (const auto& value : content.manifest(game)) {
    const auto item = value.toObject();
    QJsonObject record{{"path", item["path"]},
                       {"fileSize", item["size"]},
                       {"hashes", QJsonObject{{"sha256", item["sha256"]}}},
                       {"embedded", true},
                       {"roomItem", item},
                       {"kind", item["kind"]}};
    validate_content_record(record, names);
    records.append(record);
  }
  const auto base_instance = specification.value("baseInstance").toString();
  auto identity_data = QJsonDocument(game).toJson(QJsonDocument::Compact);
  if (!base_instance.isEmpty()) identity_data += base_instance.toUtf8();
  const auto identity =
      QCryptographicHash::hash(identity_data, QCryptographicHash::Sha256).toHex().left(16);
  const auto staging_id = ".room-" + QString::fromLatin1(identity);
  const auto staging = safe_path(root_, "versions/" + staging_id);
  const auto destination = safe_path(root_, "versions/" + name);
  const bool existing = QFileInfo::exists(safe_path(destination, name + ".json"));
  if (existing) {
    if (!check_room(name, game).value("compatible").toBool())
      invalid_pack(QCoreApplication::translate("Bugg", "房间实例已改变，请重新同步"));
    for (const auto& value : records)
      verify_content_file(safe_path(destination, value.toObject()["path"].toString()),
                          value.toObject(), cancelled_);
    return name;
  }
  auto install_specification = specification;
  install_specification["name"] = staging_id;
  if (!QFileInfo::exists(safe_path(staging, staging_id + ".json"))) {
    const auto base = specification.value("baseInstance").toString();
    if (base.isEmpty()) {
      install(install_specification);
    } else {
      if (!check_room(base, game).value("canSupplement").toBool())
        invalid_pack(QCoreApplication::translate("Bugg", "请选择相同游戏版本和加载器的配置"));
      auto metadata = load_version(base);
      metadata["id"] = staging_id;
      if (!metadata.contains("jar"))
        metadata["jar"] =
            QFileInfo::exists(safe_path(root_, "versions/" + base + '/' + base + ".jar"))
                ? base
                : game["version"].toString();
      metadata["bugg"] = QJsonObject{
          {"version", game["version"]},
          {"loader", game["loader"]},
          {"loaderVersion", instance_descriptor(metadata).value("loaderVersion").toString()}};
      write_json(safe_path(staging, staging_id + ".json"), metadata);
    }
  }
  int completed = 0;
  for (const auto& value : records) {
    check_cancelled(cancelled_);
    const auto record = value.toObject();
    const auto item = record["roomItem"].toObject();
    const auto target = safe_path(staging, record["path"].toString());
    QDir().mkpath(QFileInfo(target).absolutePath());
    bool valid = false;
    try {
      verify_content_file(target, record, cancelled_);
      valid = true;
    } catch (...) {
      check_cancelled(cancelled_);
    }
    if (!valid) {
      QFile::remove(target);
      // 优先复用本机同名、同大小、同 SHA-256 文件，避免重复传输已有模组。
      const auto versions = QDir(safe_path(root_, "versions"))
                                .entryList(QDir::Dirs | QDir::NoDotAndDotDot | QDir::NoSymLinks);
      for (const auto& version : versions) {
        try {
          const auto candidate =
              safe_path(root_, "versions/" + version + '/' + record["path"].toString());
          if (candidate == target) continue;
          verify_content_file(candidate, record, cancelled_);
          valid = QFile::copy(candidate, target);
        } catch (...) {
          check_cancelled(cancelled_);
        }
        if (valid) break;
      }
    }
    if (!valid) {
      auto urls = content.sources(item);
      if (!urls.isEmpty()) {
        try {
          resources_.fetch({{urls.takeFirst(), target, item["sha1"].toString().toLatin1(),
                             item["size"].toVariant().toLongLong(), urls}});
          verify_content_file(target, record, cancelled_);
          valid = true;
        } catch (...) {
          check_cancelled(cancelled_);
        }
      }
    }
    if (!valid && QRegularExpression("^[0-9a-f]{40}$").match(item["sha1"].toString()).hasMatch()) {
      try {
        auto downloads = item["downloads"].toArray();
        if (downloads.isEmpty()) {
          const auto release = resources_.json(
              QUrl("https://api.modrinth.com/v2/version_file/" + item["sha1"].toString()));
          for (const auto& file : release["files"].toArray()) {
            if (file.toObject()["hashes"].toObject()["sha1"] == item["sha1"] &&
                file.toObject()["size"] == item["size"])
              downloads.append(file.toObject()["url"]);
          }
        }
        if (!downloads.isEmpty()) {
          auto public_record = record;
          public_record["embedded"] = false;
          public_record["downloads"] = downloads;
          public_record["hashes"] = QJsonObject{{"sha1", item["sha1"]}, {"sha256", item["sha256"]}};
          QSet<QString> public_names;
          validate_content_record(public_record, public_names);
          QList<QUrl> urls;
          for (const auto& url : downloads) urls.append(QUrl(url.toString()));
          resources_.fetch({{urls.takeFirst(), target, item["sha1"].toString().toLatin1(),
                             item["size"].toVariant().toLongLong(), urls}});
          verify_content_file(target, record, cancelled_);
          valid = true;
        }
      } catch (...) {
        check_cancelled(cancelled_);
      }
    }
    if (!valid) {
      QFile::remove(target);
      QElapsedTimer retry;
      retry.start();
      while (true) {
        try {
          content.transfer("mods.fetch",
                           {{"kind", record["kind"]}, {"item", item}, {"target", target}});
          break;
        } catch (const std::exception& error) {
          check_cancelled(cancelled_);
          if (retry.elapsed() >= 45000 ||
              !QString::fromUtf8(error.what()).contains("P2P file channel is not connected"))
            throw;
          QThread::msleep(350);
        }
      }
      verify_content_file(target, record, cancelled_);
    }
    report(
        double(++completed) / qMax(1, records.size()),
        QCoreApplication::translate("Bugg", "同步文件 %1 / %2").arg(completed).arg(records.size()));
  }
  return commit_content(staging_id, name, load_version(staging_id), records, "BUGG Room");
}
QString GameOperations::commit_content(const QString& staging_id, const QString& name,
                                       QJsonObject metadata, const QJsonArray& records,
                                       const QString& source) {
  const auto staging = safe_path(root_, "versions/" + staging_id);
  const auto destination = safe_path(root_, "versions/" + name);
  // 覆盖文件不得替换启动器生成的版本描述；最后一次重写后再发布可见目录。
  auto checked_records = records;
  QStringList remove;
  const auto receipt = check_dependencies(staging, staging, remove, checked_records, metadata,
                                         source == "BUGG Room" ? "room_manifest" : "authored_pack");
  if (!receipt.isEmpty()) metadata["buggDependencyDecision"] = receipt;
  metadata["id"] = name;
  metadata["buggcraftModpack"] = QJsonObject{{"source", source}, {"resources", checked_records}};
  write_json(safe_path(staging, name + ".json"), metadata);
  check_cancelled(cancelled_);
  if (!QDir().rename(staging, destination))
    invalid_pack(QCoreApplication::translate("Bugg", "无法提交整合包实例"));
  QFile::remove(safe_path(destination, staging_id + ".json"));
  report(1, QCoreApplication::translate("Bugg", "游戏安装完成"));
  return name;
}

void GameOperations::export_pack(const QString& id, const QString& destination, bool compact,
                                 bool saves) {
  const auto source = safe_path(root_, "versions/" + id);
  const auto output = QFileInfo(destination).absoluteFilePath();
  if (output.startsWith(source + '/', Qt::CaseInsensitive))
    invalid_pack(QCoreApplication::translate("Bugg", "导出位置不能位于当前实例内"));
  const auto metadata = load_version(id);
  const auto descriptor = instance_descriptor(metadata);
  const auto loader = descriptor.value("loader").toString();
  QJsonObject manifest{{"format", "buggcraft"},
                       {"formatVersion", 1},
                       {"name", id},
                       {"version", "1.0.0"},
                       {"minecraft", descriptor.value("version").toString()},
                       {"loader", loader == "Minecraft" ? QString() : loader},
                       {"loaderVersion", descriptor.value("loaderVersion").toString()},
                       {"exportMode", compact ? "compact" : "standard"},
                       {"recommendedRam", 0}};
  QMap<QString, QJsonObject> known;
  for (const auto& value : metadata["buggcraftModpack"].toObject()["resources"].toArray()) {
    const auto record = value.toObject();
    known.insert(record["path"].toString(), record);
  }
  QStringList folders{"mods",   "config",  "defaultconfigs", "resourcepacks", "shaderpacks",
                      "kubejs", "scripts", "datapacks",      "global_packs"};
  if (saves) folders.append("saves");
  QMap<QString, QString> files;
  QJsonArray records;
  const auto collect_file = [&](const QString& path) {
    check_cancelled(cancelled_);
    const auto relative = QDir(source).relativeFilePath(path);
    safe_path(source, relative);
    const auto hashes = file_digests(path, {"sha1", "sha256"}, cancelled_);
    const auto sha1 = QString::fromLatin1(hashes.value("sha1"));
    const auto sha256 = QString::fromLatin1(hashes.value("sha256"));
    const auto size = QFileInfo(path).size();
    const auto record = known.value(relative);
    const bool external = compact && !record["downloads"].toArray().isEmpty() &&
                          record["fileSize"].toVariant().toLongLong() == size &&
                          record["hashes"].toObject()["sha1"] == sha1;
    QJsonObject entry{{"path", relative},
                      {"size", size},
                      {"sha1", sha1},
                      {"sha256", sha256},
                      {"embedded", !external}};
    if (external)
      entry["downloads"] = record["downloads"];
    else
      files.insert("files/" + relative, path);
    records.append(entry);
    report(-1, QCoreApplication::translate("Bugg", "整理整合包：") + relative);
  };
  // Start at allowed roots so logs, natives and unselected saves are never
  // traversed. Hashing and atomic ZIP writing remain the shared implementation.
  for (const auto& folder : folders) {
    check_cancelled(cancelled_);
    const QFileInfo entry(source + '/' + folder);
    if (entry.isSymLink()) continue;
    if (entry.isFile()) {
      collect_file(entry.absoluteFilePath());
      continue;
    }
    if (!entry.isDir()) continue;
    QDirIterator iterator(entry.absoluteFilePath(), QDir::Files | QDir::NoSymLinks,
                          QDirIterator::Subdirectories);
    while (iterator.hasNext()) collect_file(iterator.next());
  }
  for (const auto* name : {"options.txt", "optionsof.txt"}) {
    const QFileInfo entry(source + '/' + name);
    if (entry.isFile() && !entry.isSymLink()) collect_file(entry.absoluteFilePath());
  }
  manifest["files"] = records;
  archive_write(output, files,
                {{"buggcraft.pack.json", QJsonDocument(manifest).toJson(QJsonDocument::Compact)}},
                cancelled_, [this](int done, int total) {
                  report(total ? double(done) / total : 1,
                         QCoreApplication::translate("Bugg", "正在导出整合包"));
                });
}
}  // namespace bugg
