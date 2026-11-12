#include <QCryptographicHash>
#include <QDir>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QSignalSpy>
#include <QTcpServer>
#include <QTcpSocket>
#include <QTemporaryDir>
#include <QTest>
#include <QTimer>

#include "modules/catalog/application/game_catalog_service.h"
#include "modules/catalog/infrastructure/game_catalog_provider.h"
#include "modules/game_install/ui/install_catalog_session.h"
#include "modules/settings/ui/source_settings.h"
#include "platform/http/http_client.h"

namespace bugg {
namespace {
const QByteArray kManifest =
    QJsonDocument(
        QJsonObject{{"latest", QJsonObject{{"release", "26.3"}}},
                    {"versions", QJsonArray{QJsonObject{{"id", "26.4-snapshot-1"},
                                                        {"type", "snapshot"},
                                                        {"url", "https://example.com/snapshot"}},
                                            QJsonObject{{"id", "26.3"},
                                                        {"type", "release"},
                                                        {"url", "https://example.com/26.3"},
                                                        {"sha1", "abc"}},
                                            QJsonObject{{"id", "1.21.1"},
                                                        {"type", "release"},
                                                        {"url", "https://example.com/1.21.1"}}}}})
        .toJson();

class FakeHttp : public HttpClient {
 public:
  QVector<QUrl> urls;
  QVector<quint64> cancelled;
  QVector<QStringList> redirect_blocks;
  quint64 last = 0;
  quint64 get(const QUrl& url, const QStringList& blocked_redirect_hosts = {}) override {
    urls.push_back(url);
    redirect_blocks.push_back(blocked_redirect_hosts);
    return ++last;
  }
  void cancel(quint64 id) override { cancelled.push_back(id); }
  void answer(quint64 id, const QByteArray& body, const QString& error = {}) {
    emit completed(id, body, error);
  }
};

class FakeCatalog : public GameCatalogPort {
 public:
  QHash<quint64, CatalogQuery> queries;
  QVector<quint64> cancelled;
  quint64 last = 0;
  void query(quint64 id, const CatalogQuery& query) override {
    queries[id] = query;
    last = id;
  }
  void cancel(quint64 id) override { cancelled.push_back(id); }
  void select_sources(const QStringList&, const QUrl& = {}) override {
    emit source_selection_changed();
  }
  void answer(quint64 id, const CatalogResult& result) { emit finished(id, result); }
};

// Controlled short responses exercise the actual HTTP/file implementation.
class ResumeServer : public QTcpServer {
 public:
  QByteArray payload = QByteArray(256 * 1024, 'x');
  QList<QByteArray> ranges;
  qint64 sent = 0;
  bool drop_first = true, ignore_range = false, wrong_range = false, corrupt = false;
  bool stall = false, encoded = false;
  ResumeServer() {
    for (int i = 0; i < payload.size(); ++i) payload[i] = char(i % 251);
    listen(QHostAddress::LocalHost);
    connect(this, &QTcpServer::newConnection, this, [this] {
      while (hasPendingConnections()) {
        auto* socket = nextPendingConnection();
        socket->setParent(this);
        connect(socket, &QTcpSocket::disconnected, socket, &QObject::deleteLater);
        connect(socket, &QTcpSocket::readyRead, socket, [this, socket] {
          auto request = socket->property("request").toByteArray() + socket->readAll();
          socket->setProperty("request", request);
          if (!request.contains("\r\n\r\n") || socket->property("handled").toBool()) return;
          socket->setProperty("handled", true);
          QByteArray range;
          for (const auto& line : request.split('\n'))
            if (line.toLower().startsWith("range:")) range = line.mid(6).trimmed();
          ranges.append(range);
          const auto first =
              !range.isEmpty() && !ignore_range ? range.mid(6).split('-').first().toLongLong() : 0;
          auto bytes = payload.mid(first);
          if (corrupt) bytes[0] = char(bytes[0] ^ 1);
          auto header = QByteArray("HTTP/1.1 ") + (first ? "206 Partial Content" : "200 OK") +
                        "\r\nContent-Length: " + QByteArray::number(bytes.size()) +
                        "\r\nConnection: close\r\n";
          if (first)
            header += "Content-Range: bytes " + QByteArray::number(first + (wrong_range ? 1 : 0)) +
                      '-' + QByteArray::number(payload.size() - 1) + '/' +
                      QByteArray::number(payload.size()) + "\r\n";
          if (encoded && first) header += "Content-Encoding: gzip\r\n";
          if ((drop_first && ranges.size() == 1) || stall) bytes.truncate(64 * 1024);
          sent += bytes.size();
          socket->write(header + "\r\n" + bytes);
          if (!stall) socket->disconnectFromHost();
        });
      }
    });
  }
  HttpRequest file(const QString& path) const {
    HttpRequest request;
    request.url = QUrl(QString("http://127.0.0.1:%1/file").arg(serverPort()));
    request.output_path = path;
    request.sha1 = QCryptographicHash::hash(payload, QCryptographicHash::Sha1).toHex();
    request.expected_size = payload.size();
    request.parallel_ranges = false;
    request.resume = true;
    return request;
  }
};
}  // namespace

class CatalogTest : public QObject {
  Q_OBJECT
 private slots:
  void priority_capabilities_and_default_fallback() {
    const auto defaults = supported_download_sources();
    QCOMPARE(defaults, (QStringList{"BUGG", "BMCLAPI", "官方"}));
    for (const auto& definition : download_sources()) {
      for (const auto capability : definition.capabilities) {
        const auto route = resolve_source(definition.id, capability);
        QVERIFY(route.error.isEmpty());
        QCOMPARE(route.actual, definition.id);
      }
    }
    const auto games = resolve_sources(defaults, SourceCapability::MinecraftCatalog);
    QCOMPARE(games.routes.size(), 3);
    for (int i = 0; i < defaults.size(); ++i) QCOMPARE(games.routes[i].actual, defaults[i]);
    for (const auto capability :
         {SourceCapability::CurseForgeContent, SourceCapability::ModrinthContent}) {
      const auto content = resolve_sources(defaults, capability);
      QCOMPARE(content.routes.size(), 2);
      QCOMPARE(content.routes[0].actual, "BUGG");
      QCOMPARE(content.routes[1].selected, "BMCLAPI");
      QCOMPARE(content.routes[1].actual, "官方");
      QVERIFY(!content.routes[1].reason.isEmpty());
      const auto reordered = resolve_sources({"BMCLAPI", "BUGG", "官方"}, capability);
      QCOMPARE(reordered.routes.size(), 2);
      QCOMPARE(reordered.routes[0].actual, "官方");
      QCOMPARE(reordered.routes[1].actual, "BUGG");
    }
    QVERIFY(!resolve_sources({}, SourceCapability::MinecraftCatalog).error.isEmpty());
    QVERIFY(!resolve_sources({"BUGG", "BUGG"}, SourceCapability::MinecraftCatalog).error.isEmpty());
    QVERIFY(!resolve_sources({"unknown"}, SourceCapability::MinecraftCatalog).error.isEmpty());
    QVERIFY(!resolve_source("BUGG", static_cast<SourceCapability>(999)).error.isEmpty());

    FakeHttp http;
    GameCatalogService service(&http);
    QSignalSpy done(&service, &GameCatalogPort::finished);
    service.query(1, {"minecraft", {}});
    QTRY_COMPARE(http.last, 1);
    QCOMPARE(http.urls.last().host(), "mirror.bugg.icu");
    http.answer(1, {}, "BUGG temporarily unavailable");
    QTRY_COMPARE(http.last, 2);
    QCOMPARE(http.urls.last().host(), "bmclapi2.bangbang93.com");
    http.answer(2, {}, "BMCLAPI temporarily unavailable");
    QTRY_COMPARE(http.last, 3);
    QCOMPARE(http.urls.last().host(), "piston-meta.mojang.com");
    http.answer(3, kManifest);
    QTRY_COMPARE(done.size(), 1);
    QCOMPARE(qvariant_cast<CatalogResult>(done[0][1]).source, "官方");
  }

