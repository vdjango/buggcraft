#include "modules/launch/domain/minecraft_metadata.h"

#include <QCoreApplication>
#include <QDir>
#include <QFileInfo>
#include <QProcess>
#include <QRegularExpression>
#include <QSet>
#include <QSysInfo>
#include <QUrl>
#include <stdexcept>

#include "platform/files/game_files.h"

namespace bugg {
QString minecraft_os() {
#if defined(Q_OS_WIN)
  return "windows";
#elif defined(Q_OS_MACOS)
  return "osx";
#else
  return "linux";
#endif
}
QString maven_path(const QString& coordinate) {
  const auto parts = coordinate.split('@');
  const auto tokens = parts[0].split(':');
  if (tokens.size() < 3 || tokens.size() > 4)
    throw std::runtime_error(
        QCoreApplication::translate("Bugg", "Maven 依赖坐标无效").toStdString());
  auto group = tokens[0];
  group.replace('.', '/');
  const auto extension = parts.size() > 1 ? parts[1] : "jar";
  return group + '/' + tokens[1] + '/' + tokens[2] + '/' + tokens[1] + '-' + tokens[2] +
         (tokens.size() == 4 ? '-' + tokens[3] : QString()) + '.' + extension;
}
QVariantMap instance_descriptor(const QJsonObject& metadata) {
  const auto own = metadata["bugg"].toObject();
  auto version = own["version"].toString(
      metadata["inheritsFrom"].toString(metadata["jar"].toString(metadata["id"].toString())));
  auto loader = own["loader"].toString().toLower();
  auto loader_version = own["loaderVersion"].toString();
  if (loader.isEmpty() || loader == "vanilla" || loader == "minecraft") {
    loader = "vanilla";
    const QMap<QString, QString> coordinates{{"net.minecraftforge:forge", "forge"},
                                             {"net.neoforged:neoforge", "neoforge"},
                                             {"net.neoforged:forge", "neoforge"},
                                             {"net.fabricmc:fabric-loader", "fabric"},
                                             {"org.quiltmc:quilt-loader", "quilt"}};
    for (const auto& value : metadata["libraries"].toArray()) {
      const auto coordinate = value.toObject()["name"].toString();
      const auto candidate = coordinates.value(coordinate.section(':', 0, 1));
      if (candidate.isEmpty()) continue;
      loader = candidate;
      loader_version = coordinate.section(':', 2, 2).section('@', 0, 0);
      if ((loader == "forge" || loader == "neoforge") && loader_version.contains('-')) {
        if (!own.contains("version") && !metadata.contains("inheritsFrom") &&
            !metadata.contains("jar"))
          version = loader_version.section('-', 0, 0);
        loader_version = loader_version.section('-', 1);
      }
      break;
    }
  }
  // Some complete Forge client profiles omit the aggregate forge coordinate.
  // Their explicit FML arguments still identify the game and loader versions.
  const auto game_arguments = metadata["arguments"].toObject()["game"].toArray();
  QString fml_game, fml_forge;
  for (int i = 0; i + 1 < game_arguments.size(); ++i) {
    if (game_arguments[i] == "--fml.mcVersion") fml_game = game_arguments[i + 1].toString();
    if (game_arguments[i] == "--fml.forgeVersion") fml_forge = game_arguments[i + 1].toString();
  }
  if (!fml_forge.isEmpty() && loader == "vanilla") {
    loader = "forge";
    loader_version = fml_forge;
  }
  if (!own.contains("version") && !fml_game.isEmpty()) version = fml_game;
  const QMap<QString, QString> names{{"vanilla", "Minecraft"},
                                     {"forge", "Forge"},
                                     {"neoforge", "NeoForge"},
                                     {"fabric", "Fabric"},
                                     {"quilt", "Quilt"}};
  return {{"version", version},
          {"loader", names.value(loader, loader)},
          {"loaderVersion", loader_version}};
}
bool rules_allow(const QJsonArray& rules, const QVariantMap& features) {
  bool allowed = rules.isEmpty();
  for (const auto& value : rules) {
    const auto rule = value.toObject();
    const auto os = rule["os"].toObject();
    if (os.contains("name") && os["name"].toString() != minecraft_os()) continue;
    if (os.contains("arch") && os["arch"].toString() != QSysInfo::currentCpuArchitecture() &&
        !(os["arch"] == "x86" && QSysInfo::currentCpuArchitecture() == "i386"))
      continue;
    if (os.contains("version") &&
        !QRegularExpression(os["version"].toString()).match(QSysInfo::kernelVersion()).hasMatch())
      continue;
    bool matches = true;
    const auto required = rule["features"].toObject();
    for (auto it = required.begin(); it != required.end(); ++it)
      matches &= features.value(it.key(), false).toBool() == it.value().toBool();
    if (matches) allowed = rule["action"] == "allow";
  }
  return allowed;
}
QJsonObject merge_metadata(const QJsonObject& parent, const QJsonObject& child) {
  auto result = parent;
  for (auto it = child.begin(); it != child.end(); ++it) {
    if (it.key() == "libraries") {
      auto libraries = result["libraries"].toArray();
      for (const auto& lib : it.value().toArray()) libraries.append(lib);
      result[it.key()] = effective_libraries(libraries);
    } else if (it.key() == "arguments") {
      auto arguments = result["arguments"].toObject();
      const auto addition = it.value().toObject();
      for (const auto& key : {"jvm", "game"}) {
        auto list = arguments[key].toArray();
        for (const auto& argument : addition[key].toArray()) list.append(argument);
        arguments[key] = list;
      }
      result[it.key()] = arguments;
    } else if (it.key() != "inheritsFrom")
      result[it.key()] = it.value();
  }
  result.remove("inheritsFrom");
  return result;
}
QJsonArray effective_libraries(const QJsonArray& libraries) {
  QJsonArray result;
  QHash<QString, int> positions;
  for (const auto& value : libraries) {
    const auto object = value.toObject();
    if (!rules_allow(object["rules"].toArray())) continue;
    auto tokens = object["name"].toString().split(':');
    if (tokens.size() < 3)
      throw std::runtime_error(
          QCoreApplication::translate("Bugg", "依赖缺少合法 Maven 名称").toStdString());
    // 继承顺序中子版本覆盖父版本；native/classifier 与普通 JAR 是不同依赖。
    const auto key = tokens[0] + ':' + tokens[1] + ':' +
                     (tokens.size() > 3 ? tokens[3] : QString()) + ':' +
                     (object.contains("natives") ? "natives" : "artifact");
    if (positions.contains(key))
      result[positions[key]] = value;
    else {
      positions.insert(key, result.size());
      result.append(value);
    }
  }
  return result;
}
QStringList unique_classpath(const QStringList& paths) {
  QStringList result;
  QSet<QString> seen;
  for (const auto& path : paths) {
    const QFileInfo info(path);
    auto key = info.exists() ? info.canonicalFilePath() : info.absoluteFilePath();
#ifdef Q_OS_WIN
    key = key.toLower();
#endif
    if (!seen.contains(key)) {
      seen.insert(key);
      result.append(QDir::fromNativeSeparators(info.exists() ? info.canonicalFilePath()
                                                             : info.absoluteFilePath()));
    }
  }
  return result;
}
QStringList normalize_arguments(const QStringList& arguments, bool jvm) {
  QList<QStringList> units;
  QStringList keys;
  QHash<QString, int> last;
  const QSet<QString> pairs = {"-cp",           "-classpath",    "--class-path",  "-p",
                               "--module-path", "--add-opens",   "--add-exports", "--add-modules",
                               "--add-reads",   "--patch-module"};
  for (int i = 0; i < arguments.size(); ++i) {
    const auto argument = arguments[i];
    QStringList unit{argument};
    QString key;
    const bool paired = (jvm ? pairs.contains(argument) : argument.startsWith("--")) &&
                        !argument.contains('=') && i + 1 < arguments.size() &&
                        !arguments[i + 1].startsWith("--");
    if (paired) unit.append(arguments[++i]);
    if (jvm && (argument.startsWith("-Xmx") || argument.startsWith("-Xms")))
      key = argument.left(4);
    else if (jvm && argument.startsWith("-D"))
      key = argument.section('=', 0, 0);
    else if (jvm && (argument == "-cp" || argument == "-classpath" || argument == "--class-path")) {
      key = "classpath";
      if (unit.size() == 2)
        unit[1] = unique_classpath(unit[1].split(QDir::listSeparator(), Qt::SkipEmptyParts))
                      .join(QDir::listSeparator());
    } else if (!jvm && argument == "--tweakClass")
      key = unit.join(QChar(0x1f));
    else if (!jvm && argument.startsWith("--"))
      key = argument.section('=', 0, 0);
    else if (jvm && argument.startsWith("--add-") || (jvm && argument.startsWith("--patch-module")))
      key = unit.join(QChar(0x1f));
    // 未知 JVM 项只合并完全相同项；不单独去重参数值。
    else if (jvm && argument.startsWith('-'))
      key = unit.join(QChar(0x1f));
    units.append(unit);
    keys.append(key);
    if (!key.isEmpty()) last[key] = units.size() - 1;
  }
  QStringList result;
  for (int i = 0; i < units.size(); ++i)
    if (keys[i].isEmpty() || last[keys[i]] == i) result.append(units[i]);
  if (jvm && result.contains("ALL-MODULE-PATH")) {
    // Java exposes a resolved module's resources separately from -cp. The
    // same physical ASM JAR in both paths becomes file:/// and file:/ URLs;
    // Fabric's bootstrap correctly rejects the resulting duplicate classes.
    QStringList modules;
    for (int i = 0; i + 1 < result.size(); ++i)
      if (result[i] == "-p" || result[i] == "--module-path")
        modules.append(
            unique_classpath(result[i + 1].split(QDir::listSeparator(), Qt::SkipEmptyParts)));
    for (int i = 0; i + 1 < result.size(); ++i) {
      if (result[i] != "-cp" && result[i] != "-classpath" && result[i] != "--class-path") continue;
      auto paths = unique_classpath(result[i + 1].split(QDir::listSeparator(), Qt::SkipEmptyParts));
      paths.removeIf([&](const QString& path) {
        return std::any_of(modules.begin(), modules.end(), [&](const QString& module) {
#ifdef Q_OS_WIN
          return path.compare(module, Qt::CaseInsensitive) == 0;
#else
          return path == module;
#endif
        });
      });
      result[i + 1] = paths.join(QDir::listSeparator());
    }
  }
  return result;
}
LaunchCommand build_launch_command(const QJsonObject& metadata, const QString& root,
                                   const QString& instance_id, const QString& java, int memory_mb,
                                   const GameIdentity& identity, const QVariantMap& contributions) {
  const auto directory = safe_path(root, "versions/" + instance_id);
  const auto natives = safe_path(directory, "natives");
  QStringList classpath;
  for (const auto& value : effective_libraries(metadata["libraries"].toArray())) {
    const auto lib = value.toObject();
    const auto downloads = lib["downloads"].toObject();
    const auto artifact = downloads["artifact"].toObject();
    if (downloads.contains("artifact") || !lib.contains("natives"))
      classpath.append(safe_path(
          root, "libraries/" + artifact["path"].toString(maven_path(lib["name"].toString()))));
  }
  const auto jar_id = metadata["jar"].toString(metadata["id"].toString());
  classpath.append(safe_path(root, "versions/" + jar_id + '/' + jar_id + ".jar"));
  classpath.append(contributions.value("classpath").toStringList());
  classpath = unique_classpath(classpath);
  const auto assets = safe_path(root, "assets");
  const bool fullscreen = contributions.value("fullscreen").toBool();
  const bool window_size = !fullscreen && contributions.contains("resolution");
  // Quick Play 将地址视为普通服务器，无法采用 LAN 入场的离线会话处理。
  // 离线房间仍由 MultiplayerService 广播到游戏的局域网列表，不提交失败的自动入场。
  const auto server = contributions.value("lanServer").toBool() && identity.kind == "offline"
                          ? QString{}
                          : contributions.value("server").toString();
  const QMap<QString, QString> replacements = {
      {"auth_player_name", identity.name},
      {"auth_uuid", identity.uuid},
      {"auth_access_token", identity.access_token.isEmpty() ? "0" : identity.access_token},
      {"auth_session", identity.access_token.isEmpty() ? "0" : identity.access_token},
      {"user_type", identity.kind == "microsoft" ? "msa" : "legacy"},
      {"user_properties", "{}"},
      {"version_name", instance_id},
      {"version_type", metadata["type"].toString("release")},
      {"game_directory", directory},
      {"assets_root", assets},
      {"game_assets", metadata["assets"] == "legacy" ? assets + "/virtual/legacy" : assets},
      {"assets_index_name",
       metadata["assetIndex"].toObject()["id"].toString(metadata["assets"].toString())},
      {"natives_directory", natives},
      {"launcher_name", "Bugg"},
      {"launcher_version", BUGG_VERSION},
      {"classpath", classpath.join(QDir::listSeparator())},
      {"classpath_separator", QString(QDir::listSeparator())},
      {"library_directory", safe_path(root, "libraries")},
      {"clientid", identity.client_id},
      {"auth_xuid", identity.xuid},
      {"quickPlayMultiplayer", server},
      {"resolution_width",
       contributions.value("resolution", "1280x720").toString().section('x', 0, 0)},
      {"resolution_height",
       contributions.value("resolution", "1280x720").toString().section('x', 1, 1)}};
  const auto expand = [&](QString argument) {
    // BootstrapLauncher 的忽略列表指向实际原版核心文件名；实例名可能已自定义。
    if (argument.startsWith("-DignoreList="))
      argument.replace("${version_name}.jar", jar_id + ".jar");
    for (auto it = replacements.begin(); it != replacements.end(); ++it)
      argument.replace("${" + it.key() + '}', it.value());
    if (argument.contains("${"))
      throw std::runtime_error(
          QCoreApplication::translate("Bugg", "启动参数包含尚未支持的占位符").toStdString());
    return argument;
  };
  const auto collect = [&](const QJsonArray& values) {
    QStringList result;
    for (const auto& value : values) {
      if (value.isString())
        result.append(expand(value.toString()));
      else {
        const auto object = value.toObject();
        if (!rules_allow(object["rules"].toArray(),
                         {{"has_custom_resolution", window_size},
                          {"is_quick_play_multiplayer", !server.isEmpty()}}))
          continue;
        if (object["value"].isString())
          result.append(expand(object["value"].toString()));
        else
          for (const auto& item : object["value"].toArray()) result.append(expand(item.toString()));
      }
    }
    return result;
  };
  const auto arguments = metadata["arguments"].toObject();
  auto jvm = collect(arguments["jvm"].toArray());
  if (jvm.isEmpty())
    jvm = {"-Djava.library.path=" + natives, "-cp", classpath.join(QDir::listSeparator())};
  const auto logging = metadata["logging"].toObject()["client"].toObject();
  if (!logging.isEmpty()) {
    auto argument = logging["argument"].toString();
    const auto path =
        safe_path(root, "assets/log_configs/" + logging["file"].toObject()["id"].toString());
    argument.replace("${path}", QUrl::fromLocalFile(path).toString(QUrl::FullyEncoded));
    jvm.append(argument);
  }
  jvm.append(QString("-Xmx%1M").arg(memory_mb));
  jvm.append(contributions.value("jvm").toStringList());
  auto game = collect(arguments["game"].toArray());
  if (metadata.contains("minecraftArguments")) {
    game.clear();
    for (const auto& value : QProcess::splitCommand(metadata["minecraftArguments"].toString()))
      game.append(expand(value));
  }
  game.append(contributions.value("game").toStringList());
  if (!server.isEmpty() && !game.contains("--quickPlayMultiplayer"))
    game.append({"--server", server.section(':', 0, 0), "--port", server.section(':', -1)});
  if (fullscreen) {
    game.append("--fullscreen");
  } else if (window_size) {
    game.append({"--width", replacements.value("resolution_width"), "--height",
                 replacements.value("resolution_height")});
  }
  const auto main_class = metadata["mainClass"].toString();
  if (main_class.isEmpty())
    throw std::runtime_error(QCoreApplication::translate("Bugg", "版本缺少入口类").toStdString());
  // 所有版本、加载器、房间、用户贡献均已收齐；去重只在此最终边界执行。
  auto final = normalize_arguments(jvm, true);
  final.append(main_class);
  final.append(normalize_arguments(game, false));
  return {java, final, directory, safe_path(directory, "logs/launcher-game.log")};
}
}  // namespace bugg
