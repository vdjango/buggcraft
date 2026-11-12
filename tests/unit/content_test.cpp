#include <QBuffer>
#include <QCryptographicHash>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QQmlApplicationEngine>
#include <QQmlComponent>
#include <QQmlContext>
#include <QQmlEngine>
#include <QQuickItem>
#include <QQuickStyle>
#include <QQuickWindow>
#include <QSignalSpy>
#include <QTcpServer>
#include <QTcpSocket>
#include <QTemporaryDir>
#include <QTest>
#include <QTimer>
#include <QUrlQuery>
#include <QtConcurrent/QtConcurrentRun>

#include "contracts/dependency_decision.h"
#include "language_asset_server.h"
#include "modules/account/application/microsoft_account.h"
#include "modules/catalog/application/content_catalog_service.h"
#include "modules/catalog/infrastructure/content_description.h"
#include "modules/catalog/infrastructure/content_provider.h"
#include "modules/catalog/ui/content_catalog_session.h"
#include "modules/game_install/application/game_operations.h"
#include "modules/game_install/application/game_runtime.h"
#include "modules/game_install/application/modpack_plan.h"
#include "modules/game_install/ui/install_catalog_session.h"
#include "modules/settings/application/language_service.h"
#include "modules/settings/ui/source_settings.h"
#include "modules/update/application/launcher_update_service.h"
#include "platform/files/game_files.h"
#include "shell/desktop_environment.h"

namespace bugg {
namespace {
class ContentProbe : public ContentCatalogPort {
 public:
  QMap<quint64, QVariantMap> queries;
  QList<quint64> cancelled;
  void query(quint64 id, const QVariantMap& value) override { queries[id] = value; }
  void cancel(quint64 id) override { cancelled.append(id); }
  void answer(quint64 id, const QVariantMap& value) { emit finished(id, value); }
};
class ContentGameCatalogProbe : public GameCatalogPort {
 public:
  QSet<quint64> cancelled;
  void query(quint64 id, const CatalogQuery& query) override {
    QTimer::singleShot(0, this, [this, id, query] {
      if (cancelled.contains(id)) return;
      emit finished(id, query.kind == "minecraft"
                            ? CatalogResult{{{"26.3"}, {"1.21.1"}}, "26.3", "fixture", {}}
                            : CatalogResult{{{"0.16.0"}}, "0.16.0", "fixture", {}});
    });
  }
  void cancel(quint64 id) override { cancelled.insert(id); }
  void select_sources(const QStringList&, const QUrl& = {}) override {}
};
// Real loopback HTTP and product streaming/hash code, with deterministic latency.
QByteArray content_fixture_payload(QByteArray bytes, const QString& filename) {
  if (filename.startsWith("dependency-")) {
    const auto identity = filename.toUtf8();
    bytes.replace(0, qMin(bytes.size(), identity.size()), identity);
  }
  return bytes;
}
class ContentFilesServer : public QTcpServer {
 public:
  QMap<QString, QByteArray> files;
  QByteArray payload = QByteArray(256 * 1024, 'm');
  QByteArray profile;
  int active = 0, peak = 0, requests = 0;
  QString failing;
  int initial_delay_ms = 90;
  int chunk_delay_ms = 45;
  ContentFilesServer() {
    listen(QHostAddress::LocalHost);
    connect(this, &QTcpServer::newConnection, this, [this] {
      while (hasPendingConnections()) {
        auto* socket = nextPendingConnection();
        connect(socket, &QTcpSocket::disconnected, socket, [this, socket] {
          if (socket->property("handled").toBool()) --active;
          socket->deleteLater();
        });
        connect(socket, &QTcpSocket::readyRead, socket, [this, socket] {
          const auto request = socket->property("request").toByteArray() + socket->readAll();
          socket->setProperty("request", request);
          if (!request.contains("\r\n\r\n") || socket->property("handled").toBool()) return;
          socket->setProperty("handled", true);
          ++requests;
          peak = qMax(peak, ++active);
          const bool fail = !failing.isEmpty() && request.contains(failing.toUtf8());
          const auto filename =
              QFileInfo(QUrl(QString::fromUtf8(request.split(' ').value(1))).path()).fileName();
          const auto bytes = files.contains(filename) ? files.value(filename)
                             : filename == "json" && !profile.isEmpty()
                                 ? profile
                                 : content_fixture_payload(payload, filename);
          auto* timer = new QTimer(socket);
          connect(timer, &QTimer::timeout, socket, [this, bytes, socket, timer, fail] {
            int offset = socket->property("offset").toInt();
            if (!offset) {
              if (fail) {
                socket->write(
                    "HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n");
                timer->stop();
                socket->disconnectFromHost();
                return;
              }
              socket->write("HTTP/1.1 200 OK\r\nContent-Length: " +
                            QByteArray::number(bytes.size()) + "\r\nConnection: close\r\n\r\n");
            }
            const auto count = qMin(64 * 1024, int(bytes.size()) - offset);
            socket->write(bytes.constData() + offset, count);
            offset += count;
            socket->setProperty("offset", offset);
            if (offset == bytes.size()) {
              timer->stop();
              socket->disconnectFromHost();
            } else
              timer->setInterval(chunk_delay_ms);
          });
          timer->start(initial_delay_ms);
        });
      }
    });
  }
};
class ContentFilesHttp : public HttpClient {
 public:
  explicit ContentFilesHttp(quint16 port) : port_(port) {}
  quint64 request(const HttpRequest& original) override {
    auto local = original;
    local.url = QUrl("http://127.0.0.1:" + QString::number(port_) + original.url.path());
    return HttpClient::request(local);
  }

