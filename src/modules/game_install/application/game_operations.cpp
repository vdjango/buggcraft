#include "modules/game_install/application/game_operations.h"

#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QJsonDocument>
#include <QRegularExpression>
#include <QTemporaryDir>
#include <stdexcept>

#include "modules/settings/application/language_service.h"
#include "platform/runtime/runtime_environment.h"

namespace bugg {
namespace {
GameResource described_resource(const QJsonObject& object, const QString& path) {
  return {QUrl(object["url"].toString()), path, object["sha1"].toString().toLatin1(),
          object.contains("size") ? qint64(object["size"].toDouble()) : -1};
}
QJsonObject archive_json(const QString& archive, const QString& name) {
  const auto document = QJsonDocument::fromJson(archive_read(archive, name));
  if (!document.isObject())
    throw std::runtime_error(
        QCoreApplication::translate("Bugg", "加载器描述文件无效").toStdString());
  return document.object();
}
QString native_classifier(const QJsonObject& library) {
  auto classifier = library["natives"].toObject()[minecraft_os()].toString();
  classifier.replace("${arch}", sizeof(void*) == 8 ? "64" : "32");
  return classifier;
}
}  // namespace
GameOperations::GameOperations(QString game_root, QString portable_root, QStringList source_order,
                               Cancellation cancelled, Progress progress, int concurrency,
                               HttpClient* transport, QUrl bugg_base)
    : root_(std::move(game_root)),
      portable_(std::move(portable_root)),
      cancelled_(std::move(cancelled)),
      progress_(std::move(progress)),
      resources_(
          std::move(source_order), cancelled_,
          [this](double fraction, const QString& detail) { report(fraction, detail, true); },
          transport, concurrency, bugg_base),
      facts_base_(std::move(bugg_base)) {
  resources_.set_transfer_progress([this](const QVariantMap& transfer) {
    const auto path = transfer.value("path").toString();
    if (!content_transfers_.contains(path)) return;
    auto file = content_transfers_.value(path);
    for (const auto& key : {"speedText", "transferText", "aggregateSpeedText", "activeTransfers",
                            "received", "total"})
      file[key] = transfer.value(key);
    content_update(file, transfer.value("state").toString(), transfer.value("progress").toDouble(),
                   transfer.value("detail").toString());
  });
}
void GameOperations::report(double progress, const QString& detail, bool immediate) {
  check_cancelled(cancelled_);
  // Coalesce before queued GUI delivery, while keeping phase boundaries and
  // completion immediate. Cancellation is checked even for suppressed updates.
  if (!immediate && progress_clock_.isValid() && progress < 1 &&
      (progress < 0) == (reported_progress_ < 0) && !(progress < 0 && detail != reported_detail_) &&
      progress_clock_.elapsed() < 100)
    return;
  progress_clock_.start();
  reported_progress_ = progress;
  reported_detail_ = detail;
  progress_(progress, detail);
  if (content_progress_ && content_transfers_.isEmpty() && !content_item_.isEmpty()) {
    content_item_["progress"] = progress;
    content_item_["detail"] = detail;
    content_progress_(content_item_);
  }
}
void GameOperations::content_update(const QVariantMap& file, const QString& state, double progress,
                                    const QString& detail) {
  check_cancelled(cancelled_);
  content_item_.clear();
  for (const auto& key :
       {"title", "versionName", "filename", "publisher", "projectId", "versionId", "dependency",
        "speedText", "transferText", "aggregateSpeedText", "activeTransfers", "received", "total"})
    content_item_[key] = file.value(key);
  content_item_["key"] =
      file.value("publisher").toString() + ':' +
      (file.value("projectId").toString().isEmpty()
           ? file.value("versionId").toString() + ':' + file.value("filename").toString()
           : file.value("projectId").toString());
  content_item_["state"] = state;
  content_item_["progress"] = progress;
  content_item_["detail"] = detail;
  if (content_progress_) content_progress_(content_item_);
  if (state == "done" || state == "installed" || state == "failed") content_item_.clear();
}
QJsonObject GameOperations::base_version(const QString& version) {
  const auto cached = safe_path(portable_cache_root(portable_), "metadata/" + version + ".json");
  if (QFileInfo::exists(cached)) {
    try {
      return read_json(cached);
    } catch (...) {
      check_cancelled(cancelled_);
    }
  }
  report(-1, QCoreApplication::translate("Bugg", "获取 Minecraft 版本元数据"));
  const auto manifest =
      resources_.json(QUrl("https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"));
  for (const auto& item : manifest["versions"].toArray()) {
    const auto entry = item.toObject();
    if (entry["id"] != version) continue;
    const auto metadata_file =
        safe_path(portable_cache_root(portable_), "metadata/" + version + ".json");
    resources_.fetch({described_resource(entry, metadata_file)});
    return read_json(metadata_file);
  }
  throw std::runtime_error(
      QCoreApplication::translate("Bugg", "找不到所选 Minecraft 版本").toStdString());
}
QJsonObject GameOperations::load_version(const QString& id) {
  check_cancelled(cancelled_);
  if (resolving_.contains(id) || resolving_.size() > 16)
    throw std::runtime_error(
        QCoreApplication::translate("Bugg", "版本继承出现循环或层数过多").toStdString());
  resolving_.insert(id);
  const auto path = safe_path(root_, "versions/" + id + '/' + id + ".json");
  auto data = QFileInfo::exists(path) ? read_json(path) : base_version(id);
  const auto parent = data["inheritsFrom"].toString();
  if (!parent.isEmpty()) data = merge_metadata(load_version(parent), data);
  resolving_.remove(id);
  return data;
}
QList<GameResource> GameOperations::library_resources(const QJsonArray& libraries) {
  QList<GameResource> resources;
  // 安装处理器可能分别依赖同一 Maven 库的不同版本，必须全部准备。
  // 游戏进程的版本覆盖/去重由最终元数据与命令归一化负责。
  for (const auto& item : libraries) {
    const auto library = item.toObject();
    if (!rules_allow(library["rules"].toArray())) continue;
    const auto downloads = library["downloads"].toObject();
    auto artifact = downloads["artifact"].toObject();
    const auto coordinate = library["name"].toString();
    if (!downloads.contains("artifact") && !library.contains("natives")) {
      const auto path = maven_path(coordinate);
      auto base = library["url"].toString("https://libraries.minecraft.net/");
      if (!base.endsWith('/')) base += '/';
      artifact = {{"path", path}, {"url", base + path}};
    }
    if (!artifact["url"].toString().isEmpty())
      resources.append(described_resource(
          artifact,
          safe_path(root_, "libraries/" + artifact["path"].toString(maven_path(coordinate)))));
    const auto classifier = native_classifier(library);
    if (!classifier.isEmpty()) {
      const auto native = downloads["classifiers"].toObject()[classifier].toObject();
      if (native.isEmpty())
        throw std::runtime_error(
            QCoreApplication::translate("Bugg", "缺少当前平台 native 依赖").toStdString());
      resources.append(described_resource(
          native, safe_path(root_, "libraries/" + native["path"].toString(
                                                      maven_path(coordinate + ':' + classifier)))));
    }
  }
  return resources;
}
void GameOperations::fetch_libraries(const QJsonArray& libraries) {
  resources_.fetch(library_resources(libraries));
}
void GameOperations::prepare_files(const QJsonObject& metadata, const QString& instance_id) {
  report(-1, QCoreApplication::translate("Bugg", "校验游戏核心与运行库"));
  const auto client = metadata["downloads"].toObject()["client"].toObject();
  const auto jar_id = metadata["jar"].toString(metadata["id"].toString());
  auto downloads = library_resources(metadata["libraries"].toArray());
  downloads.append(pack_resources_);
  if (!client.isEmpty())
    downloads.append(
        described_resource(client, safe_path(root_, "versions/" + jar_id + '/' + jar_id + ".jar")));
  const auto logging = metadata["logging"].toObject()["client"].toObject()["file"].toObject();
  if (!logging.isEmpty())
    downloads.append(described_resource(
        logging, safe_path(root_, "assets/log_configs/" + logging["id"].toString())));
  const auto asset_index = metadata["assetIndex"].toObject();
  if (!asset_index.isEmpty()) {
    report(-1, QCoreApplication::translate("Bugg", "校验游戏资源"));
    const auto index_path =
        safe_path(root_, "assets/indexes/" + asset_index["id"].toString() + ".json");
    resources_.fetch({described_resource(asset_index, index_path)});
    const auto index = read_json(index_path);
    const auto objects = index["objects"].toObject();
    QList<GameResource> assets;
    for (auto it = objects.begin(); it != objects.end(); ++it) {
      const auto object = it.value().toObject();
      const auto hash = object["hash"].toString();
      if (!QRegularExpression("\\A[0-9a-f]{40}\\z").match(hash).hasMatch())
        throw std::runtime_error(
            QCoreApplication::translate("Bugg", "资源摘要格式错误").toStdString());
      const auto path = hash.left(2) + '/' + hash;
      assets.append({QUrl("https://resources.download.minecraft.net/" + path),
                     safe_path(root_, "assets/objects/" + path), hash.toLatin1(),
                     qint64(object["size"].toDouble())});
    }
    downloads.append(assets);
    resources_.fetch(downloads);
    downloads.clear();
    if (index["virtual"].toBool() || index["map_to_resources"].toBool()) {
      const auto destination =
          index["map_to_resources"].toBool()
              ? safe_path(root_, "versions/" + instance_id + "/resources")
              : safe_path(root_, "assets/virtual/" + asset_index["id"].toString());
      for (auto it = objects.begin(); it != objects.end(); ++it) {
        check_cancelled(cancelled_);
        const auto hash = it.value().toObject()["hash"].toString();
        const auto target = safe_path(destination, it.key());
        QDir().mkpath(QFileInfo(target).absolutePath());
        if (!QFileInfo::exists(target) &&
            !QFile::copy(safe_path(root_, "assets/objects/" + hash.left(2) + '/' + hash), target))
          throw std::runtime_error(
              QCoreApplication::translate("Bugg", "无法创建旧版资源映射").toStdString());
      }
    }
  }
  if (!downloads.isEmpty()) resources_.fetch(downloads);
  report(-1, QCoreApplication::translate("Bugg", "准备本地运行库"));
  const auto natives = safe_path(root_, "versions/" + instance_id + "/natives");
  for (const auto& item : effective_libraries(metadata["libraries"].toArray())) {
    const auto library = item.toObject();
    const auto classifier = native_classifier(library);
    if (classifier.isEmpty()) continue;
    const auto native =
        library["downloads"].toObject()["classifiers"].toObject()[classifier].toObject();
    QStringList excludes{"META-INF/"};
    for (const auto& exclude : library["extract"].toObject()["exclude"].toArray())
      excludes.append(exclude.toString());
    archive_extract(
        safe_path(root_, "libraries/" + native["path"].toString(maven_path(
                                            library["name"].toString() + ':' + classifier))),
        natives, {}, excludes, cancelled_);
  }
}
QString GameOperations::ensure_java(const QJsonObject& metadata, const QString& preferred) {
  report(-1, QCoreApplication::translate("Bugg", "匹配 Java 运行环境"));
  const auto java = metadata["javaVersion"].toObject();
  int required = java["majorVersion"].toInt(8);
  if (!preferred.isEmpty()) {
    if (java_major(preferred, cancelled_) == required) return preferred;
    check_cancelled(cancelled_);
    report(-1, QCoreApplication::translate("Bugg", "所选 Java 不兼容，正在自动匹配"));
  }
  for (const auto& executable : java_candidates(portable_, cancelled_))
    if (java_major(executable, cancelled_) == required) return executable;
  QString component = java["component"].toString();
  if (component.isEmpty())
    component = required <= 8    ? "jre-legacy"
                : required <= 17 ? "java-runtime-gamma"
                                 : "java-runtime-delta";
  const auto all =
      resources_.json(QUrl("https://launchermeta.mojang.com/v1/products/java-runtime/"
                           "2ec0cc96c44e5a76b9c8b7c39df7210883d12871/all.json"));
  QString platform = minecraft_os() == "windows" ? "windows-x64"
                     : minecraft_os() == "osx"   ? "mac-os"
                                                 : "linux";
#if defined(Q_PROCESSOR_ARM_64)
  platform = minecraft_os() == "osx"       ? "mac-os-arm64"
             : minecraft_os() == "windows" ? "windows-arm64"
                                           : "linux-arm64";
#endif
  const auto versions = all[platform].toObject()[component].toArray();
  if (versions.isEmpty())
    throw std::runtime_error(
        QCoreApplication::translate("Bugg",
                                    "没有适合此平台的 Java，请在 Java 设置中指定已安装的兼容版本")
            .toStdString());
  const auto manifest =
      resources_.json(QUrl(versions[0].toObject()["manifest"].toObject()["url"].toString()));
  const auto destination =
      safe_path(portable_cache_root(portable_), "runtime/" + component + '/' + platform);
  const auto files = manifest["files"].toObject();
  QList<GameResource> downloads;
  for (auto it = files.begin(); it != files.end(); ++it) {
    const auto file = it.value().toObject();
    if (file["type"] == "file")
      downloads.append(described_resource(file["downloads"].toObject()["raw"].toObject(),
                                          safe_path(destination, it.key())));
    else if (file["type"] == "directory")
      QDir().mkpath(safe_path(destination, it.key()));
  }
  resources_.fetch(downloads);
  for (auto it = files.begin(); it != files.end(); ++it) {
    const auto file = it.value().toObject();
    const auto path = safe_path(destination, it.key());
    if (file["type"] == "link") {
      const auto target =
          QDir::cleanPath(QFileInfo(path).absolutePath() + '/' + file["target"].toString());
      const auto relative = QDir(destination).relativeFilePath(target);
      const auto verified = safe_path(destination, relative);
      if (!QFileInfo::exists(path) && !QFile::link(verified, path))
        throw std::runtime_error(
            QCoreApplication::translate("Bugg", "无法创建 Java 运行库链接").toStdString());
    } else if (file["executable"].toBool())
      QFile::setPermissions(
          path, QFile::permissions(path) | QFile::ExeOwner | QFile::ExeGroup | QFile::ExeOther);
  }
  const auto executable =
      safe_path(destination, minecraft_os() == "osx"       ? "jre.bundle/Contents/Home/bin/java"
                             : minecraft_os() == "windows" ? "bin/java.exe"
                                                           : "bin/java");
  const auto downloaded_major = java_major(executable, cancelled_);
  if (downloaded_major == required) return executable;
  // A downloaded runtime may take longer to become executable while the OS scans it.
  // Recheck verified absolute candidates rather than invoking an unvalidated bare java.
  for (const auto& candidate : java_candidates(portable_, cancelled_))
    if (java_major(candidate, cancelled_) == required) return candidate;
  throw std::runtime_error(
      QCoreApplication::translate("Bugg",
                                  "下载的 Java 无法运行或版本不符（需要 %1，检测到 "
                                  "%2），请重试下载或在 Java 设置选择兼容版本")
          .arg(required)
          .arg(downloaded_major)
          .toStdString());
}
void GameOperations::run_processors(const QJsonObject& profile, const QString& installer,
                                    const QString& extracted, const QString& java) {
  QMap<QString, QString> variables{
      {"SIDE", "client"},
      {"ROOT", root_},
      {"INSTALLER", installer},
      {"MINECRAFT_JAR", safe_path(root_, "versions/" + profile["minecraft"].toString() + '/' +
                                             profile["minecraft"].toString() + ".jar")}};
  const auto data = profile["data"].toObject();
  for (auto it = data.begin(); it != data.end(); ++it) {
    auto value = it.value().toObject()["client"].toString();
    if (value.startsWith('[') && value.endsWith(']'))
      value = safe_path(root_, "libraries/" + maven_path(value.mid(1, value.size() - 2)));
    else if (value.startsWith('/'))
      value = safe_path(extracted, value.mid(1));
    else if (value.startsWith('\'') && value.endsWith('\''))
      value = value.mid(1, value.size() - 2);
    variables[it.key()] = value;
  }
  const auto expand = [&](QString value) {
    if (value.startsWith('[') && value.endsWith(']'))
      return safe_path(root_, "libraries/" + maven_path(value.mid(1, value.size() - 2)));
    for (int pass = 0; pass < 4; ++pass)
      for (auto it = variables.begin(); it != variables.end(); ++it)
        value.replace('{' + it.key() + '}', it.value());
    return value;
  };
  for (const auto& item : profile["processors"].toArray()) {
    check_cancelled(cancelled_);
    const auto processor = item.toObject();
    if (processor.contains("sides") && !processor["sides"].toArray().contains("client")) continue;
    report(-1,
           QCoreApplication::translate("Bugg", "执行加载器处理器 ") + processor["jar"].toString());
    QStringList classpath;
    for (const auto& coordinate : processor["classpath"].toArray())
      classpath.append(safe_path(root_, "libraries/" + maven_path(coordinate.toString())));
    const auto jar = safe_path(root_, "libraries/" + maven_path(processor["jar"].toString()));
    classpath.append(jar);
    auto manifest = QString::fromUtf8(archive_read(jar, "META-INF/MANIFEST.MF"));
    manifest.replace("\r\n ", "");
    const auto match = QRegularExpression("(?:^|\\n)Main-Class: ([^\\r\\n]+)").match(manifest);
    if (!match.hasMatch())
      throw std::runtime_error(
          QCoreApplication::translate("Bugg", "处理器缺少入口类").toStdString());
    QStringList arguments{"-cp", unique_classpath(classpath).join(QDir::listSeparator()),
                          match.captured(1).trimmed()};
    for (const auto& argument : processor["args"].toArray())
      arguments.append(expand(argument.toString()));
    run_java_tool(java, arguments, root_,
                  safe_path(portable_cache_root(portable_), "logs/install.log"), cancelled_);
    const auto outputs = processor["outputs"].toObject();
    for (auto it = outputs.begin(); it != outputs.end(); ++it) {
      auto hash = expand(it.value().toString());
      hash.remove('\'');
      if (!valid_file(expand(it.key()), hash.toLatin1(), -1, cancelled_))
        throw std::runtime_error(
            QCoreApplication::translate("Bugg", "处理器未生成有效的目标文件").toStdString());
    }
  }
}
void GameOperations::validate_libraries(const QJsonObject& metadata) {
  for (const auto& item : effective_libraries(metadata["libraries"].toArray())) {
    check_cancelled(cancelled_);
    const auto library = item.toObject();
    const auto artifact = library["downloads"].toObject()["artifact"].toObject();
    if (library.contains("natives") && artifact.isEmpty()) continue;
    const auto path = artifact["path"].toString(maven_path(library["name"].toString()));
    if (!QFileInfo::exists(safe_path(root_, "libraries/" + path)))
      throw std::runtime_error((QCoreApplication::translate("Bugg", "缺少必需的运行库：") + path +
                                QCoreApplication::translate("Bugg", "，请重新安装对应加载器"))
                                   .toUtf8()
                                   .constData());
  }
}
QString GameOperations::install(const QVariantMap& specification) {
  check_cancelled(cancelled_);
  const auto id = specification.value("name").toString().trimmed();
  const auto version = specification.value("game").toString();
  const auto loader = specification.value("loader", "vanilla").toString().toLower();
  const auto loader_version = specification.value("loaderVersion").toString();
  const auto final = safe_path(root_, "versions/" + id + '/' + id + ".json");
  const bool update = specification.value("updateExisting").toBool();
  if (QFileInfo::exists(final) && !update)
    throw std::runtime_error(
        QCoreApplication::translate("Bugg", "同名实例已经存在，请修改安装名称").toStdString());
  if (id.isEmpty() || id.contains('/') || id.contains('\\') || version.isEmpty())
    throw std::runtime_error(QCoreApplication::translate("Bugg", "安装规格不完整").toStdString());
  auto metadata = update ? load_version(id) : base_version(version);
  const QJsonValue original_jar = metadata.value("jar");
  if (update) {
    const auto current = instance_descriptor(metadata);
    if (current.value("version").toString() != version)
      throw std::runtime_error(
          QCoreApplication::translate("Bugg", "补装不能改变当前游戏版本").toStdString());
    const auto current_loader = current.value("loader").toString().toLower();
    if (current_loader != "vanilla" && current_loader != "minecraft") {
      if (current_loader == loader && current.value("loaderVersion").toString() == loader_version)
        return id;
      throw std::runtime_error(
          QCoreApplication::translate("Bugg", "当前游戏已有其他加载器，不能覆盖安装")
              .toStdString());
    }
    if (loader != "fabric" && loader != "quilt" && loader != "forge" && loader != "neoforge")
      throw std::runtime_error(
          QCoreApplication::translate("Bugg", "请选择要补装的加载器").toStdString());
  } else {
    metadata["jar"] = version;
  }
  QJsonObject profile;
  QString installer;
  QDir().mkpath(safe_path(portable_cache_root(portable_), "staging"));
  QTemporaryDir stage(safe_path(portable_cache_root(portable_), "staging/install-XXXXXX"));
  if (!stage.isValid())
    throw std::runtime_error(
        QCoreApplication::translate("Bugg", "无法创建安装工作目录").toStdString());
  if (loader == "fabric" || loader == "quilt") {
    const QString host =
        loader == "fabric" ? "https://meta.fabricmc.net/v2" : "https://meta.quiltmc.org/v3";
    const auto addition = resources_.json(
        QUrl(host + QString("/versions/loader/%1/%2/profile/json").arg(version, loader_version)));
    metadata = merge_metadata(metadata, addition);
  } else if (loader == "forge" || loader == "neoforge") {
    QString coordinate;
    QString base;
    if (loader == "forge") {
      coordinate = "net.minecraftforge:forge:" +
                   (loader_version.startsWith(version + '-') ? loader_version
                                                             : version + '-' + loader_version) +
                   ":installer";
      base = "https://maven.minecraftforge.net/";
    } else {
      coordinate = (version == "1.20.1" ? "net.neoforged:forge:" + version + '-'
                                        : "net.neoforged:neoforge:") +
                   loader_version + ":installer";
      base = "https://maven.neoforged.net/releases/";
    }
    installer = safe_path(portable_cache_root(portable_), "installers/" + maven_path(coordinate));
    resources_.fetch({{QUrl(base + maven_path(coordinate)), installer, {}, -1}});
    profile = archive_json(installer, "install_profile.json");
    QJsonObject addition;
    if (profile.contains("versionInfo"))
      addition = profile["versionInfo"].toObject();
    else
      addition = archive_json(installer, "version.json");
    metadata = merge_metadata(metadata, addition);
    archive_extract(installer, stage.path(), {}, {"META-INF/"}, cancelled_);
    archive_extract(installer, safe_path(root_, "libraries"), "maven/", {}, cancelled_);
    // 旧安装器将 universal JAR 放根目录；统一写到 Maven 路径。
    if (profile.contains("install")) {
      const auto install = profile["install"].toObject();
      const auto embedded = safe_path(stage.path(), install["filePath"].toString());
      const auto target = safe_path(root_, "libraries/" + maven_path(install["path"].toString()));
      QDir().mkpath(QFileInfo(target).absolutePath());
      if (!QFileInfo::exists(target) && !QFile::copy(embedded, target))
        throw std::runtime_error(
            QCoreApplication::translate("Bugg", "无法提取 Forge 核心").toStdString());
    }
  } else if (loader != "vanilla" && loader != "minecraft" && loader != "原版")
    throw std::runtime_error(QCoreApplication::translate("Bugg", "未知加载器").toStdString());
  metadata["id"] = id;
  if (update) {
    if (original_jar.isUndefined())
      metadata.remove("jar");
    else
      metadata["jar"] = original_jar;
  } else {
    metadata["jar"] = version;
  }
  auto own = metadata["bugg"].toObject();
  own["version"] = version;
  own["loader"] = loader;
  own["loaderVersion"] = loader_version;
  metadata["bugg"] = own;
  if (update)
    fetch_libraries(metadata["libraries"].toArray());
  else
    prepare_files(metadata, id);
  if (!profile.isEmpty()) {
    const auto java = ensure_java(metadata);
    fetch_libraries(profile["libraries"].toArray());
    run_processors(profile, installer, stage.path(), java);
  }
  if (!update && profile.isEmpty()) ensure_java(metadata);
  // 最终输出校验，生成库无 URL 时也必须确实存在。
  validate_libraries(metadata);
  check_cancelled(cancelled_);
  write_json(final, metadata);
  report(1, QCoreApplication::translate("Bugg", "安装完成"));
  return id;
}
LaunchCommand GameOperations::prepare(const QString& instance_id, int memory_mb,
                                      const GameIdentity& identity,
                                      const QVariantMap& contributions) {
  auto metadata = load_version(instance_id);
  if (contributions.contains("roomGame")) {
    const auto checked = check_room(
        instance_id, QJsonObject::fromVariantMap(contributions.value("roomGame").toMap()));
    if (!checked.value("compatible").toBool())
      throw std::runtime_error((QCoreApplication::translate("Bugg", "房间配置已改变，请重新同步") +
                                " · " + checked.value("detail").toString())
                                   .toStdString());
  }
  prepare_files(metadata, instance_id);
  validate_libraries(metadata);
  const auto java = ensure_java(metadata, contributions.value("javaPath").toString());
  check_cancelled(cancelled_);
  apply_game_options(root_, instance_id, metadata, contributions);
  return build_launch_command(metadata, root_, instance_id, java, memory_mb, identity,
                              contributions);
}
}  // namespace bugg