  void manifest_latest_and_schema() {
    auto providers = default_catalog_providers();
    for (const auto& source : providers) {
      const auto result = source->parse({"minecraft", {}}, kManifest);
      QVERIFY(result.error.isEmpty());
      QCOMPARE(result.preferred, "26.3");
      QCOMPARE(result.entries.size(), 2);
      QCOMPARE(result.entries.front().sha1, "abc");
      QVERIFY(!source->parse({"minecraft", {}}, "<html>error</html>").error.isEmpty());
      QVERIFY(!source->parse({"minecraft", {}}, R"({"versions":[]})").error.isEmpty());
    }
  }

  void providers_normalize_and_filter() {
    auto sources = default_catalog_providers({"BMCLAPI", "官方"});
    const auto forge = sources[0]->parse({"forge", "1.21.1"}, R"([
      {"mcversion":"1.21.1","version":"52.0.9"},
      {"mcversion":"1.21.1","version":"52.0.100"},
      {"mcversion":"1.21","version":"51.0.1"},
      {"mcversion":"1.21.1","version":"52.0.100"}])");
    QCOMPARE(forge.entries.size(), 2);
    QCOMPARE(forge.preferred, "52.0.100");
    const auto xml = QByteArray("<metadata><versioning><versions>") +
                     "<version>1.21.1-52.0.9</version><version>1.21.1-52.0.100</version>" +
                     "<version>1.21-51.0.1</version></versions></versioning></metadata>";
    const auto official = sources[1]->parse({"forge", "1.21.1"}, xml);
    QCOMPARE(official.preferred, forge.preferred);
    QCOMPARE(official.entries.size(), forge.entries.size());
    const auto fabric = sources[0]->parse({"fabric", "1.21.1"}, R"([
      {"loader":{"version":"0.17.10","stable":true},"intermediary":{"version":"1.21.1"}},
      {"loader":{"version":"0.18.0-beta.2","stable":false},"intermediary":{"version":"1.21.1"}},
      {"loader":{"version":"9.0.0"},"intermediary":{"version":"1.21"}}])");
    QCOMPARE(fabric.preferred, "0.17.10");
    QCOMPARE(fabric.entries.size(), 2);
    const auto quilt = sources[1]->parse({"quilt", "1.21.1"}, R"([
      {"loader":{"version":"0.30.0-beta.9"},"hashed":{"version":"1.21.1"}},
      {"loader":{"version":"0.30.0-beta.10"},"hashed":{"version":"1.21.1"}}])");
    QCOMPARE(quilt.preferred, "0.30.0-beta.10");
    QVERIFY(!quilt.entries.front().stable);
    const QByteArray quilt_snapshot = R"({"hashed":[{"version":"1.20.1"}],
      "loader":[{"version":"0.23.0"},{"version":"0.23.0-beta.3"}]})";
    const auto mirror_quilt = sources[0]->parse({"quilt", "1.20.1"}, quilt_snapshot);
    QCOMPARE(mirror_quilt.preferred, "0.23.0");
    QVERIFY(sources[0]->parse({"quilt", "1.21.1"}, quilt_snapshot).entries.isEmpty());
    QVERIFY(sources[0]->parse({"quilt", "1.21.1"}, quilt_snapshot).error.isEmpty());
    const auto bugg = default_catalog_providers({"BUGG"}).front();
    QCOMPARE(bugg->request_url({"forge", "1.21.1"}).path(),
             "/maven/net/minecraftforge/forge/maven-metadata.xml");
    QCOMPARE(bugg->parse({"forge", "1.21.1"}, xml).preferred, forge.preferred);
    QCOMPARE(bugg->request_url({"neoforge", "1.21.1"}).path(),
             "/neoforge-maven/releases/net/neoforged/neoforge/maven-metadata.xml");
    QVERIFY(sources[0]->parse({"forge", "1.21.1"}, "[]").error.isEmpty());
    QVERIFY(!sources[0]->parse({"forge", "1.21.1"}, R"([{"error":"oops"}])").error.isEmpty());
  }

  void neoforge_version_eras() {
    const auto source = default_catalog_providers({"官方"}).front();
    const QByteArray xml = R"(<metadata><versioning><versions>
      <version>21.1.9</version><version>21.1.100</version><version>21.10.20</version>
      <version>26.1.0.5-beta</version><version>26.1.0.6</version>
      <version>26.1.2.19</version><version>26.1.20.1</version>
      <version>26.1.0.7-alpha.2+snapshot-1</version>
      <version>1.20.1-47.1.100</version></versions></versioning></metadata>)";
    QCOMPARE(source->parse({"neoforge", "1.21.1"}, xml).preferred, "21.1.100");
    QCOMPARE(source->parse({"neoforge", "26.1"}, xml).preferred, "26.1.0.6");
    QCOMPARE(source->parse({"neoforge", "26.1.2"}, xml).preferred, "26.1.2.19");
    QCOMPARE(source->parse({"neoforge", "1.20.1"}, xml).preferred, "47.1.100");
    QVERIFY(source->parse({"neoforge", "1.19.2"}, xml).entries.empty());
  }

  void source_fallback_cancel_and_late_completion() {
    FakeHttp http;
    GameCatalogService service(&http, {"BMCLAPI", "官方"});
    QSignalSpy sources(&service, &GameCatalogPort::source_changed);
    QVector<CatalogResult> results;
    connect(&service, &GameCatalogPort::finished, this,
            [&](quint64, const CatalogResult& result) { results.push_back(result); });
    service.query(1, {"minecraft", {}});
    QTRY_COMPARE(http.last, 1);
    QCOMPARE(http.urls[0].host(), "bmclapi2.bangbang93.com");
    QVERIFY(http.redirect_blocks[0].contains("fabricmc.net"));
    QCOMPARE(sources.last()[1].toString(), "BMCLAPI");
    http.answer(1, "<html>bad gateway</html>");
    QTRY_COMPARE(http.last, 2);
    QCOMPARE(sources.last()[1].toString(), "官方");
    QVERIFY(http.urls[1].host().contains("mojang.com"));
    http.answer(2, kManifest);
    QTRY_COMPARE(results.size(), 1);
    QCOMPARE(results[0].source, "官方");
    service.query(2, {"forge", "1.21.1"});
    QTRY_COMPARE(http.last, 3);
    http.answer(3, "[]");
    QTRY_COMPARE(http.last, 4);
    http.answer(4, "<metadata><versioning><versions/></versioning></metadata>");
    QTRY_COMPARE(results.size(), 2);
    QCOMPARE(http.last, 4);  // 所有源都无兼容数据，最终才返回空列表。
    service.refresh(3, {"minecraft", {}});
    QTRY_COMPARE(http.last, 5);
    service.cancel(3);
    http.answer(5, kManifest);
    QTest::qWait(40);
    QCOMPARE(results.size(), 2);
    QVERIFY(http.cancelled.contains(5));
    // 同一逻辑 ID 在排队阶段重用，只允许新一代发出网络请求。
    service.query(4, {"minecraft", {}});
    service.refresh(4, {"forge", "1.21.1"});
    QTRY_COMPARE(http.last, 6);
    QCOMPARE(http.urls.last().path(), "/forge/minecraft/1.21.1");
    http.answer(6, {}, "镜像接收超时");
    QTRY_COMPARE(http.last, 7);
    http.answer(7, {}, "官方连接超时");
    QTRY_COMPARE(results.size(), 3);
    QVERIFY(results.last().error.contains("BMCLAPI · 镜像接收超时"));
    QVERIFY(results.last().error.contains("官方 · 官方连接超时"));
    // 明确注入单源时绝不越过该选择访问官网。
    GameCatalogService mirror_only(&http, {"BMCLAPI"});
    QSignalSpy mirror_results(&mirror_only, &GameCatalogPort::finished);
    mirror_only.query(5, {"fabric", "1.21.1"});
    QTRY_COMPARE(http.last, 8);
    QCOMPARE(http.urls.last().toString(),
             "https://bmclapi2.bangbang93.com/fabric-meta/v2/versions/loader/1.21.1");
    http.answer(8, {}, "镜像接收超时");
    QTRY_COMPARE(mirror_results.size(), 1);
    QCOMPARE(http.last, 8);
  }

  void selection_exclusive_and_stale_results() {
    FakeCatalog port;
    InstallCatalogSession session;
    session.set_service(&port);
    session.ensure_loaded();
    QCOMPARE(port.queries.size(), 1);
    port.answer(port.last, {{{"26.3"}, {"1.21.1"}}, "26.3", "fixture", {}});
    QCOMPARE(session.status()["game"].toString(), "26.3");
    QCOMPARE(session.status()["instanceName"].toString(), "26.3");
    QVERIFY(session.status()["ready"].toBool());
    session.select_loader("neoforge");
    const auto old = port.last;
    QVERIFY(session.status()["loadingLoaders"].toBool());
    QVERIFY(!session.status()["ready"].toBool());
    session.select_loader("fabric");
    const auto current = port.last;
    emit port.source_changed(old, "迟到的源");
    QVERIFY(session.status()["loaderSource"].toString().isEmpty());
    emit port.source_changed(current, "BMCLAPI");
    QCOMPARE(session.status()["loaderSource"].toString(), "BMCLAPI");
    QVERIFY(!port.cancelled.contains(old));  // 切换仅换呈现，旧组合继续缓存。
    port.answer(old, {{{"26.3.0.1"}}, "26.3.0.1", "old", {}});
    QVERIFY(session.status()["loaderVersion"].toString().isEmpty());
    port.answer(current, {{{"0.18.0"}, {"0.17.0"}}, "0.18.0", "fixture", {}});
    QCOMPARE(session.status()["loader"].toString(), "fabric");
    QCOMPARE(session.status()["loaderVersion"].toString(), "0.18.0");
    QCOMPARE(session.status()["instanceName"].toString(), "26.3-fabric-0.18.0");
    session.select_loader_version("0.17.0");
    QCOMPARE(session.status()["instanceName"].toString(), "26.3-fabric-0.17.0");
    session.set_instance_name("My world");
    session.select_game("1.21.1");
    QCOMPARE(port.queries[port.last].game_version, "1.21.1");
    QVERIFY(session.status()["loaderVersion"].toString().isEmpty());
    QCOMPARE(session.status()["instanceName"].toString(), "My world");
    port.answer(port.last, {{}, {}, "fixture", {}});
    QVERIFY(!session.status()["ready"].toBool());
    session.select_loader("vanilla");
    QVERIFY(session.status()["ready"].toBool());
    session.select_game("not-real");
    session.select_loader("all-loaders");
    QCOMPARE(session.status()["game"].toString(), "1.21.1");
    QCOMPARE(session.status()["loader"].toString(), "vanilla");
    session.ensure_loaded();
    QCOMPARE(port.queries.size(), 5);  // 再进入由端口检查有效期，原生缓存不重复发 HTTP。
  }

  void loader_switch_reuses_pending_and_preserves_cached_selection() {
    FakeHttp http;
    GameCatalogService service(&http, {"BMCLAPI"});
    InstallCatalogSession session;
    session.set_service(&service);
    session.ensure_loaded();
    QTRY_COMPARE(http.last, 1);
    http.answer(1, kManifest);
    QTRY_VERIFY(session.status()["ready"].toBool());
    session.select_game("1.21.1");
    session.select_loader("fabric");
    QTRY_COMPARE(http.last, 2);
    session.select_loader("forge");
    QTRY_COMPARE(http.last, 3);
    session.select_loader("fabric");
    QTest::qWait(20);
    QCOMPARE(http.last, 3);  // 切回来仍用在途 Fabric 请求，不取消、不重发。
    http.answer(3, R"([{"mcversion":"1.21.1","version":"52.0.100"}])");
    http.answer(2, R"([
      {"loader":{"version":"0.20.1","stable":true},"intermediary":{"version":"1.21.1"}},
      {"loader":{"version":"0.19.0","stable":true},"intermediary":{"version":"1.21.1"}}])");
    QTRY_COMPARE(session.status()["loaderVersion"].toString(), "0.20.1");
    session.select_loader_version("0.19.0");
    session.select_loader("forge");
    QTRY_COMPARE(session.status()["loaderVersion"].toString(), "52.0.100");
    session.select_loader("fabric");
    QCOMPARE(session.status()["loaderVersion"].toString(), "0.19.0");
    session.ensure_loaded();
    QTest::qWait(20);
    QCOMPARE(http.last, 3);  // 成功目录缓存命中，切换不新增 HTTP。
    session.retry_loaders();
    QVERIFY(session.status()["ready"].toBool());
    QVERIFY(!session.status()["loadingLoaders"].toBool());
    QTRY_COMPARE(http.last, 4);
    http.answer(4, {}, "offline");
    QTRY_VERIFY(!session.status()["refreshing"].toBool());
    QVERIFY(session.status()["ready"].toBool());
    QCOMPARE(session.status()["loaderVersion"].toString(), "0.19.0");
    QVERIFY(!session.status()["loaderError"].toString().isEmpty());
    session.cancel();
  }

  void cached_defaults_follow_latest_but_manual_choices_stay() {
    FakeCatalog port;
    InstallCatalogSession session;
    session.set_service(&port);
    session.ensure_loaded();
    const auto game_request = port.last;
    emit port.cached(game_request, {{{"1.21.1"}}, "1.21.1", "BUGG", {}});
    QVERIFY(session.status()["ready"].toBool());
    port.answer(game_request, {{{"26.3"}, {"1.21.1"}}, "26.3", "BUGG", {}});
    QCOMPARE(session.status()["game"].toString(), "26.3");
    session.select_loader("fabric");
    const auto loader_request = port.last;
    emit port.cached(loader_request, {{{"0.19.0"}}, "0.19.0", "BUGG", {}});
    port.answer(loader_request, {{{"0.20.1"}, {"0.19.0"}}, "0.20.1", "BUGG", {}});
    QCOMPARE(session.status()["loaderVersion"].toString(), "0.20.1");
    session.select_game("1.21.1");
    session.refresh();
    const auto ids = port.queries.keys();
    for (const auto id : ids)
      if (port.queries[id].kind == "minecraft")
        port.answer(id, {{{"26.3"}, {"1.21.1"}}, "26.3", "BUGG", {}});
    QCOMPARE(session.status()["game"].toString(), "1.21.1");
    session.cancel();
  }
  void content_guide_waits_for_catalogue_and_selects_compatible_game() {
    FakeCatalog port;
    InstallCatalogSession session;
    session.set_service(&port);
    session.prepare_selection("1.21.1", "fabric");
    const auto games = port.last;
    QVERIFY(session.status()["loadingGames"].toBool());
    port.answer(games, {{{"26.3"}, {"1.21.1"}}, "26.3", "BUGG", {}});
    QCOMPARE(session.status()["game"].toString(), "1.21.1");
    QCOMPARE(session.status()["loader"].toString(), "fabric");
    QCOMPARE(port.queries[port.last].game_version, "1.21.1");
    port.answer(port.last, {{{"0.16.0"}}, "0.16.0", "BUGG", {}});
    QVERIFY(session.status()["ready"].toBool());
    session.prepare_selection("1.21.1", "forge");
    QCOMPARE(session.status()["loader"].toString(), "forge");
    session.cancel();
  }

  void local_cache_background_refresh_and_source_isolation() {
    QTemporaryDir dir;
    const auto path = dir.filePath(".buggcraft/catalog-cache.json");
    const CatalogQuery query{"fabric", "1.21.1"};
    const CatalogResult saved{{{"0.19.0"}}, "0.19.0", "BMCLAPI", {}};
    CatalogCache cache(path);
    QTRY_VERIFY(cache.ready());
    cache.store(CatalogCache::key({"BMCLAPI"}, query), saved);
    // 确认异步原子写已完成，才模拟新进程读取。
    QTRY_VERIFY(QFile::exists(path));
    FakeHttp http;
    GameCatalogService service(&http, {"BMCLAPI"}, nullptr, path);
    QSignalSpy snapshots(&service, &GameCatalogPort::cached);
    QSignalSpy done(&service, &GameCatalogPort::finished);
    service.query(1, query);
    QTRY_COMPARE(snapshots.size(), 1);
    QCOMPARE(qvariant_cast<CatalogResult>(snapshots[0][1]).preferred, "0.19.0");
    QCOMPARE(done.size(), 0);
    QTRY_COMPARE(http.last, 1);
    http.answer(1, {}, "offline");
    QTRY_COMPARE(done.size(), 1);
    service.query(2, query);
    QTRY_COMPARE(done.size(), 2);
    QCOMPARE(http.last, 1);  // 离线冷却内直接复用缓存。
    QCOMPARE(qvariant_cast<CatalogResult>(done[1][1]).preferred, "0.19.0");
    service.refresh(3, query);
    QTRY_COMPARE(http.last, 2);
    service.cancel(3);
    http.answer(
        2,
        R"([{"loader":{"version":"0.20.1","stable":true},"intermediary":{"version":"1.21.1"}}])");
    QTest::qWait(20);
    QCOMPARE(done.size(), 2);  // 取消后的结果不能通知或覆盖缓存。
    service.select_sources({"官方"});
    service.query(4, query);
    QTRY_COMPARE(http.last, 3);
    QCOMPARE(snapshots.size(), 2);  // 不使用 BMCLAPI 策略缓存。
    http.answer(
        3,
        R"([{"loader":{"version":"0.20.1","stable":true},"intermediary":{"version":"1.21.1"}}])");
    QTRY_COMPARE(done.size(), 3);
    QCOMPARE(qvariant_cast<CatalogResult>(done[2][1]).source, "官方");

    QFile invalid(dir.filePath("invalid.json"));
    QVERIFY(invalid.open(QIODevice::WriteOnly));
    invalid.write("broken-json");
    invalid.close();
    CatalogCache broken(invalid.fileName());
    QTRY_VERIFY(broken.ready());
    QVERIFY(!broken.lookup(CatalogCache::key({"BMCLAPI"}, query)));
  }

  void http_cancel_and_bounds() {
    QTcpServer server;
    QVERIFY(server.listen(QHostAddress::LocalHost));
    HttpClient http;
    QSignalSpy completed(&http, &HttpClient::completed);
    const auto invalid = http.get(QUrl("file:///bad"));
    http.cancel(invalid);
    QTest::qWait(20);
    QCOMPARE(completed.size(), 0);
    connect(&server, &QTcpServer::newConnection, this, [&] {
      auto* socket = server.nextPendingConnection();
      socket->setParent(&server);
      connect(socket, &QTcpSocket::readyRead, socket, [socket] {
        socket->readAll();
        socket->write("HTTP/1.1 200 OK\r\nContent-Length: 9000000\r\nConnection: close\r\n\r\n");
        socket->write(QByteArray(9000000, 'x'));
        socket->disconnectFromHost();
      });
    });
    http.get(QUrl(QString("http://127.0.0.1:%1/catalog").arg(server.serverPort())));
    QTRY_COMPARE_WITH_TIMEOUT(completed.size(), 1, 3000);
    QVERIFY(completed[0][1].toByteArray().isEmpty());
    QVERIFY(!completed[0][2].toString().isEmpty());
  }

  void http_timeouts_and_real_cancellation() {
    QTcpServer server;
    QVERIFY(server.listen(QHostAddress::LocalHost));
    // 接受连接但不回数据：确定性复现无进展、总时限和主动取消三种情况。
    connect(&server, &QTcpServer::newConnection, this, [&] {
      while (server.hasPendingConnections()) server.nextPendingConnection()->setParent(&server);
    });
    const QUrl url(QString("http://127.0.0.1:%1/stalled").arg(server.serverPort()));
    HttpClient idle_http(nullptr, {50, 1000});
    QSignalSpy idle_done(&idle_http, &HttpClient::completed);
    QSignalSpy unreachable(&idle_http, &HttpClient::unreachable);
    idle_http.get(url);
    QTRY_COMPARE_WITH_TIMEOUT(idle_done.size(), 1, 2000);
    QVERIFY(idle_done[0][2].toString().contains("接收数据超时"));
    QVERIFY(!idle_done[0][2].toString().contains("canceled"));
    QCOMPARE(unreachable.size(), 1);
    QCOMPARE(unreachable[0][0].toUrl(), url);

    HttpClient total_http(nullptr, {1000, 60});
    QSignalSpy total_done(&total_http, &HttpClient::completed);
    total_http.get(url);
    QTRY_COMPARE_WITH_TIMEOUT(total_done.size(), 1, 2000);
    QVERIFY(total_done[0][2].toString().contains("总时限"));

    HttpClient canceled_http(nullptr, {50, 100});
    QSignalSpy canceled_done(&canceled_http, &HttpClient::completed);
    QSignalSpy canceled_unreachable(&canceled_http, &HttpClient::unreachable);
    const auto id = canceled_http.get(url);
    canceled_http.cancel(id);
    QTest::qWait(150);
    QCOMPARE(canceled_done.size(), 0);
    QCOMPARE(canceled_unreachable.size(), 0);
  }

  void http_partial_resume_survives_client_restart() {
    ResumeServer server;
    QTemporaryDir directory;
    const auto options = server.file(directory.filePath("file.jar"));
    QFile original(options.output_path);
    QVERIFY(original.open(QIODevice::WriteOnly));
    original.write("keep existing until verified");
    original.close();
    {
      HttpClient first;
      QSignalSpy done(&first, &HttpClient::response);
      first.request(options);
      QTRY_COMPARE_WITH_TIMEOUT(done.size(), 1, 3000);
      QVERIFY(!done[0][2].toString().isEmpty());
    }
    QVERIFY(original.open(QIODevice::ReadOnly));
    QCOMPARE(original.readAll(), QByteArray("keep existing until verified"));
    original.close();
    const QDir parts(directory.filePath(".bugg-downloads"));
    QCOMPARE(parts.entryList({"*.part"}, QDir::Files).size(), 1);
    HttpClient restarted;
    QSignalSpy done(&restarted, &HttpClient::response);
    QSignalSpy restored(&restarted, &HttpClient::resumed);
    auto alternate = options;
    alternate.url.setPath("/same-content-alternate-route");
    restarted.request(alternate);
    QTRY_COMPARE_WITH_TIMEOUT(done.size(), 1, 3000);
    QVERIFY2(done[0][2].toString().isEmpty(), qPrintable(done[0][2].toString()));
    QCOMPARE(restored.size(), 1);
    QCOMPARE(restored[0][1].toLongLong(), 64 * 1024);
    QCOMPARE(server.ranges, (QList<QByteArray>{"", "bytes=65536-"}));
    QCOMPARE(server.sent, server.payload.size());
    QVERIFY(original.open(QIODevice::ReadOnly));
    QCOMPARE(original.readAll(), server.payload);
    QCOMPARE(parts.entryList({"*.part"}, QDir::Files).size(), 0);
  }

  void http_resume_fallback_and_integrity_data() {
    QTest::addColumn<QString>("mode");
    QTest::newRow("range-ignored") << "ignored";
    QTest::newRow("wrong-content-range") << "wrong";
    QTest::newRow("bad-content-hash") << "corrupt";
    QTest::newRow("encoded-range") << "encoded";
  }
  void http_resume_fallback_and_integrity() {
    QFETCH(QString, mode);
    ResumeServer server;
    QTemporaryDir directory;
    const auto options = server.file(directory.filePath("file.jar"));
    HttpClient http;
    QSignalSpy done(&http, &HttpClient::response);
    http.request(options);
    QTRY_COMPARE_WITH_TIMEOUT(done.size(), 1, 3000);
    QVERIFY(!done[0][2].toString().isEmpty());
    server.ignore_range = mode == "ignored";
    server.wrong_range = mode == "wrong";
    server.corrupt = mode == "corrupt";
    server.encoded = mode == "encoded";
    http.request(options);
    QTRY_COMPARE_WITH_TIMEOUT(done.size(), 2, 3000);
    QCOMPARE(server.ranges.last(), QByteArray("bytes=65536-"));
    const bool success = mode == "ignored";
    QCOMPARE(done[1][2].toString().isEmpty(), success);
    QCOMPARE(QFile::exists(options.output_path), success);
    QCOMPARE(QDir(directory.filePath(".bugg-downloads")).entryList({"*.part"}, QDir::Files).size(),
             0);
    if (success) {
      QFile file(options.output_path);
      QVERIFY(file.open(QIODevice::ReadOnly));
      QCOMPARE(file.readAll(), server.payload);
    }
  }

  void http_resume_cancel_and_exclusive_writer() {
    ResumeServer server;
    server.stall = true;
    QTemporaryDir directory;
    const auto options = server.file(directory.filePath("file.jar"));
    HttpClient first;
    QSignalSpy first_done(&first, &HttpClient::response);
    const auto id = first.request(options);
    const QDir parts(directory.filePath(".bugg-downloads"));
    QTRY_COMPARE_WITH_TIMEOUT(parts.entryList({"*.part"}, QDir::Files).size(), 1, 2000);
    QTRY_COMPARE_WITH_TIMEOUT(
        QFileInfo(parts.filePath(parts.entryList({"*.part"}, QDir::Files).first())).size(),
        64 * 1024, 2000);
    HttpClient other;
    QSignalSpy done(&other, &HttpClient::response);
    other.request(options);
    QTRY_COMPARE_WITH_TIMEOUT(done.size(), 1, 2000);
    QVERIFY(!done[0][2].toString().isEmpty());
    first.cancel(id);
    QCOMPARE(first_done.size(), 0);
    QVERIFY(!QFile::exists(options.output_path));
    server.stall = false;
    other.request(options);
    QTRY_COMPARE_WITH_TIMEOUT(done.size(), 2, 3000);
    QVERIFY2(done[1][2].toString().isEmpty(), qPrintable(done[1][2].toString()));
    QCOMPARE(server.ranges.last(), QByteArray("bytes=65536-"));
    QTest::qWait(30);
    QCOMPARE(first_done.size(), 0);
  }

  void source_switch_and_persistence() {
    FakeHttp http;
    GameCatalogService service(&http, {"BMCLAPI"});
    InstallCatalogSession session;
    session.set_service(&service);
    session.ensure_loaded();
    QTRY_COMPARE(http.last, 1);
    service.select_sources({"BUGG"});
    QTRY_COMPARE(http.last, 2);
    QVERIFY(http.cancelled.contains(1));
    QCOMPARE(http.urls.last().host(), "mirror.bugg.icu");
    http.answer(1, kManifest);  // 旧源迟到不能覆写新源。
    QVERIFY(session.status()["loadingGames"].toBool());
    http.answer(2, kManifest);
    QTRY_VERIFY(session.status()["ready"].toBool());
    QCOMPARE(session.status()["source"].toString(), "BUGG");
    service.select_sources({"BMCLAPI"});
    QTRY_COMPARE(http.last, 3);
    QCOMPARE(http.urls.last().host(), "bmclapi2.bangbang93.com");
    http.answer(3, {}, "network failed");
    QTRY_VERIFY(!session.status()["loadingGames"].toBool());
    QCOMPARE(http.last, 3);  // 固定 BMCLAPI 失败，没有任何官方请求。
    service.select_sources({"not-a-source"});
    service.select_sources({"BMCLAPI"});
    QCOMPARE(http.last, 3);

    QTemporaryDir dir;
    const auto path = dir.filePath("portable/.buggcraft/source-settings.json");
    SourceSettings settings(nullptr, path);
    QTRY_VERIFY(!settings.status()["loading"].toBool());
    QCOMPARE(settings.source_order(), supported_download_sources());
    QSignalSpy changed(&settings, &SourceSettings::source_order_changed);
    QVERIFY(!settings.set_source_order({"unknown"}));
    QVERIFY(!settings.set_source_order({"BUGG", "BUGG", "官方"}));
    QVERIFY(!settings.move_source(0, -1));
    QVERIFY(!settings.move_source(2, 1));
    QVERIFY(settings.move_source(1, -1));
    QVERIFY(settings.move_source(0, 1));
    QVERIFY(settings.move_source(1, -1));
    QTRY_VERIFY(!settings.status()["saving"].toBool());
    QVERIFY(settings.status()["error"].toString().isEmpty());
    QCOMPARE(changed.size(), 3);
    QVERIFY(settings.set_source_order(settings.source_order()));
    QCOMPARE(changed.size(), 3);
    SourceSettings restored(nullptr, path);
    QTRY_VERIFY(!restored.status()["loading"].toBool());
    QCOMPARE(restored.source_order(), (QStringList{"BMCLAPI", "BUGG", "官方"}));
    // 旧配置保留主动选源，并补齐其余优先级；不持有双份设置。
    QFile legacy(dir.filePath("legacy.json"));
    QVERIFY(legacy.open(QIODevice::WriteOnly));
    legacy.write(R"({"version":1,"game_source":"官方"})");
    legacy.close();
    SourceSettings migrated(nullptr, legacy.fileName());
    QTRY_VERIFY(!migrated.status()["loading"].toBool());
    QCOMPARE(migrated.source_order(), (QStringList{"官方", "BUGG", "BMCLAPI"}));
  }

  void source_origin_is_persisted_and_isolates_catalog_cache() {
    QTemporaryDir directory;
    const auto path = directory.filePath("sources.json");
    SourceSettings settings(nullptr, path);
    QTRY_VERIFY(!settings.status()["loading"].toBool());
    QSignalSpy changed(&settings, &SourceSettings::configuration_changed);
    QVERIFY(settings.set_bugg_base_url("https://source.example/launcher///"));
    QCOMPARE(settings.bugg_base_url(), QUrl("https://source.example/launcher"));
    QCOMPARE(changed.size(), 1);
    QVERIFY(settings.set_bugg_base_url("https://source.example/launcher/"));
    QCOMPARE(changed.size(), 1);
    QVERIFY(!settings.set_bugg_base_url("https://source.example/?secret=test"));
    QCOMPARE(settings.bugg_base_url(), QUrl("https://source.example/launcher"));
    QVERIFY(settings.set_bugg_base_url("https://source.example/launcher"));
    QTRY_VERIFY(!settings.status()["saving"].toBool());
    SourceSettings restored(nullptr, path);
    QTRY_VERIFY(!restored.status()["loading"].toBool());
    QCOMPARE(restored.bugg_base_url(), settings.bugg_base_url());

    FakeHttp http;
    GameCatalogService service(&http, {"BUGG"});
    QSignalSpy result(&service, &GameCatalogPort::finished);
    service.query(1, {});
    QTRY_COMPARE(http.last, 1);
    http.answer(1, kManifest);
    QTRY_COMPARE(result.size(), 1);
    service.select_sources({"BUGG"}, settings.bugg_base_url());
    service.query(2, {});
    QTRY_COMPARE(http.last, 2);
    QCOMPARE(http.urls.last(),
             QUrl("https://source.example/launcher/mc/game/version_manifest_v2.json"));
    http.answer(2, kManifest);
    QTRY_COMPARE(result.size(), 2);
    for (const auto& kind : {"minecraft", "forge", "neoforge", "fabric", "quilt"}) {
      const auto providers =
          default_catalog_providers({"BUGG"}, {kind, "1.21.1"}, settings.bugg_base_url());
      QCOMPARE(providers.size(), size_t(1));
      const auto url = providers.front()->request_url({kind, "1.21.1"});
      QCOMPARE(url.host(), "source.example");
      QVERIFY(url.path().startsWith("/launcher/"));
    }
  }

  void http_rejects_other_source_redirects() {
    QTcpServer origin;
    QTcpServer other;
    QVERIFY(origin.listen(QHostAddress::LocalHost));
    QVERIFY(other.listen(QHostAddress::LocalHost));
    int other_connections = 0;
    connect(&other, &QTcpServer::newConnection, this, [&] { ++other_connections; });
    connect(&origin, &QTcpServer::newConnection, this, [&] {
      auto* socket = origin.nextPendingConnection();
      socket->setParent(&origin);
      connect(socket, &QTcpSocket::readyRead, socket, [socket, &other] {
        socket->readAll();
        socket->write("HTTP/1.1 307 Temporary Redirect\r\nLocation: http://127.0.0.1:" +
                      QByteArray::number(other.serverPort()) +
                      "/must-not-request\r\nContent-Length: 0\r\nConnection: close\r\n\r\n");
        socket->disconnectFromHost();
      });
    });
    HttpClient http;
    QSignalSpy done(&http, &HttpClient::completed);
    http.get(QUrl(QString("http://127.0.0.1:%1/source").arg(origin.serverPort())), {"127.0.0.1"});
    QTRY_COMPARE_WITH_TIMEOUT(done.size(), 1, 2000);
    QVERIFY(!done[0][2].toString().isEmpty());
    QCOMPARE(other_connections, 0);
  }

  void live_catalogs() {
    if (!qEnvironmentVariableIsSet("BUGG_LIVE_CATALOG"))
      QSKIP("Live endpoint smoke test is opt-in");
    HttpClient http;
    const auto source = qEnvironmentVariable("BUGG_LIVE_SOURCE", "BMCLAPI");
    const auto order = source == "default" ? supported_download_sources() : QStringList{source};
    GameCatalogService service(&http, order);
    int completed = 0;
    QStringList errors;
    connect(
        &service, &GameCatalogPort::finished, this, [&](quint64 id, const CatalogResult& result) {
          ++completed;
          qInfo().noquote() << id << result.source << result.entries.size() << result.preferred
                            << result.error;
          if (!result.error.isEmpty() || result.entries.empty() || !order.contains(result.source))
            errors.push_back(QString::number(id) + result.error);
        });
    service.query(1, {"minecraft", {}});
    service.query(2, {"forge", "1.21.1"});
    service.query(3, {"neoforge", "1.21.1"});
    service.query(4, {"fabric", "1.21.1"});
    service.query(5, {"quilt", "1.20.1"});
    QTRY_COMPARE_WITH_TIMEOUT(completed, 5, 100000);
    QVERIFY2(errors.isEmpty(), qPrintable(errors.join("; ")));
  }
};
}  // namespace bugg

QTEST_GUILESS_MAIN(bugg::CatalogTest)
#include "catalog_test.moc"