 private:
  quint16 port_;
};
class ContentServer : public QTcpServer {
 public:
  QList<QUrl> requests;
  bool empty = false;
  bool broken = false;
  bool conflicting = false;
  bool missing_dependency = false;
  bool real_categories = false;
  int delay = 0;
  int total = 40;
  QString kind = "mod";
  QString shader_loader = "fabric";
  QString game_version = "1.21.1";
  QJsonArray compatibility_rules;
  QHash<QString, QJsonValue> responses;
  QString cf_core_project;
  QSet<QString> unavailable_projects;
  bool no_shader_core = false;
  QString shader_hash = QString(40, 'a');
  QString translation_state = "ready";
  QJsonObject translation_payload;
  QHash<QString, QByteArray> artifacts;
  QJsonObject update_feed;
  QByteArray update_archive;
  int translation_sessions = 0, translation_ensures = 0;
  QJsonObject project(bool mr, QString id = "root") const {
    const auto picture = "http://127.0.0.1:" + QString::number(serverPort()) + "/picture.webp";
    if (mr)
      return {{"id", id},
              {"project_id", id},
              {"project_type", id == "iris" || id == "oculus" ? "mod" : kind},
              {"title", "Sodium"},
              {"description", "客户端渲染优化，适用于当前游戏版本。"},
              {"body", "# 更流畅的方块世界\n\n![游戏截图](" + picture +
                           ")\n\n## 项目介绍\n\n**Sodium** 为 Minecraft 提供渲染优化。\n\n- "
                           "提升渲染性能\n- 保留原版视觉\n\n## "
                           "使用方式\n\n请选择与游戏版本和加载器匹配的文件。\n\n[查看说明](https://"
                           "modrinth.com/mod/sodium)"},
              {"author", "CaffeineMC"}};
    return {
        {"id", 100},
        {"gameId", 432},
        {"classId",
         QMap<QString, int>{{"mod", 6}, {"resourcepack", 12}, {"shader", 6552}, {"modpack", 4471}}
             .value(kind)},
        {"name", "Sodium"},
        {"summary", "客户端渲染优化，适用于当前游戏版本。"},
        {"categories", QJsonArray{QJsonObject{{"id", real_categories ? 407 : 10}}}}};
  }
  QJsonObject version(bool mr, QString id = "v1", QString project = "root") const {
    const bool core = project == "iris" || project == "oculus";
    const QString suffix = kind == "mod" || core ? ".jar" : kind == "modpack" ? ".mrpack" : ".zip";
    if (mr)
      return {
          {"id", id},
          {"project_id", project},
          {"name", "1.0 · Minecraft 1.21.1"},
          {"game_versions", QJsonArray{game_version}},
          {"loaders", QJsonArray{core               ? shader_loader
                                 : kind == "shader" ? "iris"
                                                    : "fabric"}},
          {"dependencies",
           project == "root" && kind == "mod"
               ? QJsonArray{QJsonObject{{"project_id", conflicting ? "root" : "dep"},
                                        {"version_id", conflicting ? "v2" : "vdep"},
                                        {"dependency_type", "required"}},
                            QJsonObject{{"project_id", "optional"},
                                        {"dependency_type", "optional"}}}
               : QJsonArray{}},
          {"files", QJsonArray{QJsonObject{
                        {"filename", project + suffix},
                        {"url", "https://cdn.modrinth.com/data/test/" + project + suffix},
                        {"size", 7},
                        {"hashes", QJsonObject{{"sha1", core ? shader_hash : QString(40, 'a')}}},
                        {"primary", true}}}}};
    return {{"id", 200},
            {"modId", 100},
            {"displayName", "1.0 · Minecraft 1.21.1"},
            {"fileName", "root" + suffix},
            {"gameVersions", QJsonArray{game_version, kind == "shader" ? "Iris" : "Fabric"}},
            {"fileLength", 7},
            {"isAvailable", true},
            {"hashes", QJsonArray{QJsonObject{{"algo", 1}, {"value", QString(40, 'a')}}}}};
  }
  ContentServer() {
    listen(QHostAddress::LocalHost);
    connect(this, &QTcpServer::newConnection, this, [this] {
      while (hasPendingConnections()) {
        auto* socket = nextPendingConnection();
        connect(socket, &QTcpSocket::disconnected, socket, &QObject::deleteLater);
        connect(socket, &QTcpSocket::readyRead, socket, [this, socket] {
          auto bytes = socket->property("request").toByteArray() + socket->readAll();
          socket->setProperty("request", bytes);
          if (!bytes.contains("\r\n\r\n") || socket->property("handled").toBool()) return;
          const auto head_end = bytes.indexOf("\r\n\r\n") + 4;
          const auto length = QRegularExpression("Content-Length: ([0-9]+)",
                                                 QRegularExpression::CaseInsensitiveOption)
                                  .match(QString::fromLatin1(bytes.left(head_end)))
                                  .captured(1)
                                  .toInt();
          if (bytes.size() - head_end < length) return;
          socket->setProperty("handled", true);
          const QUrl url("http://localhost" + QString::fromLatin1(bytes.split(' ').value(1)));
          requests.append(url);
          const bool mr = url.path().startsWith("/mr") || url.path().contains("/modrinth/");
          QJsonValue response;
          const auto path = url.path().startsWith("/v1/catalog/")
                                ? (mr ? "/mr" : "/cf") + url.path().mid(url.path().indexOf('/', 12))
                                : url.path();
          if (path.startsWith("/api/launcher/assets/")) {
            socket->write("HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Length: " +
                          QByteArray::number(update_archive.size()) + "\r\n\r\n" + update_archive);
            socket->disconnectFromHost();
            return;
          }
          if (responses.contains(path)) {
            response = responses.value(path);
          } else if (path == "/api/launcher/update") {
            response = update_feed;
          } else if (path == "/picture.webp") {
            QFile picture(QFINDTESTDATA("../../qml/Bugg/DesignSystem/assets/home-siege-1.webp"));
            picture.open(QIODevice::ReadOnly);
            const auto body = picture.readAll();
            socket->write(
                "HTTP/1.1 200 OK\r\nContent-Type: image/webp\r\nConnection: "
                "close\r\nContent-Length: " +
                QByteArray::number(body.size()) + "\r\n\r\n" + body);
            socket->disconnectFromHost();
            return;
          } else if (path == "/v1/sessions/anonymous") {
            ++translation_sessions;
            response = QJsonObject{{"access_token", "fixture-anonymous"}, {"expires_in", 3600}};
          } else if (path == "/v1/translations:ensure") {
            ++translation_ensures;
            response = QJsonObject{{"accepted", true}};
          } else if (path == "/v1/translations:resolve") {
            translation_payload = QJsonDocument::fromJson(bytes.mid(head_end)).object();
            QJsonArray results;
            for (const auto& value : translation_payload["items"].toArray()) {
              const auto expected = value.toObject();
              QJsonArray fields;
              for (const auto& value : expected["fields"].toArray()) {
                const auto field = value.toObject();
                const auto name = field["field"].toString();
                QJsonObject translated{
                    {"format", name == "body" ? "markdown" : "plain"},
                    {"text", name == "body" ? "# 中文介绍\n\n这是经过匹配的中文图文介绍。"
                                            : "中文简介：提升游戏体验"}};
                if (name == "body") {
                  auto artifact = translated;
                  for (const auto& key : {"resource"}) artifact[key] = expected[key];
                  artifact["field"] = name;
                  artifact["source_hash"] = field["source_hash"];
                  artifact["target_language"] = "zh-Hans";
                  artifact["profile"] = "minecraft-v1";
                  const auto raw = QJsonDocument(artifact).toJson(QJsonDocument::Compact);
                  const auto digest = QString::fromLatin1(
                      QCryptographicHash::hash(raw, QCryptographicHash::Sha256).toHex());
                  artifacts[digest] = translation_state == "corrupt" ? raw + " " : raw;
                  translated.remove("text");
                  translated["artifact"] = QJsonObject{{"artifact_sha256", digest},
                                                       {"url", "https://invalid.example/ignored"}};
                }
                fields.append(
                    QJsonObject{{"field", name},
                                {"requested_source_hash", translation_state == "wrongHash"
                                                              ? QJsonValue("sha256:wrong")
                                                              : field["source_hash"]},
                                {"state", (translation_state == "pending" ||
                                           (translation_state == "summaryOnly" && name == "body"))
                                              ? "missing"
                                          : translation_state == "failed" ? "failed"
                                                                          : "ready"},
                                {"matches_request", true},
                                {"is_current", translation_state != "stale"},
                                {"translation", translated}});
              }
              auto result = expected;
              result["fields"] = fields;
              results.append(result);
            }
            response = QJsonObject{{"results", results}};
          } else if (path.startsWith("/v1/artifacts/")) {
            const auto raw = artifacts.value(path.section('/', -1));
            socket->write("HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Length: " +
                          QByteArray::number(raw.size()) + "\r\n\r\n" + raw);
            socket->disconnectFromHost();
            return;
          } else if (path.endsWith("search")) {
            QJsonArray items;
            if (!empty)
              for (int i = 0; i < 20; ++i) {
                auto item = project(mr);
                items.append(item);
              }
            response = QJsonObject{{mr ? "hits" : "data", items},
                                   {"total_hits", empty ? 0 : total},
                                   {"pagination", QJsonObject{{"totalCount", empty ? 0 : total}}}};
          } else if (path.endsWith("/category") || path.endsWith("/categories")) {
            QJsonArray categories;
            for (const auto& type : {"mod", "resourcepack", "shader", "modpack"})
              categories.append(QJsonObject{
                  {"id", 10},
                  {"classId",
                   QMap<QString, int>{
                       {"mod", 6}, {"resourcepack", 12}, {"shader", 6552}, {"modpack", 4471}}
                       .value(type)},
                  {"project_type", type},
                  {"name", "optimization"},
                  {"slug", "optimization"}});
            if (!mr && real_categories) {
              QFile file(QFINDTESTDATA("../fixtures/content/curseforge-categories.json"));
              file.open(QIODevice::ReadOnly);
              categories = QJsonDocument::fromJson(file.readAll()).array();
            }
            response = mr ? QJsonValue(categories) : QJsonValue(QJsonObject{{"data", categories}});
          } else if (url.path() == "/v1/catalog/shader-runtimes") {
            response = QJsonObject{
                {"schema", "bugg-shader-support-v1"},
                {"compatibilityRules", compatibility_rules},
                {"runtimes",
                 QJsonArray{QJsonObject{{"id", "iris"},
                                        {"name", "Iris Shaders"},
                                        {"publisher", "Modrinth"},
                                        {"projectId", "iris"},
                                        {"curseforgeProjectId", cf_core_project},
                                        {"loaders", QJsonArray{"fabric", "neoforge", "quilt"}},
                                        {"markers", QJsonArray{"net/irisshaders/iris/Iris.class"}}},
                            QJsonObject{{"id", "oculus"},
                                        {"name", "Oculus"},
                                        {"publisher", "Modrinth"},
                                        {"projectId", "oculus"},
                                        {"loaders", QJsonArray{"forge", "neoforge"}},
                                        {"markers", QJsonArray{"net/coderbot/iris/Iris.class"}}}}}};
          } else if (path.contains("/version_file/")) {
            response = version(true, "older-core", "iris");
          } else if (path.endsWith("/description")) {
            response = QJsonObject{
                {"data",
                 "<h1>更流畅的方块世界</h1><p><img src='http://127.0.0.1:" +
                     QString::number(serverPort()) +
                     "/picture.webp'></p><h2>项目介绍</h2><p><b>Sodium</b> 为 Minecraft "
                     "提供渲染优化。</p><ul><li>提升渲染性能</li><li>保留原版视觉</li></ul>"}};
          } else if (path.endsWith("/version") || path.endsWith("/files")) {
            const auto project_id = path.split('/').value(3);
            QJsonArray items{version(mr, project_id == "dep" ? "vdep" : "v1", project_id)};
            if (no_shader_core && (project_id == "iris" || project_id == "oculus")) items = {};
            if (unavailable_projects.contains(project_id)) items = {};
            response = mr ? QJsonValue(items)
                          : QJsonValue(QJsonObject{{"data", items},
                                                   {"pagination", QJsonObject{{"totalCount", 1}}}});
          } else if (path.contains("/version/") || path.contains("/files/")) {
            const bool dep = path.endsWith("vdep");
            const auto item = version(mr,
                                      path.endsWith("v2") ? "v2"
                                      : dep               ? "vdep"
                                                          : "v1",
                                      dep ? "dep" : "root");
            response = mr ? QJsonValue(item) : QJsonValue(QJsonObject{{"data", item}});
          } else {
            const auto item = project(mr, path.split('/').last());
            response = mr ? QJsonValue(item) : QJsonValue(QJsonObject{{"data", item}});
          }
          const auto body = (broken || missing_dependency &&
                                           (path.endsWith("vdep") || path.contains("/project/dep")))
                                ? QByteArray("broken")
                            : response.isArray() ? QJsonDocument(response.toArray()).toJson()
                                                 : QJsonDocument(response.toObject()).toJson();
          QTimer::singleShot(delay, socket, [socket, body] {
            socket->write(
                "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: "
                "close\r\nContent-Length: " +
                QByteArray::number(body.size()) + "\r\n\r\n" + body);
            socket->disconnectFromHost();
          });
        });
      }
    });
  }
  ContentEndpoints endpoints() const {
    const auto base = "http://127.0.0.1:" + QString::number(serverPort());
    return {QUrl(base), QUrl(base + "/cf"), QUrl(base + "/mr"), "test-key"};
  }
};
QVariantMap content_plan(const QString& kind, const QByteArray& bytes) {
  return {
      {"kind", kind},
      {"files",
       QVariantList{QVariantMap{
           {"filename", kind == "mod" ? "sample.jar" : "sample.zip"},
           {"kind", kind},
           {"publisher", "Modrinth"},
           {"projectId", "sample-" + kind},
           {"versionId", "v1"},
           {"title", "测试模组"},
           {"versionName", "1.0"},
           {"gameVersions", QStringList{"1.21.1"}},
           {"loaders", QStringList{"fabric"}},
           {"url", "https://cdn.modrinth.com/data/test/sample.jar"},
           {"size", bytes.size()},
           {"hashes", QVariantMap{{"sha1", QString::fromLatin1(QCryptographicHash::hash(
                                                                   bytes, QCryptographicHash::Sha1)
                                                                   .toHex())}}}}}}};
}
QVariantMap dependency_plan(const QByteArray& payload, int count = 6) {
  auto plan = content_plan("mod", payload);
  auto files = plan.value("files").toList();
  for (int i = 0; i < count; ++i) {
    auto file = files.first().toMap();
    const auto name = "dependency-" + QString::number(i);
    file["projectId"] = name;
    file["title"] = name;
    file["filename"] = name + ".jar";
    const auto bytes = content_fixture_payload(payload, file["filename"].toString());
    file["size"] = bytes.size();
    file["hashes"] = QVariantMap{
        {"sha1",
         QString::fromLatin1(QCryptographicHash::hash(bytes, QCryptographicHash::Sha1).toHex())}};
    file["url"] = "https://cdn.modrinth.com/data/test/" + name + ".jar";
    file["dependency"] = true;
    files.append(file);
  }
  plan["files"] = files;
  return plan;
}
void put(const QString& path, const QByteArray& bytes) {
  QDir().mkpath(QFileInfo(path).absolutePath());
  QFile file(path);
  if (!file.open(QIODevice::WriteOnly) || file.write(bytes) != bytes.size())
    throw std::runtime_error("fixture write");
}
QQuickItem* visual_item(QQuickItem* root, const QString& name) {
  QList<QQuickItem*> pending{root};
  while (!pending.isEmpty()) {
    auto* item = pending.takeLast();
    if (item->objectName() == name && item->isVisible()) return item;
    pending.append(item->childItems());
  }
  return nullptr;
}
}  // namespace
class ContentTest : public QObject {
  Q_OBJECT
 private slots:
  void native_dependency_choices_preserve_original_and_repair_atomically() {
    QTemporaryDir root;
    ContentFilesServer server;
    server.initial_delay_ms = server.chunk_delay_ms = 1;
    const auto cancelled = std::make_shared<std::atomic_bool>(false);
    const auto jar = [&](const QString& name, const QByteArray& metadata) {
      const auto path = root.filePath(name);
      archive_write(path, {}, {{"fabric.mod.json", metadata}}, cancelled, {});
      QFile file(path);
      file.open(QIODevice::ReadOnly);
      server.files[name] = file.readAll();
    };
    jar("alpha.jar",
        R"({"schemaVersion":1,"id":"alpha","version":"1","depends":{"library":">=2 <3"}})");
    jar("library1.jar", R"({"schemaVersion":1,"id":"library","version":"1"})");
    jar("library2.jar", R"({"schemaVersion":1,"id":"library","version":"2"})");
    const auto file = [&](const QString& name, const QString& project) {
      return QVariantMap{
          {"kind", "mod"},
          {"filename", name},
          {"publisher", "Modrinth"},
          {"projectId", project},
          {"versionId", name},
          {"gameVersions", QStringList{"26.3"}},
          {"loaders", QStringList{"fabric"}},
          {"size", server.files[name].size()},
          {"url", "https://cdn.modrinth.com/" + name},
          {"hashes", QVariantMap{{"sha1", QString::fromLatin1(
                                              QCryptographicHash::hash(server.files[name],
                                                                       QCryptographicHash::Sha1)
                                                  .toHex())}}}};
    };
    const auto base = QUrl("http://127.0.0.1:" + QString::number(server.serverPort()));
    write_json(
        root.filePath("versions/check/check.json"),
        {{"id", "check"},
         {"bugg",
          QJsonObject{{"version", "26.3"}, {"loader", "fabric"}, {"loaderVersion", "0.19.0"}}}});
    put(root.filePath("versions/check/saves/own.dat"), "unchanged");
    const auto before = read_json(root.filePath("versions/check/check.json"));
    const QVariantMap plan{
        {"kind", "mod"},
        {"files", QVariantList{file("alpha.jar", "alpha"), file("library1.jar", "library")}}};
    const auto replacement = file("library2.jar", "library");
    const ContentRequest request = [replacement](const QVariantMap& query, const Cancellation&) {
      if (query.value("operation") == "bindings")
        return QVariantMap{{"items", QVariantList{QVariantMap{{"provider", "modrinth"},
                                                              {"project_id", "library"},
                                                              {"mod_id", "library"},
                                                              {"sha256", QString(64, 'a')}}}}};
      if (query.value("operation") == "versions")
        return QVariantMap{{"versions", QVariantList{QVariantMap{{"id", "library2.jar"},
                                                                 {"channel", "release"}}}}};
      return QVariantMap{{"files", QVariantList{replacement}}};
    };
    const auto run = [&](QVariantMap specification) {
      return QtConcurrent::run([=, path = root.path(), port = server.serverPort()] {
        ContentFilesHttp http(port);
        GameOperations operations(
            path, path, {"官方"}, cancelled, [](double, const QString&) {}, 2, &http, base);
        try {
          operations.install_content(specification, request);
          return QVariantMap{{"done", true}};
        } catch (const DependencyDecision& decision) {
          return decision.value();
        } catch (const std::exception& error) {
          return QVariantMap{{"testError", QString::fromUtf8(error.what())}};
        }
      });
    };
    QVariantMap specification{{"id", "check"}, {"plan", plan}, {"replace", true}};
    auto future = run(specification);
    QTRY_VERIFY_WITH_TIMEOUT(future.isFinished(), 30000);
    const auto decision = future.result();
    QVERIFY2(!decision.contains("testError"), qPrintable(decision.value("testError").toString()));
    QVERIFY(!decision.value("fingerprint").toString().isEmpty());
    QVERIFY(!QFileInfo::exists(root.filePath("versions/check/mods/alpha.jar")));
    QCOMPARE(read_json(root.filePath("versions/check/check.json")), before);
    specification["dependencyFingerprint"] = decision.value("fingerprint");
    specification["dependencyChoice"] = "repair";
    future = run(specification);
    QTRY_VERIFY_WITH_TIMEOUT(future.isFinished(), 30000);
    const auto repaired = future.result();
    QVERIFY2(!repaired.contains("testError"), qPrintable(repaired.value("testError").toString()));
    QVERIFY2(repaired.value("done").toBool(),
             qPrintable(QString::fromUtf8(QJsonDocument::fromVariant(repaired).toJson())));
    QVERIFY(QFileInfo::exists(root.filePath("versions/check/mods/alpha.jar")));
    QVERIFY(QFileInfo::exists(root.filePath("versions/check/mods/library2.jar")));
    QVERIFY(!QFileInfo::exists(root.filePath("versions/check/mods/library1.jar")));
    const auto receipt =
        read_json(root.filePath("versions/check/check.json"))["buggDependencyDecision"].toObject();
    QCOMPARE(receipt["choice"].toString(), QString("repair"));
    QCOMPARE(receipt["check"].toObject()["state"].toString(), QString("satisfied_declared"));
    QFile saved(root.filePath("versions/check/saves/own.dat"));
    QVERIFY(saved.open(QIODevice::ReadOnly));
    QCOMPARE(saved.readAll(), QByteArray("unchanged"));
    // A platform omission can be repaired automatically using a parser-backed binding,
    // while the staged JAR still decides whether the dependency version satisfies it.
    write_json(root.filePath("versions/automatic/automatic.json"),
               {{"id", "automatic"}, {"bugg", before["bugg"]}});
    const QVariantMap omitted{{"kind", "mod"}, {"files", QVariantList{file("alpha.jar", "alpha")}}};
    future = run({{"id", "automatic"}, {"plan", omitted}});
    QTRY_VERIFY_WITH_TIMEOUT(future.isFinished(), 30000);
    QVERIFY2(future.result().value("done").toBool(),
             qPrintable(QString::fromUtf8(QJsonDocument::fromVariant(future.result()).toJson())));
    QVERIFY(QFileInfo::exists(root.filePath("versions/automatic/mods/library2.jar")));
  }
  void native_26_3_shader_installation() {
    const auto portable = qEnvironmentVariable("BUGG_TEST_NATIVE_DEPENDENCIES");
    if (portable.isEmpty()) QSKIP("Explicit isolated 26.3 acceptance only");
    QVERIFY(portable.startsWith("D:/BuggBuild/dependency-plan-20261112/"));
    const auto cancelled = std::make_shared<std::atomic_bool>(false);
    const ContentRequest request = [](const QVariantMap& query, const Cancellation& stop) {
      return request_content(query, {"官方"}, ContentEndpoints{}, stop);
    };
    auto future = QtConcurrent::run([=] {
      const auto game = portable + "/.minecraft";
      const auto id = QString("26.3-neoforge-26.3.0.101");
      QVariantMap query{{"operation", "versions"},      {"kind", "shader"},
                        {"publisher", "Modrinth"},      {"projectId", "HVnmMxH1"},
                        {"gameVersion", "26.3"},        {"loader", "neoforge"},
                        {"loaderVersion", "26.3.0.101"}};
      const auto versions = request(query, cancelled).value("versions").toList();
      if (versions.isEmpty()) throw std::runtime_error("no_shader_release");
      query["versionId"] = versions.first().toMap().value("id");
      query["operation"] = "plan";
      const auto plan = request(query, cancelled);
      QVariantMap specification{{"id", id}, {"plan", plan}, {"replace", true}};
      GameOperations operations(
          game, portable, {"官方"}, cancelled, [](double, const QString&) {}, 4, nullptr,
          QUrl("http://127.0.0.1:9"));
      try {
        operations.install_content(specification, request);
      } catch (const DependencyDecision& decision) {
        write_json(portable + "/initial-decision.json",
                   QJsonObject::fromVariantMap(decision.value()));
        specification["dependencyChoice"] = "repair";
        specification["dependencyFingerprint"] = decision.value().value("fingerprint");
        operations.install_content(specification, request);
      }
      const auto metadata = operations.load_version(id);
      write_json(portable + "/native-install-receipt.json",
                 metadata["buggDependencyDecision"].toObject());
      write_json(portable + "/native-plan.json", QJsonObject::fromVariantMap(plan));
      return metadata;
    });
    QTRY_VERIFY_WITH_TIMEOUT(future.isFinished(), 300000);
    const auto receipt = future.result()["buggDependencyDecision"].toObject();
    QCOMPARE(receipt["choice"].toString(), QString("repair"));
    QCOMPARE(receipt["check"].toObject()["state"].toString(), QString("satisfied_declared"));
    QVERIFY(!receipt["changes"].toArray().isEmpty());
  }
  void launcher_update_download_verifies_native_bundle() {
    QTemporaryDir root;
    ContentServer server;
    HttpClient http;
    const auto endpoint =
        QUrl("http://127.0.0.1:" + QString::number(server.serverPort()) + "/api/launcher/update");
    const auto executable = QFileInfo(QCoreApplication::applicationFilePath()).fileName();
    const auto archive = root.filePath("fixture.zip");
    const auto cancelled = std::make_shared<std::atomic_bool>(false);
    archive_write(archive, {},
                  {{"bugg-update.json",
                    QJsonDocument(QJsonObject{{"format", 1},
                                              {"version", "2.0.2"},
                                              {"platform", LauncherUpdateService::platform_id()}})
                        .toJson()},
                   {executable, "replacement"}},
                  cancelled, {});
    QFile file(archive);
    QVERIFY(file.open(QIODevice::ReadOnly));
    server.update_archive = file.readAll();
    QJsonObject asset{
        {"url", endpoint.resolved(QUrl("/api/launcher/assets/2.0.2/Bugg-native.zip")).toString()},
        {"size", server.update_archive.size()},
        {"sha256",
         QString::fromLatin1(
             QCryptographicHash::hash(server.update_archive, QCryptographicHash::Sha256).toHex())}};
    server.update_feed = {{"update_available", true}, {"version", "2.0.2"}, {"asset", asset}};
    LauncherUpdateService updates(&http, root.filePath("cache"), nullptr, endpoint);
    updates.check();
    QTRY_COMPARE(updates.status().value("state").toString(), "available");
    updates.download();
    updates.download();
    QTRY_VERIFY_WITH_TIMEOUT(!updates.busy(), 15000);
    QCOMPARE(updates.status().value("state").toString(), "ready");
    QCOMPARE(QUrlQuery(server.requests.first()).queryItemValue("runtime"), "cpp");
    QCOMPARE(std::count_if(server.requests.cbegin(), server.requests.cend(),
                           [](const QUrl& url) { return url.path().contains("/assets/"); }),
             1);
    const auto folder = root.filePath("cache/updates/" + asset["sha256"].toString());
    QVERIFY(QFileInfo::exists(folder + "/payload/" + executable));
    QVERIFY(QFileInfo::exists(folder + "/helper/" + executable));
    QVERIFY(QFileInfo::exists(folder + "/install.json"));
    updates.shutdown();
    asset["sha256"] = QString(64, 'a');
    server.update_feed["asset"] = asset;
    LauncherUpdateService corrupt(&http, root.filePath("other-cache"), nullptr, endpoint);
    corrupt.check();
    QTRY_COMPARE(corrupt.status().value("state").toString(), "available");
    corrupt.download();
    QTRY_VERIFY_WITH_TIMEOUT(!corrupt.busy(), 15000);
    QCOMPARE(corrupt.status().value("state").toString(), "error");
    QVERIFY(!QFileInfo::exists(
        root.filePath("other-cache/updates/" + QString(64, 'a') + "/package.zip")));
    corrupt.shutdown();
    LauncherUpdateService stopped(&http, root.filePath("cancel-cache"), nullptr, endpoint);
    asset["sha256"] = QString::fromLatin1(
        QCryptographicHash::hash(server.update_archive, QCryptographicHash::Sha256).toHex());
    server.update_feed["asset"] = asset;
    stopped.check();
    QTRY_COMPARE(stopped.status().value("state").toString(), "available");
    stopped.download();
    stopped.shutdown();
    QTRY_VERIFY_WITH_TIMEOUT(!stopped.busy(), 5000);
    QVERIFY(!QFileInfo::exists(
        root.filePath("cancel-cache/updates/" + asset["sha256"].toString() + "/install.json")));
  }
  void initTestCase() { QQuickStyle::setStyle("Basic"); }
  void room_member_page_renders_both_latency_paths_at_player_widths() {
    QQmlEngine engine;
    engine.addImportPath(QCoreApplication::applicationDirPath() + "/qml");
    const auto shots = QCoreApplication::applicationDirPath() + "/verification/room-latency";
    QVERIFY(QDir().mkpath(shots));
    for (const int width : {410, 800}) {
      QQuickWindow window;
      window.setColor(Qt::white);
      window.resize(width, 560);
      window.show();
      QQmlComponent component(&engine);
      component.setData(R"QML(
        import QtQuick
        import Bugg.Pages
        RoomLobbyPage {
          activeView: "members"
          viewportHeight: height
          status: ({room: {
            role: "guest", nodeName: "北京节点", nodeLatencyMs: 9, latencyMs: 23,
            isManager: false, members: [
              {id: "host", name: "房主", online: true, state: "playing"},
              {id: "guest", name: "玩家", online: true, state: "ready",
               node_rtt_ms: 9, host_rtt_ms: 23.25, host_rtt_method: "minecraft-status-ping"}
            ], lobby: {manager_id: "host", provider_id: "host", self_id: "guest"}
          }})
        }
      )QML",
                        QUrl("file:///RoomLatencyCapture.qml"));
      QScopedPointer<QObject> page(component.create());
      QVERIFY2(page, qPrintable(component.errorString()));
      auto* item = qobject_cast<QQuickItem*>(page.data());
      QVERIFY(item);
      item->setParentItem(window.contentItem());
      item->setWidth(width);
      item->setHeight(window.height());
      QTest::qWait(160);
      QStringList text;
      for (auto* object : page->findChildren<QObject*>()) {
        const auto value = object->property("text");
        if (value.isValid()) text.append(value.toString());
      }
      const auto joined = text.join('\n');
      QVERIFY(joined.contains("到节点 9 ms"));
      QVERIFY(joined.contains("到房主 23 ms"));
      QVERIFY(window.grabWindow().save(shots + "/members-" + QString::number(width) + ".png"));
      page.reset();
      window.close();
    }
  }
  void panel_only_topmost_and_fullscreen_entry_setting() {
    QTemporaryDir root;
    HttpClient http;
    MicrosoftAccount account(&http, root.filePath("credentials.bin"));
    GameRuntime runtime(root.path(), root.filePath(".minecraft"), &account);
    runtime.initialize();
    QTRY_VERIFY_WITH_TIMEOUT(!runtime.loading_instances(), 15000);
    DesktopEnvironment desktop;
    QQmlApplicationEngine engine;
    engine.addImportPath(QCoreApplication::applicationDirPath() + "/qml");
    engine.setInitialProperties({{"desktopEnvironment", QVariant::fromValue(&desktop)},
                                 {"gameRuntime", QVariant::fromValue(&runtime)}});
    engine.load(QUrl::fromLocalFile(QFINDTESTDATA("../../qml/Main.qml")));
    QVERIFY(!engine.rootObjects().isEmpty());
    auto* window = qobject_cast<QQuickWindow*>(engine.rootObjects().first());
    auto* controller = window->findChild<QObject*>("windowController");
    auto* dock = window->findChild<QObject*>("edgeDock");
    auto* deck = window->findChild<QObject*>("toolContent");
    auto* tray = window->findChild<QObject*>("panelTrayIcon");
    QVERIFY(controller && dock && deck && tray);
    const auto shots = QCoreApplication::applicationDirPath() + "/verification/download-repair";
    QDir().mkpath(shots);
    for (const auto& theme : {"classic", "panel", "small", "large"}) {
      QVERIFY(QMetaObject::invokeMethod(controller, "selectTheme", Q_ARG(QVariant, theme)));
      QTRY_COMPARE(window->flags().testFlag(Qt::WindowStaysOnTopHint),
                   QByteArray(theme) == "panel");
      const bool panel = QByteArray(theme) == "panel";
      const bool available = tray->property("available").toBool();
      QTRY_COMPARE(window->type(), panel && available ? Qt::Tool : Qt::Window);
      QTRY_COMPARE(tray->property("visible").toBool(), panel && available);
      QTRY_VERIFY(window->isVisible());
      if (QByteArray(theme) == "classic" || QByteArray(theme) == "panel") {
        QVERIFY(QMetaObject::invokeMethod(deck, "openToolPage", Q_ARG(QVariant, 4),
                                          Q_ARG(QVariant, "general")));
        QTRY_COMPARE(deck->property("route").toString(), QString("general"));
        QTest::qWait(1000);
        QVERIFY(visual_item(window->contentItem(), "fullscreenOverlayToggle"));
        QVERIFY(window->grabWindow().save(shots + "/general-" + theme + ".png"));
        QVERIFY(QMetaObject::invokeMethod(deck, "openToolPage", Q_ARG(QVariant, 4),
                                          Q_ARG(QVariant, "logs")));
        QTest::qWait(350);
        auto* button = visual_item(window->contentItem(), "exportDiagnosticsButton");
        QVERIFY(button && button->property("enabled").toBool());
        QVERIFY(window->grabWindow().save(shots + "/logs-" + theme + ".png"));
      }
    }
    QVERIFY(QMetaObject::invokeMethod(controller, "selectTheme", Q_ARG(QVariant, "panel")));
    const auto route = deck->property("route");
    window->hide();
    QVERIFY(QMetaObject::invokeMethod(controller, "restoreFromTray"));
    QTRY_VERIFY(window->isVisible());
    QCOMPARE(deck->property("route"), route);
    window->showMinimized();
    QVERIFY(QMetaObject::invokeMethod(controller, "restoreFromTray"));
    QTRY_VERIFY(window->visibility() != QWindow::Minimized);
    QVERIFY(
        QMetaObject::invokeMethod(dock, "dockNearest", Q_ARG(QVariant, 0), Q_ARG(QVariant, false)));
    QTRY_VERIFY(dock->property("attachment").toInt() != 0);
    QTest::qWait(350);
    QQuickWindow game;
    game.setScreen(window->screen());
    game.setGeometry(window->screen()->geometry());
    game.setFlags(Qt::Window | Qt::FramelessWindowHint | Qt::WindowStaysOnTopHint);
    game.showFullScreen();
    game.raise();
    game.requestActivate();
    QTRY_VERIFY_WITH_TIMEOUT(desktop.fullscreen_foreground(window), 3000);
    QVERIFY(QMetaObject::invokeMethod(dock, "setFolded", Q_ARG(QVariant, true)));
    QTRY_VERIFY(dock->property("folded").toBool());
    QTRY_VERIFY_WITH_TIMEOUT(!window->isVisible(), 3000);
    QVERIFY(runtime.set_preference("showOverlayInFullscreen", true));
    QTRY_VERIFY_WITH_TIMEOUT(window->isVisible(), 3000);
    game.requestActivate();
    QVERIFY(runtime.set_preference("showOverlayInFullscreen", false));
    QTRY_VERIFY_WITH_TIMEOUT(!window->isVisible(), 3000);
    game.showNormal();
    game.setGeometry(120, 120, 640, 400);
    game.raise();
    game.requestActivate();
    QTRY_VERIFY(game.isActive());
    QTRY_VERIFY_WITH_TIMEOUT(!desktop.fullscreen_foreground(window), 3000);
    QVERIFY(QMetaObject::invokeMethod(controller, "updateFullscreenSuppression"));
    QTRY_VERIFY_WITH_TIMEOUT(window->isVisible(), 3000);
    QVERIFY(!desktop.fullscreen_foreground(window));
    game.close();
    window->close();
    runtime.shutdown();
    QTRY_VERIFY(!runtime.busy());
  }
  void installation_progress_wait_and_download_in_both_layouts() {
    // A bounded real HTTP install on the production worker and QML task page.
    // Existing vanilla -> Fabric exercises cached checks, metadata and transfer.
    QTemporaryDir root;
    const auto game = root.filePath("game");
    write_json(
        game + "/versions/Original/Original.json",
        {{"id", "Original"}, {"bugg", QJsonObject{{"version", "1.21.1"}, {"loader", "vanilla"}}}});
    ContentFilesServer server;
    server.initial_delay_ms = 650;
    server.chunk_delay_ms = 110;
    server.payload = QByteArray(2 * 1024 * 1024, 'p');
    const QJsonObject artifact{
        {"path", "net/fabricmc/fabric-loader/1/loader-1.jar"},
        {"url", "https://maven.fabricmc.net/loader-1.jar"},
        {"size", server.payload.size()},
        {"sha1", QString::fromLatin1(
                     QCryptographicHash::hash(server.payload, QCryptographicHash::Sha1).toHex())}};
    server.profile =
        QJsonDocument(
            QJsonObject{{"libraries", QJsonArray{QJsonObject{
                                          {"name", "net.fabricmc:fabric-loader:1"},
                                          {"downloads", QJsonObject{{"artifact", artifact}}}}}}})
            .toJson();
    HttpClient http;
    MicrosoftAccount account(&http, root.filePath("credentials.bin"));
    GameRuntime runtime(root.path(), game, &account);
    runtime.initialize();
    QTRY_VERIFY_WITH_TIMEOUT(!runtime.loading_instances(), 15000);
    runtime.select_sources({"BUGG"},
                           QUrl("http://127.0.0.1:" + QString::number(server.serverPort())));
    DesktopEnvironment desktop;
    QQmlApplicationEngine engine;
    engine.addImportPath(QCoreApplication::applicationDirPath() + "/qml");
    engine.setInitialProperties({{"desktopEnvironment", QVariant::fromValue(&desktop)},
                                 {"gameRuntime", QVariant::fromValue(&runtime)}});
    engine.load(QUrl::fromLocalFile(QFINDTESTDATA("../../qml/Main.qml")));
    QVERIFY(!engine.rootObjects().isEmpty());
    auto* window = qobject_cast<QQuickWindow*>(engine.rootObjects().first());
    auto* controller = window->findChild<QObject*>("windowController");
    auto* deck = window->findChild<QObject*>("toolContent");
    QVERIFY(controller && deck);
    QVERIFY(QMetaObject::invokeMethod(deck, "openToolPage", Q_ARG(QVariant, 0),
                                      Q_ARG(QVariant, "tasks")));
    runtime.install({{"name", "Original"},
                     {"game", "1.21.1"},
                     {"loader", "fabric"},
                     {"loaderVersion", "1"},
                     {"updateExisting", true}});
    const auto task = [&] { return runtime.tasks().value(0).toMap(); };
    QTRY_VERIFY(task().value("detail").toString().contains("获取资源信息"));
    QTRY_VERIFY(task().value("detail").toString().contains("正在连接下载源"));
    QTRY_VERIFY(task().value("detail").toString().contains("等待数据"));
    const auto shots = QCoreApplication::applicationDirPath() + "/verification/window-install";
    QDir().mkpath(shots);
    QVERIFY(window->grabWindow().save(shots + "/waiting-small.png"));
    QTRY_VERIFY(task().value("progress").toDouble() > 0 && task().value("progress").toDouble() < 1);
    for (const auto* theme : {"small", "panel"}) {
      QVERIFY(QMetaObject::invokeMethod(controller, "selectTheme", Q_ARG(QVariant, theme)));
      QTRY_COMPARE(window->width(), QByteArray(theme) == "panel" ? 410 : 800);
      QVERIFY(QTest::qWaitForWindowExposed(window));
      QTest::qWait(250);
      QVERIFY(task().value("detail").toString().contains("/s"));
      QVERIFY(window->grabWindow().save(shots + "/downloading-" + theme + ".png"));
    }
    QTRY_COMPARE_WITH_TIMEOUT(task().value("state").toString(), QString("done"), 15000);
    QTRY_COMPARE(deck->property("route").toString(), QString());
    QCOMPARE(runtime.preferences().value("selectedInstance").toString(), QString("Original"));
    QTest::qWait(400);
    QVERIFY(window->grabWindow().save(shots + "/installed-home-panel.png"));
    QVERIFY(QMetaObject::invokeMethod(deck, "openToolPage", Q_ARG(QVariant, 0),
                                      Q_ARG(QVariant, "tasks")));
    QTest::qWait(250);
    QVERIFY(window->grabWindow().save(shots + "/complete-panel.png"));
    QCOMPARE(server.requests, 2);
    QCOMPARE(file_digest(game + "/libraries/" + artifact["path"].toString(), "sha1",
                         std::make_shared<std::atomic_bool>(false)),
             artifact["sha1"].toString().toLatin1());
    window->close();
    runtime.shutdown();
    QTRY_VERIFY(!runtime.busy());
  }
  void debug_log_filters_complete_events_and_empty_state_in_both_layouts() {
    QTemporaryDir root;
    const auto game = root.filePath("game");
    put(game + "/versions/Debug/logs/launcher-game.log",
        "<log4j:Event logger=\"mixin\" timestamp=\"1794447240000\" level=\"FATAL\" "
        "thread=\"Render thread\"><log4j:Message><![CDATA[Mixin apply for mod sodium failed]]>"
        "</log4j:Message><log4j:Throwable><![CDATA[Caused by: InvalidInjectionException\n"
        " at fixture.Renderer.render(Renderer.java:1)]]></log4j:Throwable></log4j:Event>\n");
    GameRuntime runtime(root.path(), game, nullptr);
    runtime.initialize();
    QTRY_VERIFY(!runtime.loading_instances());
    QVERIFY(runtime.set_preference("selectedInstance", "Debug"));
    DesktopEnvironment desktop;
    QQmlApplicationEngine engine;
    engine.addImportPath(QCoreApplication::applicationDirPath() + "/qml");
    engine.setInitialProperties({{"desktopEnvironment", QVariant::fromValue(&desktop)},
                                 {"gameRuntime", QVariant::fromValue(&runtime)}});
    engine.load(QUrl::fromLocalFile(QFINDTESTDATA("../../qml/Main.qml")));
    QVERIFY(!engine.rootObjects().isEmpty());
    auto* window = qobject_cast<QQuickWindow*>(engine.rootObjects().first());
    auto* controller = window->findChild<QObject*>("windowController");
    auto* deck = window->findChild<QObject*>("toolContent");
    const auto shots = QCoreApplication::applicationDirPath() + "/verification/window-install";
    QDir().mkpath(shots);
    for (const auto* theme : {"small", "panel"}) {
      QVERIFY(QMetaObject::invokeMethod(controller, "selectTheme", Q_ARG(QVariant, theme)));
      QVERIFY(QMetaObject::invokeMethod(deck, "openToolPage", Q_ARG(QVariant, 4),
                                        Q_ARG(QVariant, "logs")));
      QTest::qWait(350);
      auto* level = visual_item(window->contentItem(), "debugLogLevel");
      auto* logger = visual_item(window->contentItem(), "debugLogLogger");
      auto* search = visual_item(window->contentItem(), "debugLogSearch");
      auto* events = visual_item(window->contentItem(), "debugLogEntries");
      QVERIFY(level && logger && search && events);
      search->setProperty("text", "InvalidInjectionException");
      QVERIFY(QMetaObject::invokeMethod(level, "chosen", Q_ARG(QString, "FATAL")));
      QVERIFY(QMetaObject::invokeMethod(logger, "chosen", Q_ARG(QString, "sodium")));
      QTRY_COMPARE(events->property("count").toInt(), 1);
      QTRY_VERIFY(visual_item(window->contentItem(), "debugLogRow"));
      auto* row = visual_item(window->contentItem(), "debugLogRow");
      QVERIFY(QMetaObject::invokeMethod(row, "clicked"));
      auto* detail = visual_item(window->contentItem(), "debugLogDetail");
      QVERIFY(detail && detail->property("text").toString().contains("Renderer.java:1"));
      QTest::qWait(200);
      QVERIFY(window->grabWindow().save(shots + "/logs-fatal-" + theme + ".png"));
      search->setProperty("text", "no-such-log-record");
      QTRY_COMPARE(events->property("count").toInt(), 0);
      QVERIFY(window->grabWindow().save(shots + "/logs-empty-" + theme + ".png"));
    }
    window->close();
    runtime.shutdown();
    QTRY_VERIFY(!runtime.busy());
  }
  void language_page_download_error_retry_and_single_background() {
    QTemporaryDir cache;
    LanguageAssetServer server;
    QVERIFY(server.listen(QHostAddress::LocalHost));
    LanguageService languages(nullptr, cache.path(), server.origin());
    DesktopEnvironment desktop;
    QQmlApplicationEngine engine;
    connect(&languages, &LanguageService::changed, &engine, &QQmlApplicationEngine::retranslate);
    engine.addImportPath(QCoreApplication::applicationDirPath() + "/qml");
    engine.setInitialProperties({{"desktopEnvironment", QVariant::fromValue(&desktop)},
                                 {"languageService", QVariant::fromValue(&languages)}});
    engine.load(QUrl::fromLocalFile(QFINDTESTDATA("../../qml/Main.qml")));
    QVERIFY(!engine.rootObjects().isEmpty());
    auto* window = qobject_cast<QQuickWindow*>(engine.rootObjects().first());
    QVERIFY(window);
    auto* controller = window->findChild<QObject*>("windowController");
    auto* deck = window->findChild<QObject*>("toolContent");
    QVERIFY(controller && deck);
    const auto shots = QCoreApplication::applicationDirPath() + "/verification/languages";
    QDir().mkpath(shots);
    for (const auto& theme : {"classic", "panel"}) {
      QVERIFY(languages.set_code("zh_cn"));
      QVERIFY(QMetaObject::invokeMethod(controller, "selectTheme", Q_ARG(QVariant, theme)));
      QVERIFY(QMetaObject::invokeMethod(deck, "openToolPage", Q_ARG(QVariant, 4),
                                        Q_ARG(QVariant, "language")));
      QTest::qWait(600);
      server.delay_ms = 500;
      server.corrupt = true;
      // A different locale per layout forces a real, uncached download.
      const QString code = QByteArray(theme) == "classic" ? "en_us" : "ja_jp";
      QVERIFY(languages.set_code(code));
      QCOMPARE(languages.status().value("state").toString(), QString("loading"));
      QTest::qWait(100);
      QVERIFY(window->grabWindow().save(shots + "/loading-" + theme + ".png"));
      QTRY_COMPARE(languages.status().value("state").toString(), QString("error"));
      QTest::qWait(100);
      QVERIFY(window->grabWindow().save(shots + "/error-" + theme + ".png"));
      server.corrupt = false;
      server.delay_ms = 0;
      auto* retry = window->findChild<QObject*>("languageDownloadRetry");
      QVERIFY(retry);
      QVERIFY(QMetaObject::invokeMethod(retry, "clicked"));
      QTRY_COMPARE(languages.code(), code);
      QTest::qWait(200);
      QVERIFY(window->grabWindow().save(shots + "/ready-" + theme + ".png"));
      QVERIFY(languages.set_code("zh_cn"));
      QVERIFY(QMetaObject::invokeMethod(deck, "goHome"));
      QTest::qWait(600);
      QVERIFY(window->grabWindow().save(shots + "/home-" + theme + ".png"));
    }
    languages.shutdown();
    QTRY_VERIFY(!languages.busy());
    window->close();
  }
  void descriptions_keep_format_images_and_limits() {
    const auto sized = content_description(
        "<p align='center'><img src='https://example.com/badge.png' width='96' height='24'></p>",
        false, {});
    QCOMPARE(sized.first().toMap().value("width").toDouble(), 96.0);
    QCOMPARE(sized.first().toMap().value("height").toDouble(), 24.0);
    QCOMPARE(sized.first().toMap().value("alignment").toString(), "center");
    for (const bool markdown : {true, false}) {
      const auto blocks = content_description(
          markdown ? "# Heading\n\nBefore **bold**\n\n![World](picture.webp)\n\nAfter "
                     "[link](https://modrinth.com)"
                   : "<h1>Heading</h1><p>Before <b>bold</b></p><img src='picture.webp'><p>After <a "
                     "href='https://modrinth.com'>link</a></p>",
          markdown, QUrl("https://modrinth.com/mod/example/"));
      QCOMPARE(blocks.size(), 3);
      QVERIFY(blocks.first().toMap().value("html").toString().contains("Heading"));
      QCOMPARE(blocks[1].toMap().value("image").toString(),
               "https://modrinth.com/mod/example/picture.webp");
      QVERIFY(blocks.last().toMap().value("html").toString().contains("After"));
      QVERIFY(!blocks.first().toMap().value("html").toString().contains("<img"));
    }
    const auto unsafe = content_description(
        "<p>Safe text</p><img src='file:///private/secret.png'><script>bad()</script>", false, {});
    QVERIFY(!unsafe.isEmpty());
    for (const auto& block : unsafe) QVERIFY(!block.toMap().contains("image"));
    const auto html_markdown = content_description(
        "<center><p>Round <strong>trees</strong></p><img src='picture.webp'>"
        "<details><summary>Supported mods</summary><ul><li>Example</li></ul></details></center>",
        true, QUrl("https://modrinth.com/resourcepack/round-trees/"));
    QCOMPARE(html_markdown.size(), 3);
    QVERIFY(html_markdown.first().toMap().value("html").toString().contains("Round"));
    QCOMPARE(html_markdown[1].toMap().value("image").toString(),
             "https://modrinth.com/resourcepack/round-trees/picture.webp");
    QVERIFY(html_markdown.last().toMap().value("html").toString().contains("Example"));
    const auto badge = content_description(
        "[![Install](https://example.com/button.png)](https://example.com/install)", true, {});
    QCOMPARE(badge.size(), 1);
    QCOMPARE(badge.first().toMap().value("link").toString(), "https://example.com/install");
    QString many;
    for (int i = 0; i < 50; ++i) many += "![world](https://example.com/image.png)\n\n";
    QCOMPARE(content_description(many, true, {}).size(), 32);
  }
  void defaults_overrides_guidance_and_stale_categories() {
    ContentProbe probe;
    ContentCatalogSession session;
    session.set_service(&probe);
    const QVariantMap target{{"id", "game"}, {"version", "1.21.1"}, {"loader", "Fabric"}};
    session.ensure_context(target);
    QCOMPARE(probe.queries.last().value("gameVersion").toString(), "1.21.1");
    QCOMPARE(probe.queries.last().value("loader").toString(), "fabric");
    const auto category = probe.queries.firstKey();
    session.edit("publisher", "Modrinth");
    const auto fresh_category = probe.queries.lastKey();
    probe.answer(category, {{"categories", QVariantList{QVariantMap{{"id", "wrong"}}}}});
    QVERIFY(session.status().value("categories").toList().isEmpty());
    probe.answer(fresh_category,
                 {{"categories", QVariantList{QVariantMap{{"id", "optimization"}}}}});
    QCOMPARE(session.status().value("categories").toList().first().toMap().value("id").toString(),
             "optimization");
    session.edit("gameVersion", "1.20.1");
    session.search();
    probe.answer(probe.queries.lastKey(), {{"items", QVariantList{QVariantMap{{"id", "root"}}}}});
    session.ensure_context(target);
    QCOMPARE(session.status().value("gameVersion").toString(), "1.20.1");
    session.open_project("root", target);
    QCOMPARE(probe.queries.last().value("gameVersion").toString(), "1.20.1");
    probe.answer(probe.queries.lastKey(),
                 {{"versions", QVariantList{QVariantMap{{"id", "v1"},
                                                        {"gameVersions", QStringList{"1.20.1"}},
                                                        {"loaders", QStringList{"fabric"}}}}}});
    QCOMPARE(session.status().value("compatibility").toString(), "incompatible");
    session.match_target();
    QCOMPARE(probe.queries.last().value("gameVersion").toString(), "1.21.1");
    auto vanilla = target;
    vanilla["loader"] = "vanilla";
    session.select_target(vanilla);
    probe.answer(probe.queries.lastKey(),
                 {{"versions", QVariantList{QVariantMap{{"id", "v1"},
                                                        {"gameVersions", QStringList{"1.21.1"}},
                                                        {"loaders", QStringList{"fabric"}}}}}});
    QCOMPARE(session.status().value("compatibility").toString(), "missingLoader");
    QCOMPARE(session.status().value("suggestedLoader").toString(), "fabric");
    QCOMPARE(session.status().value("suggestedGame").toString(), "1.21.1");
  }
  void target_switch_cancels_stale_versions_and_blocks_loading_results() {
    ContentProbe probe;
    ContentCatalogSession session;
    session.set_service(&probe);
    QVariantMap target{{"id", "new"},
                       {"version", "26.3"},
                       {"loader", "NeoForge"},
                       {"loaderVersion", "26.3.0.101"}};
    session.browse("shader", {}, target);
    QCOMPARE(probe.queries.last().value("gameVersion").toString(), "26.3");
    QCOMPARE(probe.queries.last().value("loaderVersion").toString(), "26.3.0.101");
    probe.answer(probe.queries.lastKey(), {{"items", QVariantList{QVariantMap{{"id", "root"}}}}});
    session.edit("query", "other shader");
    const auto before = probe.queries.size();
    session.open_project("root");
    QCOMPARE(probe.queries.size(), before);
    QVERIFY(session.status().value("project").toMap().value("id").toString().isEmpty());
    session.search();
    probe.answer(probe.queries.lastKey(), {{"items", QVariantList{QVariantMap{{"id", "root"}}}}});
    session.open_project("root");
    const auto old_detail = probe.queries.lastKey();
    target["id"] = "old";
    target["version"] = "1.21.11";
    target["loaderVersion"] = "21.11.48";
    session.select_target(target);
    const auto new_detail = probe.queries.lastKey();
    QCOMPARE(probe.queries.last().value("gameVersion").toString(), "1.21.11");
    QCOMPARE(probe.queries.last().value("loaderVersion").toString(), "21.11.48");
    probe.answer(old_detail, {{"versions", QVariantList{QVariantMap{{"id", "wrong"}}}}});
    QVERIFY(session.status().value("versions").toList().isEmpty());
    probe.answer(new_detail,
                 {{"versions", QVariantList{QVariantMap{{"id", "correct"},
                                                        {"gameVersions", QStringList{"1.21.11"}},
                                                        {"loaders", QStringList{"neoforge"}}},
                                            QVariantMap{{"id", "other"},
                                                        {"gameVersions", QStringList{"1.21.11"}},
                                                        {"loaders", QStringList{"neoforge"}}}}}});
    QCOMPARE(session.status().value("version").toMap().value("id").toString(), "correct");
    QCOMPARE(session.status().value("compatibility").toString(), "compatible");
    const auto old_plan = probe.queries.lastKey();
    session.select_version("other");
    const auto new_plan = probe.queries.lastKey();
    QCOMPARE(probe.queries[new_plan].value("versionId").toString(), "other");
    probe.answer(old_plan, {{"files", QVariantList{QVariantMap{{"projectId", "old-dependency"}}}}});
    QVERIFY(session.status().value("plan").toMap().isEmpty());
    probe.answer(new_plan, {{"files", QVariantList{QVariantMap{{"projectId", "new-dependency"}}}}});
    QCOMPARE(session.status()
                 .value("plan")
                 .toMap()
                 .value("files")
                 .toList()
                 .first()
                 .toMap()
                 .value("projectId")
                 .toString(),
             "new-dependency");
    target["loaderVersion"] = "21.11.49";
    session.select_target(target);
    QCOMPARE(probe.queries.last().value("loaderVersion").toString(), "21.11.49");
    QVERIFY(session.status().value("version").toMap().isEmpty());
    session.cancel();
  }
  void translations_use_one_bugg_origin_with_bmclapi_and_validate_artifacts() {
    ContentServer server;
    ContentCatalogService service(nullptr, server.endpoints());
    service.select_sources({"BMCLAPI"});
    QSignalSpy finished(&service, &ContentCatalogPort::finished);
    service.query(1, {{"operation", "detail"},
                      {"publisher", "Modrinth"},
                      {"kind", "mod"},
                      {"projectId", "root"}});
    QTRY_COMPARE(finished.size(), 1);
    const auto project = finished.last()[1].toMap().value("project").toMap();
    QVERIFY(!project.isEmpty());
    const auto original_fields = project.value("translationFields").toList();
    QCOMPARE(original_fields.size(), 2);
    // Fixed cross-language vector generated by the old Python mc-text-v1 protocol.
    QCOMPARE(original_fields.first().toMap().value("source_hash").toString(),
             QString("sha256:9fcb357607bf2c732e9a9313505083747605fe30e74939e3a4517c23ca9f4d98"));
    quint64 id = 1;
    QVariantMap query{{"operation", "translations"},
                      {"publisher", "Modrinth"},
                      {"items", QVariantList{project}},
                      {"detail", true}};
    for (const auto& state :
         {"ready", "summaryOnly", "stale", "wrongHash", "corrupt", "failed", "pending"}) {
      server.translation_state = state;
      query["fixtureRevision"] = state;
      query["ensure"] = QString(state) == "pending";
      service.query(++id, query);
      QTRY_COMPARE(finished.size(), int(id));
      const auto result = finished.last()[1].toMap();
      QVERIFY(!result.contains("_translationToken"));
      QVERIFY(!result.contains("_translationExpires"));
      if (QString(state) == "wrongHash" || QString(state) == "corrupt") {
        QVERIFY(result.contains("error"));
      } else {
        QVERIFY2(!result.contains("error"), qPrintable(result.value("error").toString()));
        const auto values = result.value("translations").toMap().value("root").toMap();
        if (QString(state) == "ready" || QString(state) == "summaryOnly") {
          QCOMPARE(values.value("description").toString(), QString("中文简介：提升游戏体验"));
          QCOMPARE(values.value("body").toList().isEmpty(), QString(state) == "summaryOnly");
        } else {
          QVERIFY(values.isEmpty());
        }
      }
    }
    QCOMPARE(server.translation_sessions, 1);
    QCOMPARE(server.translation_ensures, 1);
    query["ensure"] = true;
    service.query(++id, query);
    QTRY_COMPARE(finished.size(), int(id));
    QCOMPARE(server.translation_ensures, 1);
    query["detail"] = false;
    service.query(++id, query);
    QTRY_COMPARE(finished.size(), int(id));
    QCOMPARE(server.translation_sessions, 1);
    QCOMPARE(server.translation_ensures, 2);
    ContentServer second;
    second.translation_state = "pending";
    service.select_sources({"BMCLAPI"}, second.endpoints().bugg_base);
    service.query(++id, query);
    QTRY_COMPARE(finished.size(), int(id));
    QCOMPARE(second.translation_sessions, 1);
    QCOMPARE(second.translation_ensures, 1);
    QVERIFY(!finished.last()[1].toMap().contains("_translationToken"));
    // Bypass result-cache key only, retaining identical ensure identity.
    query["ensure"] = false;
    service.query(++id, query);
    QTRY_COMPARE(finished.size(), int(id));
    QCOMPARE(server.translation_sessions, 1);
    QCOMPARE(server.translation_ensures, 2);
    QCOMPARE(second.translation_sessions, 1);
    QCOMPARE(second.translation_ensures, 1);
    QCOMPARE(server.translation_payload["target_language"].toString(), QString("zh-Hans"));
    for (const auto& url : server.requests) QVERIFY(url.host() != "invalid.example");
    service.shutdown();
    QTRY_VERIFY(!service.busy());
  }
  void translation_session_keeps_original_and_cancels_late_results() {
    ContentProbe probe;
    ContentCatalogSession session;
    session.set_service(&probe);
    session.set_active(true);
    session.browse("mod");
    const auto search = probe.queries.lastKey();
    const QVariantMap project{
        {"id", "root"},
        {"publisher", "CurseForge"},
        {"description", "Original summary"},
        {"translationFields",
         QVariantList{QVariantMap{{"field", "summary"}, {"source_hash", "hash"}}}}};
    probe.answer(search, {{"items", QVariantList{project}}, {"total", 1}});
    const auto translation = probe.queries.lastKey();
    QCOMPARE(probe.queries[translation].value("operation").toString(), QString("translations"));
    probe.answer(translation, {{"translations",
                                QVariantMap{{"root", QVariantMap{{"description", "中文简介"}}}}}});
    session.open_project("root");
    const auto detail = probe.queries.lastKey();
    probe.answer(detail, {{"project", project}});
    const auto body_translation = probe.queries.lastKey();
    probe.answer(body_translation,
                 {{"translations", QVariantMap{{"root", QVariantMap{{"description", "中文简介"}}}}},
                  {"pending", true}});
    const auto partial = session.status().value("project").toMap();
    QVERIFY(partial.value("translatedSummary").toBool());
    QVERIFY(!partial.value("translatedBody").toBool());
    QVERIFY(session.status().value("translationPending").toBool());
    session.set_original_text(true);
    QCOMPARE(session.status().value("project").toMap().value("description").toString(),
             "Original summary");
    QVERIFY(session.translation_enabled());
    QCOMPARE(
        session.status().value("items").toList().first().toMap().value("description").toString(),
        QString("中文简介"));
    session.set_detail_view(false);
    session.set_detail_view(true);
    QCOMPARE(session.status().value("project").toMap().value("description").toString(),
             QString("中文简介"));
    QCOMPARE(
        session.status().value("items").toList().first().toMap().value("description").toString(),
        QString("中文简介"));
    session.set_translation_enabled(false);
    QCOMPARE(
        session.status().value("items").toList().first().toMap().value("description").toString(),
        QString("Original summary"));
    session.set_translation_enabled(true);
    const auto late = probe.queries.lastKey();
    session.edit("publisher", "Modrinth");
    QVERIFY(probe.cancelled.contains(late));
    probe.answer(late, {{"translations",
                         QVariantMap{{"root", QVariantMap{{"description", "错误的旧译文"}}}}}});
    QVERIFY(
        session.status().value("items").toList().first().toMap().value("description").toString() !=
        "错误的旧译文");
    session.set_active(false);
    session.cancel();
  }
  void live_translation_with_bmclapi_priority() {
    if (qgetenv("BUGG_TEST_LIVE_CONTENT") != "1") QSKIP("Explicit public translation verification");
    ContentCatalogService service;
    service.select_sources({"BMCLAPI"});
    QSignalSpy finished(&service, &ContentCatalogPort::finished);
    const QVariantMap project{
        {"id", "1004111"},
        {"publisher", "CurseForge"},
        {"translationFields",
         QVariantList{
             QVariantMap{
                 {"field", "summary"},
                 {"source_hash",
                  "sha256:f9ac0b330680e3b4c65b7801abcf1c0e6c722f78302adb2f8b53567272ae3bf3"}},
             QVariantMap{
                 {"field", "body"},
                 {"source_hash",
                  "sha256:c13b5c156d13c38bc6d1f36cb282fdd860a8df75ffa26e1dd23f74ee886db771"}}}}};
    service.query(1, {{"operation", "translations"}, {"items", QVariantList{project}}});
    QTRY_COMPARE_WITH_TIMEOUT(finished.size(), 1, 60000);
    const auto result = finished.first()[1].toMap();
    QVERIFY2(!result.contains("error"), qPrintable(result.value("error").toString()));
    QVERIFY(!result.value("translations")
                 .toMap()
                 .value("1004111")
                 .toMap()
                 .value("body")
                 .toList()
                 .isEmpty());
    QVERIFY(result.value("translations")
                .toMap()
                .value("1004111")
                .toMap()
                .value("description")
                .toString()
                .contains("整合包"));
    put(QCoreApplication::applicationDirPath() +
            "/verification/content/translation-bmclapi-live.json",
        QJsonDocument::fromVariant(result).toJson());
    service.shutdown();
    QTRY_VERIFY(!service.busy());
  }
  void curseforge_session_sends_selected_official_category() {
    ContentProbe probe;
    ContentCatalogSession session;
    session.set_service(&probe);
    session.browse("mod");
    session.edit("category", "406");
    session.search();
    QCOMPARE(probe.queries.last().value("category").toString(), "406");
    QVERIFY(!probe.queries.last().contains("categoryIds"));
  }
  void curseforge_categories_have_localized_display_names() {
    QFile file(QFINDTESTDATA("../fixtures/content/curseforge-categories.json"));
    QVERIFY(file.open(QIODevice::ReadOnly));
    const auto categories = QJsonDocument::fromJson(file.readAll()).array();
    QVERIFY(categories.size() > 80);
    const QRegularExpression chinese("[\\x{4e00}-\\x{9fff}]");
    for (const auto& value : categories) {
      const auto category = value.toObject();
      const auto label =
          content_category_name(category["slug"].toString(), category["name"].toString());
      QVERIFY2(chinese.match(label).hasMatch(),
               qPrintable(category["slug"].toString() + ':' + label));
    }
  }
  void official_categories_are_grouped_and_keep_selectable_official_ids() {
    ContentServer server;
    server.real_categories = true;
    ContentCatalogService service(nullptr, server.endpoints());
    QSignalSpy finished(&service, &ContentCatalogPort::finished);
    service.query(1, {{"publisher", "CurseForge"}, {"kind", "mod"}, {"operation", "categories"}});
    QTRY_COMPARE(finished.size(), 1);
    const auto categories = finished.last()[1].toMap().value("categories").toList();
    QSet<QString> closed;
    QString previous;
    QVariantMap create, addons;
    for (const auto& value : categories) {
      const auto item = value.toMap();
      const auto group = item.value("group").toString();
      QVERIFY(!group.isEmpty());
      if (group != previous) {
        QVERIFY(!closed.contains(group));
        closed.insert(previous);
        previous = group;
      }
      if (item.value("id") == "6484") create = item;
      if (item.value("id") == "426") addons = item;
    }
    QCOMPARE(create.value("name").toString(), QString::fromUtf8("机械动力"));
    QCOMPARE(create.value("group").toString(), QString::fromUtf8("附属模组"));
    QCOMPARE(addons.value("name").toString(), QString::fromUtf8("全部附属模组"));
    QCOMPARE(addons.value("group"), create.value("group"));
  }
  void actual_categories_are_typed_and_filters_intersect() {
    ContentServer server;
    ContentCatalogService service(nullptr, server.endpoints());
    service.select_sources({"BUGG"});
    QSignalSpy finished(&service, &ContentCatalogPort::finished);
    quint64 id = 0;
    for (const auto& publisher : {"Modrinth", "CurseForge"})
      for (const auto& kind : {"mod", "resourcepack", "shader", "modpack"}) {
        server.kind = kind;
        QVariantMap query{{"publisher", publisher}, {"kind", kind}, {"operation", "categories"}};
        service.query(++id, query);
        QTRY_COMPARE_WITH_TIMEOUT(finished.size(), int(id), 5000);
        const auto categories = finished.last()[1].toMap().value("categories").toList();
        QCOMPARE(categories.size(), 1);
        const auto category = categories.first().toMap();
        QCOMPARE(category.value("name").toString(), QString::fromUtf8("优化"));
        query["operation"] = "search";
        query["category"] = category.value("id");
        query["gameVersion"] = "1.21.1";
        query["loader"] = "fabric";
        service.query(++id, query);
        QTRY_COMPARE_WITH_TIMEOUT(finished.size(), int(id), 5000);
        const QUrlQuery params(server.requests.last());
        if (publisher == QString("Modrinth")) {
          const auto facets =
              QJsonDocument::fromJson(params.queryItemValue("facets", QUrl::FullyDecoded).toUtf8())
                  .array();
          QCOMPARE(facets.size(), kind == QString("mod") || kind == QString("modpack") ? 4 : 3);
          QVERIFY(facets.contains(QJsonArray{"categories:optimization"}));
          QVERIFY(facets.contains(QJsonArray{"versions:1.21.1"}));
        } else {
          QCOMPARE(params.queryItemValue("categoryId"), category.value("id").toString());
          QCOMPARE(params.hasQueryItem("modLoaderType"),
                   kind == QString("mod") || kind == QString("modpack"));
          QCOMPARE(params.queryItemValue("gameVersion"), "1.21.1");
        }
        const auto items = finished.last()[1].toMap().value("items").toList();
        QVERIFY(!items.isEmpty());
        query["operation"] = "detail";
        query["projectId"] = items.first().toMap().value("id");
        service.query(++id, query);
        QTRY_COMPARE_WITH_TIMEOUT(finished.size(), int(id), 5000);
        const auto detail = finished.last()[1].toMap();
        QVERIFY2(!detail.contains("error"), qPrintable(detail.value("error").toString()));
        const auto versions = detail.value("versions").toList();
        QVERIFY(!versions.isEmpty());
        query["operation"] = "plan";
        query["versionId"] = versions.first().toMap().value("id");
        service.query(++id, query);
        QTRY_COMPARE_WITH_TIMEOUT(finished.size(), int(id), 5000);
        QVERIFY2(!finished.last()[1].toMap().contains("error"),
                 qPrintable(finished.last()[1].toMap().value("error").toString()));
      }
    for (const auto& url : server.requests)
      QVERIFY2(url.path().startsWith("/v1/catalog/curseforge/") ||
                   url.path().startsWith("/v1/catalog/modrinth/") ||
                   url.path() == "/v1/catalog/shader-runtimes",
               qPrintable(url.toString()));
  }
  void source_origin_change_cancels_old_query_and_invalidates_cache() {
    ContentServer first, second;
    auto endpoints = first.endpoints();
    ContentCatalogService service(nullptr, endpoints);
    service.select_sources({"BUGG"});
    QSignalSpy finished(&service, &ContentCatalogPort::finished);
    const QVariantMap query{{"publisher", "CurseForge"}, {"kind", "mod"}};
    service.query(1, query);
    QTRY_COMPARE(finished.size(), 1);
    first.delay = 250;
    service.query(2, {{"publisher", "Modrinth"}, {"kind", "mod"}});
    QTRY_COMPARE(first.requests.size(), 2);
    service.select_sources({"BUGG"}, second.endpoints().bugg_base);
    service.query(3, query);
    QTRY_COMPARE(finished.size(), 2);
    QCOMPARE(finished.last().first().toULongLong(), quint64(3));
    QCOMPARE(second.requests.size(), 1);
    QTest::qWait(300);
    QCOMPARE(finished.size(), 2);
    service.query(4, query);
    QTRY_COMPARE(finished.size(), 3);
    QCOMPARE(second.requests.size(), 1);
  }
  void official_category_pagination_uses_one_request_and_provider_total() {
    ContentServer server;
    server.total = 67;
    ContentCatalogService service(nullptr, server.endpoints());
    ContentCatalogSession session;
    session.set_service(&service);
    session.browse("mod");
    QTRY_VERIFY(!session.status().value("loading").toBool());
    session.edit("category", "407");
    session.search();
    QTRY_VERIFY(!session.status().value("loading").toBool());
    QCOMPARE(session.status().value("items").toList().size(), 20);
    QCOMPARE(session.status().value("total").toInt(), 67);
    QVERIFY(session.status().value("hasMore").toBool());
    const int first_requests = server.requests.size();
    session.search(1);
    QTRY_VERIFY(!session.status().value("loading").toBool());
    QCOMPARE(server.requests.size() - first_requests, 1);
    const QUrlQuery params(server.requests.last());
    QCOMPARE(params.queryItemValue("index"), "20");
    QCOMPARE(params.queryItemValue("categoryId"), "407");
  }
  void bmclapi_content_uses_official_endpoint_and_category_parameter() {
    ContentServer server;
    auto endpoints = server.endpoints();
    endpoints.bugg_base =
        QUrl("http://127.0.0.1:" + QString::number(server.serverPort()) + "/gateway");
    ContentCatalogService service(nullptr, endpoints);
    service.select_sources({"BMCLAPI"});
    QSignalSpy finished(&service, &ContentCatalogPort::finished);
    service.query(1, {{"publisher", "CurseForge"},
                      {"kind", "mod"},
                      {"operation", "search"},
                      {"category", "407"},
                      {"gameVersion", "1.21.1"},
                      {"loader", "fabric"}});
    QTRY_COMPARE(finished.size(), 1);
    QVERIFY2(!finished.last()[1].toMap().contains("error"),
             qPrintable(finished.last()[1].toMap().value("error").toString()));
    QCOMPARE(server.requests.size(), 1);
    QCOMPARE(server.requests.last().path(), "/cf/mods/search");
    QCOMPARE(QUrlQuery(server.requests.last()).queryItemValue("categoryId"), "407");
    QCOMPARE(QUrlQuery(server.requests.last()).queryItemValue("modLoaderType"), "4");
  }
  void native_client_queries_new_source_gateway() {
    const auto origin = qEnvironmentVariable("BUGG_TEST_CONTENT_GATEWAY_ORIGIN");
    if (origin.isEmpty()) QSKIP("Explicit local bugg-source integration only");
    QVERIFY(origin.startsWith("http://127.0.0.1:"));
    ContentEndpoints endpoints{QUrl(origin), QUrl(origin + "/v1/catalog/curseforge"),
                               QUrl(origin + "/v1/catalog/modrinth"), "test-key"};
    ContentCatalogService service(nullptr, endpoints);
    service.select_sources({"BUGG"});
    QSignalSpy finished(&service, &ContentCatalogPort::finished);
    quint64 id = 0;
    for (const auto& publisher : {"CurseForge", "Modrinth"})
      for (const auto& kind : {"mod", "resourcepack", "shader", "modpack"}) {
        service.query(++id,
                      {{"operation", "search"},
                       {"publisher", publisher},
                       {"kind", kind},
                       {"category", publisher == QString("CurseForge") ? "407" : "technology"},
                       {"gameVersion", "1.21.1"},
                       {"loader", "fabric"},
                       {"offset", 20}});
        QTRY_COMPARE_WITH_TIMEOUT(finished.size(), int(id), 5000);
        const auto result = finished.last()[1].toMap();
        QVERIFY2(!result.contains("error"), qPrintable(result.value("error").toString()));
        QCOMPARE(result.value("total").toInt(), 73);
        QCOMPARE(result.value("items").toList().size(), 1);
      }
    service.shutdown();
    QTRY_VERIFY(!service.busy());
  }
  void session_discards_late_results_and_resolves_target() {
    ContentProbe probe;
    ContentCatalogSession session;
    session.set_service(&probe);
    session.browse("mod");
    const auto original = probe.queries.lastKey();
    session.edit("query", "new");
    probe.answer(original, {{"items", QVariantList{QVariantMap{{"id", "wrong"}}}}});
    QVERIFY(session.status().value("items").toList().isEmpty());
    QTRY_COMPARE(probe.queries.size(), 3);
    const auto search = probe.queries.lastKey();
    probe.answer(search, {{"items", QVariantList{QVariantMap{{"id", "root"}}}}, {"total", 1}});
    session.open_project("root", {{"version", "1.21.1"}, {"loader", "Fabric"}});
    const auto detail = probe.queries.lastKey();
    QCOMPARE(probe.queries[detail].value("gameVersion").toString(), "1.21.1");
    QCOMPARE(probe.queries[detail].value("loader").toString(), "fabric");
    probe.answer(detail,
                 {{"versions", QVariantList{QVariantMap{{"id", "version"}}}}, {"total", 1}});
    const auto plan = probe.queries.lastKey();
    session.version_page(1);
    probe.answer(plan, {{"files", QVariantList{QVariantMap{{"filename", "stale.jar"}}}}});
    QVERIFY(session.status().value("plan").toMap().isEmpty());
    QVERIFY(probe.cancelled.contains(plan));
    session.cancel();
    QVERIFY(!session.status().value("detailLoading").toBool());
  }
  void publishers_categories_paging_and_dependencies() {
    ContentServer server;
    ContentCatalogService service(nullptr, server.endpoints());
    QSignalSpy finished(&service, &ContentCatalogPort::finished);
    quint64 id = 0;
    for (const auto& publisher : {"Modrinth", "CurseForge"})
      for (const auto& kind : {"mod", "resourcepack", "shader", "modpack"}) {
        server.kind = kind;
        QVariantMap query{{"publisher", publisher},
                          {"kind", kind},
                          {"gameVersion", "1.21.1"},
                          {"loader", "fabric"},
                          {"offset", 20}};
        service.query(++id, query);
        QTRY_COMPARE_WITH_TIMEOUT(finished.size(), int(id), 5000);
        const auto result = finished.last()[1].toMap();
        QVERIFY2(!result.contains("error"), qPrintable(result.value("error").toString()));
        QCOMPARE(result.value("items").toList().size(), 20);
        QVERIFY(!result.value("hasMore").toBool());
        const auto project = result.value("items").toList().first().toMap().value("id");
        query["operation"] = "detail";
        query["projectId"] = project;
        query["offset"] = 0;
        service.query(++id, query);
        QTRY_COMPARE_WITH_TIMEOUT(finished.size(), int(id), 5000);
        const auto detail = finished.last()[1].toMap();
        QVERIFY2(!detail.contains("error"), qPrintable(detail.value("error").toString()));
        const auto versions = detail.value("versions").toList();
        QVERIFY(!versions.isEmpty());
        query["operation"] = "plan";
        query["versionId"] = versions.first().toMap().value("id");
        service.query(++id, query);
        QTRY_COMPARE_WITH_TIMEOUT(finished.size(), int(id), 5000);
        const auto plan = finished.last()[1].toMap();
        QVERIFY2(!plan.contains("error"), qPrintable(plan.value("error").toString()));
        QCOMPARE(
            plan.value("files").toList().size(),
            kind == QString("shader") || publisher == QString("Modrinth") && kind == QString("mod")
                ? 2
                : 1);
      }
    for (const auto& url : server.requests) {
      if (url.path() != "/mr/search") continue;
      const auto facets = QJsonDocument::fromJson(
                              QUrlQuery(url).queryItemValue("facets", QUrl::FullyDecoded).toUtf8())
                              .array();
      QVERIFY(!facets.isEmpty());
      QVERIFY(facets.first().isArray());
      QCOMPARE(facets.first().toArray().first().toString().section(':', 0, 0), "project_type");
    }
    QVERIFY(std::none_of(server.requests.cbegin(), server.requests.cend(),
                         [](const auto& url) { return url.path().contains("optional"); }));
    service.shutdown();
    QTRY_VERIFY(!service.busy());
  }
  void required_dependency_conflict_preserves_primary() {
    ContentServer server;
    server.conflicting = true;
    ContentCatalogService service(nullptr, server.endpoints());
    QSignalSpy finished(&service, &ContentCatalogPort::finished);
    service.query(1, {{"publisher", "Modrinth"},
                      {"kind", "mod"},
                      {"operation", "plan"},
                      {"projectId", "root"},
                      {"versionId", "v1"}});
    QTRY_COMPARE_WITH_TIMEOUT(finished.size(), 1, 5000);
    const auto plan = finished.first()[1].toMap();
    QVERIFY(plan.value("error").toString().isEmpty());
    QCOMPARE(plan.value("files").toList().size(), 1);
    QCOMPARE(plan.value("files").toList().first().toMap().value("projectId").toString(), "root");
    QCOMPARE(plan.value("missingDependencies").toList().size(), 1);
  }
  void failed_dependency_metadata_preserves_installable_primary() {
    ContentServer server;
    server.missing_dependency = true;
    ContentCatalogService service(nullptr, server.endpoints());
    QSignalSpy finished(&service, &ContentCatalogPort::finished);
    service.query(1, {{"publisher", "Modrinth"},
                      {"kind", "mod"},
                      {"operation", "plan"},
                      {"projectId", "root"},
                      {"versionId", "v1"}});
    QTRY_COMPARE_WITH_TIMEOUT(finished.size(), 1, 5000);
    const auto plan = finished.first()[1].toMap();
    QVERIFY(plan.value("error").toString().isEmpty());
    QCOMPARE(plan.value("files").toList().size(), 1);
    QVERIFY(!plan.value("files").toList().first().toMap().value("dependency").toBool());
    QCOMPARE(plan.value("missingDependencies").toList().size(), 1);
    QCOMPARE(
        plan.value("missingDependencies").toList().first().toMap().value("projectId").toString(),
        "dep");
    QVERIFY(!plan.value("missingDependencies")
                 .toList()
                 .first()
                 .toMap()
                 .value("reason")
                 .toString()
                 .isEmpty());
  }
  void cache_cancel_source_change_and_error() {
    ContentServer server;
    ContentCatalogService service(nullptr, server.endpoints());
    QSignalSpy finished(&service, &ContentCatalogPort::finished);
    QVariantMap query{{"publisher", "Modrinth"}, {"kind", "mod"}};
    service.query(1, query);
    QTRY_COMPARE(finished.size(), 1);
    const auto count = server.requests.size();
    service.query(2, query);
    QTRY_COMPARE(finished.size(), 2);
    QCOMPARE(server.requests.size(), count);
    service.select_sources({"官方"});
    server.delay = 300;
    service.query(3, query);
    QTRY_VERIFY(service.busy());
    service.cancel(3);
    QTRY_VERIFY(!service.busy());
    QCOMPARE(finished.size(), 2);
    server.broken = true;
    server.delay = 0;
    service.query(4, query);
    QTRY_COMPARE(finished.size(), 3);
    QVERIFY(!finished.last()[1].toMap().value("error").toString().isEmpty());
  }
  void query_cache_measurement() {
    ContentServer server;
    server.delay = 15;
    ContentCatalogService service(nullptr, server.endpoints());
    QSignalSpy finished(&service, &ContentCatalogPort::finished);
    QVariantMap query{{"publisher", "Modrinth"}, {"kind", "mod"}};
    QJsonArray cold, warm;
    quint64 id = 0;
    for (int trial = 0; trial < 7; ++trial) {
      service.select_sources(trial % 2 ? QStringList{"官方", "BUGG"} : QStringList{"BUGG", "官方"});
      QElapsedTimer clock;
      clock.start();
      service.query(++id, query);
      QVERIFY(finished.wait(5000));
      cold.append(clock.nsecsElapsed() / 1000000.0);
      clock.restart();
      service.query(++id, query);
      QVERIFY(finished.wait(5000));
      warm.append(clock.nsecsElapsed() / 1000000.0);
    }
    QCOMPARE(server.requests.size(), 7);
    put(QCoreApplication::applicationDirPath() + "/verification/content/cache-report.json",
        QJsonDocument(QJsonObject{{"coldMs", cold},
                                  {"warmMs", warm},
                                  {"httpRequests", server.requests.size()},
                                  {"queries", int(id)},
                                  {"fixtureDelayMs", 15}})
            .toJson());
  }
  void installation_conflicts_hash_compatibility_and_cancel() {
    QTemporaryDir root;
    QVERIFY(root.isValid());
    const auto game = root.path() + "/game", portable = root.path() + "/portable";
    write_json(
        game + "/versions/fixture/fixture.json",
        {{"id", "fixture"}, {"bugg", QJsonObject{{"version", "1.21.1"}, {"loader", "fabric"}}}});
    auto cancelled = std::make_shared<std::atomic_bool>(false);
    GameOperations operation(game, portable, {"官方"}, cancelled, [](double, const QString&) {});
    // Shader installation has mandatory prerequisites; covered separately below.
    for (const auto& kind : {"mod", "resourcepack"}) {
      const auto plan = content_plan(kind, "content");
      const auto prepared = operation.check_content_install("fixture", plan);
      const auto records = QJsonArray::fromVariantList(prepared.value("records").toList());
      const auto fingerprint =
          QCryptographicHash::hash(QJsonDocument(records).toJson(QJsonDocument::Compact),
                                   QCryptographicHash::Sha256)
              .toHex()
              .left(24);
      const auto relative = records.first().toObject()["path"].toString();
      const auto target = game + "/versions/fixture/" + relative;
      put(game + "/versions/fixture/.content-" + fingerprint + "/files/" + relative, "content");
      put(target, "old");
      QVERIFY(!operation.check_content_install("fixture", plan)
                   .value("conflicts")
                   .toStringList()
                   .isEmpty());
      QVariantMap spec{{"kind", "content"}, {"id", "fixture"}, {"plan", plan}};
      QVERIFY_EXCEPTION_THROWN(operation.install_content(spec), std::runtime_error);
      QCOMPARE(file_digest(target, "sha1", cancelled),
               QCryptographicHash::hash("old", QCryptographicHash::Sha1).toHex());
      spec["replace"] = true;
      operation.install_content(spec);
      QCOMPARE(file_digest(target, "sha1", cancelled),
               QCryptographicHash::hash("content", QCryptographicHash::Sha1).toHex());
      cancelled->store(true);
      QVERIFY_EXCEPTION_THROWN(operation.install_content(spec), std::runtime_error);
      cancelled->store(false);
      auto wrong = plan;
      auto files = wrong.value("files").toList();
      auto file = files[0].toMap();
      file["gameVersions"] = QStringList{"1.20.1"};
      files[0] = file;
      wrong["files"] = files;
      QVERIFY_EXCEPTION_THROWN(operation.check_content_install("fixture", wrong),
                               std::runtime_error);
    }
    QCOMPARE(read_json(game + "/versions/fixture/fixture.json")["buggcraftModpack"]
                 .toObject()["resources"]
                 .toArray()
                 .size(),
             2);
  }
  void publication_failure_restores_old_files() {
    QTemporaryDir root;
    QVERIFY(root.isValid());
    const auto game = root.path() + "/game", directory = game + "/versions/fixture";
    write_json(
        directory + "/fixture.json",
        {{"id", "fixture"}, {"bugg", QJsonObject{{"version", "1.21.1"}, {"loader", "fabric"}}}});
    auto plan = content_plan("mod", "content");
    auto files = plan.value("files").toList();
    files.append(content_plan("resourcepack", "content").value("files").toList().first());
    plan["files"] = files;
    auto cancelled = std::make_shared<std::atomic_bool>(false);
    GameOperations operation(game, root.path() + "/portable", {"官方"}, cancelled,
                             [](double, const QString&) {});
    const auto prepared = operation.check_content_install("fixture", plan);
    const auto records = QJsonArray::fromVariantList(prepared.value("records").toList());
    const auto fingerprint =
        QCryptographicHash::hash(QJsonDocument(records).toJson(QJsonDocument::Compact),
                                 QCryptographicHash::Sha256)
            .toHex()
            .left(24);
    for (const auto& record : records)
      put(directory + "/.content-" + fingerprint + "/files/" + record.toObject()["path"].toString(),
          "content");
    put(directory + "/mods/sample.jar", "old");
    put(directory + "/resourcepacks", "blocks directory creation");
    const auto original = file_digest(directory + "/fixture.json", "sha1", cancelled);
    QVERIFY_EXCEPTION_THROWN(
        operation.install_content(
            {{"kind", "content"}, {"id", "fixture"}, {"plan", plan}, {"replace", true}}),
        std::runtime_error);
    QCOMPARE(file_digest(directory + "/mods/sample.jar", "sha1", cancelled),
             QCryptographicHash::hash("old", QCryptographicHash::Sha1).toHex());
    QCOMPARE(file_digest(directory + "/fixture.json", "sha1", cancelled), original);
  }
  void content_uses_runtime_task_queue_and_receipts() {
    QTemporaryDir root;
    QVERIFY(root.isValid());
    const auto game = root.path() + "/game";
    write_json(
        game + "/versions/fixture/fixture.json",
        {{"id", "fixture"}, {"bugg", QJsonObject{{"version", "1.21.1"}, {"loader", "fabric"}}}});
    put(game + "/versions/fixture/mods/sample.jar", "content");
    HttpClient http;
    MicrosoftAccount account(&http, root.path() + "/credentials.bin");
    GameRuntime runtime(root.path(), game, &account);
    QSignalSpy initialized(&runtime, &GameRuntime::initialized);
    runtime.initialize();
    QTRY_COMPARE_WITH_TIMEOUT(initialized.size(), 1, 15000);
    const auto plan = content_plan("mod", "content");
    runtime.inspect_content_install("fixture", plan);
    QCOMPARE(runtime.content_installation().value("requestedPlan").toMap(), plan);
    QTRY_VERIFY(!runtime.content_installation().value("loading").toBool());
    QVERIFY(!runtime.content_installation().contains("error"));
    runtime.install(
        {{"kind", "content"}, {"id", "fixture"}, {"name", "Install content"}, {"plan", plan}});
    QTRY_VERIFY_WITH_TIMEOUT(
        !runtime.tasks().isEmpty() && runtime.tasks().first().toMap().value("state") == "done",
        15000);
    QCOMPARE(read_json(game + "/versions/fixture/fixture.json")["buggcraftModpack"]
                 .toObject()["resources"]
                 .toArray()
                 .size(),
             1);
    runtime.refresh_content("fixture", "mods");
    QTRY_VERIFY(!runtime.content().value("loading").toBool());
    QCOMPARE(runtime.content().value("entries").toList().size(), 1);
    runtime.shutdown();
    QTRY_VERIFY(!runtime.busy());
  }
  void dependency_failure_preserves_primary_and_runtime_retry_repairs() {
    QTemporaryDir root;
    const auto game = root.path() + "/game", instance = game + "/versions/fixture";
    write_json(
        instance + "/fixture.json",
        {{"id", "fixture"}, {"bugg", QJsonObject{{"version", "1.21.1"}, {"loader", "fabric"}}}});
    put(instance + "/mods/sample.jar", "content");
    auto plan = content_plan("mod", "content");
    auto file = plan.value("files").toList().first().toMap();
    file["projectId"] = "dep";
    file["filename"] = "dependency.jar";
    file["title"] = "Fabric API";
    file["dependency"] = true;
    file["url"] = "https://cdn.modrinth.com/data/test/dependency.jar";
    put(instance + "/mods/dependency.jar", "old incompatible dependency");
    auto files = plan.value("files").toList();
    files.append(file);
    plan["files"] = files;
    plan["query"] = QVariantMap{{"operation", "plan"}};
    HttpClient http;
    MicrosoftAccount account(&http, root.path() + "/credentials.bin");
    GameRuntime runtime(root.path(), game, &account);
    int resolutions = 0;
    runtime.set_content_request([&](const auto&, const auto&) {
      ++resolutions;
      return plan;
    });
    QSignalSpy initialized(&runtime, &GameRuntime::initialized);
    runtime.initialize();
    QTRY_COMPARE_WITH_TIMEOUT(initialized.size(), 1, 15000);
    runtime.install(
        {{"kind", "content"}, {"id", "fixture"}, {"name", "Install content"}, {"plan", plan}});
    QTRY_VERIFY_WITH_TIMEOUT(
        !runtime.tasks().isEmpty() && runtime.tasks().first().toMap().value("state") == "done",
        15000);
    const auto task = runtime.tasks().first().toMap();
    QCOMPARE(resolutions, 0);  // Healthy normalized plans do not repeat metadata I/O.
    const auto items = task.value("contentItems").toList();
    QCOMPARE(items.size(), 2);
    QCOMPARE(items.first().toMap().value("state").toString(), "installed");
    QCOMPARE(items.first().toMap().value("versionName").toString(), "1.0");
    QVERIFY(!items.first().toMap().value("dependency").toBool());
    QCOMPARE(items.last().toMap().value("state").toString(), "failed");
    QVERIFY(items.last().toMap().value("dependency").toBool());
    QVERIFY(!items.last().toMap().value("detail").toString().isEmpty());
    QCOMPARE(task.value("missingDependencies").toList().size(), 1);
    QCOMPARE(task.value("missingDependencies").toList().first().toMap().value("title").toString(),
             "Fabric API");
    QCOMPARE(read_json(instance + "/fixture.json")["buggcraftModpack"]
                 .toObject()["resources"]
                 .toArray()
                 .size(),
             1);
    QVERIFY(QFileInfo::exists(instance + "/mods/sample.jar"));
    QCOMPARE(
        file_digest(instance + "/mods/dependency.jar", "sha1",
                    std::make_shared<std::atomic_bool>(false)),
        QCryptographicHash::hash("old incompatible dependency", QCryptographicHash::Sha1).toHex());
    put(instance + "/mods/dependency.jar", "content");
    runtime.retry_task(task.value("id").toString());
    QTRY_VERIFY_WITH_TIMEOUT(runtime.tasks().first().toMap().value("state") == "done", 15000);
    QCOMPARE(resolutions, 1);
    const auto repaired = runtime.tasks().first().toMap().value("contentItems").toList();
    QCOMPARE(repaired.size(), 2);
    QVERIFY2(repaired.last().toMap().value("state").toString() == "installed",
             qPrintable(QString::fromUtf8(QJsonDocument::fromVariant(runtime.tasks()).toJson())));
    QCOMPARE(repaired.last().toMap().value("title").toString(), "Fabric API");
    QVERIFY2(runtime.tasks().first().toMap().value("missingDependencies").toList().isEmpty(),
             qPrintable(QString::fromUtf8(QJsonDocument::fromVariant(runtime.tasks()).toJson())));
    QCOMPARE(read_json(instance + "/fixture.json")["buggcraftModpack"]
                 .toObject()["resources"]
                 .toArray()
                 .size(),
             2);
    runtime.shutdown();
    QTRY_VERIFY(!runtime.busy());
    GameRuntime reopened(root.path(), game, &account);
    QSignalSpy restored(&reopened, &GameRuntime::initialized);
    reopened.initialize();
    QTRY_COMPARE_WITH_TIMEOUT(restored.size(), 1, 15000);
    QCOMPARE(QJsonDocument::fromVariant(reopened.tasks().first().toMap().value("contentItems")),
             QJsonDocument::fromVariant(repaired));
    reopened.shutdown();
    QTRY_VERIFY(!reopened.busy());
  }
  void installed_content_shows_version_and_explicit_upgrade_replaces() {
    QTemporaryDir root;
    const auto directory = root.path() + "/game/versions/fixture";
    write_json(
        directory + "/fixture.json",
        {{"id", "fixture"}, {"bugg", QJsonObject{{"version", "1.21.1"}, {"loader", "fabric"}}}});
    put(directory + "/mods/sample.jar", "content");
    auto cancelled = std::make_shared<std::atomic_bool>(false);
    GameOperations operation(root.path() + "/game", root.path(), {"官方"}, cancelled,
                             [](double, const QString&) {});
    const auto original = content_plan("mod", "content");
    operation.install_content({{"kind", "content"}, {"id", "fixture"}, {"plan", original}});
    auto preview = operation.check_content_install("fixture", original);
    QCOMPARE(preview.value("installed").toList().first().toMap().value("versionName").toString(),
             "1.0");
    QVERIFY(preview.value("installed").toList().first().toMap().value("matchesSelected").toBool());
    // A manually updated file can share its filename with an older receipt.
    // Its verified bytes, rather than that stale receipt, identify the version.
    auto same_name = original;
    auto selected = same_name.value("files").toList().first().toMap();
    selected["versionName"] = "1.1";
    selected["versionId"] = "v1.1";
    same_name["files"] = QVariantList{selected};
    preview = operation.check_content_install("fixture", same_name);
    QCOMPARE(preview.value("installed").toList().first().toMap().value("versionName").toString(),
             "1.1");
    auto next = content_plan("mod", "updated");
    auto file = next.value("files").toList().first().toMap();
    file["filename"] = "sample-2.0.jar";
    file["versionId"] = "v2";
    file["versionName"] = "2.0";
    next["files"] = QVariantList{file};
    preview = operation.check_content_install("fixture", next);
    QVERIFY(!preview.value("installed").toList().first().toMap().value("matchesSelected").toBool());
    QCOMPARE(preview.value("installed").toList().first().toMap().value("versionName").toString(),
             "1.0");
    QVERIFY(preview.value("conflicts").toStringList().contains("mods/sample.jar"));
    QVariantMap spec{{"kind", "content"}, {"id", "fixture"}, {"plan", next}};
    QVERIFY_EXCEPTION_THROWN(operation.install_content(spec), std::runtime_error);
    const auto records = QJsonArray::fromVariantList(preview.value("records").toList());
    const auto fingerprint =
        QCryptographicHash::hash(QJsonDocument(records).toJson(QJsonDocument::Compact),
                                 QCryptographicHash::Sha256)
            .toHex()
            .left(24);
    put(directory + "/.content-" + fingerprint + "/files/mods/sample-2.0.jar", "updated");
    spec["replace"] = true;
    operation.install_content(spec);
    QVERIFY(!QFileInfo::exists(directory + "/mods/sample.jar"));
    QVERIFY(QFileInfo::exists(directory + "/mods/sample-2.0.jar"));
    preview = operation.check_content_install("fixture", next);
    QCOMPARE(preview.value("installed").toList().first().toMap().value("versionName").toString(),
             "2.0");
    QVERIFY(preview.value("installed").toList().first().toMap().value("matchesSelected").toBool());
  }
  void renamed_content_is_identified_reused_and_upgraded() {
    for (const auto& kind : {QString("mod"), QString("resourcepack")}) {
      QTemporaryDir root;
      const auto directory = root.path() + "/versions/fixture";
      write_json(
          directory + "/fixture.json",
          {{"id", "fixture"}, {"bugg", QJsonObject{{"version", "1.21.1"}, {"loader", "fabric"}}}});
      const auto folder = kind == "mod"            ? "mods"
                          : kind == "resourcepack" ? "resourcepacks"
                                                   : "shaderpacks";
      const auto suffix = kind == "mod" ? ".jar" : ".zip";
      const auto renamed = QString(folder) + "/my-renamed-file" + suffix;
      put(directory + '/' + renamed, "content");
      // Same size is not sufficient; the wrong bytes must never be adopted.
      put(directory + '/' + folder + "/wrong" + suffix, "CONTENT");
      GameOperations operation(root.path(), root.path(), {"官方"},
                               std::make_shared<std::atomic_bool>(false),
                               [](double, const QString&) {});
      const auto original = content_plan(kind, "content");
      auto preview = operation.check_content_install("fixture", original);
      QCOMPARE(preview.value("installed").toList().first().toMap().value("path").toString(),
               renamed);
      QVERIFY(
          preview.value("installed").toList().first().toMap().value("matchesSelected").toBool());
      QVERIFY(preview.value("conflicts").toStringList().isEmpty());
      // The URL is unreachable in this test: reuse must require no transfer.
      operation.install_content({{"kind", "content"}, {"id", "fixture"}, {"plan", original}});
      QVERIFY(QFileInfo::exists(directory + '/' + renamed));
      QVERIFY(!QFileInfo::exists(directory + '/' + folder + "/sample" + suffix));
      auto metadata = read_json(directory + "/fixture.json");
      QCOMPARE(metadata["buggcraftModpack"]
                   .toObject()["resources"]
                   .toArray()
                   .first()
                   .toObject()["path"]
                   .toString(),
               renamed);
      // Rename again after the receipt exists, then upgrade: the old actual
      // file must be shown and removed only after explicit replacement.
      const auto again = QString(folder) + "/renamed-again" + suffix;
      QVERIFY(QFile::rename(directory + '/' + renamed, directory + '/' + again));
      auto next = content_plan(kind, "updated");
      auto file = next.value("files").toList().first().toMap();
      file["filename"] = "sample-2" + QString(suffix);
      file["versionName"] = "2.0";
      file["versionId"] = "v2";
      next["files"] = QVariantList{file};
      preview = operation.check_content_install("fixture", next);
      QVERIFY(preview.value("conflicts").toStringList().contains(again));
      const auto records = QJsonArray::fromVariantList(preview.value("records").toList());
      const auto fingerprint =
          QCryptographicHash::hash(QJsonDocument(records).toJson(QJsonDocument::Compact),
                                   QCryptographicHash::Sha256)
              .toHex()
              .left(24);
      put(directory + "/.content-" + fingerprint + "/files/" + folder + "/sample-2" + suffix,
          "updated");
      operation.install_content(
          {{"kind", "content"}, {"id", "fixture"}, {"plan", next}, {"replace", true}});
      QVERIFY(!QFileInfo::exists(directory + '/' + again));
      QVERIFY(QFileInfo::exists(directory + '/' + folder + "/sample-2" + suffix));
      metadata = read_json(directory + "/fixture.json");
      QCOMPARE(metadata["buggcraftModpack"].toObject()["resources"].toArray().size(), 1);
    }
  }
  void translation_models_update_without_resetting_the_view() {
    ContentListModel model;
    const QVariantList initial{QVariantMap{{"html", "Original"}},
                               QVariantMap{{"image", "picture.png"}}};
    model.reconcile("project-1", initial);
    QSignalSpy resets(&model, &QAbstractItemModel::modelReset);
    QSignalSpy updates(&model, &QAbstractItemModel::dataChanged);
    model.reconcile("project-1", {QVariantMap{{"html", "译文"}}, initial[1]});
    QCOMPARE(resets.size(), 0);
    QCOMPARE(updates.size(), 1);
    model.reconcile("project-1", {QVariantMap{{"html", "译文"}}, initial[1]});
    QCOMPARE(updates.size(), 1);
    model.reconcile("project-2", initial);
    QCOMPARE(resets.size(), 1);
  }
  void translated_document_keeps_scroll_and_small_image_dimensions() {
    QTemporaryDir root;
    QImage badge(48, 12, QImage::Format_ARGB32);
    badge.fill(QColor("#7863ca"));
    const auto path = root.filePath("badge.png");
    QVERIFY(badge.save(path));
    ContentListModel model;
    QVariantList rows{QVariantMap{{"image", QUrl::fromLocalFile(path).toString()}}};
    for (int i = 0; i < 80; ++i)
      rows.append(
          QVariantMap{{"html", QString("<p>Paragraph %1: Original text for reading.</p>").arg(i)}});
    model.reconcile("project", rows);
    QQmlApplicationEngine engine;
    engine.addImportPath(QCoreApplication::applicationDirPath() + "/qml");
    engine.rootContext()->setContextProperty("documentModel", &model);
    engine.loadData(R"(
      import QtQuick
      import QtQuick.Window
      import Bugg.DesignSystem
      Window {
        width: 800; height: 520; visible: true; color: "white"
        RichDocument { objectName: "document"; anchors.fill: parent; anchors.margins: 24; model: documentModel }
      })");
    QVERIFY(!engine.rootObjects().isEmpty());
    auto* window = qobject_cast<QQuickWindow*>(engine.rootObjects().first());
    auto* document = window->findChild<QObject*>("document");
    QVERIFY(document);
    QTest::qWait(150);
    QList<QQuickItem*> pending{window->contentItem()};
    QQuickItem* picture = nullptr;
    while (!pending.isEmpty()) {
      auto* item = pending.takeLast();
      pending.append(item->childItems());
      if (item->objectName() == "contentPicture") picture = item;
    }
    QVERIFY(picture);
    QTRY_COMPARE(picture->width(), 48.0);
    QTRY_COMPARE(picture->height(), 12.0);
    const auto shots = QCoreApplication::applicationDirPath() + "/verification/content/scroll";
    QDir().mkpath(shots);
    QVERIFY(window->grabWindow().save(shots + "/native-small-image.png"));
    document->setProperty("contentY", 640);
    QTest::qWait(100);
    const auto before = document->property("contentY").toDouble();
    QVERIFY(before > 0);
    QVERIFY(window->grabWindow().save(shots + "/before-translation.png"));
    for (int i = 1; i < rows.size(); ++i)
      rows[i] = QVariantMap{
          {"html", QString("<p>段落 %1：正在阅读的中文译文，保持当前位置。</p>").arg(i)}};
    QSignalSpy reset(&model, &QAbstractItemModel::modelReset);
    model.reconcile("project", rows);
    QTest::qWait(150);
    QCOMPARE(reset.size(), 0);
    // ListView can refine its offscreen extent estimate by a fraction of a
    // logical pixel after delegates change height. A reset to the top or a
    // visible scroll jump must still fail under render/load variations.
    QVERIFY(qAbs(document->property("contentY").toDouble() - before) < 1.0);
    QVERIFY(window->grabWindow().save(shots + "/after-translation.png"));
    window->close();
  }
  void shader_core_selection_and_local_identity() {
    ContentServer server;
    server.kind = "shader";
    ContentCatalogService service(nullptr, server.endpoints());
    QSignalSpy finished(&service, &ContentCatalogPort::finished);
    quint64 serial = 0;
    QVariantMap query{{"operation", "plan"}, {"publisher", "Modrinth"},
                      {"kind", "shader"},    {"projectId", "root"},
                      {"versionId", "v1"},   {"gameVersion", "1.21.1"},
                      {"loader", "fabric"},  {"offset", 40}};
    for (const auto& loader : {"fabric", "neoforge", "forge", "quilt"}) {
      server.shader_loader = loader;
      query["loader"] = loader;
      service.query(++serial, query);
      QTRY_COMPARE(finished.size(), int(serial));
      const auto result = finished.last()[1].toMap();
      QVERIFY2(!result.contains("error"), qPrintable(result.value("error").toString()));
      QCOMPARE(result.value("shaderSupport").toMap().value("id").toString(),
               QString(loader) == "forge" ? "oculus" : "iris");
      const auto files = result.value("files").toList();
      QCOMPARE(files.size(), 2);
      QVERIFY(!files.first().toMap().value("dependency").toBool());
      QVERIFY(files.last().toMap().value("prerequisite").toBool());
      QVERIFY(files.last().toMap().value("loaders").toStringList().contains(loader));
    }
    QTemporaryDir root;
    const auto directory = root.path() + "/versions/fixture";
    write_json(
        directory + "/fixture.json",
        {{"id", "fixture"}, {"bugg", QJsonObject{{"version", "1.21.1"}, {"loader", "fabric"}}}});
    const auto cancelled = std::make_shared<std::atomic_bool>(false);
    const auto renamed = directory + "/mods/my-renamed-core.jar";
    archive_write(renamed, {}, {{"net/irisshaders/iris/Iris.class", "fixture"}}, cancelled, {});
    server.shader_hash = QString::fromLatin1(file_digest(renamed, "sha1", cancelled));
    server.shader_loader = "fabric";
    query["loader"] = "fabric";
    query["offset"] = 0;  // Distinct query after fixture file identity changed.
    service.query(++serial, query);
    QTRY_COMPARE(finished.size(), int(serial));
    const auto plan = finished.last()[1].toMap();
    GameOperations operation(root.path(), root.path(), {"官方"}, cancelled,
                             [](double, const QString&) {});
    const ContentRequest request = [endpoints = server.endpoints()](const QVariantMap& value,
                                                                    const Cancellation& flag) {
      return request_content(value, {"官方"}, endpoints, flag);
    };
    auto future = QtConcurrent::run(
        [&] { return operation.prepare_content_install("fixture", plan, request); });
    QTRY_VERIFY_WITH_TIMEOUT(future.isFinished(), 15000);
    auto result = future.result();
    QVERIFY(result.value("shaderSupport").toMap().value("installed").toBool());
    QCOMPARE(result.value("files").toList().last().toMap().value("versionId").toString(),
             "older-core");
    QCOMPARE(result.value("shaderSupport").toMap().value("path").toString(),
             "mods/my-renamed-core.jar");
    HttpClient http;
    MicrosoftAccount account(&http, root.path() + "/credentials.bin");
    GameRuntime runtime(root.path(), root.path(), &account);
    runtime.set_content_request(request);
    QSignalSpy initialized(&runtime, &GameRuntime::initialized);
    runtime.initialize();
    QTRY_COMPARE_WITH_TIMEOUT(initialized.size(), 1, 15000);
    runtime.inspect_content_install("fixture", plan);
    QTRY_VERIFY_WITH_TIMEOUT(!runtime.content_installation().value("loading").toBool(), 15000);
    QVERIFY2(!runtime.content_installation().contains("error"),
             qPrintable(runtime.content_installation().value("error").toString()));
    QVERIFY(
        runtime.content_installation().value("shaderSupport").toMap().value("installed").toBool());
    QCOMPARE(runtime.content_installation().value("requestedPlan").toMap(), plan);
    runtime.shutdown();
    QTRY_VERIFY(!runtime.busy());
    QVERIFY(QFile::copy(renamed, directory + "/mods/duplicate.jar"));
    QVERIFY_EXCEPTION_THROWN(operation.prepare_content_install("fixture", plan, request),
                             std::runtime_error);
    QVERIFY(QFile::remove(directory + "/mods/duplicate.jar"));
    QVERIFY(QFile::rename(renamed, renamed + ".disabled"));
    QVERIFY_EXCEPTION_THROWN(operation.prepare_content_install("fixture", plan, request),
                             std::runtime_error);
    server.no_shader_core = true;
    query["offset"] = 1;
    service.query(++serial, query);
    QTRY_COMPARE(finished.size(), int(serial));
    QVERIFY(finished.last()[1].toMap().contains("error"));
    service.shutdown();
    QTRY_VERIFY(!service.busy());
  }
  void release_snapshot_is_used_before_publisher_and_missing_falls_back() {
    ContentServer server;
    const QJsonObject identity{
        {"provider", "modrinth"}, {"project_id", "root"}, {"release_id", "v1"}};
    const QJsonObject observation{{"algorithm", "sha1"},
                                  {"digest", QString(40, 'a')},
                                  {"publisher_data", server.version(true)}};
    const QJsonObject item{{"identity", identity},
                           {"snapshots", QJsonArray{QJsonObject{{"observation", observation}}}}};
    server.responses["/api/v1/dependency-releases/query"] =
        QJsonObject{{"schema", "bugg-dependency-releases-v1"}, {"items", QJsonArray{item}}};
    ContentCatalogService service(nullptr, server.endpoints());
    service.select_sources({"BUGG", "官方"}, server.endpoints().bugg_base);
    QSignalSpy finished(&service, &ContentCatalogPort::finished);
    QVariantMap query{{"operation", "plan"}, {"publisher", "Modrinth"},
                      {"kind", "mod"},       {"projectId", "root"},
                      {"versionId", "v1"},   {"gameVersion", server.game_version},
                      {"loader", "fabric"}};
    service.query(1, query);
    QTRY_COMPARE(finished.size(), 1);
    const auto result = finished.last()[1].toMap();
    QVERIFY2(!result.contains("error"), qPrintable(result.value("error").toString()));
    for (const auto& url : server.requests) QVERIFY(!url.path().endsWith("/version/v1"));
    server.requests.clear();
    server.responses["/api/v1/dependency-releases/query"] = QJsonObject{
        {"schema", "bugg-dependency-releases-v1"},
        {"items", QJsonArray{QJsonObject{
                      {"identity", identity}, {"state", "missing"}, {"snapshots", QJsonArray{}}}}}};
    query["nonce"] = 1;
    service.query(2, query);
    QTRY_COMPARE(finished.size(), 2);
    QVERIFY(!finished.last()[1].toMap().contains("error"));
    bool fetched = false;
    for (const auto& url : server.requests) fetched |= url.path().endsWith("/version/v1");
    QVERIFY(fetched);
    service.shutdown();
    QTRY_VERIFY(!service.busy());
  }
  void shader_core_choices_keep_exact_publisher_and_release() {
    ContentServer server;
    server.kind = "shader";
    server.shader_loader = "fabric";
    server.cf_core_project = "100";
    server.unavailable_projects.insert("oculus");
    auto first = server.version(true, "one", "iris");
    auto second = server.version(true, "two", "iris");
    first["name"] = "one";
    second["name"] = "two";
    server.responses["/mr/project/iris/version"] = QJsonArray{first, second};
    auto cf = server.version(false);
    cf["gameVersions"] = QJsonArray{server.game_version, "Fabric"};
    server.responses["/cf/mods/100/files"] =
        QJsonObject{{"data", QJsonArray{cf}}, {"pagination", QJsonObject{{"totalCount", 1}}}};
    ContentCatalogService service(nullptr, server.endpoints());
    QSignalSpy finished(&service, &ContentCatalogPort::finished);
    QVariantMap query{{"operation", "plan"}, {"publisher", "Modrinth"},
                      {"kind", "shader"},    {"projectId", "root"},
                      {"versionId", "v1"},   {"gameVersion", server.game_version},
                      {"loader", "fabric"}};
    service.query(1, query);
    QTRY_COMPARE(finished.size(), 1);
    auto result = finished.last()[1].toMap();
    QVERIFY2(!result.contains("error"), qPrintable(result.value("error").toString()));
    const auto support = result.value("shaderSupport").toMap();
    const auto choices = support.value("choices").toList();
    QCOMPARE(choices.size(), 3);
    QCOMPARE(choices[0].toMap().value("status").toString(), "dependency_unknown");
    query["shaderRuntimeChoice"] = "Modrinth/iris/two";
    service.query(2, query);
    QTRY_COMPARE(finished.size(), 2);
    result = finished.last()[1].toMap();
    QVERIFY2(!result.contains("error"), qPrintable(result.value("error").toString()));
    QCOMPARE(result.value("shaderSupport").toMap().value("choice").toString(), "Modrinth/iris/two");
    QCOMPARE(result.value("files").toList().last().toMap().value("versionId").toString(), "two");
    service.shutdown();
    QTRY_VERIFY(!service.busy());
  }
  void shader_manual_review_requires_exact_target_and_file_lock() {
    ContentServer server;
    server.kind = "shader";
    server.shader_loader = "fabric";
    server.unavailable_projects.insert("oculus");
    auto first = server.version(true, "one", "iris");
    auto second = server.version(true, "two", "iris");
    auto files = second["files"].toArray();
    auto file = files[0].toObject();
    file["hashes"] = QJsonObject{{"sha1", server.shader_hash}, {"sha256", QString(64, 'd')}};
    files[0] = file;
    second["files"] = files;
    server.responses["/mr/project/iris/version"] = QJsonArray{first, second};
    QJsonObject mark{{"game_version", server.game_version},
                     {"loader", "fabric"},
                     {"loader_version", "0.16.0"},
                     {"state", "available"},
                     {"core", QJsonObject{{"provider", "modrinth"},
                                          {"project_id", "iris"},
                                          {"release_id", "two"},
                                          {"sha256", QString(64, 'd')}}},
                     {"dependencies", QJsonArray{}}};
    server.responses["/api/v1/shader-compatibility"] =
        QJsonObject{{"schema", "bugg-shader-compatibility-v1"}, {"items", QJsonArray{mark}}};
    ContentCatalogService service(nullptr, server.endpoints());
    service.select_sources({"BUGG", "官方"}, server.endpoints().bugg_base);
    QSignalSpy finished(&service, &ContentCatalogPort::finished);
    QVariantMap query{{"operation", "plan"}, {"publisher", "Modrinth"},
                      {"kind", "shader"},    {"projectId", "root"},
                      {"versionId", "v1"},   {"gameVersion", server.game_version},
                      {"loader", "fabric"},  {"loaderVersion", "0.16.0"}};
    service.query(1, query);
    QTRY_COMPARE(finished.size(), 1);
    auto result = finished.last()[1].toMap();
    QVERIFY2(!result.contains("error"), qPrintable(result.value("error").toString()));
    QCOMPARE(result.value("shaderSupport").toMap().value("choice").toString(), "Modrinth/iris/two");
    query["loaderVersion"] = "0.16.1";
    service.query(2, query);
    QTRY_COMPARE(finished.size(), 2);
    result = finished.last()[1].toMap();
    QCOMPARE(result.value("shaderSupport").toMap().value("choice").toString(), "Modrinth/iris/one");
    query["loaderVersion"] = "0.16.0";
    query["nonce"] = 1;
    mark["state"] = "unavailable";
    mark["note"] = "Exact reviewed failure";
    server.responses["/api/v1/shader-compatibility"] =
        QJsonObject{{"schema", "bugg-shader-compatibility-v1"}, {"items", QJsonArray{mark}}};
    service.query(3, query);
    QTRY_COMPARE(finished.size(), 3);
    result = finished.last()[1].toMap();
    QCOMPARE(result.value("shaderSupport").toMap().value("choices").toList().size(), 1);
    service.shutdown();
    QTRY_VERIFY(!service.busy());
  }
  void shader_core_falls_back_to_curseforge_for_exact_target() {
    ContentServer server;
    server.kind = "shader";
    server.game_version = "26.1.1";
    server.shader_loader = "neoforge";
    server.no_shader_core = true;
    server.cf_core_project = "100";
    auto file = server.version(false);
    file["id"] = 7867946;
    file["fileName"] = "iris-neoforge.jar";
    file["gameVersions"] = QJsonArray{"26.1.1", "NeoForge"};
    server.responses["/cf/mods/100/files"] =
        QJsonObject{{"data", QJsonArray{file}}, {"pagination", QJsonObject{{"totalCount", 1}}}};
    ContentCatalogService service(nullptr, server.endpoints());
    QSignalSpy finished(&service, &ContentCatalogPort::finished);
    QVariantMap query{{"operation", "plan"},  {"publisher", "Modrinth"},
                      {"kind", "shader"},     {"projectId", "root"},
                      {"versionId", "v1"},    {"gameVersion", "26.1.1"},
                      {"loader", "neoforge"}, {"offset", 40}};
    service.query(1, query);
    QTRY_COMPARE(finished.size(), 1);
    const auto result = finished.last()[1].toMap();
    QVERIFY2(!result.contains("error"), qPrintable(result.value("error").toString()));
    const auto core = result.value("files").toList().last().toMap();
    QCOMPARE(core.value("publisher").toString(), "CurseForge");
    QCOMPARE(core.value("projectId").toString(), "100");
    QCOMPARE(core.value("versionId").toString(), "7867946");
    QVERIFY(core.value("prerequisite").toBool());
    server.responses["/cf/mods/100/files/7867946"] = QJsonObject{{"data", file}};
    query["shaderRuntimeHash"] = QString(40, 'a');
    query["shaderRuntimeCurseForgeProject"] = "100";
    query["shaderRuntimeCurseForgeVersion"] = "7867946";
    service.query(2, query);
    QTRY_COMPARE(finished.size(), 2);
    QVERIFY2(!finished.last()[1].toMap().contains("error"),
             qPrintable(finished.last()[1].toMap().value("error").toString()));
    QVERIFY(finished.last()[1].toMap().value("shaderSupport").toMap().value("installed").toBool());
    QTemporaryDir root;
    const auto directory = root.path() + "/versions/fixture";
    const auto existing = directory + "/mods/renamed-iris.jar";
    const auto cancelled = std::make_shared<std::atomic_bool>(false);
    archive_write(existing, {}, {{"net/irisshaders/iris/Iris.class", "fixture"}}, cancelled, {});
    const auto actual_hash = QString::fromLatin1(file_digest(existing, "sha1", cancelled));
    file["hashes"] = QJsonArray{QJsonObject{{"algo", 1}, {"value", actual_hash}}};
    // The hash lookup must identify the same bytes as the saved CF file.
    auto matched = server.version(true, "older-core", "iris");
    auto matched_files = matched["files"].toArray();
    auto matched_file = matched_files[0].toObject();
    matched_file["hashes"] = QJsonObject{{"sha1", actual_hash}};
    matched_files[0] = matched_file;
    matched["files"] = matched_files;
    server.responses["/mr/version_file/" + actual_hash] = matched;
    server.responses["/cf/mods/100/files/7867946"] = QJsonObject{{"data", file}};
    const QJsonObject saved_core{{"publisher", "CurseForge"},
                                 {"projectId", "100"},
                                 {"versionId", "7867946"},
                                 {"hashes", QJsonObject{{"sha1", actual_hash}}}};
    const QJsonObject saved_pack{{"resources", QJsonArray{saved_core}}};
    write_json(directory + "/fixture.json",
               {{"id", "fixture"},
                {"bugg", QJsonObject{{"version", "26.1.1"}, {"loader", "neoforge"}}},
                {"buggcraftModpack", saved_pack}});
    GameOperations operation(root.path(), root.path(), {"官方"}, cancelled,
                             [](double, const QString&) {});
    const ContentRequest request = [endpoints = server.endpoints()](const QVariantMap& value,
                                                                    const Cancellation& flag) {
      return request_content(value, {"官方"}, endpoints, flag);
    };
    auto future = QtConcurrent::run(
        [&] { return operation.prepare_content_install("fixture", result, request); });
    QTRY_VERIFY_WITH_TIMEOUT(future.isFinished(), 15000);
    const auto reused = future.result().value("shaderSupport").toMap();
    QVERIFY(reused.value("installed").toBool());
    QCOMPARE(reused.value("path").toString(), "mods/renamed-iris.jar");
    query["shaderRuntimeHash"] = QString(40, 'b');
    service.query(3, query);
    QTRY_COMPARE(finished.size(), 3);
    QVERIFY(finished.last()[1].toMap().contains("error"));
    query.remove("shaderRuntimeHash");
    query.remove("shaderRuntimeCurseForgeProject");
    query.remove("shaderRuntimeCurseForgeVersion");
    file["gameVersions"] = QJsonArray{"26.1.1", "Fabric"};
    server.responses["/cf/mods/100/files"] =
        QJsonObject{{"data", QJsonArray{file}}, {"pagination", QJsonObject{{"totalCount", 1}}}};
    query["offset"] = 41;
    service.query(4, query);
    QTRY_COMPARE(finished.size(), 4);
    QVERIFY(finished.last()[1].toMap().contains("error"));
    service.shutdown();
    QTRY_VERIFY(!service.busy());
  }
  void shader_rules_match_loader_build_without_replacing_pinned_dependencies() {
    ContentServer server;
    server.kind = "shader";
    server.game_version = "26.3";
    server.shader_loader = "neoforge";
    server.unavailable_projects.insert("oculus");
    server.compatibility_rules =
        QJsonArray{QJsonObject{{"publisher", "Modrinth"},
                               {"projectId", "iris"},
                               {"versionId", "v1"},
                               {"gameVersion", "26.3"},
                               {"loader", "neoforge"},
                               {"minLoaderVersion", "26.3.0.65"},
                               {"reason", "Pinned Sodium is incompatible with this loader"},
                               {"reference", "https://github.com/CaffeineMC/sodium/pull/3948"}}};
    ContentCatalogService service(nullptr, server.endpoints());
    QSignalSpy finished(&service, &ContentCatalogPort::finished);
    QVariantMap query{{"operation", "plan"},  {"publisher", "Modrinth"},
                      {"kind", "shader"},     {"projectId", "root"},
                      {"versionId", "v1"},    {"gameVersion", "26.3"},
                      {"loader", "neoforge"}, {"loaderVersion", "26.3.0.64-beta"}};
    service.query(1, query);
    QTRY_COMPARE(finished.size(), 1);
    QVERIFY2(!finished.last()[1].toMap().contains("error"),
             qPrintable(finished.last()[1].toMap().value("error").toString()));
    query["loaderVersion"] = "26.3.0.101";
    service.query(2, query);
    QTRY_COMPARE(finished.size(), 2);
    QVERIFY(finished.last()[1].toMap().value("error").toString().contains("Pinned Sodium"));
    QVERIFY(!finished.last()[1].toMap().contains("files"));
    query["gameVersion"] = "1.21.11";
    service.query(3, query);
    QTRY_COMPARE(finished.size(), 3);
    QVERIFY(finished.last()[1].toMap().contains("error"));
    query["gameVersion"] = "26.3";
    query["loader"] = "fabric";
    server.shader_loader = "fabric";
    service.query(4, query);
    QTRY_COMPARE(finished.size(), 4);
    QVERIFY2(!finished.last()[1].toMap().contains("error"),
             qPrintable(finished.last()[1].toMap().value("error").toString()));
    service.shutdown();
    QTRY_VERIFY(!service.busy());
  }
  void curseforge_core_uses_exact_same_artifact_dependencies_and_rules() {
    ContentServer server;
    server.game_version = "26.3";
    server.shader_loader = "neoforge";
    server.cf_core_project = "100";
    auto cf = server.version(false);
    cf["gameVersions"] = QJsonArray{"26.3", "NeoForge"};
    cf["dependencies"] = QJsonArray{QJsonObject{{"modId", 999}, {"relationType", 3}}};
    auto core = server.version(true, "vcore", "iris");
    core["dependencies"] = QJsonArray{QJsonObject{
        {"project_id", "dep"}, {"version_id", "vdep"}, {"dependency_type", "required"}}};
    auto pinned = server.version(true, "vdep", "dep");
    pinned["loaders"] = QJsonArray{"neoforge"};
    const auto hash_route = "/mr/version_file/" + QString(40, 'a');
    server.responses["/cf/mods/100/files/200"] = QJsonObject{{"data", cf}};
    server.responses[hash_route] = core;
    server.responses["/mr/version/vdep"] = pinned;
    server.compatibility_rules =
        QJsonArray{QJsonObject{{"publisher", "Modrinth"},
                               {"projectId", "iris"},
                               {"versionId", "vcore"},
                               {"gameVersion", "26.3"},
                               {"loader", "neoforge"},
                               {"minLoaderVersion", "26.3.0.65"},
                               {"reason", "Iris pinned Sodium conflict"},
                               {"reference", "https://example.org/author"}}};
    ContentCatalogService service(nullptr, server.endpoints());
    QSignalSpy finished(&service, &ContentCatalogPort::finished);
    QVariantMap query{{"operation", "plan"},  {"publisher", "CurseForge"},
                      {"kind", "mod"},        {"projectId", "100"},
                      {"versionId", "200"},   {"gameVersion", "26.3"},
                      {"loader", "neoforge"}, {"loaderVersion", "26.3.0.64"}};
    service.query(1, query);
    QTRY_COMPARE(finished.size(), 1);
    const auto result = finished.last()[1].toMap();
    QVERIFY2(!result.contains("error"), qPrintable(result.value("error").toString()));
    const auto files = result.value("files").toList();
    QCOMPARE(files.size(), 2);
    QCOMPARE(files.first().toMap().value("publisher").toString(), "CurseForge");
    QCOMPARE(files.first().toMap().value("versionId").toString(), "200");
    QCOMPARE(files.last().toMap().value("publisher").toString(), "Modrinth");
    QCOMPARE(files.last().toMap().value("versionId").toString(), "vdep");
    for (const auto& url : server.requests)
      QVERIFY2(!url.path().contains("/mods/999"),
               "Must not select the latest unpinned CF dependency");
    query["loaderVersion"] = "26.3.0.76";
    service.query(2, query);
    QTRY_COMPARE(finished.size(), 2);
    QVERIFY(finished.last()[1].toMap().value("error").toString().contains("pinned Sodium"));
    query["loaderVersion"] = "26.3.0.64";
    query["nonce"] = 1;
    auto wrong = core;
    wrong["files"] = QJsonArray{};
    server.responses[hash_route] = wrong;
    service.query(3, query);
    QTRY_COMPARE(finished.size(), 3);
    QVERIFY(finished.last()[1].toMap().contains("error"));
    server.responses[hash_route] = core;
    server.responses["/mr/version/vdep"] = QJsonObject{};
    query["nonce"] = 2;
    service.query(4, query);
    QTRY_COMPARE(finished.size(), 4);
    QVERIFY(finished.last()[1].toMap().contains("error"));
    service.shutdown();
    QTRY_VERIFY(!service.busy());
  }
  void curseforge_shader_file_requires_explicit_target_game() {
    ContentServer server;
    server.kind = "shader";
    auto file = server.version(false);
    file["gameVersions"] = QJsonArray{"1.17.1", "1.21", "1.16.5", "26.2", "26.3", "Iris"};
    ContentCatalogService service(nullptr, server.endpoints());
    QSignalSpy finished(&service, &ContentCatalogPort::finished);
    QVariantMap query{{"operation", "versions"},
                      {"publisher", "CurseForge"},
                      {"kind", "shader"},
                      {"projectId", "100"},
                      {"gameVersion", "26.3"}};
    int serial = 0;
    for (const auto& game : {"26.3", "26.2", "26.4"}) {
      server.responses["/cf/mods/100/files"] = QJsonObject{{"data", QJsonArray{file}}};
      query["gameVersion"] = game;
      service.query(++serial, query);
      QTRY_COMPARE(finished.size(), serial);
      QCOMPARE(finished.last()[1].toMap().value("versions").toList().size(),
               QString(game) == "26.4" ? 0 : 1);
      if (QString(game) != "26.4") {
        const auto version = finished.last()[1].toMap().value("versions").toList().first().toMap();
        QVERIFY(version.value("loaders").toStringList().contains("iris"));
        QVERIFY(!version.value("gameVersions").toStringList().contains("Iris"));
      }
    }
    file["gameVersions"] = QJsonArray{"26.2", "Iris"};
    server.responses["/cf/mods/100/files"] = QJsonObject{{"data", QJsonArray{file}}};
    query["gameVersion"] = "26.3";
    query["nonce"] = 1;
    service.query(++serial, query);
    QTRY_COMPARE(finished.size(), serial);
    QVERIFY(finished.last()[1].toMap().value("versions").toList().isEmpty());
    file["gameVersions"] = QJsonArray{"26.3", "OptiFine"};
    server.responses["/cf/mods/100/files/200"] = QJsonObject{{"data", file}};
    query["operation"] = "plan";
    query["versionId"] = "200";
    query["loader"] = "neoforge";
    service.query(++serial, query);
    QTRY_COMPARE(finished.size(), serial);
    QVERIFY(finished.last()[1].toMap().value("error").toString().contains("Iris"));
    service.shutdown();
    QTRY_VERIFY(!service.busy());
  }
  void mod_preflight_rebinds_legacy_plan_to_actual_loader_build() {
    QTemporaryDir root;
    write_json(root.filePath("versions/fixture/fixture.json"),
               {{"id", "fixture"},
                {"bugg", QJsonObject{{"version", "26.3"},
                                     {"loader", "NeoForge"},
                                     {"loaderVersion", "26.3.0.76"}}}});
    const auto cancelled = std::make_shared<std::atomic_bool>(false);
    GameOperations operations(root.path(), root.path(), {"官方"}, cancelled,
                              [](double, const QString&) {});
    auto plan = content_plan("mod", "content");
    plan["query"] = QVariantMap{{"gameVersion", "26.3"}, {"loader", "neoforge"}};
    QVariantMap received;
    const ContentRequest request = [&](const QVariantMap& query, const Cancellation&) {
      received = query;
      auto current = plan;
      current["query"] = query;
      return current;
    };
    const auto effective = operations.prepare_content_install("fixture", plan, request);
    QCOMPARE(received.value("loaderVersion").toString(), "26.3.0.76");
    QCOMPARE(effective.value("query").toMap(), received);
    QVERIFY_EXCEPTION_THROWN(operations.prepare_content_install("fixture", plan, {}),
                             std::runtime_error);
  }
  void shader_prerequisite_failure_blocks_pack() {
    for (const auto& mode : {"success", "failure", "cancel"}) {
      ContentFilesServer server;
      if (QString(mode) == "failure") server.failing = "dependency-0.jar";
      QTemporaryDir root;
      const auto directory = root.path() + "/versions/fixture";
      write_json(
          directory + "/fixture.json",
          {{"id", "fixture"}, {"bugg", QJsonObject{{"version", "1.21.1"}, {"loader", "fabric"}}}});
      auto plan = dependency_plan(server.payload, 2);
      auto files = plan.value("files").toList();
      auto primary = files.first().toMap();
      primary["kind"] = "shader";
      primary["filename"] = "sample.zip";
      files[0] = primary;
      plan["files"] = files;
      plan["kind"] = "shader";
      plan["query"] = QVariantMap{{"gameVersion", "1.21.1"}, {"loader", "fabric"}};
      plan["shaderSupport"] = QVariantMap{
          {"name", "Iris"},
          {"loader", "fabric"},
          {"runtimes",
           QVariantList{QVariantMap{{"markers", QStringList{"net/irisshaders/iris/Iris.class"}}}}}};
      const auto cancelled = std::make_shared<std::atomic_bool>(false);
      auto future = QtConcurrent::run([=, path = root.path(), port = server.serverPort()] {
        ContentFilesHttp http(port);
        GameOperations operation(
            path, path, {"官方"}, cancelled, [](double, const QString&) {}, 4, &http);
        operation.set_content_progress([&](const QVariantMap& row) {
          if (QString(mode) == "cancel" && row.value("state") == "downloading")
            cancelled->store(true);
        });
        try {
          operation.install_content({{"id", "fixture"}, {"plan", plan}});
          return QString{};
        } catch (const std::exception& error) {
          return QString::fromUtf8(error.what());
        }
      });
      QTRY_VERIFY_WITH_TIMEOUT(future.isFinished(), 15000);
      QVERIFY2(future.result().isEmpty() == (QString(mode) == "success"),
               qPrintable(future.result()));
      QCOMPARE(QFileInfo::exists(directory + "/shaderpacks/sample.zip"),
               QString(mode) == "success");
      if (QString(mode) == "success") {
        QVERIFY(QFileInfo::exists(directory + "/mods/dependency-0.jar"));
        QVERIFY(QFileInfo::exists(directory + "/mods/dependency-1.jar"));
      }
    }
  }
  void dependency_files_share_concurrency_and_report_speed() {
    for (const auto& mode : {"normal", "failure", "cancel"}) {
      ContentFilesServer server;
      if (QString(mode) == "failure") server.failing = "dependency-2.jar";
      QTemporaryDir root;
      const auto directory = root.path() + "/versions/fixture";
      write_json(
          directory + "/fixture.json",
          {{"id", "fixture"}, {"bugg", QJsonObject{{"version", "1.21.1"}, {"loader", "fabric"}}}});
      put(directory + "/mods/sample.jar", server.payload);
      const auto plan = dependency_plan(server.payload);
      const auto cancelled = std::make_shared<std::atomic_bool>(false);
      auto work = QtConcurrent::run([=, port = server.serverPort(), path = root.path()] {
        ContentFilesHttp http(port);
        QVariantList details;
        bool speed_seen = false;
        GameOperations operation(
            path, path, {"官方"}, cancelled, [](double, const QString&) {}, 4, &http);
        operation.set_content_progress([&](const QVariantMap& item) {
          details.append(item);
          if (item.value("state") == "downloading" && item.value("received").toLongLong() > 0) {
            speed_seen = speed_seen || !item.value("speedText").toString().startsWith('0');
            if (QString(mode) == "cancel") cancelled->store(true);
          }
        });
        QVariantMap result;
        try {
          result =
              operation.install_content({{"kind", "content"}, {"id", "fixture"}, {"plan", plan}});
        } catch (const std::exception& error) {
          result["error"] = QString::fromUtf8(error.what());
        }
        result["speedSeen"] = speed_seen;
        result["details"] = details;
        return result;
      });
      QTRY_VERIFY_WITH_TIMEOUT(work.isFinished(), 15000);
      const auto result = work.result();
      QVERIFY(server.peak > 1);
      QVERIFY(server.peak <= 4);
      const auto records = read_json(directory + "/fixture.json")["buggcraftModpack"]
                               .toObject()["resources"]
                               .toArray();
      if (QString(mode) == "cancel") {
        QVERIFY(result.contains("error"));
        QCOMPARE(records.size(), 1);
      } else {
        QVERIFY2(!result.contains("error"), qPrintable(result.value("error").toString()));
        QVERIFY(result.value("speedSeen").toBool());
        QCOMPARE(result.value("missingDependencies").toList().size(),
                 QString(mode) == "failure" ? 1 : 0);
        QCOMPARE(records.size(), QString(mode) == "failure" ? 6 : 7);
        QCOMPARE(server.requests, 6);
      }
    }
  }
  void content_concurrency_measurement() {
    if (qgetenv("BUGG_TEST_CONTENT_BENCHMARK") != "1")
      QSKIP("Explicit content concurrency benchmark only");
    ContentFilesServer server;
    const auto plan = dependency_plan(server.payload);
    QJsonArray measurements;
    for (int iteration = 0; iteration < 5; ++iteration) {
      for (const bool serial : {iteration % 2 == 0, iteration % 2 != 0}) {
        QTemporaryDir root;
        const auto directory = root.path() + "/versions/fixture";
        write_json(directory + "/fixture.json",
                   {{"id", "fixture"},
                    {"bugg", QJsonObject{{"version", "1.21.1"}, {"loader", "fabric"}}}});
        put(directory + "/mods/sample.jar", server.payload);
        QTRY_COMPARE(server.active, 0);
        server.peak = server.requests = 0;
        auto work = QtConcurrent::run([=, port = server.serverPort(), path = root.path()] {
          ContentFilesHttp http(port);
          GameOperations operation(
              path, path, {"官方"}, std::make_shared<std::atomic_bool>(false),
              [](double, const QString&) {}, 6, &http);
          QElapsedTimer clock;
          clock.start();
          if (serial) {
            // Reference the previous per-dependency fetch/commit loop, with the
            // same current transfer, hashing, payload and transaction code.
            for (const auto& value : plan.value("files").toList()) {
              auto file = value.toMap();
              file["dependency"] = false;
              auto single = plan;
              single["files"] = QVariantList{file};
              operation.install_content({{"kind", "content"}, {"id", "fixture"}, {"plan", single}});
            }
          } else
            operation.install_content({{"kind", "content"}, {"id", "fixture"}, {"plan", plan}});
          return clock.elapsed();
        });
        QTRY_VERIFY_WITH_TIMEOUT(work.isFinished(), 15000);
        QCOMPARE(server.requests, 6);
        QCOMPARE(read_json(directory + "/fixture.json")["buggcraftModpack"]
                     .toObject()["resources"]
                     .toArray()
                     .size(),
                 7);
        for (const auto& value : plan.value("files").toList()) {
          QFile file(directory + "/mods/" + value.toMap().value("filename").toString());
          QVERIFY(file.open(QIODevice::ReadOnly));
          QCOMPARE(file.readAll(),
                   content_fixture_payload(server.payload, file.fileName().section('/', -1)));
        }
        measurements.append(QJsonObject{{"referenceSerialLoop", serial},
                                        {"elapsedMs", work.result()},
                                        {"peakConnections", server.peak},
                                        {"requests", server.requests},
                                        {"downloadBytes", 6 * server.payload.size()},
                                        {"iteration", iteration}});
      }
    }
    put(QCoreApplication::applicationDirPath() + "/verification/content/concurrency-report.json",
        QJsonDocument(measurements).toJson());
  }
  void shader_loader_addition_preserves_existing_game() {
    for (int mode = 0; mode < 3; ++mode) {
      QTemporaryDir root;
      const auto game = root.path() + "/game", directory = game + "/versions/Original";
      const auto final = directory + "/Original.json";
      const QJsonObject original{
          {"id", "Original"},
          {"jar", "Original"},
          {"bugg", QJsonObject{{"version", "1.21.1"}, {"loader", "vanilla"}, {"custom", true}}}};
      write_json(final, original);
      put(directory + "/saves/My world/level.dat", "world must remain");
      put(directory + "/options.txt", "user preferences");
      put(directory + "/Original.jar", "existing game client");
      ContentFilesServer server;
      server.payload = "loader library";
      const auto payload = content_fixture_payload(server.payload, "loader-1.jar");
      const QJsonObject artifact{
          {"path", "net/fabricmc/fabric-loader/1/loader-1.jar"},
          {"url", "https://maven.fabricmc.net/loader-1.jar"},
          {"size", payload.size()},
          {"sha1", QString::fromLatin1(
                       QCryptographicHash::hash(payload, QCryptographicHash::Sha1).toHex())}};
      const QJsonObject library{{"name", "net.fabricmc:fabric-loader:1"},
                                {"downloads", QJsonObject{{"artifact", artifact}}}};
      server.profile =
          QJsonDocument(
              QJsonObject{{"id", "fabric-generated"},
                          {"mainClass", "net.fabricmc.loader.impl.launch.knot.KnotClient"},
                          {"libraries", QJsonArray{library}}})
              .toJson();
      if (mode == 1) server.failing = "/profile/json";
      auto cancelled = std::make_shared<std::atomic_bool>(mode == 2);
      const QVariantMap spec{{"name", "Original"},
                             {"game", "1.21.1"},
                             {"loader", "fabric"},
                             {"loaderVersion", "1"},
                             {"updateExisting", true}};
      auto work = QtConcurrent::run([&] {
        ContentFilesHttp transport(server.serverPort());
        GameOperations operation(
            game, root.path() + "/portable", {"官方"}, cancelled, [](double, const QString&) {}, 4,
            &transport);
        try {
          operation.install(spec);
          return QString();
        } catch (const std::exception& e) {
          return QString::fromUtf8(e.what());
        }
      });
      QTRY_VERIFY_WITH_TIMEOUT(work.isFinished(), 15000);
      if (mode == 0)
        QVERIFY2(work.result().isEmpty(), qPrintable(work.result()));
      else
        QVERIFY(!work.result().isEmpty());
      const auto metadata = read_json(final);
      if (mode == 0) {
        QCOMPARE(instance_descriptor(metadata).value("loader").toString(), "Fabric");
        QCOMPARE(metadata["id"].toString(), "Original");
        QCOMPARE(metadata["jar"].toString(), "Original");
        QVERIFY(metadata["bugg"].toObject()["custom"].toBool());
        QCOMPARE(server.requests,
                 2);  // Profile and loader only: no client/assets/Java installation.
      } else
        QCOMPARE(metadata, original);
      cancelled->store(false);
      QCOMPARE(file_digest(directory + "/saves/My world/level.dat", "sha1", cancelled),
               QCryptographicHash::hash("world must remain", QCryptographicHash::Sha1).toHex());
      QFile options(directory + "/options.txt"), client(directory + "/Original.jar");
      QVERIFY(options.open(QIODevice::ReadOnly) && client.open(QIODevice::ReadOnly));
      QCOMPARE(options.readAll(), QByteArray("user preferences"));
      QCOMPARE(client.readAll(), QByteArray("existing game client"));
      QCOMPARE(QDir(game + "/versions").entryList(QDir::Dirs | QDir::NoDotAndDotDot),
               QStringList{"Original"});
    }
  }
  void guided_creation_uses_hidden_publication_and_retry() {
    QTemporaryDir root;
    const auto game = root.path() + "/game";
    const auto plan = content_plan("mod", "content");
    const QVariantMap spec{
        {"kind", "installWithContent"}, {"name", "Guided game"},     {"game", "1.21.1"},
        {"loader", "fabric"},           {"loaderVersion", "0.16.0"}, {"plan", plan}};
    const auto staging_id =
        ".content-game-" +
        QString::fromLatin1(QCryptographicHash::hash(
                                QJsonDocument::fromVariant(spec).toJson(QJsonDocument::Compact),
                                QCryptographicHash::Sha256)
                                .toHex()
                                .left(20));
    const auto stage = game + "/versions/" + staging_id;
    write_json(
        stage + '/' + staging_id + ".json",
        {{"id", staging_id}, {"bugg", QJsonObject{{"version", "1.21.1"}, {"loader", "fabric"}}}});
    put(stage + "/mods/sample.jar", "content");
    auto cancelled = std::make_shared<std::atomic_bool>(true);
    GameOperations operation(game, root.path() + "/portable", {"官方"}, cancelled,
                             [](double, const QString&) {});
    QVERIFY_EXCEPTION_THROWN(operation.install_with_content(spec), std::runtime_error);
    QVERIFY(!QFileInfo::exists(game + "/versions/Guided game"));
    cancelled->store(false);
    QCOMPARE(operation.install_with_content(spec).value("instance").toString(), "Guided game");
    const auto metadata = read_json(game + "/versions/Guided game/Guided game.json");
    QCOMPARE(metadata["buggcraftModpack"].toObject()["resources"].toArray().size(), 1);
    QVERIFY(!QFileInfo::exists(stage));
    QVERIFY(QFileInfo::exists(game + "/versions/Guided game/mods/sample.jar"));
    QVERIFY_EXCEPTION_THROWN(operation.install_with_content(spec), std::runtime_error);
  }
  void online_pack_uses_existing_import_transaction() {
    QTemporaryDir root;
    QVERIFY(root.isValid());
    const auto game = root.path() + "/game", portable = root.path() + "/portable";
    const auto cancelled = std::make_shared<std::atomic_bool>(false);
    const auto initial = root.path() + "/fixture.mrpack";
    const auto manifest =
        QJsonDocument(QJsonObject{{"formatVersion", 1},
                                  {"game", "minecraft"},
                                  {"versionId", "1.0"},
                                  {"name", "Online pack"},
                                  {"dependencies", QJsonObject{{"minecraft", "1.21.1"}}},
                                  {"files", QJsonArray{}}})
            .toJson();
    archive_write(initial, {},
                  {{"modrinth.index.json", manifest}, {"overrides/options.txt", "fixture:true"}},
                  cancelled, {});
    QFile file(initial);
    QVERIFY(file.open(QIODevice::ReadOnly));
    const auto bytes = file.readAll();
    file.close();
    auto plan = content_plan("modpack", bytes);
    auto files = plan.value("files").toList();
    auto entry = files.first().toMap();
    entry["filename"] = "fixture.mrpack";
    files[0] = entry;
    plan["files"] = files;
    const auto archive = portable + "/.buggcraft/content/" +
                         entry.value("hashes").toMap().value("sha1").toString() + "/fixture.mrpack";
    put(archive, bytes);
    const auto staging =
        ".import-" +
        QString::fromLatin1(
            QCryptographicHash::hash(
                (QFileInfo(archive).absoluteFilePath() +
                 ":Online pack:" + QString::number(bytes.size()) + ':' +
                 QString::number(QFileInfo(archive).lastModified().toMSecsSinceEpoch()))
                    .toUtf8(),
                QCryptographicHash::Sha256)
                .toHex()
                .left(20));
    // Seed the already-tested game install stage, then exercise real archive,
    // overrides, receipt and final publication through the new online branch.
    write_json(
        game + "/versions/" + staging + '/' + staging + ".json",
        {{"id", staging}, {"bugg", QJsonObject{{"version", "1.21.1"}, {"loader", "vanilla"}}}});
    GameOperations operation(game, portable, {"官方"}, cancelled, [](double, const QString&) {});
    const QVariantMap spec{{"kind", "onlinePack"}, {"instanceName", "Online pack"}, {"plan", plan}};
    QStringList phases;
    operation.set_content_progress([&](const QVariantMap& item) {
      const auto phase = item.value("state").toString();
      if (phases.isEmpty() || phases.last() != phase) phases.append(phase);
    });
    operation.install_content(spec);
    QCOMPARE(phases, (QStringList{"queued", "downloading", "installing", "done"}));
    QCOMPARE(read_json(game + "/versions/Online pack/Online pack.json")["id"].toString(),
             "Online pack");
    QVERIFY(QFileInfo::exists(game + "/versions/Online pack/options.txt"));
    QVERIFY_EXCEPTION_THROWN(operation.install_content(spec), std::runtime_error);
  }
  void live_categories_and_illustrated_details() {
    if (qgetenv("BUGG_TEST_LIVE_CONTENT") != "1") QSKIP("Explicit live network verification only");
    ContentCatalogService service;
    service.select_sources({"BUGG"});
    QSignalSpy finished(&service, &ContentCatalogPort::finished);
    quint64 id = 0;
    QJsonArray report;
    for (const auto& publisher : {"Modrinth", "CurseForge"})
      for (const auto& kind : {"mod", "resourcepack", "shader", "modpack"}) {
        QVariantMap query{{"publisher", publisher}, {"kind", kind}, {"operation", "categories"}};
        service.query(++id, query);
        QTRY_COMPARE_WITH_TIMEOUT(finished.size(), int(id), 90000);
        const auto categories_result = finished.last()[1].toMap();
        QVERIFY2(!categories_result.contains("error"),
                 qPrintable(QString(publisher) + '/' + kind + ": " +
                            categories_result.value("error").toString()));
        const auto categories = categories_result.value("categories").toList();
        QVERIFY(!categories.isEmpty());
        query["operation"] = "search";
        query["category"] = categories.first().toMap().value("id");
        service.query(++id, query);
        QTRY_COMPARE_WITH_TIMEOUT(finished.size(), int(id), 90000);
        const auto search = finished.last()[1].toMap();
        QVERIFY2(!search.contains("error"), qPrintable(QString(publisher) + '/' + kind + ": " +
                                                       search.value("error").toString()));
        const auto items = search.value("items").toList();
        QVERIFY(!items.isEmpty());
        query["operation"] = "detail";
        query["projectId"] = items.first().toMap().value("id");
        service.query(++id, query);
        QTRY_COMPARE_WITH_TIMEOUT(finished.size(), int(id), 90000);
        const auto detail = finished.last()[1].toMap();
        QVERIFY2(!detail.contains("error"), qPrintable(detail.value("error").toString()));
        const auto project = detail.value("project").toMap();
        QVERIFY2(!project.contains("bodyError"), qPrintable(project.value("bodyError").toString()));
        const auto body = project.value("body").toList();
        QVERIFY(!body.isEmpty());
        int images = project.value("gallery").toList().size();
        for (const auto& block : body) images += block.toMap().contains("image");
        report.append(
            QJsonObject{{"publisher", publisher},
                        {"kind", kind},
                        {"categories", categories.size()},
                        {"selectedCategory", categories.first().toMap().value("name").toString()},
                        {"project", project.value("title").toString()},
                        {"blocks", body.size()},
                        {"images", images}});
      }
    put(QCoreApplication::applicationDirPath() +
            "/verification/content/categories-details-live.json",
        QJsonDocument(report).toJson());
    service.shutdown();
    QTRY_VERIFY(!service.busy());
  }
  void live_curseforge_shader_version_and_core_dependency_audit() {
    if (qgetenv("BUGG_TEST_LIVE_VERSION_AUDIT") != "1") QSKIP("Explicit metadata-only audit");
    ContentCatalogService service;
    service.select_sources({"BUGG"});
    QSignalSpy finished(&service, &ContentCatalogPort::finished);
    QJsonArray evidence;
    QVariantMap query{{"operation", "versions"},
                      {"publisher", "CurseForge"},
                      {"kind", "shader"},
                      {"projectId", "627557"},
                      {"gameVersion", "26.3"}};
    service.query(1, query);
    QTRY_COMPARE_WITH_TIMEOUT(finished.size(), 1, 90000);
    auto result = finished.last()[1].toMap();
    QVERIFY2(!result.contains("error"), qPrintable(result.value("error").toString()));
    bool found = false;
    for (const auto& value : result.value("versions").toList()) {
      const auto version = value.toMap();
      if (version.value("id").toString() != "8884654") continue;
      found = true;
      QVERIFY(version.value("gameVersions").toStringList().contains("26.3"));
      QVERIFY(version.value("gameVersions").toStringList().contains("26.2"));
      QVERIFY(version.value("loaders").toStringList().contains("iris"));
      evidence.append(QJsonObject::fromVariantMap(version));
    }
    QVERIFY(found);
    query = {{"operation", "plan"},   {"publisher", "CurseForge"},   {"kind", "mod"},
             {"projectId", "455508"}, {"versionId", "9015109"},      {"gameVersion", "26.3"},
             {"loader", "neoforge"},  {"loaderVersion", "26.3.0.76"}};
    service.query(2, query);
    QTRY_COMPARE_WITH_TIMEOUT(finished.size(), 2, 90000);
    result = finished.last()[1].toMap();
    QVERIFY2(result.value("error").toString().contains("Sodium"),
             qPrintable(result.value("error").toString()));
    QVERIFY(!result.contains("files"));
    evidence.append(QJsonObject::fromVariantMap(result));
    query.remove("versionId");
    query["operation"] = "versions";
    query["gameVersion"] = "26.2";
    query["loaderVersion"] = "26.2.0.93";
    service.query(3, query);
    QTRY_COMPARE_WITH_TIMEOUT(finished.size(), 3, 90000);
    result = finished.last()[1].toMap();
    QVERIFY2(!result.contains("error"), qPrintable(result.value("error").toString()));
    QVERIFY(!result.value("versions").toList().isEmpty());
    query["versionId"] = result.value("versions").toList().first().toMap().value("id");
    query["operation"] = "plan";
    service.query(4, query);
    QTRY_COMPARE_WITH_TIMEOUT(finished.size(), 4, 90000);
    result = finished.last()[1].toMap();
    QVERIFY2(!result.contains("error"), qPrintable(result.value("error").toString()));
    bool pinned = false;
    for (const auto& value : result.value("files").toList()) {
      const auto file = value.toMap();
      if (file.value("projectId").toString() != "AANobbMI") continue;
      pinned = true;
      QCOMPARE(file.value("publisher").toString(), "Modrinth");
      QCOMPARE(file.value("versionId").toString(), "DmnNKsfS");
      QVERIFY(file.value("filename").toString().contains("0.9.2"));
    }
    QVERIFY(pinned);
    evidence.append(QJsonObject::fromVariantMap(result));
    put(QCoreApplication::applicationDirPath() + "/verification/content/cf-version-audit.json",
        QJsonDocument(evidence).toJson());
    service.shutdown();
    QTRY_VERIFY(!service.busy());
  }
  void live_shader_2611_neoforge_installation() {
    if (qgetenv("BUGG_TEST_LIVE_CONTENT") != "1") QSKIP("Explicit real core downloads only");
    ContentCatalogService service;
    QSignalSpy finished(&service, &ContentCatalogPort::finished);
    QVariantMap query{{"publisher", "Modrinth"},          {"kind", "shader"},
                      {"projectId", "izsIPI7a"},          {"operation", "versions"},
                      {"gameVersion", "26.1.1"},          {"loader", "neoforge"},
                      {"loaderVersion", "26.1.1.15-beta"}};
    service.query(1, query);
    QTRY_COMPARE_WITH_TIMEOUT(finished.size(), 1, 120000);
    auto result = finished.last()[1].toMap();
    QVERIFY2(!result.contains("error"), qPrintable(result.value("error").toString()));
    QVERIFY(!result.value("versions").toList().isEmpty());
    query["versionId"] = result.value("versions").toList().first().toMap().value("id");
    query["operation"] = "plan";
    service.query(2, query);
    QTRY_COMPARE_WITH_TIMEOUT(finished.size(), 2, 180000);
    const auto plan = finished.last()[1].toMap();
    QVERIFY2(!plan.contains("error"), qPrintable(plan.value("error").toString()));
    QTemporaryDir root;
    const auto directory = root.path() + "/versions/shader2611";
    write_json(directory + "/shader2611.json",
               {{"id", "shader2611"},
                {"bugg", QJsonObject{{"version", "26.1.1"},
                                     {"loader", "neoforge"},
                                     {"loaderVersion", "26.1.1.15-beta"}}}});
    const auto cancelled = std::make_shared<std::atomic_bool>(false);
    const auto request = service.requester();
    auto future = QtConcurrent::run([=, path = root.path()]() -> QString {
      try {
        GameOperations operation(path, path, supported_download_sources(), cancelled,
                                 [](double, const QString&) {});
        operation.install_content({{"id", "shader2611"}, {"plan", plan}}, request);
        return {};
      } catch (const std::exception& error) {
        return QString::fromUtf8(error.what());
      }
    });
    QTRY_VERIFY_WITH_TIMEOUT(future.isFinished(), 240000);
    const auto error = future.result();
    QVERIFY2(error.isEmpty(), qPrintable(error));
    QVERIFY(!QDir(directory + "/shaderpacks").entryList({"*.zip"}, QDir::Files).isEmpty());
    QVERIFY(!QDir(directory + "/mods").entryList({"*.jar"}, QDir::Files).isEmpty());
    service.shutdown();
    QTRY_VERIFY(!service.busy());
  }
  void live_shader_core_installation() {
    if (qgetenv("BUGG_TEST_LIVE_CONTENT") != "1") QSKIP("Explicit real core downloads only");
    ContentCatalogService service;
    QSignalSpy finished(&service, &ContentCatalogPort::finished);
    quint64 serial = 0;
    const auto cancelled = std::make_shared<std::atomic_bool>(false);
    QTemporaryDir root;
    QJsonArray evidence;
    QVariantMap query{{"publisher", "Modrinth"}, {"kind", "shader"}, {"query", "MakeUp"}};
    service.query(++serial, query);
    QTRY_COMPARE_WITH_TIMEOUT(finished.size(), int(serial), 90000);
    auto result = finished.last()[1].toMap();
    QVERIFY2(!result.contains("error"), qPrintable(result.value("error").toString()));
    QVERIFY(!result.value("items").toList().isEmpty());
    query["projectId"] = result.value("items").toList().first().toMap().value("id");
    for (const auto& pair : QList<QPair<QString, QString>>{{"1.20.1", "fabric"},
                                                           {"1.21.1", "neoforge"},
                                                           {"26.3", "neoforge"},
                                                           {"1.20.1", "forge"},
                                                           {"1.20.1", "quilt"}}) {
      query["operation"] = "detail";
      query["gameVersion"] = pair.first;
      query["loader"] = pair.second;
      service.query(++serial, query);
      QTRY_COMPARE_WITH_TIMEOUT(finished.size(), int(serial), 90000);
      result = finished.last()[1].toMap();
      QVERIFY2(!result.contains("error"), qPrintable(result.value("error").toString()));
      QVERIFY(!result.value("versions").toList().isEmpty());
      query["versionId"] = result.value("versions").toList().first().toMap().value("id");
      query["operation"] = "plan";
      service.query(++serial, query);
      QTRY_COMPARE_WITH_TIMEOUT(finished.size(), int(serial), 180000);
      const auto plan = finished.last()[1].toMap();
      QVERIFY2(!plan.contains("error"), qPrintable(plan.value("error").toString()));
      const auto support = plan.value("shaderSupport").toMap();
      QCOMPARE(support.value("id").toString(), pair.second == "forge" ? "oculus" : "iris");
      QVERIFY(plan.value("files").toList().size() >= 3);
      const auto instance = pair.first + '-' + pair.second;
      const auto directory = root.path() + "/versions/" + instance;
      write_json(
          directory + '/' + instance + ".json",
          {{"id", instance},
           {"bugg", QJsonObject{{"version", pair.first},
                                {"loader", pair.second == "fabric" ? "vanilla" : pair.second}}}});
      put(directory + "/saves/Existing world/level.dat", "unchanged world");
      put(directory + "/options.txt", "unchanged preferences");
      put(directory + '/' + instance + ".jar", "existing client is not replaced");
      const auto request = service.requester();
      auto future = QtConcurrent::run([=, path = root.path()] {
        GameOperations operation(path, path, supported_download_sources(), cancelled,
                                 [](double, const QString&) {});
        if (pair.second == "fabric")
          operation.install_with_content({{"id", instance},
                                          {"name", instance},
                                          {"game", pair.first},
                                          {"loader", "fabric"},
                                          {"loaderVersion", "0.16.14"},
                                          {"plan", plan}},
                                         request);
        else
          operation.install_content({{"id", instance}, {"plan", plan}}, request);
        return operation.check_content_install(instance, plan);
      });
      QTRY_VERIFY_WITH_TIMEOUT(future.isFinished(), 240000);
      const auto inspected = future.result();
      QVERIFY(!inspected.value("installed").toList().isEmpty());
      for (const auto& entry : QList<QPair<QString, QByteArray>>{
               {"saves/Existing world/level.dat", "unchanged world"},
               {"options.txt", "unchanged preferences"},
               {instance + ".jar", "existing client is not replaced"}}) {
        QFile file(directory + '/' + entry.first);
        QVERIFY(file.open(QIODevice::ReadOnly));
        QCOMPARE(file.readAll(), entry.second);
      }
      QJsonArray installed;
      QString core_path;
      for (const auto& value : plan.value("files").toList()) {
        const auto file = value.toMap();
        const auto path = directory +
                          (file.value("dependency").toBool() ? "/mods/" : "/shaderpacks/") +
                          file.value("filename").toString();
        QVERIFY(QFileInfo::exists(path));
        const auto hashes = file.value("hashes").toMap();
        for (auto it = hashes.begin(); it != hashes.end(); ++it)
          QCOMPARE(QString::fromLatin1(file_digest(path, it.key().toLatin1(), cancelled)),
                   it.value().toString());
        if (file.value("projectId") == (pair.second == "forge" ? "GchcoXML" : "YL57xq9U")) {
          core_path = path;
          const auto entries = archive_entries(path, cancelled);
          QVERIFY(entries.contains("net/irisshaders/iris/Iris.class") ||
                  entries.contains("net/coderbot/iris/Iris.class"));
          QVERIFY(entries.contains("fabric.mod.json") || entries.contains("META-INF/mods.toml") ||
                  entries.contains("META-INF/neoforge.mods.toml"));
        }
        installed.append(QJsonObject::fromVariantMap(file));
      }
      QVERIFY(!core_path.isEmpty());
      const auto renamed = directory + "/mods/renamed-shader-core.jar";
      QVERIFY(QFile::rename(core_path, renamed));
      auto reuse = QtConcurrent::run([=, path = root.path()] {
        GameOperations operation(path, path, supported_download_sources(), cancelled,
                                 [](double, const QString&) {});
        const auto effective = operation.prepare_content_install(instance, plan, request);
        operation.install_content({{"id", instance}, {"plan", effective}}, request);
        return effective.value("shaderSupport").toMap();
      });
      QTRY_VERIFY_WITH_TIMEOUT(reuse.isFinished(), 180000);
      QVERIFY(reuse.result().value("installed").toBool());
      QVERIFY(QFileInfo::exists(renamed));
      QVERIFY(!QFileInfo::exists(core_path));
      evidence.append(QJsonObject{{"game", pair.first},
                                  {"loader", pair.second},
                                  {"support", QJsonObject::fromVariantMap(support)},
                                  {"installedFiles", installed},
                                  {"renamedCoreReused", true}});
      if (pair.second == "fabric") {
        auto entry = evidence.last().toObject();
        entry["installedIntoExistingVanilla"] = true;
        entry["clientWorldSettingsPreserved"] = true;
        evidence.replace(evidence.size() - 1, entry);
      }
      put(QCoreApplication::applicationDirPath() + "/verification/shader-support/native-live.json",
          QJsonDocument(evidence).toJson());
    }
    query["gameVersion"] = "1.21.1";
    query["loader"] = "forge";
    query["operation"] = "plan";
    service.query(++serial, query);
    QTRY_COMPARE_WITH_TIMEOUT(finished.size(), int(serial), 180000);
    QVERIFY(finished.last()[1].toMap().contains("error"));
    service.shutdown();
    QTRY_VERIFY(!service.busy());
  }
  void live_publishers_and_real_downloads() {
    if (qgetenv("BUGG_TEST_LIVE_CONTENT") != "1") QSKIP("Explicit live network verification only");
    QTemporaryDir root;
    QVERIFY(root.isValid());
    ContentCatalogService service;
    QSignalSpy finished(&service, &ContentCatalogPort::finished);
    quint64 id = 0;
    const QMap<QString, QString> searches{{"mod", "Sodium"},
                                          {"resourcepack", "Round Trees"},
                                          {"shader", "MakeUp"},
                                          {"modpack", "Fabulously Optimized"}};
    QJsonArray report;
    for (const auto& publisher : {"Modrinth", "CurseForge"})
      for (auto it = searches.begin(); it != searches.end(); ++it) {
        if (!qEnvironmentVariable("BUGG_TEST_CONTENT_PUBLISHER").isEmpty() &&
            qEnvironmentVariable("BUGG_TEST_CONTENT_PUBLISHER") != publisher)
          continue;
        if (!qEnvironmentVariable("BUGG_TEST_CONTENT_KIND").isEmpty() &&
            qEnvironmentVariable("BUGG_TEST_CONTENT_KIND") != it.key())
          continue;
        QElapsedTimer clock;
        clock.start();
        QVariantMap query{{"publisher", publisher}, {"kind", it.key()}, {"query", it.value()}};
        service.query(++id, query);
        QTRY_COMPARE_WITH_TIMEOUT(finished.size(), int(id), 90000);
        auto result = finished.last()[1].toMap();
        QVERIFY2(!result.contains("error"), qPrintable(result.value("error").toString()));
        const auto items = result.value("items").toList();
        QVERIFY2(!items.isEmpty(), qPrintable(QString(publisher) + ' ' + it.key()));
        query["operation"] = "detail";
        query["projectId"] = items.first().toMap().value("id");
        service.query(++id, query);
        QTRY_COMPARE_WITH_TIMEOUT(finished.size(), int(id), 90000);
        result = finished.last()[1].toMap();
        QVERIFY2(!result.contains("error"), qPrintable(result.value("error").toString()));
        const auto versions = result.value("versions").toList();
        QVERIFY(!versions.isEmpty());
        const auto version = versions.first().toMap();
        query["operation"] = "plan";
        query["versionId"] = version.value("id");
        query["gameVersion"] = version.value("gameVersions").toStringList().value(0);
        query["loader"] = version.value("loaders").toStringList().value(0);
        service.query(++id, query);
        QTRY_COMPARE_WITH_TIMEOUT(finished.size(), int(id), 90000);
        const auto plan = finished.last()[1].toMap();
        QVERIFY2(!plan.contains("error"), qPrintable(plan.value("error").toString()));
        QJsonObject measurement{{"publisher", publisher},
                                {"kind", it.key()},
                                {"project", items.first().toMap().value("title").toString()},
                                {"metadataMs", clock.elapsed()},
                                {"files", plan.value("files").toList().size()}};
        {
          const auto game = root.path() + "/game", portable = root.path() + "/portable";
          const auto instance = it.key();
          write_json(game + "/versions/" + instance + '/' + instance + ".json",
                     {{"id", instance},
                      {"bugg", QJsonObject{{"version", query.value("gameVersion").toString()},
                                           {"loader", query.value("loader").toString()}}}});
          clock.restart();
          auto future = QtConcurrent::run([=] {
            const auto cancelled = std::make_shared<std::atomic_bool>(false);
            try {
              if (instance == "modpack") {
                const auto file = plan.value("files").toList().first().toMap();
                const auto archive = portable + '/' + file.value("filename").toString();
                ResourceClient client(supported_download_sources(), cancelled,
                                      [](double, const QString&) {});
                client.fetch({{QUrl(file.value("url").toString()), archive,
                               file.value("hashes").toMap().value("sha1").toByteArray(),
                               file.value("size").toLongLong()}});
                const auto inspected = inspect_modpack(archive, cancelled);
                if (inspected.specification.value("game").toString().isEmpty())
                  throw std::runtime_error("missing pack game version");
              } else {
                GameOperations operation(game, portable, supported_download_sources(), cancelled,
                                         [](double, const QString&) {});
                operation.install_content({{"kind", "content"}, {"id", instance}, {"plan", plan}});
              }
              return QString{};
            } catch (const std::exception& error) {
              return QString::fromUtf8(error.what());
            }
          });
          QTRY_VERIFY_WITH_TIMEOUT(future.isFinished(), 180000);
          QVERIFY2(future.result().isEmpty(), qPrintable(future.result()));
          measurement["downloadAndInstallMs"] = clock.elapsed();
          qint64 bytes = 0;
          for (const auto& file : plan.value("files").toList())
            bytes += file.toMap().value("size").toLongLong();
          measurement["bytes"] = bytes;
        }
        report.append(measurement);
        const auto tag = qEnvironmentVariable("BUGG_TEST_CONTENT_PUBLISHER") + '-' +
                         qEnvironmentVariable("BUGG_TEST_CONTENT_KIND");
        put(QCoreApplication::applicationDirPath() + "/verification/content/live" +
                (tag == "-" ? QString{} : '-' + tag) + "-report.json",
            QJsonDocument(report).toJson());
      }
    service.shutdown();
    QTRY_VERIFY(!service.busy());
  }
  void source_origin_window_routes() {
    if (!qEnvironmentVariableIsSet("BUGG_TEST_SOURCE_CAPTURE")) QSKIP("Explicit source UI review");
    ContentServer server;
    ContentGameCatalogProbe games;
    SourceSettings sources;
    const bool live = qEnvironmentVariableIsSet("BUGG_TEST_CONTENT_CAPTURE_LIVE");
    ContentCatalogService service(nullptr, live ? ContentEndpoints{} : server.endpoints());
    service.select_sources({"BUGG"});
    DesktopEnvironment desktop;
    QQmlApplicationEngine engine;
    engine.addImportPath(QCoreApplication::applicationDirPath() + "/qml");
    engine.setInitialProperties(
        {{"desktopEnvironment", QVariant::fromValue(&desktop)},
         {"sourceSettings", QVariant::fromValue(static_cast<QObject*>(&sources))},
         {"contentService", QVariant::fromValue(static_cast<QObject*>(&service))},
         {"catalogService", QVariant::fromValue(static_cast<QObject*>(&games))},
         {"instances", QVariantList{QVariantMap{{"id", "fixture"},
                                                {"name", "Minecraft 1.21.1"},
                                                {"version", "1.21.1"},
                                                {"loader", "fabric"}}}}});
    engine.load(QUrl::fromLocalFile(QFINDTESTDATA("../../qml/Main.qml")));
    QVERIFY(!engine.rootObjects().isEmpty());
    auto* window = qobject_cast<QQuickWindow*>(engine.rootObjects().first());
    QVERIFY(window);
    auto* controller = window->findChild<QObject*>("windowController");
    auto* deck = window->findChild<QObject*>("toolContent");
    auto* session = window->findChild<ContentCatalogSession*>("contentCatalogSession");
    QVERIFY(controller && deck && session);
    window->findChild<QObject*>("edgeDock")->setProperty("autoFoldEnabled", false);
    QTest::qWait(400);
    const auto shots = QCoreApplication::applicationDirPath() + "/verification/source-origin/" +
                       (live ? "live" : "fixture");
    QDir().mkpath(shots);
    for (const auto& theme : {"classic", "panel"}) {
      QMetaObject::invokeMethod(controller, "selectTheme", Q_ARG(QVariant, theme));
      QTRY_COMPARE(window->width(), QString(theme) == "panel" ? 410 : 960);
      QMetaObject::invokeMethod(deck, "openPage", Q_ARG(QVariant, "sources"));
      QTRY_COMPARE(deck->property("route").toString(), "sources");
      QTest::qWait(400);
      QQuickItem* input = nullptr;
      QTRY_VERIFY((input = visual_item(window->contentItem(), "buggSourceBaseUrl")));
      QCOMPARE(input->property("text").toString(), default_bugg_source().toString());
      input->setProperty("text", "https://source.example/launcher");
      QVERIFY(QMetaObject::invokeMethod(input, "editingFinished"));
      QCOMPARE(sources.bugg_base_url(), QUrl("https://source.example/launcher"));
      input->setProperty("text", default_bugg_source().toString());
      QVERIFY(QMetaObject::invokeMethod(input, "editingFinished"));
      QVERIFY(window->grabWindow().save(shots + "/sources-" + theme + ".png"));
      QMetaObject::invokeMethod(deck, "openToolPage", Q_ARG(QVariant, 1),
                                Q_ARG(QVariant, "catalog"));
      QTRY_COMPARE(deck->property("toolIndex").toInt(), 1);
      QTRY_COMPARE(deck->property("route").toString(), "catalog");
      session->edit("publisher", "CurseForge");
      session->browse("mod", "", {{"id", "fixture"}, {"version", "1.21.1"}, {"loader", "fabric"}});
      QTRY_VERIFY_WITH_TIMEOUT(!session->status().value("loading").toBool() &&
                                   !session->status().value("categoriesLoading").toBool(),
                               90000);
      session->edit("category", live ? "423" : "10");
      session->search();
      QTRY_VERIFY_WITH_TIMEOUT(!session->status().value("loading").toBool(), 90000);
      QVERIFY2(session->status().value("error").toString().isEmpty(),
               qPrintable(session->status().value("error").toString()));
      QVERIFY(!session->status().value("items").toList().isEmpty());
      QTest::qWait(300);
      QVERIFY(window->grabWindow().save(shots + "/filtered-" + theme + ".png"));
      if (live) continue;
      server.empty = true;
      session->edit("query", "no-results");
      session->search();
      QTRY_VERIFY(!session->status().value("loading").toBool());
      QTest::qWait(100);
      QVERIFY(window->grabWindow().save(shots + "/empty-" + theme + ".png"));
      server.delay = 600;
      server.broken = true;
      session->edit("query", "error");
      session->search();
      QTest::qWait(100);
      QVERIFY(session->status().value("loading").toBool());
      QVERIFY(window->grabWindow().save(shots + "/waiting-" + theme + ".png"));
      QTRY_VERIFY(!session->status().value("loading").toBool());
      QVERIFY(!session->status().value("error").toString().isEmpty());
      QTest::qWait(100);
      QVERIFY(window->grabWindow().save(shots + "/error-" + theme + ".png"));
      server.empty = server.broken = false;
      server.delay = 0;
    }
    service.shutdown();
    QTRY_VERIFY(!service.busy());
    window->close();
  }
  void render_native_window_routes() {
    ContentServer server;
    ContentGameCatalogProbe games;
    const bool live = qEnvironmentVariableIsSet("BUGG_TEST_CONTENT_CAPTURE_LIVE");
    const auto kind = qEnvironmentVariable("BUGG_TEST_CONTENT_KIND", "mod");
    const bool shader_review = qEnvironmentVariableIsSet("BUGG_TEST_SHADER_CHOICES_CAPTURE");
    server.kind = kind;
    const QMap<QString, QString> searches{{"mod", "Sodium"},
                                          {"resourcepack", "Round Trees"},
                                          {"shader", "MakeUp"},
                                          {"modpack", "Fabulously Optimized"}};
    ContentCatalogService service(nullptr, live ? ContentEndpoints{} : server.endpoints());
    DesktopEnvironment desktop;
    QQmlApplicationEngine engine;
    engine.addImportPath(QCoreApplication::applicationDirPath() + "/qml");
    engine.setInitialProperties(
        {{"desktopEnvironment", QVariant::fromValue(&desktop)},
         {"contentService", QVariant::fromValue(static_cast<QObject*>(&service))},
         {"catalogService", QVariant::fromValue(static_cast<QObject*>(&games))},
         {"instances", QVariantList{QVariantMap{{"id", "fixture"},
                                                {"name", "Minecraft 1.21.1"},
                                                {"version", "1.21.1"},
                                                {"loader", "fabric"}}}}});
    engine.load(QUrl::fromLocalFile(QFINDTESTDATA("../../qml/Main.qml")));
    QVERIFY(!engine.rootObjects().isEmpty());
    auto* window = qobject_cast<QQuickWindow*>(engine.rootObjects().first());
    QVERIFY(window);
    auto* controller = window->findChild<QObject*>("windowController");
    QVERIFY(controller);
    auto* deck = window->findChild<QObject*>("toolContent");
    QVERIFY(deck);
    auto* session = window->findChild<ContentCatalogSession*>("contentCatalogSession");
    QVERIFY(session);
    auto* dock = window->findChild<QObject*>("edgeDock");
    QVERIFY(dock);
    dock->setProperty("autoFoldEnabled", false);
    const auto shots = QCoreApplication::applicationDirPath() + "/verification/content" +
                       (live ? "/live" + (kind == "mod" ? QString{} : '/' + kind) : "");
    QDir().mkpath(shots);
    const auto capture = [&](const QString& path) {
      if (shader_review && !path.contains("/shader-core-")) return true;
      if (qEnvironmentVariableIsSet("BUGG_TEST_CAPTURE_TASKS_ONLY") &&
          !path.contains("window-task-"))
        return true;
      // Navigation fades the shell and page independently. Wait for both
      // animations and a rendered frame, rather than accepting a blank capture.
      QTest::qWait(80);
      QElapsedTimer settling;
      settling.start();
      while ((window->property("contentReveal").toReal() < 0.999 ||
              deck->property("pageReveal").toReal() < 0.999) &&
             settling.elapsed() < 5000)
        QTest::qWait(20);
      if (window->property("contentReveal").toReal() < 0.999 ||
          deck->property("pageReveal").toReal() < 0.999)
        return false;
      QTest::qWait(80);
      return window->grabWindow().save(path);
    };
    // The same directory is reachable from instance files under the launch tool.
    // Its translation owner must follow the route, not only the plaza tool index.
    QVERIFY(QMetaObject::invokeMethod(deck, "openPage", Q_ARG(QVariant, "catalog")));
    QTRY_VERIFY(session->active());
    QVERIFY(!session->detail_view());
    QVERIFY(QMetaObject::invokeMethod(deck, "goBack"));
    QTRY_VERIFY(!session->active());
    for (const auto& theme : {"classic", "panel", "small", "large"}) {
      if (shader_review && QStringList{"small", "large"}.contains(theme)) continue;
      if (qEnvironmentVariableIsSet("BUGG_TEST_CAPTURE_TASKS_ONLY") &&
          QStringList{"small", "large"}.contains(theme))
        continue;
      QMetaObject::invokeMethod(controller, "selectTheme", Q_ARG(QVariant, theme));
      QMetaObject::invokeMethod(deck, "openToolPage", Q_ARG(QVariant, 1),
                                Q_ARG(QVariant, "catalog"));
      session->edit("publisher", "Modrinth");
      session->browse(kind, live ? searches.value(kind) : "");
      QTRY_VERIFY_WITH_TIMEOUT(!session->status().value("loading").toBool(), 60000);
      QVERIFY2(session->status().value("error").toString().isEmpty(),
               qPrintable(session->status().value("error").toString()));
      QTest::qWait(500);
      QVERIFY(capture(shots + "/window-catalog-" + theme + ".png"));
      QVERIFY(QMetaObject::invokeMethod(deck, "goBack"));
      QTRY_VERIFY(deck->property("route").toString().isEmpty());
      QTRY_VERIFY(session->active());
      QTRY_VERIFY_WITH_TIMEOUT(!session->status().value("translationLoading").toBool(), 60000);
      if (!live)
        QVERIFY(session->status()
                    .value("items")
                    .toList()
                    .first()
                    .toMap()
                    .value("translatedSummary")
                    .toBool());
      QTest::qWait(160);
      QVERIFY(capture(shots + "/window-plaza-" + theme + ".png"));
      QVERIFY(QMetaObject::invokeMethod(deck, "openPage", Q_ARG(QVariant, "catalog")));
      QTest::qWait(160);
      auto* browser = window->findChild<QObject*>("contentBrowserPage");
      auto* disclosure = window->findChild<QObject*>("contentFilterDisclosure");
      QVERIFY(browser && disclosure);
      browser->setProperty("filtersExpanded", true);
      QVERIFY(QMetaObject::invokeMethod(disclosure, "clicked"));
      QTRY_VERIFY(!browser->property("filtersExpanded").toBool());
      QTest::qWait(120);
      QVERIFY(capture(shots + "/window-filters-collapsed-" + theme + ".png"));
      QVERIFY(QMetaObject::invokeMethod(disclosure, "clicked"));
      QTRY_VERIFY(browser->property("filtersExpanded").toBool());
      QTest::qWait(120);
      QVERIFY(capture(shots + "/window-filters-" + theme + ".png"));
      auto* categories = window->findChild<QObject*>("contentCategoryFilterPopup");
      QVERIFY(categories);
      QVERIFY(QMetaObject::invokeMethod(categories, "open"));
      QTest::qWait(160);
      QVERIFY(capture(shots + "/window-categories-" + theme + ".png"));
      QVERIFY(QMetaObject::invokeMethod(categories, "close"));
      if (!live && kind == "mod") {
        server.real_categories = true;
        session->edit("publisher", "CurseForge");
        QTRY_VERIFY(!session->status().value("categoriesLoading").toBool());
        QVERIFY(session->status().value("categories").toList().size() > 40);
        QVERIFY(QMetaObject::invokeMethod(categories, "open"));
        QTest::qWait(180);
        QVERIFY(capture(shots + "/window-curseforge-categories-" + theme + ".png"));
        auto* category_search = categories->findChild<QObject*>("versionSearchField");
        QVERIFY(category_search);
        category_search->setProperty("text", QString::fromUtf8("附属模组"));
        QTest::qWait(120);
        QVERIFY(capture(shots + "/window-curseforge-addons-" + theme + ".png"));
        category_search->setProperty("text", QString::fromUtf8("科技"));
        QTest::qWait(120);
        QVERIFY(capture(shots + "/window-curseforge-technology-" + theme + ".png"));
        QVERIFY(QMetaObject::invokeMethod(categories, "close"));
        session->edit("category", "406");
        session->search();
        QTRY_VERIFY(!session->status().value("loading").toBool());
        QVERIFY(!session->status().value("items").toList().isEmpty());
        QTest::qWait(120);
        QVERIFY(capture(shots + "/window-curseforge-matches-" + theme + ".png"));
        session->edit("publisher", "Modrinth");
        session->search();
        QTRY_VERIFY(!session->status().value("categoriesLoading").toBool() &&
                    !session->status().value("loading").toBool());
      }
      QVERIFY(QMetaObject::invokeMethod(disclosure, "clicked"));
      QTRY_VERIFY(!browser->property("filtersExpanded").toBool());
      const auto projects = session->status().value("items").toList();
      QVERIFY(!projects.isEmpty());
      session->open_project(projects.first().toMap().value("id").toString(),
                            {{"id", "fixture"}, {"version", "1.21.1"}, {"loader", "fabric"}});
      QMetaObject::invokeMethod(deck, "openPage", Q_ARG(QVariant, "content"));
      QTRY_VERIFY_WITH_TIMEOUT(!session->status().value("detailLoading").toBool() &&
                                   !session->status().value("planning").toBool(),
                               60000);
      QTest::qWait(350);
      if (live) {
        // Remote images have their own asynchronous transport. Capture the
        // settled document rather than assuming metadata completion loads them.
        QElapsedTimer images;
        images.start();
        bool loading = true;
        while (loading && images.elapsed() < 25000) {
          loading = false;
          // ListView delegates belong to the visual tree, not necessarily the
          // QObject ownership tree. Include their asynchronous image items.
          QList<QQuickItem*> pending{window->contentItem()};
          while (!pending.isEmpty()) {
            auto* object = pending.takeLast();
            pending.append(object->childItems());
            if (object->metaObject()->indexOfProperty("illustration") >= 0 &&
                object->property("loading").toBool())
              loading = true;
          }
          if (loading) QTest::qWait(100);
        }
      }
      QVERIFY(!session->status().value("project").toMap().value("body").toList().isEmpty());
      put(shots + "/project-" + theme + ".json",
          QJsonDocument::fromVariant(session->status().value("project")).toJson());
      QVERIFY(capture(shots + "/window-detail-" + theme + ".png"));
      if (qEnvironmentVariableIsSet("BUGG_TEST_TRANSLATION_CAPTURE")) {
        QTRY_VERIFY_WITH_TIMEOUT(!session->status().value("translationLoading").toBool(), 60000);
        QVERIFY(session->status().value("project").toMap().value("hasTranslation").toBool());
        QVERIFY(capture(shots + "/translation-ready-" + theme + ".png"));
        if (theme == "panel") {
          auto* details = window->findChild<QObject*>("contentDetailsPage");
          QVERIFY(details);
          details->setProperty("selectedTab", 1);
          QVERIFY(capture(shots + "/translation-install-panel.png"));
          details->setProperty("selectedTab", 0);
        }
        session->set_original_text(true);
        QVERIFY(capture(shots + "/translation-original-" + theme + ".png"));
        session->set_original_text(false);
        server.translation_state = "pending";
        service.select_sources({"BUGG"});
        QTRY_VERIFY_WITH_TIMEOUT(!session->status().value("detailLoading").toBool() &&
                                     !session->status().value("translationLoading").toBool(),
                                 15000);
        QVERIFY(session->status().value("translationPending").toBool());
        QVERIFY(capture(shots + "/translation-pending-" + theme + ".png"));
        server.translation_state = "wrongHash";
        service.select_sources({"BMCLAPI"});
        QTRY_VERIFY_WITH_TIMEOUT(!session->status().value("translationError").toString().isEmpty(),
                                 15000);
        QVERIFY(capture(shots + "/translation-error-" + theme + ".png"));
        server.translation_state = "summaryOnly";
        service.select_sources({"BUGG"});
        QTRY_VERIFY_WITH_TIMEOUT(
            session->status().value("translationPending").toBool() &&
                session->status().value("project").toMap().value("translatedSummary").toBool(),
            15000);
        QVERIFY(!session->status().value("project").toMap().value("translatedBody").toBool());
        QVERIFY(capture(shots + "/translation-summary-only-" + theme + ".png"));
        server.translation_state = "ready";
        service.select_sources(supported_download_sources());
        QMetaObject::invokeMethod(deck, "goBack");
        QMetaObject::invokeMethod(deck, "goBack");
        QTRY_VERIFY(deck->property("route").toString().isEmpty());
        continue;
      }
      auto* detail = window->findChild<QObject*>("contentDetailsPage");
      QVERIFY(detail);
      detail->setProperty("selectedTab", 1);
      QTest::qWait(100);
      QVERIFY(capture(shots + "/window-detail-install-" + theme + ".png"));
      if (kind == "shader") {
        auto* install = visual_item(window->contentItem(), "installContentButton");
        QVERIFY(install && install->isVisible());
        QVERIFY2(install->mapToScene(QPointF(0, install->height())).y() <= window->height() - 8,
                 qPrintable(QString("%1 button bottom=%2 window=%3")
                                .arg(theme)
                                .arg(install->mapToScene(QPointF(0, install->height())).y())
                                .arg(window->height())));
        auto support = session->status().value("plan").toMap().value("shaderSupport").toMap();
        QVERIFY(!support.value("name").toString().isEmpty());
        QVERIFY(capture(shots + "/shader-core-required-" + theme + ".png"));
        if (shader_review) {
          auto* choices = window->findChild<QObject*>("shaderCoreSelectorPopup");
          QVERIFY(choices);
          QVERIFY(QMetaObject::invokeMethod(choices, "open"));
          QVERIFY(capture(shots + "/shader-core-choices-" + theme + ".png"));
          QVERIFY(QMetaObject::invokeMethod(choices, "close"));
        }
        support["installed"] = true;
        detail->setProperty("inspection",
                            QVariantMap{{"instance", "fixture"},
                                        {"shaderSupport", support},
                                        {"requestedPlan", session->status().value("plan")}});
        QVERIFY(capture(shots + "/shader-core-reused-" + theme + ".png"));
        detail->setProperty(
            "inspection",
            QVariantMap{{"instance", "fixture"},
                        {"requestedPlan", session->status().value("plan")},
                        {"error", "已有光影核心不兼容当前游戏或加载器，请先处理冲突"}});
        QVERIFY(capture(shots + "/shader-core-error-" + theme + ".png"));
        if (shader_review) {
          QMetaObject::invokeMethod(deck, "goBack");
          QMetaObject::invokeMethod(deck, "goBack");
          continue;
        }
        const QVariantMap vanilla{{"id", "vanilla"},
                                  {"name", "Minecraft 1.21.1 原版"},
                                  {"version", "1.21.1"},
                                  {"loader", "vanilla"}};
        detail->setProperty("instances", QVariantList{vanilla});
        detail->setProperty("targetId", "vanilla");
        session->select_target(vanilla);
        QTRY_VERIFY(!session->status().value("detailLoading").toBool() &&
                    !session->status().value("planning").toBool());
        QCOMPARE(session->status().value("compatibility").toString(), "missingLoader");
        QCOMPARE(session->status().value("suggestedLoader").toString(), "fabric");
        QVERIFY(capture(shots + "/shader-core-needs-loader-" + theme + ".png"));
        auto* setup = visual_item(window->contentItem(), "setupContentLoaderButton");
        QVERIFY(setup && setup->isVisible() && setup->property("enabled").toBool());
        QVERIFY(QMetaObject::invokeMethod(setup, "clicked"));
        QTRY_COMPARE(deck->property("route").toString(), "install");
        QTRY_COMPARE(deck->property("pageTitle").toString(), "补装光影支持");
        QCOMPARE(deck->property("pageState")
                     .toMap()
                     .value("content.setupTarget")
                     .toMap()
                     .value("id")
                     .toString(),
                 "vanilla");
        QVERIFY(capture(shots + "/shader-core-inplace-" + theme + ".png"));
        QMetaObject::invokeMethod(deck, "goBack");
        QMetaObject::invokeMethod(deck, "goBack");
        continue;
      }
      if (kind != "mod") continue;
      QVERIFY(QMetaObject::invokeMethod(detail, "setupRequested", Q_ARG(QString, "1.21.1"),
                                        Q_ARG(QString, "fabric")));
      auto* installer = window->findChild<InstallCatalogSession*>("installCatalogSession");
      QVERIFY(installer);
      QTRY_VERIFY(installer->status().value("ready").toBool());
      QCOMPARE(installer->status().value("game").toString(), "1.21.1");
      QCOMPARE(installer->status().value("loader").toString(), "fabric");
      QTest::qWait(200);
      QVERIFY(capture(shots + "/window-guided-install-" + theme + ".png"));
      QMetaObject::invokeMethod(deck, "goBack");
      QMetaObject::invokeMethod(deck, "openToolPage", Q_ARG(QVariant, 0),
                                Q_ARG(QVariant, "install"));
      QTRY_COMPARE(deck->property("toolIndex").toInt(), 0);
      QTRY_COMPARE(deck->property("route").toString(), "install");
      QTest::qWait(350);
      QVERIFY(capture(shots + "/window-install-" + theme + ".png"));
      QMetaObject::invokeMethod(deck, "openToolPage", Q_ARG(QVariant, 0),
                                Q_ARG(QVariant, "instanceFiles"));
      QTRY_COMPARE(deck->property("route").toString(), "instanceFiles");
      QTest::qWait(350);
      QVERIFY(capture(shots + "/window-files-" + theme + ".png"));
      deck->setProperty(
          "tasks",
          QVariantList{
              QVariantMap{
                  {"id", "partial"},
                  {"kind", "content"},
                  {"name", "Fabric 模组"},
                  {"state", "done"},
                  {"progress", 1},
                  {"detail", "所选模组已安装；缺少必要依赖，游戏可能无法正常运行"},
                  {"contentItems",
                   QVariantList{QVariantMap{{"title", "Sodium"},
                                            {"versionName", "0.8.13"},
                                            {"filename", "sodium-fabric-0.8.13.jar"},
                                            {"state", "done"},
                                            {"detail", "安装完成"}},
                                QVariantMap{{"title", "Fabric API"},
                                            {"versionName", "0.116.6+1.21.1"},
                                            {"filename", "fabric-api-0.116.6+1.21.1.jar"},
                                            {"dependency", true},
                                            {"state", "installed"},
                                            {"detail", "已安装 · 已校验，未重复下载"}},
                                QVariantMap{{"title", "Cloth Config API"},
                                            {"versionName", "15.0.140"},
                                            {"filename", "cloth-config-15.0.140-fabric.jar"},
                                            {"dependency", true},
                                            {"state", "failed"},
                                            {"detail", "下载连接中断，请重试"}}}},
                  {"missingDependencies",
                   QVariantList{QVariantMap{{"title", "Cloth Config API"},
                                            {"reason", "下载连接中断，请重试"}}}}},
              QVariantMap{{"id", "done"},
                          {"kind", "content"},
                          {"name", "资源包 Round Trees"},
                          {"state", "done"},
                          {"progress", 1},
                          {"detail", "安装完成"}}});
      QMetaObject::invokeMethod(deck, "openPage", Q_ARG(QVariant, "tasks"));
      QTRY_COMPARE(deck->property("route").toString(), "tasks");
      QTest::qWait(150);
      QVERIFY(capture(shots + "/window-dependency-task-" + theme + ".png"));
      QPointer<QQuickItem> task_items = visual_item(window->contentItem(), "contentTaskItems");
      QVERIFY(task_items);
      QVERIFY(task_items->setProperty(
          "contentY",
          qMax(0.0, task_items->property("contentHeight").toReal() - task_items->height())));
      QTest::qWait(120);
      // Layout and outer-list virtualization can replace delegates between
      // frames; locate the current item instead of dereferencing a stale one.
      QTRY_VERIFY((task_items = visual_item(window->contentItem(), "contentTaskItems")) &&
                  task_items->property("contentY").toReal() + task_items->height() >=
                      task_items->property("contentHeight").toReal() - 1);
      QVERIFY(capture(shots + "/window-task-failed-item-" + theme + ".png"));
      auto task = deck->property("tasks").toList().first().toMap();
      auto content_items = task.value("contentItems").toList();
      auto active = content_items.last().toMap();
      active["state"] = "downloading";
      active["progress"] = 0.43;
      active["detail"] = "下载并校验 · 43%";
      content_items.last() = active;
      task["state"] = "running";
      task["progress"] = 0.43;
      task["detail"] = "正在补齐 Cloth Config API";
      task["downloadSpeed"] = "3.2 MiB/s";
      task["activeTransfers"] = 4;
      active["speedText"] = "820 KiB/s";
      active["transferText"] = "1.4 MiB / 3.2 MiB";
      content_items.last() = active;
      task["contentItems"] = content_items;
      task.remove("missingDependencies");
      deck->setProperty("tasks", QVariantList{task});
      QTest::qWait(180);
      task_items = visual_item(window->contentItem(), "contentTaskItems");
      QVERIFY(task_items);
      QVERIFY(task_items->setProperty(
          "contentY",
          qMax(0.0, task_items->property("contentHeight").toReal() - task_items->height())));
      QTest::qWait(120);
      QVERIFY(capture(shots + "/window-task-running-" + theme + ".png"));
      active["state"] = "done";
      active["progress"] = 1;
      active["detail"] = "安装完成";
      content_items.last() = active;
      task["contentItems"] = content_items;
      task["state"] = "done";
      task["progress"] = 1;
      task["detail"] = "安装完成";
      deck->setProperty("tasks", QVariantList{task});
      QTest::qWait(180);
      QVERIFY(capture(shots + "/window-task-done-" + theme + ".png"));
      auto* task_disclosure = visual_item(window->contentItem(), "contentTaskDisclosure");
      QVERIFY(task_disclosure);
      QVERIFY(QMetaObject::invokeMethod(task_disclosure, "clicked"));
      QTest::qWait(100);
      QVERIFY(capture(shots + "/window-task-collapsed-" + theme + ".png"));
      deck->setProperty("tasks", QVariantList{});
      QTest::qWait(120);
      QVERIFY(capture(shots + "/window-task-empty-" + theme + ".png"));
      QMetaObject::invokeMethod(deck, "openPage", Q_ARG(QVariant, "content"));
      QTest::qWait(150);
      detail = window->findChild<QObject*>("contentDetailsPage");
      QVERIFY(detail);
      detail->setProperty("selectedTab", 1);
      for (const bool same : {true, false}) {
        detail->setProperty(
            "inspection",
            QVariantMap{
                {"instance", "fixture"},
                {"requestedPlan", session->status().value("plan")},
                {"installed", QVariantList{QVariantMap{{"versionName", same ? "1.0" : "0.9.0"},
                                                       {"matchesSelected", same}}}},
                {"conflicts", same ? QStringList{} : QStringList{"mods/sodium-0.9.0.jar"}}});
        QTest::qWait(150);
        auto* install_button = visual_item(window->contentItem(), "installContentButton");
        QVERIFY(install_button);
        QCOMPARE(install_button->property("enabled").toBool(), same);
        if (same) {
          const auto current = detail->property("inspection").toMap();
          auto stale = current;
          stale["requestedPlan"] = QVariantMap{{"projectId", "a-different-project"}};
          detail->setProperty("inspection", stale);
          QTRY_VERIFY(!install_button->property("enabled").toBool());
          QCOMPARE(install_button->property("text").toString(), QString::fromUtf8("下载并安装"));
          QVERIFY(capture(shots + "/window-content-stale-inspection-" + theme + ".png"));
          detail->setProperty("inspection", current);
          QTRY_VERIFY(install_button->property("enabled").toBool());
        }
        if (!same) {
          auto* replace = visual_item(window->contentItem(), "replaceContentOption");
          QVERIFY(replace);
          replace->setProperty("checked", true);
          QTRY_VERIFY(install_button->property("enabled").toBool());
          QTest::qWait(180);
        }
        QVERIFY(window->grabWindow().save(
            shots + (same ? "/window-content-installed-" : "/window-content-upgrade-") + theme +
            ".png"));
      }
    }
    session->cancel();
    service.shutdown();
    QTRY_VERIFY(!service.busy());
    window->close();
  }
  void render_pages() {
    ContentServer server;
    ContentCatalogService service(nullptr, server.endpoints());
    ContentCatalogSession session;
    session.set_service(&service);
    QQmlEngine engine;
    engine.addImportPath(QCoreApplication::applicationDirPath() + "/qml");
    engine.rootContext()->setContextProperty("contentSession", &session);
    engine.rootContext()->setContextProperty("fixtureInstances",
                                             QVariantList{QVariantMap{{"id", "fixture"},
                                                                      {"name", "Minecraft 1.21.1"},
                                                                      {"version", "1.21.1"},
                                                                      {"loader", "fabric"}}});
    const auto shots = QCoreApplication::applicationDirPath() + "/verification/content";
    QDir().mkpath(shots);
    for (const bool panel : {false, true}) {
      auto* tokens = engine.singletonInstance<QObject*>("Bugg.DesignSystem", "DesignTokens");
      QVERIFY(tokens);
      tokens->setProperty("comfortable", !panel);
      tokens->setProperty("sizeClass", panel ? "panel" : "classic");
      QQuickWindow window;
      window.setColor(Qt::white);
      window.resize(panel ? 410 : 960, panel ? 580 : 640);
      window.show();
      for (const auto& kind : {"mod", "resourcepack", "shader", "modpack"}) {
        server.kind = kind;
        session.edit("publisher", "Modrinth");
        session.browse(kind, "", {});
        QTRY_VERIFY_WITH_TIMEOUT(!session.status().value("loading").toBool(), 5000);
        QQmlComponent component(&engine);
        component.setData(
            "import QtQuick; import Bugg.Pages; CatalogPage { session: contentSession; instances: "
            "fixtureInstances; viewportHeight: height }",
            QUrl("file:///ContentCapture.qml"));
        QScopedPointer<QObject> page(component.create());
        QVERIFY2(page, qPrintable(component.errorString()));
        auto* item = qobject_cast<QQuickItem*>(page.data());
        item->setParentItem(window.contentItem());
        item->setWidth(window.width());
        item->setHeight(window.height());
        QTest::qWait(100);
        QVERIFY(window.grabWindow().save(shots + "/" + kind + (panel ? "-panel" : "-classic") +
                                         ".png"));
        session.open_project("root");
        QTRY_VERIFY_WITH_TIMEOUT(!session.status().value("detailLoading").toBool() &&
                                     !session.status().value("planning").toBool(),
                                 5000);
        page.reset();
        component.setData(
            "import QtQuick; import Bugg.Pages; ContentDetailsPage { session: contentSession; "
            "instances: fixtureInstances; targetId: 'fixture'; inspection: "
            "({instance:'fixture',requestedPlan:contentSession.status.plan,conflicts:[]}) }",
            QUrl("file:///ContentCapture.qml"));
        page.reset(component.create());
        QVERIFY2(page, qPrintable(component.errorString()));
        item = qobject_cast<QQuickItem*>(page.data());
        item->setParentItem(window.contentItem());
        item->setWidth(window.width());
        item->setHeight(window.height());
        QTest::qWait(100);
        QVERIFY(window.grabWindow().save(shots + "/" + kind + "-detail" +
                                         (panel ? "-panel" : "-classic") + ".png"));
        if (QString(kind) == "mod") {
          const QVariantMap vanilla{{"id", "vanilla"},
                                    {"name", "Minecraft 1.21.1 原版"},
                                    {"version", "1.21.1"},
                                    {"loader", "vanilla"}};
          page->setProperty("instances", QVariantList{vanilla});
          page->setProperty("targetId", "vanilla");
          page->setProperty("selectedTab", 1);
          session.select_target(vanilla);
          QTRY_VERIFY_WITH_TIMEOUT(!session.status().value("detailLoading").toBool() &&
                                       !session.status().value("planning").toBool(),
                                   5000);
          QCOMPARE(session.status().value("compatibility").toString(), "missingLoader");
          QTest::qWait(150);
          QVERIFY(window.grabWindow().save(shots + "/missing-loader" +
                                           (panel ? "-panel" : "-classic") + ".png"));
        }
      }
      {
        QQmlComponent component(&engine);
        component.setData(
            "import QtQuick; import Bugg.Pages; RoomSyncPage { "
            "service: QtObject { property var status: ({room:{id:'fixture',title:'朋友的世界',"
            "syncName:'Room game',game:{version:'1.21.1',loader:'fabric'}}}) } "
            "tasks: [{id:'room-task',kind:'room',name:'Room game',state:'running',progress:0.43,"
            "detail:'正在下载并校验游戏文件'}] }",
            QUrl("file:///RoomTaskCapture.qml"));
        QScopedPointer<QObject> page(component.create());
        QVERIFY2(page, qPrintable(component.errorString()));
        auto* item = qobject_cast<QQuickItem*>(page.data());
        item->setParentItem(window.contentItem());
        item->setWidth(window.width());
        item->setHeight(window.height());
        QTest::qWait(120);
        QVERIFY(window.grabWindow().save(shots + "/room-sync-task" +
                                         (panel ? "-panel" : "-classic") + ".png"));
      }
      for (const auto& state : {"empty", "error", "loading"}) {
        service.select_sources(panel ? QStringList{"官方", "BUGG"} : QStringList{"BUGG", "官方"});
        server.empty = QString(state) == "empty";
        server.broken = QString(state) == "error";
        server.delay = QString(state) == "loading" ? 400 : 0;
        session.browse("mod", state, {});
        if (QString(state) != "loading")
          QTRY_VERIFY_WITH_TIMEOUT(!session.status().value("loading").toBool(), 5000);
        QQmlComponent component(&engine);
        component.setData(
            "import QtQuick; import Bugg.Pages; CatalogPage { session: contentSession; "
            "viewportHeight: height }",
            QUrl("file:///ContentCapture.qml"));
        QScopedPointer<QObject> page(component.create());
        QVERIFY2(page, qPrintable(component.errorString()));
        auto* item = qobject_cast<QQuickItem*>(page.data());
        item->setParentItem(window.contentItem());
        item->setWidth(window.width());
        item->setHeight(window.height());
        QTest::qWait(80);
        QVERIFY(window.grabWindow().save(shots + "/" + state + (panel ? "-panel" : "-classic") +
                                         ".png"));
        QTRY_VERIFY_WITH_TIMEOUT(!service.busy(), 5000);
      }
      server.empty = false;
      server.broken = false;
      server.delay = 0;
    }
    session.cancel();
    service.shutdown();
    QTRY_VERIFY(!service.busy());
  }
};
}  // namespace bugg
QTEST_MAIN(bugg::ContentTest)
#include "content_test.moc"
