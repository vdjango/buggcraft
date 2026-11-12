#include <QCryptographicHash>
#include <QDesktopServices>
#include <QFile>
#include <QFutureWatcher>
#include <QJSEngine>
#include <QJsonArray>
#include <QJsonDocument>
#include <QProcess>
#include <QProcessEnvironment>
#include <QRegularExpression>
#include <QSignalSpy>
#include <QSslCertificate>
#include <QSslConfiguration>
#include <QTcpServer>
#include <QTcpSocket>
#include <QTemporaryDir>
#include <QTest>
#include <QUrlQuery>
#include <QtConcurrent/QtConcurrentRun>
#include <algorithm>

#include "app/application_lifecycle.h"
#include "language_asset_server.h"
#include "miniz.h"
#include "modules/account/application/microsoft_account.h"
#include "modules/account/infrastructure/credential_store.h"
#include "modules/account/ui/identity_session.h"
#include "modules/game_install/application/game_operations.h"
#include "modules/game_install/application/game_runtime.h"
#include "modules/game_install/application/modpack_plan.h"
#include "modules/multiplayer/application/multiplayer_service.h"
#include "modules/room_sync/application/room_content_cache.h"
#include "modules/settings/application/language_service.h"
#include "modules/settings/ui/source_settings.h"
#include "modules/update/application/launcher_update_service.h"
#include "platform/diagnostics/diagnostic_log.h"
#include "platform/runtime/runtime_environment.h"
#include "platform/security/device_key.h"

namespace bugg {
// 截获系统浏览器入口，不启动真实浏览器；生产授权流程仍由 MultiplayerService 驱动。
class BrowserProbe : public QObject {
  Q_OBJECT
 public:
  BrowserProbe() { QDesktopServices::setUrlHandler("https", this, "open"); }
  ~BrowserProbe() override { QDesktopServices::unsetUrlHandler("https"); }
  QList<QUrl> urls;
 public slots:
  void open(const QUrl& url) { urls.append(url); }
};
class AuthHttp : public HttpClient {
 public:
  quint64 sequence = 0;
  QList<HttpRequest> requests;
  QList<quint64> cancelled;
  std::function<void(quint64, HttpRequest)> on_request;
  quint64 request(const HttpRequest& request) override {
    requests.append(request);
    const auto id = ++sequence;
    if (on_request) QTimer::singleShot(0, this, [this, id, request] { on_request(id, request); });
    return id;
  }
  void cancel(quint64 id) override { cancelled.append(id); }
  void answer(const QJsonObject& body, int status = 200, quint64 id = 0) {
    emit response(id ? id : sequence, QJsonDocument(body).toJson(),
                  status >= 400 ? "HTTP error" : "", status);
  }
};
// 状态探测/真实节点建房共用协议夹具，仅测试使用；不启动游戏。
class GameStatusServer : public QTcpServer {
 public:
  explicit GameStatusServer(const QString& version) {
    const auto json =
        QJsonDocument(QJsonObject{{"version", QJsonObject{{"name", version}, {"protocol", 767}}},
                                  {"players", QJsonObject{{"online", 1}, {"max", 8}}}})
            .toJson(QJsonDocument::Compact);
    const auto packet = QByteArray(1, '\0') + integer(json.size()) + json;
    connect(this, &QTcpServer::newConnection, this, [this, packet] {
      while (hasPendingConnections()) {
        auto* socket = nextPendingConnection();
        connect(socket, &QTcpSocket::readyRead, socket, [packet, socket] {
          const auto bytes = socket->readAll();
          if (!socket->property("statusSent").toBool()) {
            socket->setProperty("statusSent", true);
            socket->write(integer(packet.size()) + packet);
          } else if (bytes.size() == 10 && bytes[0] == '\x09' && bytes[1] == '\x01') {
            socket->write(bytes);
          }
        });
        connect(socket, &QTcpSocket::disconnected, socket, &QObject::deleteLater);
      }
    });
  }

 private:
  static QByteArray integer(quint32 value) {
    QByteArray bytes;
    do {
      const auto part = value & 127;
      value >>= 7;
      bytes.append(static_cast<char>(part | (value ? 128 : 0)));
    } while (value);
    return bytes;
  }
};

class RuntimeTest : public QObject {
  Q_OBJECT
 private slots:
  void open_world_probe_accepts_loader_display_names_data() {
    QTest::addColumn<QString>("detected");
    QTest::addColumn<QString>("expected");
    QTest::addColumn<bool>("accepted");
    QTest::newRow("vanilla") << QString("1.21.1") << QString("1.21.1") << true;
    QTest::newRow("neoforge") << QString("NeoForge 26.3") << QString("26.3") << true;
    QTest::newRow("fabric") << QString("Fabric 1.21.1") << QString("1.21.1") << true;
    QTest::newRow("snapshot") << QString("26.1-snapshot-1") << QString("26.1-snapshot-1") << true;
    QTest::newRow("patch-mismatch") << QString("1.21.10") << QString("1.21.1") << false;
    QTest::newRow("snapshot-mismatch") << QString("1.21.1-pre1") << QString("1.21.1") << false;
    QTest::newRow("unknown") << QString("Unknown") << QString("26.3") << false;
  }
  void open_world_probe_accepts_loader_display_names() {
    QFETCH(QString, detected);
    QFETCH(QString, expected);
    QFETCH(bool, accepted);
    // 实际 NativeBridge / game.status + 本地协议夹具，不启动 Minecraft。
    GameStatusServer server(detected);
    QVERIFY(server.listen(QHostAddress::LocalHost));
    QTemporaryDir root;
    AuthHttp http;
    MultiplayerService service(
        &http, root.path(),
        QCoreApplication::applicationDirPath() + "/native/bin/buggcraft-bridge.exe");
    bool done = false;
    QString failure;
    QJsonObject result;
    const auto probe = [&] {
      done = false;
      service.probe_world(server.serverPort(), {{"version", expected}},
                          [&](const QJsonObject& world, const QString& error) {
                            result = world;
                            failure = error;
                            done = true;
                          });
    };
    probe();
    QTRY_VERIFY_WITH_TIMEOUT(done, 10000);
    QCOMPARE(failure.isEmpty(), accepted);
    QCOMPARE(result["version"].toString(), detected);
    if (!accepted) QVERIFY(failure.contains(expected));
    // 同一通道重试可成功，不能因上一轮失败挂住 busy 或丢回调。
    expected = detected;
    probe();
    QTRY_VERIFY_WITH_TIMEOUT(done, 10000);
    QVERIFY2(failure.isEmpty(), qPrintable(failure));
    service.shutdown();
    QTRY_VERIFY_WITH_TIMEOUT(!service.busy(), 10000);
  }
  void create_with_closed_world_restores_form_state() {
    QTcpServer closed;
    QVERIFY(closed.listen(QHostAddress::LocalHost));
    const auto port = closed.serverPort();
    closed.close();
    QTemporaryDir root;
    AuthHttp http;
    MultiplayerService service(
        &http, root.path(),
        QCoreApplication::applicationDirPath() + "/native/bin/buggcraft-bridge.exe");
    service.node_ = "test-only";
    service.status_["state"] = "ready";
    QSignalSpy joined(&service, &MultiplayerService::room_joined);
    service.create_room(
        "Existing world", root.path(), "Host",
        {{"instanceId", "installed"}, {"port", port}, {"game", QVariantMap{{"version", "26.3"}}}});
    QVERIFY(service.status().value("roomBusy").toBool());
    QTRY_VERIFY_WITH_TIMEOUT(!service.status().value("roomBusy").toBool(), 10000);
    QCOMPARE(joined.count(), 0);
    QVERIFY(!service.status().contains("room"));
    QVERIFY(service.status().value("error").toString().contains(QStringLiteral("重新查找")));
    service.discover_worlds();
    QVERIFY(service.status().value("worldsLoading").toBool());
    QVERIFY(service.status().value("error").toString().isEmpty());
    // 取消不等待扫描，迟到发现结果不能恢复建房。
    service.leave_room();
    QVERIFY(!service.status().value("worldsLoading").toBool());
    service.shutdown();
    QTRY_VERIFY_WITH_TIMEOUT(!service.busy(), 15000);
    QCOMPARE(joined.count(), 0);
  }
  void launcher_updates_use_existing_download_site_and_validate_feed() {
    QTemporaryDir root;
    AuthHttp http;
    LauncherUpdateService updates(&http, root.path());
    updates.check();
    updates.check();
    QCOMPARE(http.requests.size(), 1);
    QCOMPARE(http.requests.last().url.host(), "download.bugg.icu");
    QCOMPARE(QUrlQuery(http.requests.last().url).queryItemValue("current"), "2.0.1");
    http.answer({{"update_available", false}});
    QCOMPARE(updates.status().value("state").toString(), "latest");
    updates.check();
    QJsonObject asset{
        {"url", "https://download.bugg.icu/api/launcher/assets/2.0.2/Bugg-native.zip"},
        {"size", 1024},
        {"sha256", QString(64, 'a')}};
    http.answer({{"update_available", true}, {"version", "2.0.2"}, {"asset", asset}});
    QCOMPARE(updates.status().value("state").toString(), "available");
    QVERIFY(updates.status().value("automaticPackage").toBool());
    updates.check();
    asset["url"] = "https://untrusted.example/package.zip";
    http.answer({{"update_available", true}, {"version", "2.0.2"}, {"asset", asset}});
    QCOMPARE(updates.status().value("state").toString(), "error");
    updates.check();
    const auto late = http.sequence;
    updates.cancel();
    QVERIFY(http.cancelled.contains(late));
    http.answer({{"update_available", false}}, 200, late);
    QCOMPARE(updates.status().value("state").toString(), "idle");
    updates.shutdown();
  }
  void launcher_update_rolls_back_files_on_failed_replacement() {
    QTemporaryDir root;
    const auto target = root.filePath("target"), stage = root.filePath("stage");
    QDir().mkpath(target);
    QDir().mkpath(stage);
    QFile original(target + "/bugg.exe");
    QVERIFY(original.open(QIODevice::WriteOnly));
    original.write("previous");
    original.close();
    QFile replacement(stage + "/bugg.exe");
    QVERIFY(replacement.open(QIODevice::WriteOnly));
    replacement.write("replacement");
    replacement.close();
    const auto plan = root.filePath("plan.json");
    write_json(plan, {{"target", target},
                      {"stage", stage},
                      {"backup", root.filePath("previous")},
                      {"pid", 0},
                      {"executable", "bugg.exe"},
                      {"files", QJsonArray{"bugg.exe", "missing.dll"}}});
    QCOMPARE(LauncherUpdateService::apply_staged(plan), 1);
    QVERIFY(original.open(QIODevice::ReadOnly));
    QCOMPARE(original.readAll(), QByteArray("previous"));
    QVERIFY(QFileInfo(root.filePath("failure.json")).isFile());
  }
  void live_node_restores_approved_device_and_connects() {
    if (!qEnvironmentVariableIsSet("BUGG_TEST_NODE_RESTORE_CREDENTIALS"))
      QSKIP("Explicit isolated credential restore");
    QTemporaryDir root;
    QVERIFY(QFile::copy(qEnvironmentVariable("BUGG_TEST_NODE_RESTORE_CREDENTIALS"),
                        root.filePath("node-credentials.bin")));
    HttpClient http;
    auto bridge = QCoreApplication::applicationDirPath() + "/native/bin/buggcraft-bridge";
#ifdef Q_OS_WIN
    bridge += ".exe";
#endif
    MultiplayerService nodes(&http, root.path(), bridge);
    nodes.restore();
    QTRY_VERIFY_WITH_TIMEOUT(nodes.status().value("state").toString() == "ready" ||
                                 !nodes.status().value("error").toString().isEmpty(),
                             45000);
    QVERIFY2(nodes.status().value("state").toString() == "ready",
             qPrintable(nodes.status().value("error").toString()));
    QVERIFY(nodes.status().value("authorized").toBool());
    QTRY_VERIFY_WITH_TIMEOUT(!nodes.status().value("loading").toBool(), 15000);
    QVERIFY2(nodes.status().value("error").toString().isEmpty(),
             qPrintable(nodes.status().value("error").toString()));
    nodes.shutdown();
    QTRY_VERIFY_WITH_TIMEOUT(!nodes.busy(), 5000);
  }
  void launcher_update_helper_replaces_and_restarts_isolated_program() {
#ifdef Q_OS_WIN
    QTemporaryDir root;
    const auto target = root.filePath("target"), stage = root.filePath("stage");
    QDir().mkpath(target);
    QDir().mkpath(stage);
    QFile previous(target + "/bugg.exe");
    QVERIFY(previous.open(QIODevice::WriteOnly));
    previous.write("previous");
    previous.close();
    const auto probe = qEnvironmentVariable("SystemRoot") + "/System32/whoami.exe";
    QVERIFY(QFile::copy(probe, stage + "/bugg.exe"));
    const auto plan = root.filePath("plan.json");
    write_json(plan, {{"target", target},
                      {"stage", stage},
                      {"backup", root.filePath("previous")},
                      {"pid", 0},
                      {"executable", "bugg.exe"},
                      { "files",
                        QJsonArray{"bugg.exe"} }});
    QProcess helper;
    helper.start(QCoreApplication::applicationDirPath() + "/bugg.exe", {"--apply-update", plan});
    QVERIFY(helper.waitForFinished(10000));
    QCOMPARE(helper.exitCode(), 0);
    const auto cancelled = std::make_shared<std::atomic_bool>(false);
    QCOMPARE(file_digest(target + "/bugg.exe", "sha256", cancelled),
             file_digest(probe, "sha256", cancelled));
    QFile backup(root.filePath("previous/bugg.exe"));
    QVERIFY(backup.open(QIODevice::ReadOnly));
    QCOMPARE(backup.readAll(), QByteArray("previous"));
    QTRY_VERIFY_WITH_TIMEOUT(
        !QFile::exists(target + "/bugg.exe") || QFile::remove(target + "/bugg.exe"), 5000);
#else
    QSKIP("Windows helper entry integration; portable replacement logic is covered separately");
#endif
  }
  void room_empty_poll_workload() {
    QTemporaryDir root;
    AuthHttp http;
    MultiplayerService service(&http, root.path(), root.filePath("missing-bridge"));
    service.session_ = "room";
    QVariantList messages;
    for (int i = 0; i < 200; ++i)
      messages.append(QVariantMap{{"id", QString::number(i)}, {"text", QString(200, 'x')}});
    service.status_["messages"] = messages;
    service.status_["room"] = QVariantMap{{"id", "room"}, {"role", "guest"}};
    const auto original = service.status();
    QSignalSpy changes(&service, &MultiplayerService::changed);
    QElapsedTimer timer;
    timer.start();
    for (int i = 0; i < 25000; ++i) service.apply_room_events({});
    const auto elapsed = timer.nsecsElapsed();
    QCOMPARE(service.status(), original);
    if (qEnvironmentVariableIsEmpty("BUGG_TEST_ROOM_POLL_BASELINE")) QCOMPARE(changes.count(), 0);
    qInfo().noquote() << "ROOM_EMPTY_POLL_RESULT"
                      << QJsonDocument(QJsonObject{{"calls", 25000},
                                                   {"elapsed_ns", elapsed},
                                                   {"changed_signals", changes.count()},
                                                   {"state_verified", true}})
                             .toJson(QJsonDocument::Compact);
  }
  void room_listing_connection_failure_does_not_claim_invitation_required() {
    QTemporaryDir root;
    AuthHttp http;
    MultiplayerService service(&http, root.path(), root.filePath("missing-bridge"));
    service.node_ = "isolated-node";
    service.status_["rooms"] =
        QVariantList{QVariantMap{{"id", "public"}, {"require_invite", false}}};
    service.join_listing("public");
    QVERIFY(service.status().value("roomBusy").toBool());
    QTRY_VERIFY(!service.status().value("roomBusy").toBool());
    QCOMPARE(service.status().value("rooms").toList().size(), 1);
    QVERIFY(!service.status().contains("roomOperation"));
    QVERIFY(service.status().value("error").toString().contains(QString::fromUtf8("稍后重试")));
    QVERIFY(!service.status().value("error").toString().contains(QString::fromUtf8("需要邀请")));
    service.shutdown();
  }
  void room_events_still_publish_messages_and_transport() {
    QTemporaryDir root;
    AuthHttp http;
    MultiplayerService service(&http, root.path(), root.filePath("missing-bridge"));
    service.session_ = "room";
    service.status_["room"] = QVariantMap{{"id", "room"}, {"role", "guest"}};
    QSignalSpy changes(&service, &MultiplayerService::changed);
    service.apply_room_events(QJsonArray{
        QJsonObject{{"type", "message"}, {"id", "one"}, {"sender", "friend"}, {"text", "hello"}},
        QJsonObject{{"type", "transport"}, {"transport", "p2p"}},
        QJsonObject{{"type", "latency"}, {"latency_ms", 12.5}}});
    QCOMPARE(changes.count(), 1);
    QCOMPARE(service.status().value("messages").toList().size(), 1);
    const auto room = service.status().value("room").toMap();
    QCOMPARE(room.value("connectionMode").toString(), "p2p");
    QCOMPARE(room.value("latencyMs").toDouble(), 12.5);
    service.apply_room_events(QJsonArray{
        QJsonObject{{"type", "message"}, {"id", "one"}, {"sender", "friend"}, {"text", "hello"}}});
    QCOMPARE(service.status().value("messages").toList().size(), 1);
  }
  void room_result_keeps_node_and_host_latency_independent() {
    QTemporaryDir root;
    AuthHttp http;
    MultiplayerService service(&http, root.path(), root.filePath("missing-bridge"));
    service.session_ = "room";
    service.status_["room"] = QVariantMap{{"id", "room"}, {"role", "guest"}, {"latencyMs", 12.5}};
    const auto make_result = [](QJsonObject member) {
      return QJsonObject{
          {"session", "room"},
          {"role", "guest"},
          {"transport", "relay"},
          {"info", QJsonObject{{"lobby", QJsonObject{{"self_id", "guest"},
                                                     {"manager_id", "host"},
                                                     {"provider_id", "host"},
                                                     {"members", QJsonArray{member}}}}}}};
    };
    service.room_result(make_result(QJsonObject{{"id", "guest"},
                                                {"online", true},
                                                {"path", "relay"},
                                                {"rtt_ms", 7.5},
                                                {"rtt_kind", "node"},
                                                {"node_rtt_ms", 7.5},
                                                {"host_rtt_ms", 23.25},
                                                {"host_rtt_method", "minecraft-status-ping"}}),
                        {});
    auto room = service.status().value("room").toMap();
    QCOMPARE(room.value("nodeLatencyMs").toDouble(), 7.5);
    QCOMPARE(room.value("latencyMs").toDouble(), 23.25);
    auto members = room.value("members").toList();
    QCOMPARE(members.size(), 1);
    QCOMPARE(members[0].toMap().value("node_rtt_ms").toDouble(), 7.5);
    QCOMPARE(members[0].toMap().value("host_rtt_ms").toDouble(), 23.25);
    QCOMPARE(members[0].toMap().value("host_rtt_method").toString(), "minecraft-status-ping");

    service.room_result(make_result(QJsonObject{{"id", "guest"},
                                                {"online", true},
                                                {"stale", true},
                                                {"path", "unknown"},
                                                {"rtt_ms", QJsonValue::Null},
                                                {"rtt_kind", "unknown"},
                                                {"node_rtt_ms", QJsonValue::Null},
                                                {"host_rtt_ms", QJsonValue::Null}}),
                        {});
    room = service.status().value("room").toMap();
    QCOMPARE(room.value("nodeLatencyMs").toDouble(), -1.0);
    QCOMPARE(room.value("latencyMs").toDouble(), -1.0);

    service.room_result(make_result(QJsonObject{{"id", "guest"},
                                                {"online", true},
                                                {"path", "relay"},
                                                {"rtt_ms", 31.0},
                                                {"rtt_kind", "game"}}),
                        {});
    room = service.status().value("room").toMap();
    QCOMPARE(room.value("nodeLatencyMs").toDouble(), -1.0);
    QCOMPARE(room.value("latencyMs").toDouble(), 31.0);
    QCOMPARE(room.value("members").toList().first().toMap().value("node_rtt_ms").toDouble(), -1.0);
  }
#ifdef BUGG_TEST_SINGLE_FILE_EXE
  void complete_single_file_worker_uses_existing_rpc_and_shutdown() {
    NativeBridge bridge(QString::fromUtf8(BUGG_TEST_SINGLE_FILE_EXE));
    QJsonObject reply;
    QString failure;
    bool completed = false;
    bridge.call("bridge.initialize", {}, [&](const QJsonObject& value, const QString& error) {
      reply = value;
      failure = error;
      completed = true;
    });
    QTRY_VERIFY_WITH_TIMEOUT(completed, 15000);
    QVERIFY2(failure.isEmpty(), qPrintable(failure));
    QCOMPARE(reply["protocol"].toInt(), 1);
    QCOMPARE(reply["build"].toObject()["implementation"].toString(), QString("cpp"));
    QSignalSpy drained(&bridge, &NativeBridge::drained);
    bridge.shutdown();
    QTRY_VERIFY_WITH_TIMEOUT(drained.count() > 0, 10000);
    QVERIFY(!bridge.busy());
  }
#endif
  void native_bridge_prioritizes_only_unsent_background_requests() {
    const auto engine = QCoreApplication::applicationDirPath() + "/native/bin/buggcraft-bridge.exe";
    QVERIFY(QFileInfo::exists(engine));
    NativeBridge bridge(engine);
    QStringList order;
    QStringList failures;
    const auto submit = [&](const QString& name, NativeBridge::Priority priority) {
      bridge.call(
          "bridge.initialize", {},
          [&, name](const QJsonObject& value, const QString& error) {
            if (!error.isEmpty() || value["protocol"].toInt() != 1) failures.append(name);
            order.append(name);
          },
          priority);
    };
    submit("first", NativeBridge::Priority::Interactive);
    submit("background-1", NativeBridge::Priority::Background);
    submit("background-2", NativeBridge::Priority::Background);
    submit("interaction-1", NativeBridge::Priority::Interactive);
    submit("interaction-2", NativeBridge::Priority::Interactive);
    QTRY_COMPARE_WITH_TIMEOUT(order.size(), 5, 15000);
    QCOMPARE(order, QStringList({"first", "interaction-1", "interaction-2", "background-1",
                                 "background-2"}));
    QVERIFY(failures.isEmpty());
    order.clear();
    submit("already-sent", NativeBridge::Priority::Background);
    submit("queued-background", NativeBridge::Priority::Background);
    submit("next-interaction", NativeBridge::Priority::Interactive);
    QTRY_COMPARE_WITH_TIMEOUT(order.size(), 3, 15000);
    QCOMPARE(order, QStringList({"already-sent", "next-interaction", "queued-background"}));
    QVERIFY(failures.isEmpty());
    QSignalSpy drained(&bridge, &NativeBridge::drained);
    bridge.shutdown();
    QTRY_VERIFY_WITH_TIMEOUT(drained.count() > 0, 10000);
  }
  void social_notification_categories_read_independently() {
    QTemporaryDir root;
    AuthHttp http;
    MultiplayerService service(&http, root.path(), root.filePath("missing-bridge"));
    service.apply_social(
        {{"account", QString(32, 'a') + '.' + QString(32, 'b')},
         {"requests", QJsonArray{QJsonObject{{"id", "request"}, {"incoming", true}}}},
         {"invitations", QJsonArray{QJsonObject{{"id", "invite"}}}}});
    QCOMPARE(service.status().value("notificationCount").toInt(), 2);
    QCOMPARE(service.status().value("friendRequestCount").toInt(), 1);
    QCOMPARE(service.status().value("roomNotificationCount").toInt(), 1);
    service.mark_notifications_read("rooms");
    QCOMPARE(service.status().value("notificationCount").toInt(), 1);
    QCOMPARE(service.status().value("friendRequestCount").toInt(), 1);
    QCOMPARE(service.status().value("roomNotificationCount").toInt(), 0);
    QSignalSpy changes(&service, &MultiplayerService::changed);
    service.mark_notifications_read("rooms");
    QCOMPARE(changes.count(), 0);
    service.mark_notifications_read("requests");
    QCOMPARE(service.status().value("notificationCount").toInt(), 0);
  }
  void running_room_keeps_its_selected_instance() {
    QTemporaryDir root;
    AuthHttp http;
    MultiplayerService service(&http, root.path(), root.filePath("missing-bridge"));
    service.session_ = "room";
    service.status_["room"] = QVariantMap{{"id", "room"}, {"role", "guest"}, {"instanceId", "old"}};
    QSignalSpy checks(&service, &MultiplayerService::instance_check_requested);
    for (const auto* state : {"preparing", "running", "stopping"}) {
      service.launch_progress({{"state", state}});
      service.select_room_instance("new");
      QCOMPARE(service.status().value("room").toMap().value("instanceId").toString(), "old");
    }
    QCOMPARE(checks.count(), 0);
    service.launch_progress({{"state", "idle"}});
    service.select_room_instance("new");
    QCOMPARE(checks.count(), 1);
  }
  void task_history_clear_keeps_active_queue_and_persists() {
    QTemporaryDir root;
    HttpClient http;
    MicrosoftAccount account(&http, root.filePath("credentials.bin"));
    const auto settings = root.filePath(".buggcraft/instance-settings.json");
    QJsonArray tasks;
    for (const auto* state : {"done", "failed", "cancelled", "interrupted"})
      tasks.append(QJsonObject{{"id", state}, {"state", state}, {"kind", "install"}});
    write_json(settings, {{"tasks", tasks}});
    const auto sentinel = root.filePath(".minecraft/keep.txt");
    QDir().mkpath(QFileInfo(sentinel).absolutePath());
    QFile file(sentinel);
    QVERIFY(file.open(QIODevice::WriteOnly));
    file.write("keep");
    file.close();
    GameRuntime runtime(root.path(), root.filePath(".minecraft"), &account);
    QSignalSpy initialized(&runtime, &GameRuntime::initialized);
    runtime.initialize();
    QTRY_COMPARE_WITH_TIMEOUT(initialized.count(), 1, 15000);
    QCOMPARE(runtime.tasks().size(), 4);
    runtime.install({{"name", "active"}});
    runtime.install({{"name", "queued"}});
    QCOMPARE(runtime.tasks().size(), 6);
    QCOMPARE(runtime.clear_task_history(), 4);
    QCOMPARE(runtime.tasks().size(), 2);
    QCOMPARE(runtime.tasks().first().toMap().value("state").toString(), "queued");
    QCOMPARE(runtime.tasks().last().toMap().value("state").toString(), "running");
    QCOMPARE(runtime.clear_task_history(), 0);
    QVERIFY(QFileInfo::exists(sentinel));
    QSignalSpy drained(&runtime, &GameRuntime::drained);
    runtime.shutdown();
    QTRY_COMPARE_WITH_TIMEOUT(drained.count(), 1, 10000);
    const auto restored = read_json(settings)["tasks"].toArray();
    QCOMPARE(restored.size(), 2);
    for (const auto& task : restored) QVERIFY(task.toObject()["id"].toString() != "done");
  }
  void social_notifications_keep_read_state_and_receive_order() {
    QTemporaryDir root;
    AuthHttp http;
    MultiplayerService service(&http, root.path(), root.filePath("missing-bridge"));
    const auto account = QString(32, 'a') + '.' + QString(32, 'b');
    const QJsonObject request{{"id", "request"}, {"account", "friend"}, {"incoming", true}};
    QJsonObject snapshot{{"account", account}, {"requests", QJsonArray{request}}};
    service.apply_social(snapshot);
    QCOMPARE(service.status().value("notificationCount").toInt(), 1);
    const auto received = service.status().value("notificationAt").toLongLong();
    QVERIFY(received > 0);
    service.mark_notifications_read();
    QSignalSpy changes(&service, &MultiplayerService::changed);
    service.mark_notifications_read();
    QCOMPARE(changes.count(), 0);
    service.apply_social(snapshot);
    QCOMPARE(service.status().value("notificationCount").toInt(), 0);
    QCOMPARE(service.status().value("notificationAt").toLongLong(), received);
    QTest::qWait(2);
    snapshot["invitations"] = QJsonArray{QJsonObject{{"id", "invitation"}, {"account", "friend"}}};
    snapshot["joinRequests"] =
        QJsonArray{QJsonObject{{"id", "outgoing"}, {"incoming", false}, {"status", "pending"}}};
    service.apply_social(snapshot);
    const auto messages = service.status().value("notifications").toList();
    QCOMPARE(messages.size(), 2);
    QCOMPARE(messages.first().toMap().value("id").toString(), "invitation");
    QCOMPARE(messages.first().toMap().value("notificationKind").toString(), "invitations");
    QCOMPARE(service.status().value("notificationCount").toInt(), 1);
    service.social("ignore", "friend", {{"ref", "invitation"}});
    QCOMPARE(service.status().value("notifications").toList().size(), 1);
    QCOMPARE(service.status().value("notificationCount").toInt(), 0);
    service.logout();
    QVERIFY(service.status().value("notifications").toList().isEmpty());
  }
  void room_cache_uploads_only_source_requested_files() {
    QTemporaryDir root;
    const auto cancelled = std::make_shared<std::atomic_bool>(false);
    QJsonArray files;
    QStringList hashes;
    for (const auto* name : {"first.jar", "second.jar"}) {
      const QByteArray bytes(name);
      QFile file(root.filePath("mods/" + QString(name)));
      QDir().mkpath(QFileInfo(file).absolutePath());
      QVERIFY(file.open(QIODevice::WriteOnly));
      file.write(bytes);
      const auto hash =
          QString::fromLatin1(QCryptographicHash::hash(bytes, QCryptographicHash::Sha256).toHex());
      hashes.append(hash);
      files.append(QJsonObject{{"name", name}, {"size", bytes.size()}, {"sha256", hash}});
    }
    hashes.sort();
    const QJsonObject game{
        {"mods_count", 2},
        {"mods_hash", QString::fromLatin1(QCryptographicHash::hash(hashes.join('\n').toUtf8(),
                                                                   QCryptographicHash::Sha256)
                                              .toHex())},
        {"resources_count", 0},
        {"resources_hash",
         QString::fromLatin1(QCryptographicHash::hash({}, QCryptographicHash::Sha256).toHex())}};
    AuthHttp http;
    QTimer::singleShot(3000, &http, [cancelled] { cancelled->store(true); });
    int uploaded = 0, released = 0, plans = 0;
    bool transfer_progress = false, confirmed = false;
    http.on_request = [&](quint64 id, const HttpRequest& request) {
      if (request.url.path() == "/room-cache/plan") {
        const auto body = QJsonDocument::fromJson(request.body).object();
        if (++plans == 1)
          QCOMPARE(body["files"].toArray().size(), 2);
        else
          QVERIFY(body.isEmpty());
        auto planned = files;
        auto first = planned[0].toObject();
        first["action"] = uploaded ? "cached" : "upload";
        first["path"] = "mods/first.jar";
        planned[0] = first;
        http.answer({{"protocol", "room-content-cache-v1"},
                     {"state", "ready"},
                     {"files", planned},
                     {"summary", QJsonObject{{"total", 2},
                                             {"cached", uploaded},
                                             {"redirect", 1},
                                             {"upload", 1 - uploaded},
                                             {"pending", 0}}},
                     {"upload", uploaded ? QJsonArray{} : QJsonArray{files.first()}}},
                    200, id);
      } else if (request.method == "PUT") {
        QCOMPARE(request.input_path, root.filePath("mods/first.jar"));
        QFile file(request.input_path);
        QVERIFY(file.open(QIODevice::ReadOnly));
        QCOMPARE(file.readAll(), QByteArray("first.jar"));
        QVERIFY(request.headers.contains("Authorization"));
        emit http.progress(id, 4, 9);
        ++uploaded;
        auto receipt = files.first().toObject();
        receipt["state"] = "cached";
        http.answer(receipt, 200, id);
      } else if (request.url.path() == "/room-cache/release") {
        ++released;
        http.answer({}, 200, id);
      } else
        QFAIL("Unexpected cache request");
    };
    bool shared = false;
    RoomContentCache content(
        [&](const QString& method, QJsonObject parameters, const Cancellation&) {
          if (method == "mods.manifest")
            return QJsonObject{
                {"state", "complete"}, {"items", files}, {"offset", 0}, {"total", 2}};
          if (method == "room.request") {
            shared = parameters["request"].toObject()["share"].toBool();
            return QJsonObject{{"protocol", "room-content-cache-v1"},
                               {"url", "https://source.test"},
                               {"token", "test-only"},
                               {"expires_at", double(QDateTime::currentSecsSinceEpoch() + 600)}};
          }
          return QJsonObject{};
        },
        "test-room", cancelled,
        [&](const QVariantMap& progress) {
          const auto summary = progress.value("summary").toMap();
          if (progress.value("state") == "uploading" && progress.value("done").toInt() == 4) {
            transfer_progress = true;
            QCOMPARE(summary.value("cached").toInt(), 0);
            QCOMPARE(progress.value("total").toInt(), 9);
            QVERIFY(progress.value("progress").toDouble() > 0);
          }
          if (progress.value("state") == "ready") {
            confirmed = true;
            QCOMPARE(summary.value("cached").toInt(), 1);
            QCOMPARE(summary.value("redirect").toInt(), 1);
            QCOMPARE(progress.value("cachedFiles").toStringList(), QStringList{"mods/first.jar"});
            QVERIFY(progress.value("detail").toString().contains("mods/first.jar"));
            QVERIFY(!progress.value("active").toBool());
            cancelled->store(true);
          }
        },
        &http);
    content.host(root.path(), game);
    QVERIFY(shared);
    QCOMPARE(uploaded, 1);
    QCOMPARE(released, 1);
    QCOMPARE(plans, 2);
    QVERIFY(transfer_progress);
    QVERIFY(confirmed);
  }
  void room_cache_reports_empty_and_unconfigured() {
    const auto empty_hash =
        QString::fromLatin1(QCryptographicHash::hash({}, QCryptographicHash::Sha256).toHex());
    const auto hash = QString(64, 'a');
    for (const bool empty : {true, false}) {
      const auto cancelled = std::make_shared<std::atomic_bool>(false);
      QVariantMap last;
      int grants = 0;
      RoomContentCache content(
          [&](const QString& method, QJsonObject, const Cancellation&) -> QJsonObject {
            if (method == "mods.manifest")
              return {{"state", "complete"},
                      {"offset", 0},
                      {"total", 1},
                      {"items", QJsonArray{QJsonObject{
                                    {"name", "mod.jar"}, {"sha256", hash}, {"size", 1}}}}};
            ++grants;
            throw std::runtime_error("Room upload authorization is not configured on this node");
          },
          "test-room", cancelled,
          [&](const QVariantMap& snapshot) {
            last = snapshot;
            if (snapshot.value("state") == "unavailable") cancelled->store(true);
          });
      content.host(QDir::tempPath(),
                   {{"mods_count", empty ? 0 : 1},
                    {"mods_hash",
                     empty ? empty_hash
                           : QString::fromLatin1(QCryptographicHash::hash(
                                                     hash.toLatin1(), QCryptographicHash::Sha256)
                                                     .toHex())},
                    {"resources_count", 0},
                    {"resources_hash", empty_hash}});
      QCOMPARE(last.value("state").toString(), empty ? "empty" : "unavailable");
      QVERIFY(!last.value("active").toBool());
      QCOMPARE(grants, empty ? 0 : 1);
      if (!empty) QVERIFY(last.value("detail").toString().contains("节点未配置"));
    }
  }
  void live_room_source_cache() {
    if (!qEnvironmentVariableIsSet("BUGG_TEST_ROOM_CACHE_CREDENTIALS"))
      QSKIP("显式线上节点/源站缓存验收");
    QTemporaryDir root;
    const auto fixture = qEnvironmentVariable("BUGG_TEST_ROOM_CACHE_FILE");
    QVERIFY(QDir().mkpath(root.filePath("mods")));
    QVERIFY(QFile::copy(fixture, root.filePath("mods/" + QFileInfo(fixture).fileName())));
    QVERIFY(QFile::copy(qEnvironmentVariable("BUGG_TEST_ROOM_CACHE_CREDENTIALS"),
                        root.filePath("node-credentials.bin")));
    HttpClient http;
    auto bridge = QCoreApplication::applicationDirPath() + "/native/bin/buggcraft-bridge";
#ifdef Q_OS_WIN
    bridge += ".exe";
#endif
    MultiplayerService nodes(&http, root.path(), bridge);
    QVariantMap cache;
    QString last;
    connect(&nodes, &MultiplayerService::changed, this, [&] {
      const auto trace = qEnvironmentVariable("BUGG_TEST_ROOM_CACHE_TRACE");
      if (!trace.isEmpty()) {
        const auto room = nodes.status().value("room").toMap();
        write_json(
            trace,
            {{"state", nodes.status().value("state").toString()},
             {"roomRole", room.value("role").toString()},
             {"allowSharing", room.value("allowSharing").toBool()},
             {"game", QJsonObject::fromVariantMap(room.value("game").toMap())},
             {"cache", QJsonObject::fromVariantMap(nodes.status().value("cacheProgress").toMap())},
             {"error", nodes.status().value("error").toString()}});
      }
      const auto snapshot = nodes.status().value("cacheProgress").toMap();
      if (snapshot.isEmpty()) return;
      cache = snapshot;
      const auto state = cache.value("state").toString();
      if (state == last) return;
      last = state;
      qInfo().noquote() << "CACHE_STATE" << state << cache.value("detail").toString();
      if (state == "unavailable")
        qInfo().noquote() << "CACHE_FAILURE" << cache.value("error").toString();
    });
    nodes.restore();
    QTRY_VERIFY_WITH_TIMEOUT(nodes.status().value("state") == "ready" ||
                                 !nodes.status().value("error").toString().isEmpty(),
                             45000);
    QCOMPARE(nodes.status().value("state").toString(), "ready");
    nodes.create_room("Cache verification", root.path(), "CacheCheck",
                      {{"instanceId", "cache-verification"},
                       {"cacheAcceleration", true},
                       {"game", QVariantMap{{"version", "1.21.1"}, {"loader", "neoforge"}}}});
    QTRY_VERIFY_WITH_TIMEOUT(!nodes.status().value("roomBusy").toBool(), 30000);
    QVERIFY2(nodes.status().contains("room"), qPrintable(nodes.status().value("error").toString()));
    QTRY_VERIFY_WITH_TIMEOUT(
        cache.value("state") == "ready" || cache.value("state") == "unavailable", 90000);
    const auto result = cache;
    const auto summary = result.value("summary").toMap();
    const auto cancelled = std::make_shared<std::atomic_bool>(false);
    const auto hash = file_digest(fixture, "sha256", cancelled);
    int download_status = 0;
    QByteArray downloaded_hash;
    if (summary.value("cached").toInt()) {
      // 关闭房间会释放租约；在同一有效房间内验证成员取得的实体。
      QSignalSpy response(&http, &HttpClient::response);
      HttpRequest download;
      download.url = QUrl("https://mirror.bugg.icu/room-cache/files/" + hash);
      http.request(download);
      if (QTest::qWaitFor([&] { return response.count() == 1; }, 30000)) {
        download_status = response.last()[3].toInt();
        downloaded_hash =
            QCryptographicHash::hash(response.last()[1].toByteArray(), QCryptographicHash::Sha256)
                .toHex();
      }
    }
    QSignalSpy configured(&nodes, &MultiplayerService::room_command_completed);
    nodes.room_command("configure", {{"allow_mod_transfer", false}});
    QTRY_COMPARE_WITH_TIMEOUT(configured.count(), 1, 15000);
    QVERIFY(!nodes.status().value("room").toMap().value("allowSharing").toBool());
    QVERIFY(!nodes.status().contains("cacheProgress"));
    nodes.room_command("configure", {{"allow_mod_transfer", true}});
    QTRY_COMPARE_WITH_TIMEOUT(configured.count(), 2, 15000);
    QVERIFY(nodes.status().value("room").toMap().value("allowSharing").toBool());
    QTRY_VERIFY_WITH_TIMEOUT(
        nodes.status().value("cacheProgress").toMap().value("state") == "ready", 30000);
    nodes.leave_room();
    nodes.shutdown();
    QTRY_VERIFY_WITH_TIMEOUT(!nodes.busy(), 15000);
    QVERIFY2(result.value("state") == "ready", qPrintable(result.value("error").toString()));
    QCOMPARE(summary.value("total").toInt(), 1);
    QCOMPARE(summary.value("cached").toInt(), 1);
    QCOMPARE(summary.value("pending").toInt(), 0);
    qInfo() << "CACHE_CONFIRMED" << summary;
    QCOMPARE(download_status, 200);
    QCOMPARE(downloaded_hash, hash);
    qInfo() << "CACHE_DOWNLOAD_SHA256 verified";
  }
  void room_sync_checks_manifest_and_publishes_atomically_data() {
    QTest::addColumn<QString>("scenario");
    for (const auto* value :
         {"transfer", "local-reuse", "truncated", "unsafe-path", "hash-mismatch", "cancel"})
      QTest::newRow(value) << QString(value);
  }
  void room_sync_checks_manifest_and_publishes_atomically() {
    QFETCH(QString, scenario);
    QTemporaryDir root;
    const auto game_root = root.path() + "/.minecraft";
    const QByteArray body("room-mod-contents");
    const auto digest =
        QString::fromLatin1(QCryptographicHash::hash(body, QCryptographicHash::Sha256).toHex());
    const auto empty =
        QString::fromLatin1(QCryptographicHash::hash({}, QCryptographicHash::Sha256).toHex());
    const QJsonObject item{{"name", scenario == "unsafe-path" ? "../escape.jar" : "sample.jar"},
                           {"size", body.size()},
                           {"sha256", digest}};
    const QJsonObject game{
        {"version", "1.21.1"},
        {"loader", "fabric"},
        {"loader_version", "0.16.0"},
        {"mods_count", scenario == "truncated" ? 2 : 1},
        {"mods_hash",
         QString::fromLatin1(
             QCryptographicHash::hash(digest.toUtf8(), QCryptographicHash::Sha256).toHex())},
        {"resources_count", 0},
        {"resources_hash", empty}};
    const auto stage =
        ".room-" + QString::fromLatin1(
                       QCryptographicHash::hash(QJsonDocument(game).toJson(QJsonDocument::Compact),
                                                QCryptographicHash::Sha256)
                           .toHex()
                           .left(16));
    write_json(
        game_root + "/versions/" + stage + '/' + stage + ".json",
        {{"id", stage},
         {"bugg",
          QJsonObject{{"version", "1.21.1"}, {"loader", "fabric"}, {"loaderVersion", "0.16.0"}}}});
    const auto cancelled = std::make_shared<std::atomic_bool>(false);
    int fetches = 0, cleanups = 0;
    if (scenario == "local-reuse") {
      const auto local = game_root + "/versions/local/mods/sample.jar";
      QDir().mkpath(QFileInfo(local).absolutePath());
      QFile file(local);
      QVERIFY(file.open(QIODevice::WriteOnly));
      QCOMPARE(file.write(body), body.size());
      file.close();
      QFile corrupt(game_root + "/versions/" + stage + "/mods/sample.jar");
      QDir().mkpath(QFileInfo(corrupt).absolutePath());
      QVERIFY(corrupt.open(QIODevice::WriteOnly));
      corrupt.write("corrupt checkpoint");
    }
    const RoomContentRequest request = [&](const QString& method, const QJsonObject& parameters,
                                           const Cancellation&) {
      if (method == "mods.cancel") {
        ++cleanups;
        return QJsonObject{};
      }
      if (method == "mods.manifest")
        return QJsonObject{
            {"state", "complete"}, {"items", QJsonArray{item}}, {"offset", 0}, {"total", 1}};
      if (method == "mods.fetch") {
        ++fetches;
        if (scenario == "cancel") {
          cancelled->store(true);
          return QJsonObject{{"state", "opening"}, {"transfer", "test-transfer"}};
        }
        QFile file(parameters["target"].toString());
        if (!file.open(QIODevice::WriteOnly)) throw std::runtime_error("Cannot write test content");
        file.write(scenario == "hash-mismatch" ? QByteArray("incorrect-content") : body);
        return QJsonObject{{"state", "complete"}, {"transfer", "test-transfer"}};
      }
      throw std::runtime_error("Unexpected room operation");
    };
    GameOperations operation(game_root, root.path(), {"官方"}, cancelled,
                             [](double, const QString&) {});
    const QVariantMap spec{
        {"name", "room-instance"}, {"roomSession", "test-room"}, {"roomGame", game.toVariantMap()},
        {"game", "1.21.1"},        {"loader", "fabric"},         {"loaderVersion", "0.16.0"}};
    if (scenario == "transfer" || scenario == "local-reuse") {
      try {
        QCOMPARE(operation.sync_room(spec, request), QString("room-instance"));
      } catch (const std::exception& error) {
        QFAIL(error.what());
      }
      QCOMPARE(
          file_digest(game_root + "/versions/room-instance/mods/sample.jar", "sha256", cancelled),
          digest.toLatin1());
      QVERIFY(!QDir(game_root + "/versions/" + stage).exists());
      QCOMPARE(fetches, scenario == "transfer" ? 1 : 0);
      QCOMPARE(operation.sync_room(spec, request), QString("room-instance"));
      QCOMPARE(fetches, scenario == "transfer" ? 1 : 0);
    } else {
      QVERIFY_EXCEPTION_THROWN(operation.sync_room(spec, request), std::exception);
      QVERIFY(!QDir(game_root + "/versions/room-instance").exists());
      if (scenario == "cancel") QCOMPARE(cleanups, 1);
    }
  }
  void room_matching_reuses_base_without_changing_original_and_rechecks_before_launch() {
    QTemporaryDir root;
    const auto game_root = root.filePath(".minecraft");
    const auto original = game_root + "/versions/original";
    const auto cancelled = std::make_shared<std::atomic_bool>(false);
    const QByteArray body("required room mod");
    const auto hash =
        QString::fromLatin1(QCryptographicHash::hash(body, QCryptographicHash::Sha256).toHex());
    const auto empty =
        QString::fromLatin1(QCryptographicHash::hash({}, QCryptographicHash::Sha256).toHex());
    const QJsonObject game{
        {"version", "1.21.1"},
        {"loader", "fabric"},
        {"loader_version", "0.16.0"},
        {"mods_count", 1},
        {"mods_hash",
         QString::fromLatin1(
             QCryptographicHash::hash(hash.toUtf8(), QCryptographicHash::Sha256).toHex())},
        {"resources_count", 0},
        {"resources_hash", empty}};
    const QJsonObject metadata{
        {"id", "original"},
        {"mainClass", "Main"},
        {"bugg",
         QJsonObject{{"version", "1.21.1"}, {"loader", "fabric"}, {"loaderVersion", "0.15.0"}}}};
    write_json(original + "/original.json", metadata);
    QDir().mkpath(original + "/mods");
    QFile extra(original + "/mods/extra.jar");
    QVERIFY(extra.open(QIODevice::WriteOnly));
    extra.write("original content");
    extra.close();
    GameOperations operation(game_root, root.path(), {"官方"}, cancelled,
                             [](double, const QString&) {});
    const auto mismatch = operation.check_room("original", game);
    QVERIFY(!mismatch.value("compatible").toBool());
    QVERIFY(mismatch.value("canSupplement").toBool());
    QVERIFY(!mismatch.value("warning").toString().isEmpty());
    int fetched = 0;
    const RoomContentRequest request = [&](const QString& method, const QJsonObject& parameters,
                                           const Cancellation&) {
      if (method == "mods.manifest")
        return QJsonObject{
            {"state", "complete"},
            {"offset", 0},
            {"total", 1},
            {"items", QJsonArray{QJsonObject{
                          {"name", "required.jar"}, {"size", body.size()}, {"sha256", hash}}}}};
      if (method == "mods.fetch") {
        ++fetched;
        QFile file(parameters["target"].toString());
        if (!file.open(QIODevice::WriteOnly)) throw std::runtime_error("Test file write failed");
        file.write(body);
        return QJsonObject{{"state", "complete"}, {"transfer", "fixture"}};
      }
      return QJsonObject{};
    };
    const QVariantMap specification{{"name", "prepared"},
                                    {"roomSession", "test-room"},
                                    {"roomGame", game.toVariantMap()},
                                    {"baseInstance", "original"}};
    QCOMPARE(operation.sync_room(specification, request), QString("prepared"));
    QCOMPARE(fetched, 1);
    QCOMPARE(read_json(original + "/original.json"), metadata);
    QVERIFY(QFileInfo::exists(extra.fileName()));
    QVERIFY(!QFileInfo::exists(game_root + "/versions/prepared/mods/extra.jar"));
    QVERIFY(operation.check_room("prepared", game).value("compatible").toBool());
    QCOMPARE(instance_descriptor(read_json(game_root + "/versions/prepared/prepared.json"))
                 .value("loaderVersion")
                 .toString(),
             QString("0.15.0"));
    QCOMPARE(operation.sync_room(specification, request), QString("prepared"));
    QCOMPARE(fetched, 1);
    QFile changed(game_root + "/versions/prepared/mods/required.jar");
    QVERIFY(changed.open(QIODevice::WriteOnly));
    changed.write("changed after matching");
    changed.close();
    QVERIFY(!operation.check_room("prepared", game).value("compatible").toBool());
    // The last launch boundary rejects stale matching before any Java/network preparation.
    QVERIFY_EXCEPTION_THROWN(operation.prepare("prepared", 2048, {"Player", "uuid", {}, "offline"},
                                               {{"roomGame", game.toVariantMap()}}),
                             std::exception);
    auto wrong_loader = game;
    wrong_loader["loader"] = "neoforge";
    QVERIFY(!operation.check_room("original", wrong_loader).value("canSupplement").toBool());
    write_json(
        game_root + "/versions/plain/plain.json",
        {{"id", "plain"}, {"bugg", QJsonObject{{"version", "1.21.1"}, {"loader", "vanilla"}}}});
    auto vanilla = game;
    vanilla["mods_count"] = 0;
    vanilla["mods_hash"] = empty;
    for (const auto* name : {"vanilla", "minecraft", "Minecraft"}) {
      vanilla["loader"] = name;
      QVERIFY(operation.check_room("plain", vanilla).value("compatible").toBool());
    }
  }
  void legacy_instance_export_uses_shared_descriptor_and_safe_modpack_format() {
    try {
      QTemporaryDir root;
      const auto game = root.path() + "/.minecraft";
      write_json(root.path() + "/.buggcraft/metadata/1.20.1.json",
                 {{"id", "1.20.1"}, {"mainClass", "Minecraft"}});
      write_json(game + "/versions/legacy/legacy.json",
                 {{"id", "legacy"},
                  {"inheritsFrom", "1.20.1"},
                  {"libraries",
                   QJsonArray{QJsonObject{{"name", "net.minecraftforge:forge:1.20.1-47.3.0"}}}}});
      const auto mod = game + "/versions/legacy/mods/sample.jar";
      QDir().mkpath(QFileInfo(mod).absolutePath());
      QFile file(mod);
      QVERIFY(file.open(QIODevice::WriteOnly));
      QCOMPARE(file.write("sample-mod"), 10);
      file.close();
      const auto descriptor = instance_descriptor(read_json(game + "/versions/legacy/legacy.json"));
      QCOMPARE(descriptor.value("version").toString(), "1.20.1");
      QCOMPARE(descriptor.value("loader").toString(), "Forge");
      QCOMPARE(descriptor.value("loaderVersion").toString(), "47.3.0");
      const auto output = root.path() + "/legacy.buggpack";
      GameOperations operation(game, root.path(), {"BUGG", "BMCLAPI", "官方"},
                               std::make_shared<std::atomic_bool>(false),
                               [](double, const QString&) {});
      operation.export_pack("legacy", output, false, false);
      QCOMPARE(archive_read(output, "files/mods/sample.jar"), QByteArray("sample-mod"));
      const auto plan = inspect_modpack(output, std::make_shared<std::atomic_bool>(false));
      QCOMPARE(plan.format, "Buggcraft");
      QCOMPARE(plan.specification.value("game").toString(), "1.20.1");
      QCOMPARE(plan.specification.value("loader").toString(), "forge");
      QCOMPARE(plan.specification.value("loaderVersion").toString(), "47.3.0");
      QCOMPARE(plan.files.size(), 1);
      QVERIFY_EXCEPTION_THROWN(operation.export_pack("legacy", output, false, false),
                               std::runtime_error);
    } catch (const std::exception& error) {
      QFAIL(error.what());
    }
  }
  void separate_install_tasks_survive_failures_and_restart() {
    QTemporaryDir root;
    HttpClient http;
    MicrosoftAccount account(&http, root.path() + "/credentials.bin");
    GameRuntime runtime(root.path(), root.path() + "/.minecraft", &account);
    QSignalSpy initialized(&runtime, &GameRuntime::initialized);
    runtime.initialize();
    QTRY_COMPARE_WITH_TIMEOUT(initialized.count(), 1, 15000);
    runtime.install({{"name", "first"}, {"game", ""}});
    runtime.install({{"name", "second"}, {"game", ""}});
    QTRY_VERIFY_WITH_TIMEOUT(runtime.tasks().size() == 2 &&
                                 runtime.tasks()[0].toMap().value("state") == "failed" &&
                                 runtime.tasks()[1].toMap().value("state") == "failed",
                             15000);
    const auto first = runtime.tasks()[0].toMap();
    const auto second = runtime.tasks()[1].toMap();
    QVERIFY(first.value("id") != second.value("id"));
    QCOMPARE(first.value("name").toString(), "second");
    QCOMPARE(second.value("name").toString(), "first");
    QSignalSpy drained(&runtime, &GameRuntime::drained);
    runtime.shutdown();
    QTRY_COMPARE_WITH_TIMEOUT(drained.count(), 1, 5000);
    GameRuntime reopened(root.path(), root.path() + "/.minecraft", &account);
    QSignalSpy restored(&reopened, &GameRuntime::initialized);
    reopened.initialize();
    QTRY_COMPARE_WITH_TIMEOUT(restored.count(), 1, 15000);
    QCOMPARE(reopened.tasks().size(), 2);
    QCOMPARE(reopened.tasks()[0].toMap().value("id"), first.value("id"));
    QCOMPARE(reopened.tasks()[1].toMap().value("id"), second.value("id"));
    reopened.shutdown();
  }
  void deleting_instances_does_not_create_download_records() {
    QTemporaryDir root;
    const auto game = root.path() + "/.minecraft";
    for (const auto* id : {"hidden", "deleted"})
      write_json(game + "/versions/" + id + '/' + id + ".json", {{"id", id}});
    AuthHttp http;
    MicrosoftAccount account(&http, root.path() + "/credentials.bin");
    GameRuntime runtime(root.path(), game, &account);
    QSignalSpy initialized(&runtime, &GameRuntime::initialized);
    runtime.initialize();
    QTRY_COMPARE_WITH_TIMEOUT(initialized.count(), 1, 15000);
    QCOMPARE(runtime.instances().size(), 2);
    QVERIFY(runtime.remove_instance("hidden", false));
    QTRY_COMPARE_WITH_TIMEOUT(runtime.instances().size(), 1, 5000);
    QVERIFY(QFileInfo::exists(game + "/versions/hidden/.buggcraft-removed"));
    QVERIFY(runtime.tasks().isEmpty());
    QVERIFY(runtime.remove_instance("deleted", true));
    QTRY_COMPARE_WITH_TIMEOUT(runtime.instances().size(), 0, 5000);
    QVERIFY(!QFileInfo::exists(game + "/versions/deleted"));
    QVERIFY(runtime.tasks().isEmpty());
    runtime.shutdown();
    QTRY_VERIFY_WITH_TIMEOUT(!runtime.busy(), 5000);
  }
  void languages_retranslate_and_fall_back_without_losing_game_codes() {
    QTemporaryDir cache;
    LanguageAssetServer server;
    QVERIFY(server.listen(QHostAddress::LocalHost));
    LanguageService languages(nullptr, cache.path(), server.origin());
    QVERIFY(languages.options().size() >= 100);
    QVERIFY(!LanguageService::known_language("lol_us"));
    QVERIFY(!languages.set_code("../invalid"));
    languages.set_game_codes({"qzz_zz", "../invalid"});
    QVERIFY(!languages.set_code("qzz_zz"));
    languages.set_game_codes({});
    const auto options = languages.options();
    QVERIFY(!std::any_of(options.cbegin(), options.cend(), [](const QVariant& value) {
      return value.toMap().value("id") == "qzz_zz";
    }));
    QStringList english_names;
    for (const auto& option : options) {
      const auto entry = option.toMap();
      if (entry.value("id").toString().startsWith("en_"))
        english_names.append(entry.value("name").toString());
    }
    QVERIFY(english_names.size() >= 4);
    for (int index = 0; index < english_names.size(); ++index) {
      QVERIFY(english_names[index].contains(" · "));
      QCOMPARE(english_names.indexOf(english_names[index]), index);
    }
    QVERIFY(languages.set_code("en_us"));
    QTRY_COMPARE(languages.code(), QString("en_us"));
    QCOMPARE(QCoreApplication::translate("ToolDeck", "任务"), "Tasks");
    QCOMPARE(QCoreApplication::translate("FriendsPage", "联机通知"), "Bugg notifications");
    QCOMPARE(QCoreApplication::translate("ToolDeck", "请在游戏中对局域网开放"),
             "Open your game to LAN");
    QCOMPARE(QCoreApplication::translate("HomePage", "启动游戏"), "Play");
    QCOMPARE(QCoreApplication::translate("Bugg", "文件 %1 / %2 · %3").arg(1).arg(2).arg("a"),
             "File 1 / 2 · a");
    QVERIFY(languages.set_code("ja_jp"));
    QTRY_COMPARE(languages.code(), QString("ja_jp"));
    QCOMPARE(QCoreApplication::translate("FriendsPage", "联机通知"),
             QString::fromUtf8("Bugg 通知"));
    QVERIFY(languages.complete());
    QVERIFY(QCoreApplication::translate("MemoryControl", "自动分配内存") !=
            QString::fromUtf8("自动分配内存"));
    QVERIFY(languages.set_code("zh_cn"));
    QCOMPARE(QCoreApplication::translate("Bugg", "启动游戏"), QString::fromUtf8("启动游戏"));
  }
  void language_packages_download_verify_retry_cancel_and_reuse_offline() {
    QTemporaryDir cache;
    LanguageAssetServer server;
    QVERIFY(server.listen(QHostAddress::LocalHost));
    LanguageService languages(nullptr, cache.path(), server.origin());
    QCOMPARE(server.requests, 0);
    QVERIFY(languages.set_code("zh_cn"));
    QVERIFY(!languages.set_code("../../en_us"));
    QCOMPARE(server.requests, 0);
    server.corrupt = true;
    QVERIFY(languages.set_code("en_us"));
    QTRY_COMPARE(languages.status().value("state").toString(), QString("error"));
    QCOMPARE(languages.code(), QString("zh_cn"));
    QVERIFY(QDir(cache.path() + "/languages").entryList({"*.qm"}, QDir::Files).isEmpty());
    server.corrupt = false;
    languages.retry();
    QTRY_COMPARE(languages.code(), QString("en_us"));
    const auto downloaded = server.requests;
    QVERIFY(downloaded >= 2);
    QCOMPARE(QDir(cache.path() + "/languages").entryList({"*.qm"}, QDir::Files).size(), 1);
    server.delay_ms = 400;
    QVERIFY(languages.set_code("ja_jp"));
    QTRY_VERIFY(server.requests > downloaded);
    languages.cancel();
    QTRY_VERIFY(!languages.busy());
    QTest::qWait(450);
    QCOMPARE(languages.code(), QString("en_us"));
    QVERIFY(languages.set_code("ja_jp"));
    QVERIFY(languages.set_code("de_de"));
    QTRY_COMPARE(languages.code(), QString("de_de"));
    QCOMPARE(languages.status().value("state").toString(), QString("idle"));
    server.close();
    QVERIFY(languages.set_code("zh_cn"));
    LanguageService restored(nullptr, cache.path(), server.origin());
    QVERIFY(restored.set_code("en_us"));
    QTRY_COMPARE(restored.code(), QString("en_us"));
    QCOMPARE(QCoreApplication::translate("HomePage", "启动游戏"), QString("Play"));
    QVERIFY(restored.set_code("zh_cn"));
    languages.shutdown();
    QVERIFY(!languages.set_code("fr_fr"));
    QVERIFY(!languages.busy());
  }
  void game_options_preserve_other_settings_and_respect_supported_languages() {
    QTemporaryDir root;
    QDir().mkpath(root.path() + "/versions/game");
    write_json(root.path() + "/assets/indexes/test.json",
               {{"objects", QJsonObject{{"minecraft/lang/fr_fr.json", QJsonObject{}},
                                        {"minecraft/lang/zh_cn.json", QJsonObject{}}}}});
    const QJsonObject metadata{{"assetIndex", QJsonObject{{"id", "test"}}}};
    QFile options(root.path() + "/versions/game/options.txt");
    QVERIFY(options.open(QIODevice::WriteOnly));
    options.write(
        "lang:en_us\r\nfullscreen:true\r\nrenderDistance:8\r\nkey_key.attack:key.mouse.left\r\n");
    options.close();
    apply_game_options(root.path(), "game", metadata, {{"language", "fr_fr"}});
    QVERIFY(options.open(QIODevice::ReadOnly));
    auto data = options.readAll();
    options.close();
    QVERIFY(data.contains("lang:fr_fr\n"));
    QVERIFY(data.contains("fullscreen:true\n"));
    QVERIFY(data.contains("renderDistance:8\n"));
    QVERIFY(data.contains("key_key.attack:key.mouse.left\n"));
    apply_game_options(root.path(), "game", metadata,
                       {{"language", "lol_us"}, {"fullscreen", false}});
    QVERIFY(options.open(QIODevice::ReadOnly));
    data = options.readAll();
    options.close();
    QVERIFY(data.contains("lang:en_us\n"));
    QVERIFY(data.contains("fullscreen:false\n"));
    QVERIFY_EXCEPTION_THROWN(
        apply_game_options(root.path(), "../escape", metadata, {{"language", "en_us"}}),
        std::runtime_error);
  }
  void external_instances_and_immediate_settings_survive_restart() {
    QTemporaryDir root;
    HttpClient http;
    MicrosoftAccount account(&http, root.path() + "/credentials.bin");
    GameRuntime runtime(root.path(), root.path() + "/.minecraft", &account);
    QSignalSpy initialized(&runtime, &GameRuntime::initialized);
    QVERIFY(runtime.loading_instances());
    runtime.initialize();
    QTRY_COMPARE_WITH_TIMEOUT(initialized.count(), 1, 15000);
    QVERIFY(!runtime.loading_instances());
    QDir().mkpath(root.path() + "/.minecraft/versions/external");
    QTest::qWait(400);
    QCOMPARE(runtime.instances().size(), 0);
    write_json(root.path() + "/.minecraft/versions/external/external.json",
               {{"id", "external"}, {"mainClass", "Main"}});
    QTRY_COMPARE_WITH_TIMEOUT(runtime.instances().size(), 1, 5000);
    QVERIFY(runtime.set_game_setting("", "memoryMB", 3072));
    QVERIFY(runtime.set_game_setting("", "automatic", false));
    QCOMPARE(runtime.instance_settings("external").value("memoryMB").toInt(), 3072);
    QVERIFY(runtime.set_game_setting("external", "memoryMB", 2048));
    const auto chosen_java = root.path() + "/java/bin/java.exe";
    QDir().mkpath(QFileInfo(chosen_java).absolutePath());
    QFile java_file(chosen_java);
    QVERIFY(java_file.open(QIODevice::WriteOnly));
    java_file.close();
    const auto chosen_png = root.path() + "/java/bin/splash.png";
    QFile png_file(chosen_png);
    QVERIFY(png_file.open(QIODevice::WriteOnly));
    png_file.close();
    QVERIFY(!runtime.set_game_setting("", "javaPath", QUrl::fromLocalFile(chosen_png).toString()));
    QSignalSpy notices(&runtime, &GameRuntime::notice);
    QVERIFY(runtime.set_game_setting("", "javaPath", QUrl::fromLocalFile(chosen_java).toString()));
    QTRY_VERIFY_WITH_TIMEOUT(!notices.isEmpty(), 5000);
    QVERIFY(runtime.instance_settings("external").value("javaPath").toString().isEmpty());
    const auto candidates = runtime.environment().value("javaEntries").toList();
    if (!candidates.isEmpty()) {
      const auto verified_java = candidates.first().toMap().value("id").toString();
      QVERIFY(runtime.set_game_setting("", "javaPath", verified_java));
      QCOMPARE(runtime.instance_settings("external").value("javaPath").toString(), verified_java);
    }
    QVERIFY(runtime.set_game_setting("", "memoryMB", 4096));
    QCOMPARE(runtime.instance_settings("external").value("memoryMB").toInt(), 2048);
    QVERIFY(!runtime.set_game_setting("external", "memoryMB", 128));
    QVERIFY(!runtime.set_game_setting("external", "fullscreen", "yes"));
    QVERIFY(runtime.set_preference("language", "fr_fr"));
    QVERIFY(runtime.set_preference("concurrency", 16));
    QCOMPARE(runtime.preferences().value("showOverlayInFullscreen").toBool(), false);
    QVERIFY(!runtime.set_preference("showOverlayInFullscreen", "yes"));
    QVERIFY(runtime.set_preference("showOverlayInFullscreen", true));
    QCOMPARE(runtime.preferences().value("contentTranslation").toBool(), true);
    QVERIFY(runtime.set_preference("contentTranslation", false));
    QVERIFY(!runtime.set_preference("contentTranslation", "yes"));
    QVERIFY(runtime.set_preference("multiplayerOrigin", "https://test.example"));
    QVERIFY(!runtime.set_preference("multiplayerOrigin", 42));
    {
      QJSEngine engine;
      QVERIFY(runtime.set_preference(
          "identity",
          QVariant::fromValue(engine.evaluate(
              "({offline: ['PortablePlayer'], selectedId: 'offline:PortablePlayer'})"))));
    }
    QCOMPARE(runtime.preferences().value("identity").toMap().value("selectedId").toString(),
             "offline:PortablePlayer");
    QVERIFY(!runtime.set_preference("concurrency", 100));
    QSignalSpy changed(&runtime, &GameRuntime::settings_changed);
    QVERIFY(runtime.set_preference("concurrency", 16));
    QCOMPARE(changed.count(), 0);
    runtime.reset_instance_settings("external");
    QCOMPARE(runtime.instance_settings("external").value("memoryMB").toInt(), 4096);
    QVERIFY(!runtime.instance_settings("external").value("overridden").toBool());
    QSignalSpy drained(&runtime, &GameRuntime::drained);
    runtime.shutdown();
    QTRY_COMPARE_WITH_TIMEOUT(drained.count(), 1, 5000);
    GameRuntime reopened(root.path(), root.path() + "/.minecraft", &account);
    QSignalSpy restored(&reopened, &GameRuntime::initialized);
    reopened.initialize();
    QTRY_COMPARE_WITH_TIMEOUT(restored.count(), 1, 15000);
    QCOMPARE(reopened.preferences().value("language").toString(), "fr_fr");
    QCOMPARE(reopened.preferences().value("concurrency").toInt(), 16);
    QCOMPARE(reopened.preferences().value("showOverlayInFullscreen").toBool(), true);
    QCOMPARE(reopened.preferences().value("contentTranslation").toBool(), false);
    QCOMPARE(reopened.preferences().value("multiplayerOrigin").toString(), "https://test.example");
    QCOMPARE(reopened.preferences().value("identity").toMap().value("selectedId").toString(),
             "offline:PortablePlayer");
    QCOMPARE(reopened.instance_settings("external").value("memoryMB").toInt(), 4096);
    QVERIFY(!reopened.instance_settings("external").value("automatic").toBool());
    reopened.shutdown();
  }
  void selected_cache_stays_inside_portable_tree_after_move() {
    QTemporaryDir root;
    QVERIFY(root.isValid());
    const auto portable = root.path() + "/app";
    const auto chosen = portable + "/cache-alt";
    const auto outside = root.path() + "/outside";
    QVERIFY(QDir().mkpath(chosen));
    QVERIFY(QDir().mkpath(outside));
    write_json(portable + "/.buggcraft/marker.json", {{"value", 42}});
    {
      HttpClient http;
      MicrosoftAccount account(&http, portable + "/.buggcraft/credentials.bin");
      GameRuntime runtime(portable, portable + "/.minecraft", &account);
      QSignalSpy initialized(&runtime, &GameRuntime::initialized);
      runtime.initialize();
      QTRY_COMPARE_WITH_TIMEOUT(initialized.count(), 1, 15000);
      QSignalSpy notices(&runtime, &GameRuntime::notice);
      runtime.select_cache_root(QUrl::fromLocalFile(outside).toString());
      QTRY_COMPARE_WITH_TIMEOUT(notices.count(), 1, 5000);
      QCOMPARE(runtime.cache_root(), portable + "/.buggcraft");
      QVERIFY(!QFileInfo::exists(portable + "/bugg-portable.json"));
      runtime.select_cache_root(QUrl::fromLocalFile(chosen).toString());
      QTRY_COMPARE_WITH_TIMEOUT(runtime.cache_root(), chosen, 5000);
      QCOMPARE(read_json(portable + "/bugg-portable.json")["cache"].toString(), "cache-alt");
      QSignalSpy drained(&runtime, &GameRuntime::drained);
      runtime.shutdown();
      QTRY_COMPARE_WITH_TIMEOUT(drained.count(), 1, 5000);
    }
    const auto moved = root.path() + "/moved";
    QVERIFY(QDir().rename(portable, moved));
    QCOMPARE(portable_cache_root(moved), moved + "/cache-alt");
    QCOMPARE(read_json(moved + "/cache-alt/marker.json")["value"].toInt(), 42);
  }
  void final_arguments_preserve_values_and_repeatable_options() {
    const auto game = normalize_arguments(
        {"--username", "same", "--uuid", "same", "--username", "new", "--server", "same"}, false);
    QCOMPARE(game, (QStringList{"--uuid", "same", "--username", "new", "--server", "same"}));
    const auto jvm = normalize_arguments(
        {"-Xmx2G", "-Dtest=a", "--add-opens", "a/b=ALL-UNNAMED", "--add-opens", "c/d=ALL-UNNAMED",
         "--add-opens", "a/b=ALL-UNNAMED", "-Xmx6G", "-Dtest=b"},
        true);
    QCOMPARE(jvm.count("--add-opens"), 2);
    QCOMPARE(normalize_arguments(
                 {"--tweakClass", "a.A", "--tweakClass", "b.B", "--tweakClass", "a.A"}, false),
             (QStringList{"--tweakClass", "b.B", "--tweakClass", "a.A"}));
    QVERIFY(!jvm.contains("-Xmx2G"));
    QVERIFY(jvm.contains("-Xmx6G"));
    QVERIFY(!jvm.contains("-Dtest=a"));
    QVERIFY(jvm.contains("-Dtest=b"));
  }
  void inherited_dependencies_and_final_classpath_are_deduplicated() {
    QJsonArray libraries;
    for (int i = 0; i < 100; ++i) libraries.append(QJsonObject{{"name", "org.test:shared:1.0"}});
    libraries.append(QJsonObject{{"name", "org.test:shared:2.0"}});
    QCOMPARE(effective_libraries(libraries).size(), 1);
    QCOMPARE(effective_libraries(libraries)[0].toObject()["name"].toString(),
             "org.test:shared:2.0");
    QTemporaryDir root;
    const auto command = build_launch_command(
        {{"id", "game"},
         {"mainClass", "Main"},
         {"libraries", libraries},
         {"arguments", QJsonObject{{"jvm", QJsonArray{"-cp", "${classpath}"}},
                                   {"game", QJsonArray{"--username", "${auth_player_name}"}}}}},
        root.path(), "game", "java-exact.exe", 4096, {"Player", "uuid", "TOKEN", "microsoft"},
        {{"jvm", QStringList{"-Xmx3G"}},
         {"game", QStringList{"--username", "Player"}},
         {"classpath",
          QStringList{root.path() + "/libraries/org/test/shared/2.0/shared-2.0.jar"}}});
    QCOMPARE(command.arguments.count("--username"), 1);
    QVERIFY(command.arguments.contains("-Xmx3G"));
    QVERIFY(!command.arguments.contains("-Xmx4096M"));
    const auto classpath = command.arguments[command.arguments.indexOf("-cp") + 1];
    QCOMPARE(classpath.split(QDir::listSeparator()).size(), 2);
  }
  void module_path_does_not_duplicate_asm_on_classpath() {
    QTemporaryDir root;
    const auto asm_jar = root.filePath("asm.jar");
    const auto game_jar = root.filePath("game.jar");
    const auto args = normalize_arguments(
        {"--add-modules", "ALL-MODULE-PATH", "-p", asm_jar, "-cp",
         asm_jar + QDir::listSeparator() + game_jar + QDir::listSeparator() + asm_jar},
        true);
    QCOMPARE(args[args.indexOf("-cp") + 1], QDir::fromNativeSeparators(game_jar));
    const auto ordinary = normalize_arguments({"-cp", asm_jar}, true);
    QCOMPARE(ordinary[1], QDir::fromNativeSeparators(asm_jar));
  }
  void diagnostic_view_filters_modules_levels_and_redacts() {
    QTemporaryDir root;
    GameRuntime runtime(root.path(), root.filePath("game"), nullptr);
    runtime.initialize();
    QTRY_VERIFY(!runtime.loading_instances());
    record_diagnostic("repair.failed",
                      {{"state", "failed"}, {"detail", "password=private-fixture"}});
    runtime.refresh_debug_log("repair", "ERROR", "repair.failed");
    QTRY_VERIFY(!runtime.debug_log().value("busy").toBool());
    const auto entries = runtime.debug_log().value("entries").toList();
    QCOMPARE(entries.size(), 1);
    QVERIFY(!entries.first().toMap().value("message").toString().contains("private-fixture"));
    runtime.refresh_debug_log("download", "ERROR", "unique-nonexistent-filter");
    QTRY_VERIFY(!runtime.debug_log().value("busy").toBool());
    QVERIFY(runtime.debug_log().value("entries").toList().isEmpty());
    const auto logs = root.filePath("game/versions/log-fixture/logs");
    QDir().mkpath(logs);
    QVERIFY(runtime.set_preference("selectedInstance", "log-fixture"));
    QFile log(logs + "/launcher-game.log");
    QVERIFY(log.open(QIODevice::WriteOnly));
    log.write(
        "<log4j:Event logger=\"mixin\" timestamp=\"1794447240000\" level=\"FATAL\" "
        "thread=\"Render thread\"><log4j:Message><![CDATA[Mixin apply for mod sodium failed]]>"
        "</log4j:Message><log4j:Throwable><![CDATA[Caused by: InvalidInjectionException\n"
        " at fixture.Renderer.render(Renderer.java:1)]]></log4j:Throwable></log4j:Event>\n"
        "<log4j:Event logger=\"iris\" timestamp=\"1794447241000\" level=\"INFO\" "
        "thread=\"main\"><log4j:Message><![CDATA[Loaded]]></log4j:Message></log4j:Event>\n"
        "<log4j:Event logger=\"partial");
    log.close();
    runtime.refresh_debug_log("game", "FATAL", "InvalidInjectionException", "sodium");
    QTRY_VERIFY(!runtime.debug_log().value("busy").toBool());
    const auto fatal = runtime.debug_log().value("entries").toList();
    QCOMPARE(fatal.size(), 1);
    QCOMPARE(fatal.first().toMap().value("logger").toString(), QString("mixin"));
    QCOMPARE(fatal.first().toMap().value("thread").toString(), QString("Render thread"));
    QVERIFY(fatal.first().toMap().value("message").toString().contains("Renderer.java:1"));
    QVERIFY(runtime.debug_log().value("loggers").toStringList().contains("iris"));
    QVERIFY(QFile::remove(log.fileName()));
    log.setFileName(logs + "/latest.log");
    QVERIFY(log.open(QIODevice::WriteOnly));
    log.write(
        "[10:01:02] [Render thread/ERROR] [iris]: shader failure\n"
        "java.lang.IllegalStateException: broken\n at renderer.Frame.draw(Frame.java:2)\n"
        "[10:01:03] [main/INFO]: recovered\n");
    log.close();
    runtime.refresh_debug_log("game", "ERROR", "Frame.java", "iris");
    QTRY_VERIFY(!runtime.debug_log().value("busy").toBool());
    const auto plain = runtime.debug_log().value("entries").toList();
    QCOMPARE(plain.size(), 1);
    QVERIFY(plain.first().toMap().value("message").toString().contains("shader failure"));
    runtime.shutdown();
    QTRY_VERIFY(!runtime.busy());
  }
  void six_retries_have_one_total_budget_and_cancel_during_backoff() {
    AuthHttp http;
    int attempts = 0;
    http.on_request = [&](quint64 id, const HttpRequest&) {
      ++attempts;
      emit http.response(id, {}, "HTTP 503", 503);
    };
    QTemporaryDir root;
    auto cancellation = std::make_shared<std::atomic_bool>(false);
    ResourceClient resources(
        {QStringLiteral("官方")}, cancellation, [](double, const QString&) {}, &http, 2);
    const auto failures = resources.fetch(
        {{QUrl("https://example.com/fixture.jar"), root.filePath("fixture.jar"), {}, -1}}, true);
    QCOMPARE(attempts, 7);  // First request + six automatic retries across all routes.
    QCOMPARE(failures.size(), 1);
    attempts = 0;
    QTimer::singleShot(100, &http, [cancellation] { cancellation->store(true); });
    QVERIFY_EXCEPTION_THROWN(
        resources.fetch(
            {{QUrl("https://example.com/cancel.jar"), root.filePath("cancel.jar"), {}, -1}}),
        std::runtime_error);
    QCOMPARE(attempts, 1);
  }
  void room_launch_uses_quick_play_or_legacy_server_and_keeps_normal_launch_clean() {
    QTemporaryDir root;
    QJsonObject metadata{{"id", "game"}, {"mainClass", "Main"}};
    for (const bool modern : {false, true}) {
      if (modern)
        metadata["arguments"] = QJsonObject{
            {"game",
             QJsonArray{QJsonObject{
                 {"rules", QJsonArray{QJsonObject{
                               {"action", "allow"},
                               {"features", QJsonObject{{"is_quick_play_multiplayer", true}}}}}},
                 {"value", QJsonArray{"--quickPlayMultiplayer", "${quickPlayMultiplayer}"}}}}}};
      for (const bool joining : {false, true}) {
        const auto command = build_launch_command(
            metadata, root.path(), "game", "java.exe", 2048, {"Player", "uuid", {}, "offline"},
            joining ? QVariantMap{{"server", "127.0.0.1:25578"}} : QVariantMap{});
        QCOMPARE(command.arguments.contains("--quickPlayMultiplayer"), modern && joining);
        QCOMPARE(command.arguments.contains("--server"), !modern && joining);
        QCOMPARE(command.arguments.contains("--port"), !modern && joining);
        if (modern && joining)
          QCOMPARE(command.arguments.value(command.arguments.indexOf("--quickPlayMultiplayer") + 1),
                   QString("127.0.0.1:25578"));
        if (!modern && joining)
          QCOMPARE(command.arguments.value(command.arguments.indexOf("--port") + 1),
                   QString("25578"));
      }
    }
  }
  void offline_room_uses_lan_discovery_instead_of_online_quick_play() {
    QTemporaryDir root;
    const QJsonObject metadata{
        {"id", "game"},
        {"mainClass", "Main"},
        {"arguments",
         QJsonObject{
             {"game",
              QJsonArray{QJsonObject{
                  {"rules", QJsonArray{QJsonObject{
                                {"action", "allow"},
                                {"features", QJsonObject{{"is_quick_play_multiplayer", true}}}}}},
                  {"value", QJsonArray{"--quickPlayMultiplayer", "${quickPlayMultiplayer}"}}}}}}}};
    for (const auto* kind : {"offline", "microsoft"}) {
      const auto command = build_launch_command(
          metadata, root.path(), "game", "java.exe", 2048, {"Player", "uuid", {}, kind},
          {{"server", "127.0.0.1:25578"}, {"lanServer", true}});
      QCOMPARE(command.arguments.contains("--quickPlayMultiplayer"), QString(kind) == "microsoft");
      QVERIFY(!command.arguments.contains("--server"));
    }
  }
  void source_file_mapping_keeps_priority_and_official_supplement() {
    const auto urls =
        resource_urls(QUrl("https://libraries.minecraft.net/a/b.jar"), {"BUGG", "BMCLAPI", "官方"});
    QCOMPARE(urls.size(), 3);
    QCOMPARE(urls[0].host(), "mirror.bugg.icu");
    QCOMPARE(urls[1].host(), "bmclapi2.bangbang93.com");
    const auto dynamic =
        resource_urls(QUrl("https://example.com/a?token=x"), {"BUGG", "BMCLAPI", "官方"});
    QCOMPARE(dynamic.size(), 1);
    QCOMPARE(dynamic[0].host(), "example.com");
  }

  void source_origin_reaches_every_resource_mapping() {
    const QUrl base("https://source.example/launcher");
    const QStringList paths{
        "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json",
        "https://piston-data.mojang.com/v1/objects/hash/client.jar",
        "https://resources.download.minecraft.net/ab/hash",
        "https://libraries.minecraft.net/a/b.jar",
        "https://meta.fabricmc.net/v2/versions/loader/1.21.1",
        "https://meta.quiltmc.org/v3/versions/loader/1.21.1",
        "https://maven.fabricmc.net/a/b.jar",
        "https://maven.quiltmc.org/repository/release/a/b.jar",
        "https://maven.neoforged.net/releases/a/b.jar",
        "https://cdn.modrinth.com/data/id/version/file.jar",
        "https://edge.forgecdn.net/files/1/2/a.jar",
        "https://mediafilez.forgecdn.net/files/1/2/a.jar",
        "https://api.modrinth.com/v2/version_file/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "https://api.curseforge.com/v1/mods/123/files/456?gameVersion=1.21.1"};
    for (const auto& path : paths) {
      const auto urls = resource_urls(QUrl(path), {"BUGG"}, base);
      QCOMPARE(urls.size(), path.contains("forgecdn.net") ? 2 : 1);
      for (const auto& candidate : urls) QCOMPARE(candidate.host(), base.host());
      QCOMPARE(urls.first().host(), base.host());
      QVERIFY2(urls.first().path().startsWith("/launcher/"), qPrintable(urls.first().toString()));
      QCOMPARE(urls.first().query(), QUrl(path).query());
    }
    QCOMPARE(resource_urls(QUrl(paths.last()), {"BUGG"}, base).first().path(),
             "/launcher/v1/catalog/curseforge/mods/123/files/456");
  }
  void bootstrap_ignore_list_uses_actual_core_jar_name() {
    QTemporaryDir root;
    const auto command = build_launch_command(
        {{"id", "custom-instance"},
         {"jar", "1.21.1"},
         {"mainClass", "Main"},
         {"arguments",
          QJsonObject{{"jvm", QJsonArray{"-cp", "${classpath}",
                                         "-DignoreList=client-extra,${version_name}.jar"}}}}},
        root.path(), "custom-instance", "java.exe", 2048, {"Player", "uuid", {}, "offline"});
    QVERIFY(command.arguments.contains("-DignoreList=client-extra,1.21.1.jar"));
  }
  void fullscreen_and_window_dimensions_are_exclusive() {
    QTemporaryDir root;
    const QJsonObject metadata{
        {"id", "game"},
        {"mainClass", "Main"},
        {"arguments",
         QJsonObject{
             {"game",
              QJsonArray{QJsonObject{
                  {"rules", QJsonArray{QJsonObject{
                                {"action", "allow"},
                                {"features", QJsonObject{{"has_custom_resolution", true}}}}}},
                  {"value", QJsonArray{"--width", "${resolution_width}", "--height",
                                       "${resolution_height}"}}}}}}}};
    for (const bool fullscreen : {false, true}) {
      const auto command = build_launch_command(
          metadata, root.path(), "game", "java.exe", 2048, {"Player", "uuid", {}, "offline"},
          {{"fullscreen", fullscreen}, {"resolution", "1600x900"}});
      QCOMPARE(command.arguments.contains("--fullscreen"), fullscreen);
      QCOMPARE(command.arguments.count("--width"), fullscreen ? 0 : 1);
      QCOMPARE(command.arguments.count("--height"), fullscreen ? 0 : 1);
      if (!fullscreen) {
        QCOMPARE(command.arguments[command.arguments.indexOf("--width") + 1], "1600");
        QCOMPARE(command.arguments[command.arguments.indexOf("--height") + 1], "900");
      }
    }
  }
  void memory_is_recalculated_from_each_snapshot() {
    const QVariantMap snapshot{{"totalMB", 16384}, {"availableMB", 12000}};
    const auto first = automatic_memory_mb(snapshot);
    const auto modded = automatic_memory_mb(snapshot, 100);
    const auto hosting = automatic_memory_mb(snapshot, 100, 5);
    const auto constrained =
        automatic_memory_mb({{"totalMB", 16384}, {"availableMB", 4000}}, 100, 5);
    QVERIFY(modded > first);
    QVERIFY(hosting > modded);
    QVERIFY(constrained < hosting);
    QVERIFY(first <= 8192);
    QVERIFY(constrained >= 512);
  }
  void archive_path_traversal_is_rejected() {
    QTemporaryDir root;
    const auto path = root.path() + "/archive.zip";
    mz_zip_archive zip{};
    QVERIFY(mz_zip_writer_init_file(&zip, path.toUtf8().constData(), 0));
    QVERIFY(mz_zip_writer_add_mem(&zip, "../escape.txt", "bad", 3, 0));
    QVERIFY(mz_zip_writer_finalize_archive(&zip));
    mz_zip_writer_end(&zip);
    QVERIFY_EXCEPTION_THROWN(archive_extract(path, root.path() + "/output", {}, {},
                                             std::make_shared<std::atomic_bool>(false)),
                             std::runtime_error);
    QVERIFY(!QFileInfo::exists(root.path() + "/escape.txt"));
    QVERIFY_EXCEPTION_THROWN(safe_path(root.path(), "C:/escape"), std::runtime_error);
  }
  void grouped_downloads_and_catalogues_use_configured_concurrency() {
    QTemporaryDir root;
    AuthHttp http;
    int active = 0, peak = 0;
    QHash<QString, int> groups, peaks;
    http.on_request = [&](quint64 id, const HttpRequest& request) {
      const auto group = request.url.path().split('/').value(1);
      ++active;
      ++groups[group];
      peak = qMax(peak, active);
      peaks[group] = qMax(peaks[group], groups[group]);
      QTimer::singleShot(20, &http, [&, id, request, group] {
        if (!request.output_path.isEmpty()) {
          QDir().mkpath(QFileInfo(request.output_path).absolutePath());
          QFile file(request.output_path);
          QVERIFY(file.open(QIODevice::WriteOnly));
          file.write("ok");
          file.close();
        }
        --active;
        --groups[group];
        http.answer({{"ok", true}}, 200, id);
      });
    };
    ResourceClient client(
        {"官方"}, std::make_shared<std::atomic_bool>(false), [](double, const QString&) {}, &http,
        2);
    QList<GameResource> files;
    for (const auto* group : {"libraries", "assets", "mods"})
      for (int i = 0; i < 4; ++i)
        files.append({QUrl(QString("https://files.example/%1/%2").arg(group).arg(i)),
                      root.filePath(QString("%1/%2").arg(group).arg(i)),
                      {},
                      2});
    client.fetch(files);
    QCOMPARE(peak, 6);
    for (auto value : peaks) QCOMPARE(value, 2);
    active = 0;
    peak = 0;
    peaks.clear();
    http.requests.clear();
    const auto values = client.json_many({QUrl("https://files.example/catalogue/one"),
                                          QUrl("https://files.example/catalogue/two"),
                                          QUrl("https://files.example/catalogue/one")});
    QCOMPARE(values.size(), 2);
    QCOMPARE(http.requests.size(), 2);
    QCOMPARE(peak, 2);
    int attempts = 0;
    http.on_request = [&](quint64 id, const HttpRequest&) {
      ++attempts;
      http.answer({{"ok", true}}, attempts == 1 ? 503 : 200, id);
    };
    QVERIFY(client.json(QUrl("https://files.example/retry")).value("ok").toBool());
    QCOMPARE(attempts, 2);
    http.on_request = [&](quint64 id, const HttpRequest& request) {
      QCOMPARE(request.method, QByteArray("POST"));
      QCOMPARE(QJsonDocument::fromJson(request.body).object().value("fileIds").toArray(),
               QJsonArray({11, 12}));
      http.answer({{"ok", true}}, 200, id);
    };
    QVERIFY(client.json(QUrl("https://files.example/mods/files"), {{"fileIds", QJsonArray{11, 12}}})
                .value("ok")
                .toBool());
    const auto previous = qgetenv("BUGGCRAFT_CURSEFORGE_API_KEY");
    qunsetenv("BUGGCRAFT_CURSEFORGE_API_KEY");
    ResourceClient catalogue(
        {"BUGG", "官方"}, std::make_shared<std::atomic_bool>(false), [](double, const QString&) {},
        &http);
    http.requests.clear();
    http.on_request = [&](quint64 id, const HttpRequest& request) {
      QVERIFY(request.url.host() != "api.curseforge.com");
      http.answer({{"code", "source_rate_limited"}}, 429, id);
    };
    QString failure;
    try {
      catalogue.json(QUrl("https://api.curseforge.com/v1/mods/files"),
                     {{"fileIds", QJsonArray{11}}});
    } catch (const std::runtime_error& error) {
      failure = QString::fromUtf8(error.what());
    }
    qputenv("BUGGCRAFT_CURSEFORGE_API_KEY", previous);
    QVERIFY(failure.contains("频繁"));
    QCOMPARE(http.requests.size(), 3);
  }
  void large_download_ranges_validate_fallback_and_atomic_cancel() {
    QTcpServer server;
    QVERIFY(server.listen(QHostAddress::LocalHost));
    const QByteArray payload(10 * 1024 * 1024, 'x');
    bool supports = true;
    int ranged = 0, full = 0;
    connect(&server, &QTcpServer::newConnection, this, [&] {
      while (server.hasPendingConnections()) {
        auto* socket = server.nextPendingConnection();
        connect(socket, &QTcpSocket::readyRead, socket, [&, socket] {
          if (socket->property("handled").toBool()) {
            socket->readAll();
            return;
          }
          auto header = socket->property("header").toByteArray() + socket->readAll();
          socket->setProperty("header", header);
          if (!header.contains("\r\n\r\n")) return;
          socket->setProperty("handled", true);
          qint64 first = 0, last = payload.size() - 1;
          const auto range = QRegularExpression("Range: bytes=(\\d+)-(\\d+)",
                                                QRegularExpression::CaseInsensitiveOption)
                                 .match(QString::fromLatin1(header));
          const bool partial = supports && range.hasMatch();
          if (range.hasMatch())
            ++ranged;
          else
            ++full;
          if (partial) {
            first = range.captured(1).toLongLong();
            last = range.captured(2).toLongLong();
          }
          const auto bytes = last - first + 1;
          auto response =
              QByteArray(partial ? "HTTP/1.1 206 Partial Content\r\n" : "HTTP/1.1 200 OK\r\n") +
              "Content-Length: " + QByteArray::number(bytes) + "\r\nConnection: close\r\n";
          if (partial)
            response += "Content-Range: bytes " + QByteArray::number(first) + '-' +
                        QByteArray::number(last) + '/' + QByteArray::number(payload.size()) +
                        "\r\n";
          socket->write(response + "\r\n");
          auto* timer = new QTimer(socket);
          timer->setInterval(5);
          auto position = std::make_shared<qint64>(first);
          connect(timer, &QTimer::timeout, socket, [socket, timer, position, last, &payload] {
            if (socket->state() != QAbstractSocket::ConnectedState) {
              timer->stop();
              return;
            }
            const auto size = qMin<qint64>(256 * 1024, last - *position + 1);
            socket->write(payload.constData() + *position, size);
            *position += size;
            if (*position > last) {
              timer->stop();
              socket->disconnectFromHost();
            }
          });
          timer->start();
        });
        connect(socket, &QTcpSocket::disconnected, socket, &QObject::deleteLater);
      }
    });
    QTemporaryDir root;
    HttpClient http;
    HttpRequest request;
    request.url = QUrl(QString("http://127.0.0.1:%1/file").arg(server.serverPort()));
    request.sha1 = QCryptographicHash::hash(payload, QCryptographicHash::Sha1).toHex();
    request.expected_size = payload.size();
    request.maximum_bytes = payload.size() + 1;
    QList<qint64> times;
    for (int scenario = 0; scenario < 4; ++scenario) {
      supports = scenario != 2;
      ranged = 0;
      full = 0;
      request.parallel_ranges = scenario != 0;
      request.output_path = root.filePath(QString::number(scenario));
      if (scenario == 3) request.sha1 = QByteArray(40, '0');
      QEventLoop loop;
      QString failure;
      bool done = false;
      QElapsedTimer elapsed;
      elapsed.start();
      const auto id = http.request(request);
      const auto connection =
          connect(&http, &HttpClient::response, &loop,
                  [&](quint64 current, const QByteArray&, const QString& error, int) {
                    if (current == id) {
                      failure = error;
                      done = true;
                      loop.quit();
                    }
                  });
      QTimer::singleShot(10000, &loop, &QEventLoop::quit);
      loop.exec();
      disconnect(connection);
      QVERIFY(done);
      times.append(elapsed.elapsed());
      if (scenario == 3) {
        QVERIFY(!failure.isEmpty());
        QVERIFY(!QFileInfo::exists(request.output_path));
      } else {
        QVERIFY2(failure.isEmpty(), qPrintable(failure));
        QCOMPARE(
            file_digest(request.output_path, "sha1", std::make_shared<std::atomic_bool>(false)),
            request.sha1);
      }
      if (scenario == 0) {
        QCOMPARE(ranged, 0);
        QCOMPARE(full, 1);
      }
      if (scenario == 1) {
        QCOMPARE(ranged, 3);
        QCOMPARE(full, 0);
      }
      if (scenario == 2) QCOMPARE(full, 1);
    }
    qInfo().noquote() << QString(
                             "DOWNLOAD_RANGE_BENCH controlled 10MiB: single=%1ms three-ranges=%2ms "
                             "ratio=%3; not an Internet speed claim")
                             .arg(times[0])
                             .arg(times[1])
                             .arg(double(times[0]) / qMax<qint64>(1, times[1]), 0, 'f', 2);
    request.sha1 = QCryptographicHash::hash(payload, QCryptographicHash::Sha1).toHex();
    request.output_path = root.filePath("cancelled");
    const auto id = http.request(request);
    QTimer::singleShot(10, &http, [&] { http.cancel(id); });
    QTest::qWait(160);
    QVERIFY(!QFileInfo::exists(request.output_path));
  }
  void unrelated_download_does_not_block_launch_or_share_cancellation() {
    class AccountProbe : public AccountPort {
     public:
      int acquired = 0;
      void begin() override {}
      void cancel() override {}
      void logout() override {}
      void acquire(quint64, const QString&) override { ++acquired; }
    } account;
    QTemporaryDir root;
    const auto game = root.filePath("game");
    write_json(game + "/versions/fixture/fixture.json",
               {{"id", "fixture"},
                {"mainClass", "net.minecraft.client.main.Main"},
                {"bugg", QJsonObject{{"version", "1.21.1"}, {"loader", "vanilla"}}}});
    GameRuntime runtime(root.path(), game, &account);
    QSignalSpy initialized(&runtime, &GameRuntime::initialized);
    runtime.initialize();
    QTRY_COMPARE_WITH_TIMEOUT(initialized.count(), 1, 15000);
    runtime.install({{"name", "Unrelated download"},
                     {"game", "missing-review-version"},
                     {"loader", "vanilla"}});
    QVERIFY(!runtime.tasks().isEmpty());
    QCOMPARE(runtime.tasks().first().toMap().value("state").toString(), "running");
    runtime.launch("fixture", "offline:Review");
    QCOMPARE(account.acquired, 1);
    QCOMPARE(runtime.launch_status().value("state").toString(), "preparing");
    runtime.cancel_launch();
    QCOMPARE(runtime.launch_status().value("state").toString(), "idle");
    QCOMPARE(runtime.tasks().first().toMap().value("state").toString(), "running");
    runtime.shutdown();
    QTRY_VERIFY_WITH_TIMEOUT(!runtime.busy(), 15000);

    GameRuntime same_instance(root.path(), game, &account);
    same_instance.initialize();
    QTRY_VERIFY_WITH_TIMEOUT(!same_instance.loading_instances(), 15000);
    same_instance.install({{"kind", "content"}, {"id", "fixture"}, {"name", "Pending content"}});
    const auto installation = same_instance.tasks().first().toMap().value("id");
    same_instance.launch("fixture", "offline:Review");
    QCOMPARE(same_instance.launch_status().value("state").toString(), "preparing");
    QTRY_COMPARE_WITH_TIMEOUT(account.acquired, 2, 15000);
    const auto tasks = same_instance.tasks();
    const auto paused = std::find_if(tasks.begin(), tasks.end(), [&](const QVariant& task) {
      return task.toMap().value("id") == installation;
    });
    QVERIFY(paused != tasks.end());
    QCOMPARE(paused->toMap().value("state").toString(), "queued");
    same_instance.shutdown();
    QTRY_VERIFY_WITH_TIMEOUT(!same_instance.busy(), 15000);
  }
  void complete_client_zip_import_uses_existing_transaction() {
    QTemporaryDir root;
    const auto cancelled = std::make_shared<std::atomic_bool>(false);
    const QByteArray client("client bytes");
    const QJsonObject metadata{
        {"id", "1.19.2"},
        {"mainClass", "net.minecraft.client.main.Main"},
        {"arguments", QJsonObject{{"game", QJsonArray{"--fml.mcVersion", "1.19.2",
                                                      "--fml.forgeVersion", "43.5.2"}}}},
        {"downloads",
         QJsonObject{
             {"client",
              QJsonObject{
                  {"sha1", QString::fromLatin1(
                               QCryptographicHash::hash(client, QCryptographicHash::Sha1).toHex())},
                  {"size", client.size()}}}}}};
    const auto archive = root.filePath("client.zip");
    archive_write(archive, {},
                  {{".minecraft/versions/1.19.2/1.19.2.json", QJsonDocument(metadata).toJson()},
                   {".minecraft/versions/1.19.2/1.19.2.jar", client},
                   {".minecraft/versions/1.19.2/mods/example.jar", "mod"},
                   {".minecraft/launcher_accounts.json", "private"},
                   {"launcher.exe", "do not extract"},
                   {".minecraft/assets/indexes/fixture.json", "{}"}},
                  cancelled, {});
    const auto plan = inspect_modpack(archive, cancelled);
    QCOMPARE(plan.specification.value("game").toString(), "1.19.2");
    QCOMPARE(plan.specification.value("loader").toString(), "forge");
    QCOMPARE(plan.specification.value("loaderVersion").toString(), "43.5.2");
    GameOperations operation(root.filePath("game"), root.filePath("portable"), {"官方"}, cancelled,
                             [](double, const QString&) {});
    QCOMPARE(operation.import_pack(archive, "Imported client"), "Imported client");
    const auto instance = root.filePath("game/versions/Imported client");
    QVERIFY(QFileInfo::exists(instance + "/Imported client.jar"));
    QVERIFY(QFileInfo::exists(instance + "/mods/example.jar"));
    QCOMPARE(read_json(instance + "/Imported client.json").value("jar").toString(),
             "Imported client");
    QVERIFY(!QFileInfo::exists(root.filePath("game/launcher_accounts.json")));
    QVERIFY(!QFileInfo::exists(root.filePath("game/launcher.exe")));
    QVERIFY_EXCEPTION_THROWN(operation.import_pack(archive, "Imported client"), std::runtime_error);
  }
  void live_workspace_modpack_import_without_starting_game() {
    if (!qEnvironmentVariableIsSet("BUGG_TEST_WORKSPACE_PACK"))
      QSKIP("Explicit workspace archive verification only");
    const auto root = qEnvironmentVariable("BUGG_TEST_WORKSPACE_ROOT");
    QVERIFY(!root.isEmpty());
    const auto archive = qEnvironmentVariable("BUGG_TEST_WORKSPACE_PACK");
    QFutureWatcher<QString> watcher;
    watcher.setFuture(QtConcurrent::run([root, archive] {
      try {
        const auto cancelled = std::make_shared<std::atomic_bool>(false);
        const auto plan = inspect_modpack(archive, cancelled);
        qInfo().noquote() << "WORKSPACE_PACK" << QFileInfo(archive).fileName() << plan.format
                          << plan.specification.value("game") << plan.files.size();
        GameOperations operation(
            root + "/game", root + "/portable", {"BUGG", "BMCLAPI", "官方"}, cancelled,
            [](double, const QString& detail) { qInfo().noquote() << detail; });
        const auto name = qEnvironmentVariable("BUGG_TEST_WORKSPACE_NAME", "Verified pack");
        const auto id = operation.import_pack(archive, name);
        const auto metadata = operation.load_version(id);
        if (metadata["id"].toString() != id) return QString("missing committed profile");
        qInfo().noquote() << "WORKSPACE_PACK_IMPORTED" << id << "resources"
                          << metadata["buggcraftModpack"].toObject()["resources"].toArray().size();
        return QString();
      } catch (const std::exception& error) {
        return QString::fromUtf8(error.what());
      }
    }));
    QTRY_VERIFY_WITH_TIMEOUT(watcher.isFinished(), 1200000);
    QVERIFY2(watcher.result().isEmpty(), qPrintable(watcher.result()));
  }
  void actual_http_download_is_atomic_and_hash_checked() {
    QTcpServer server;
    QVERIFY(server.listen(QHostAddress::LocalHost));
    const QByteArray payload("verified file content");
    int requests = 0;
    connect(&server, &QTcpServer::newConnection, this, [&] {
      while (server.hasPendingConnections()) {
        auto* socket = server.nextPendingConnection();
        connect(socket, &QTcpSocket::readyRead, socket, [&, socket] {
          socket->readAll();
          ++requests;
          socket->write("HTTP/1.1 200 OK\r\nContent-Length: " + QByteArray::number(payload.size()) +
                        "\r\nConnection: close\r\n\r\n" + payload);
          socket->disconnectFromHost();
        });
        connect(socket, &QTcpSocket::disconnected, socket, &QObject::deleteLater);
      }
    });
    QTemporaryDir root;
    const GameResource resource{
        QUrl(QString("http://127.0.0.1:%1/file").arg(server.serverPort())), root.path() + "/file",
        QCryptographicHash::hash(payload, QCryptographicHash::Sha1).toHex(), payload.size()};
    QFutureWatcher<QString> watcher;
    watcher.setFuture(QtConcurrent::run([resource] {
      try {
        ResourceClient client({"官方"}, std::make_shared<std::atomic_bool>(false),
                              [](double, const QString&) {});
        client.fetch({resource});
        client.fetch({resource});  // 第二次必须命中校验缓存。
        auto invalid = resource;
        invalid.path += "-bad";
        invalid.sha1 = QByteArray(40, '0');
        try {
          client.fetch({invalid});
          return QString("未拒绝错误摘要");
        } catch (...) {
        }
        if (QFileInfo::exists(invalid.path)) return QString("错误摘要文件被提交");
        return QString();
      } catch (const std::exception& error) {
        return QString::fromUtf8(error.what());
      }
    }));
    QTRY_VERIFY_WITH_TIMEOUT(watcher.isFinished(), 10000);
    QVERIFY2(watcher.result().isEmpty(), qPrintable(watcher.result()));
    QCOMPARE(requests, 2);
    QVERIFY(QFileInfo::exists(resource.path));
  }
  void cold_origin_and_interrupted_200_recover_without_manual_retry() {
    QTcpServer server;
    QVERIFY(server.listen(QHostAddress::LocalHost));
    const QByteArray payload("cold-cache-complete-resource");
    int requests = 0;
    connect(&server, &QTcpServer::newConnection, this, [&] {
      while (server.hasPendingConnections()) {
        auto* socket = server.nextPendingConnection();
        connect(socket, &QTcpSocket::disconnected, socket, &QObject::deleteLater);
        connect(socket, &QTcpSocket::readyRead, socket, [&, socket] {
          socket->readAll();
          if (socket->property("handled").toBool()) return;
          socket->setProperty("handled", true);
          const auto header =
              "HTTP/1.1 200 OK\r\nContent-Length: " + QByteArray::number(payload.size()) +
              "\r\nConnection: close\r\n\r\n";
          if (++requests == 1) {
            socket->write(header + payload.first(3));
            socket->flush();  // HTTP 200 is already known when idle timeout fires.
          } else {
            QTimer::singleShot(160, socket, [socket, header, &payload] {
              socket->write(header + payload);
              socket->disconnectFromHost();
            });
          }
        });
      }
    });
    QTemporaryDir root;
    QFutureWatcher<QString> watcher;
    watcher.setFuture(QtConcurrent::run([&] {
      try {
        HttpClient http(nullptr, {60, 2000});
        ResourceClient client(
            {"官方"}, std::make_shared<std::atomic_bool>(false), [](double, const QString&) {},
            &http, 1);
        client.fetch({{QUrl(QString("http://127.0.0.1:%1/resource.jar").arg(server.serverPort())),
                       root.filePath("resource.jar"),
                       QCryptographicHash::hash(payload, QCryptographicHash::Sha1).toHex(),
                       payload.size()}});
        return QString();
      } catch (const std::exception& error) {
        return QString::fromUtf8(error.what());
      }
    }));
    QTRY_VERIFY_WITH_TIMEOUT(watcher.isFinished(), 5000);
    QVERIFY2(watcher.result().isEmpty(), qPrintable(watcher.result()));
    QVERIFY(requests >= 2 && requests <= 3);
    QFile file(root.filePath("resource.jar"));
    QVERIFY(file.open(QIODevice::ReadOnly));
    QCOMPARE(file.readAll(), payload);
    const auto events = diagnostic_snapshot();
    QVERIFY(events.contains("http.finish"));
    QVERIFY(events.contains("download.attempt"));
  }
  void diagnostics_export_is_bounded_redacted_and_does_not_collect_credentials() {
    QTemporaryDir root;
    HttpClient http;
    MicrosoftAccount account(&http, root.filePath("credentials.bin"));
    GameRuntime runtime(root.path(), root.filePath(".minecraft"), &account);
    runtime.initialize();
    QTRY_VERIFY_WITH_TIMEOUT(!runtime.loading_instances(), 15000);
    QDir().mkpath(runtime.cache_root() + "/logs");
    QFile log(runtime.cache_root() + "/logs/install.log");
    QVERIFY(log.open(QIODevice::WriteOnly));
    log.write(
        "access_token=SECRET1 password:SECRET2 Authorization: Bearer SECRET3\n"
        "GET https://user:SECRET4@example.com/file.jar?token=SECRET5#SECRET6\n");
    log.close();
    QFile credentials(runtime.cache_root() + "/credentials.bin");
    QVERIFY(credentials.open(QIODevice::WriteOnly));
    credentials.write("NEVER_EXPORT_THIS");
    credentials.close();
    record_diagnostic("export.regression", {{"file", "test.jar"}});
    const auto path = root.filePath("diagnostics.zip");
    runtime.export_diagnostics(QUrl::fromLocalFile(path).toString());
    QVERIFY(runtime.diagnostics_status().value("busy").toBool());
    QTRY_VERIFY_WITH_TIMEOUT(!runtime.diagnostics_status().value("busy").toBool(), 5000);
    QVERIFY2(runtime.diagnostics_status().value("error").toString().isEmpty(),
             qPrintable(runtime.diagnostics_status().value("error").toString()));
    const auto cancelled = std::make_shared<std::atomic_bool>(false);
    const auto names = archive_entries(path, cancelled);
    QVERIFY(names.contains("network-current.jsonl"));
    QVERIFY(names.contains("installer.log"));
    QVERIFY(!names.contains("credentials.bin"));
    const auto content = archive_read(path, "installer.log");
    QVERIFY(!content.contains("SECRET"));
    QVERIFY(content.contains("https://example.com/file.jar"));
    QFile original(path);
    QVERIFY(original.open(QIODevice::ReadOnly));
    const auto before = original.readAll();
    original.close();
    runtime.export_diagnostics(path);
    QTRY_VERIFY_WITH_TIMEOUT(!runtime.diagnostics_status().value("busy").toBool(), 5000);
    QVERIFY(!runtime.diagnostics_status().value("error").toString().isEmpty());
    QVERIFY(original.open(QIODevice::ReadOnly));
    QCOMPARE(original.readAll(), before);
    runtime.shutdown();
    QTRY_VERIFY(!runtime.busy());
  }
  void resource_batches_skip_unreachable_origin_but_not_missing_files() {
    for (const bool unreachable_origin : {true, false}) {
      AuthHttp http;
      int primary = 0;
      http.on_request = [&](quint64 id, const HttpRequest& request) {
        if (request.url.host() == "mirror.bugg.icu") {
          ++primary;
          if (unreachable_origin) emit http.unreachable(request.url);
          http.answer({}, 404, id);
        } else
          http.answer({{"ok", true}}, 200, id);
      };
      ResourceClient client(
          {"BUGG", "BMCLAPI", "官方"}, std::make_shared<std::atomic_bool>(false),
          [](double, const QString&) {}, &http);
      for (const auto* name : {"one", "two"})
        QVERIFY(client.json(QUrl(QString("https://libraries.minecraft.net/%1.json").arg(name)))
                    .value("ok")
                    .toBool());
      QCOMPARE(primary, unreachable_origin ? 1 : 2);
    }
    QTemporaryDir root;
    AuthHttp http;
    int primary = 0;
    http.on_request = [&](quint64 id, const HttpRequest& request) {
      if (request.url.host() == "mirror.bugg.icu") {
        ++primary;
        emit http.unreachable(request.url);
        http.answer({}, 503, id);
      } else {
        QFile file(request.output_path);
        QVERIFY(file.open(QIODevice::WriteOnly));
        QCOMPARE(file.write("ok"), 2);
        file.close();
        http.answer({{"ok", true}}, 200, id);
      }
    };
    ResourceClient client(
        {"BUGG", "BMCLAPI", "官方"}, std::make_shared<std::atomic_bool>(false),
        [](double, const QString&) {}, &http);
    QList<GameResource> files;
    for (int i = 0; i < 10; ++i)
      files.append({QUrl(QString("https://libraries.minecraft.net/%1.jar").arg(i)),
                    root.path() + '/' + QString::number(i),
                    {},
                    2});
    client.fetch(files);
    QCOMPARE(primary, 6);  // 只等待最初的六个在途请求，不给后续每个文件重复等待。
    for (const auto& file : files) QVERIFY(QFileInfo::exists(file.path));
  }
  void device_login_is_real_protocol_and_cancellation_drops_old_results() {
    QTemporaryDir root;
    AuthHttp http;
    MicrosoftAccount account(&http, root.path() + "/credentials.bin");
    IdentitySession session;
    session.set_service(&account);
    QVERIFY(session.use_offline("Original"));
    session.begin_microsoft();
    QVERIFY(http.requests.last().url.path().endsWith("/devicecode"));
    const auto old = http.sequence;
    session.cancel_microsoft();
    session.begin_microsoft();
    http.answer({{"device_code", "OLD"}, {"user_code", "WRONG"}}, 200, old);
    QVERIFY(session.status().value("code").toString().isEmpty());
    http.answer({{"device_code", "DEVICE_SECRET"},
                 {"user_code", "USER-CODE"},
                 {"interval", 5},
                 {"expires_in", 900}});
    QCOMPARE(session.status().value("code").toString(), "USER-CODE");
    QTRY_VERIFY_WITH_TIMEOUT(http.requests.last().url.path().endsWith("/token"), 7000);
    http.answer({{"access_token", "MS_SECRET"}, {"refresh_token", "REFRESH_SECRET"}});
    QVERIFY(http.requests.last().url.host() == "user.auth.xboxlive.com");
    const QJsonObject xbox_user{{"uhs", "HASH"}};
    const QJsonObject claims{{"xui", QJsonArray{xbox_user}}};
    http.answer({{"Token", "XBOX_SECRET"}, {"DisplayClaims", claims}});
    http.answer({{"Token", "XSTS_SECRET"}});
    http.answer({{"access_token", "MC_SECRET"}, {"expires_in", 3600}});
    QCOMPARE(http.requests.last().headers.value("Authorization"), "Bearer MC_SECRET");
    http.answer({{"name", "RealProfile"}, {"id", "0123456789abcdef0123456789abcdef"}});
    QCOMPARE(session.status().value("name").toString(), "RealProfile");
    QVERIFY(!QJsonDocument::fromVariant(session.status()).toJson().contains("SECRET"));
    QVERIFY(session.use_offline("Original"));
    session.begin_microsoft();
    QCOMPARE(session.status().value("name").toString(), "RealProfile");
    QTRY_VERIFY_WITH_TIMEOUT(!account.busy(), 5000);
#ifdef Q_OS_WIN
    QFile encrypted(root.path() + "/credentials.bin");
    QVERIFY(encrypted.open(QIODevice::ReadOnly));
    QVERIFY(!encrypted.readAll().contains("REFRESH_SECRET"));
    encrypted.close();
    QVERIFY(load_credentials(root.path() + "/credentials.bin").contains("REFRESH_SECRET"));
#endif
    session.logout_microsoft();
    QCOMPARE(session.status().value("kind").toString(), "offline");
    QTRY_VERIFY_WITH_TIMEOUT(!account.busy(), 5000);
    QVERIFY(!QFileInfo::exists(root.path() + "/credentials.bin"));
  }
  void cancelled_install_does_not_commit_instance_or_partial_file() {
    QTemporaryDir root;
    QTcpServer server;
    QVERIFY(server.listen(QHostAddress::LocalHost));
    const auto cancelled = std::make_shared<std::atomic_bool>(false);
    connect(&server, &QTcpServer::newConnection, this, [&] {
      auto* socket = server.nextPendingConnection();
      connect(socket, &QTcpSocket::readyRead, socket, [&, socket] {
        socket->readAll();
        socket->write("HTTP/1.1 200 OK\r\nContent-Length: 100000\r\n\r\npartial");
        socket->flush();
        cancelled->store(true);
      });
      connect(socket, &QTcpSocket::disconnected, socket, &QObject::deleteLater);
    });
    write_json(root.path() + "/.buggcraft/metadata/test.json",
               {{"id", "test"},
                {"downloads",
                 QJsonObject{{"client", QJsonObject{{"url", QString("http://127.0.0.1:%1/core")
                                                                .arg(server.serverPort())},
                                                    {"size", 100000}}}}}});
    QFutureWatcher<QString> watcher;
    watcher.setFuture(QtConcurrent::run([&] {
      try {
        GameOperations operation(root.path() + "/.minecraft", root.path(), {"官方"}, cancelled,
                                 [](double, const QString&) {});
        operation.install({{"name", "cancelled"}, {"game", "test"}, {"loader", "vanilla"}});
        return QString();
      } catch (const std::exception& error) {
        return QString::fromUtf8(error.what());
      }
    }));
    QTRY_VERIFY_WITH_TIMEOUT(watcher.isFinished(), 10000);
    QVERIFY(cancelled->load());
    QVERIFY(!watcher.result().isEmpty());
    QVERIFY(!QFileInfo::exists(root.path() + "/.minecraft/versions/cancelled/cancelled.json"));
    QVERIFY(!QFileInfo::exists(root.path() + "/.minecraft/versions/test/test.jar"));
  }
  void process_exit_releases_notifier_before_closing_handle() {
#ifdef Q_OS_WIN
    QTemporaryDir root;
    GameProcess process;
    QSignalSpy exited(&process, &GameProcess::exited);
    const auto powershell =
        qEnvironmentVariable("SystemRoot") + "/System32/WindowsPowerShell/v1.0/powershell.exe";
    for (int i = 0; i < 2; ++i) {
      const auto pid = start_game_process(
          {powershell,
           {"-NoProfile", "-NonInteractive", "-Command",
            "Write-Output 'stdout-marker'; [Console]::Error.WriteLine('stderr-marker'); "
            "Start-Sleep -Milliseconds 100; exit 7"},
           root.path(),
           root.path() + "/process.log"});
      process.watch(pid);
      QTRY_COMPARE_WITH_TIMEOUT(exited.count(), i + 1, 10000);
      QCOMPARE(exited.last()[0].toInt(), 7);
      QFile log(root.path() + "/process.log");
      QVERIFY(log.open(QIODevice::ReadOnly));
      const auto output = log.readAll();
      QVERIFY(output.contains("stdout-marker"));
      QVERIFY(output.contains("stderr-marker"));
    }
#endif
  }
  void native_window_close_drains_and_exits() {
#ifdef Q_OS_WIN
    const auto build = QCoreApplication::applicationDirPath();
    QTemporaryDir root;
    const auto executable = root.path() + "/bugg.exe";
    QVERIFY(QFile::copy(build + "/bugg.exe", executable));
    for (const auto& theme : {"classic", "panel"}) {
      auto environment = QProcessEnvironment::systemEnvironment();
      environment.insert("PATH", build + QDir::listSeparator() + environment.value("PATH"));
      environment.insert("QML_IMPORT_PATH", build + "/qml");
      environment.insert("QT_QUICK_BACKEND", "software");
      QProcess process;
      process.setProcessEnvironment(environment);
      process.setWorkingDirectory(root.path());
      process.start(executable, {"--theme", theme});
      QVERIFY(process.waitForStarted(5000));
      QTest::qWait(1500);
      QCOMPARE(process.state(), QProcess::Running);
      // Windows terminate 只发 WM_CLOSE，不强杀；必须走真实 QML/生命周期收尾。
      process.terminate();
      QTRY_COMPARE_WITH_TIMEOUT(process.state(), QProcess::NotRunning, 15000);
      QCOMPARE(process.exitStatus(), QProcess::NormalExit);
      QCOMPARE(process.exitCode(), 0);
    }
#endif
  }
  void lifecycle_initializes_real_instances_and_drains_without_blocking() {
    QTemporaryDir root;
    write_json(root.path() + "/.minecraft/versions/real/real.json",
               {{"id", "real"}, {"mainClass", "Main"}});
    QDir().mkpath(root.path() + "/.minecraft/versions/broken");
    QFile broken(root.path() + "/.minecraft/versions/broken/broken.json");
    QVERIFY(broken.open(QIODevice::WriteOnly));
    broken.write("bad");
    broken.close();
    AuthHttp http;
    MicrosoftAccount account(&http, root.path() + "/credentials.bin");
    SourceSettings sources(nullptr, root.path() + "/sources.json");
    GameRuntime runtime(root.path(), root.path() + "/.minecraft", &account);
    ApplicationLifecycle lifecycle(&runtime, &account, &sources);
    QSignalSpy hooks(&lifecycle, &ApplicationLifecycle::hook);
    QSignalSpy quit(&lifecycle, &ApplicationLifecycle::quit_ready);
    lifecycle.before_mount();
    lifecycle.mounted();
    lifecycle.mounted();
    QTRY_COMPARE_WITH_TIMEOUT(lifecycle.phase(), "ready", 15000);
    QTRY_COMPARE_WITH_TIMEOUT(runtime.instances().size(), 1, 15000);
    QCOMPARE(runtime.instances()[0].toMap().value("id").toString(), "real");
    QVERIFY(runtime.instance_settings("real").value("automatic").toBool());
    runtime.save_instance_settings("real", false, 3072);
    QTRY_VERIFY_WITH_TIMEOUT(!runtime.busy(), 5000);
    const auto saved = read_json(root.path() + "/.buggcraft/instance-settings.json");
    QCOMPARE(saved["instances"].toObject()["real"].toObject()["memoryMB"].toInt(), 3072);
    QVERIFY(!QJsonDocument(saved).toJson().contains("automaticMemoryMB"));
    lifecycle.update_view("settings");
    lifecycle.set_presented(false);
    lifecycle.set_presented(true);
    QTRY_VERIFY(hooks.count() >= 9);
    lifecycle.shutdown();
    QTRY_COMPARE(quit.count(), 1);
    QCOMPARE(lifecycle.phase(), "stopped");
    GameRuntime reopened(root.path(), root.path() + "/.minecraft", &account);
    QSignalSpy restored(&reopened, &GameRuntime::initialized);
    reopened.initialize();
    QTRY_COMPARE_WITH_TIMEOUT(restored.count(), 1, 15000);
    QVERIFY(!reopened.instance_settings("real").value("automatic").toBool());
    QCOMPARE(reopened.instance_settings("real").value("memoryMB").toInt(), 3072);
    QVERIFY(reopened.environment().value("automaticMemoryMB").toInt() >= 512);
    reopened.shutdown();
  }
  void node_login_retry_and_cancellation_keep_one_authorization() {
    QTemporaryDir root;
    AuthHttp http;
    MultiplayerService nodes(&http, root.path(), root.path() + "/missing-bridge");
    nodes.login();
    QCOMPARE(http.sequence, 1);
    const auto first = http.sequence;
    nodes.login();
    QCOMPARE(http.sequence, 1);
    nodes.logout();
    QVERIFY(http.cancelled.contains(first));
    nodes.login();
    const auto second = http.sequence;
    QVERIFY(second != first);
    http.answer({{"error", "late failure"}}, 400, first);
    QCOMPARE(nodes.status().value("state").toString(), "authorizing");
    http.answer({{"error", "authorization unavailable"}}, 400, second);
    QCOMPARE(nodes.status().value("state").toString(), "signedOut");
    QCOMPARE(nodes.status().value("error").toString(), "authorization unavailable");
    nodes.login();
    http.answer({{"id", "device"},
                 {"nonce", "nonce"},
                 {"verification_uri", "https://wrong.invalid/authorize"}});
    QCOMPARE(nodes.status().value("state").toString(), "signedOut");
    QVERIFY(nodes.status().value("verificationUrl").toString().isEmpty());
    nodes.shutdown();
    QTRY_VERIFY_WITH_TIMEOUT(!nodes.busy(), 5000);
  }
  void node_browser_approval_leaves_waiting_and_connects() {
    QTemporaryDir root;
    AuthHttp http;
    BrowserProbe browser;
    MultiplayerService nodes(&http, root.path(), root.path() + "/missing-bridge");
    QStringList states;
    connect(&nodes, &MultiplayerService::changed, this,
            [&] { states.append(nodes.status().value("state").toString()); });
    nodes.login();
    const QJsonValue public_key =
        QJsonDocument::fromJson(http.requests.first().body).object()["key"];
    http.answer(
        {{"id", "device"},
         {"nonce", "nonce"},
         {"interval", 1},
         {"verification_uri",
          http.requests.first().url.resolved(QUrl("/account/access?launcher=device")).toString()}});
    QCOMPARE(browser.urls.size(), 1);
    QTRY_COMPARE_WITH_TIMEOUT(http.requests.size(), 2, 5000);
    QCOMPARE(http.requests.last().url.path(), "/api/launcher/poll");
    http.answer({{"status", "pending"}});
    QCOMPARE(nodes.status().value("state").toString(), "authorizing");
    QTRY_COMPARE_WITH_TIMEOUT(http.requests.size(), 3, 5000);
    const auto claims =
        QJsonDocument(QJsonObject{{"e", QDateTime::currentSecsSinceEpoch() + 3600},
                                  {"g", QJsonObject{{"r", "device"}, {"d", public_key}}}})
            .toJson(QJsonDocument::Compact);
    const auto token =
        "acct1." + claims.toBase64(QByteArray::Base64UrlEncoding | QByteArray::OmitTrailingEquals) +
        ".test";
    http.answer({{"status", "approved"},
                 {"name", "node"},
                 {"profile", QJsonObject{{"server_host", "127.0.0.1"},
                                         {"server_public_key", "test-key"},
                                         {"token", QString::fromLatin1(token)}}}});
    QVERIFY(states.contains("connecting"));
    QTRY_COMPARE_WITH_TIMEOUT(nodes.status().value("state").toString(), "signedOut", 3000);
    QVERIFY(!nodes.status().value("error").toString().isEmpty());
    QVERIFY(nodes.status().value("authorized").toBool());
    const auto request_count = http.requests.size();
    const auto browser_count = browser.urls.size();
    nodes.login();
    QTRY_COMPARE_WITH_TIMEOUT(nodes.status().value("state").toString(), "signedOut", 3000);
    QCOMPARE(http.requests.size(), request_count);
    QCOMPARE(browser.urls.size(), browser_count);
    nodes.shutdown();
    QTRY_VERIFY_WITH_TIMEOUT(!nodes.busy(), 5000);
  }
  void node_restore_renews_or_returns_to_authorization_data() {
    QTest::addColumn<QString>("scenario");
    for (const auto* value : {"renew", "revoked", "expired-network", "wrong-challenge", "cancel"})
      QTest::newRow(value) << QString(value);
  }
  void node_restore_renews_or_returns_to_authorization() {
#if !defined(Q_OS_WIN) && !defined(Q_OS_MACOS)
    QSKIP("当前平台不保存长期节点凭据");
#else
    QFETCH(QString, scenario);
    QTemporaryDir root;
    const auto key = create_device_key();
    const auto public_key = device_public_key(key);
    const QJsonObject claims{
        {"e", QDateTime::currentSecsSinceEpoch() + (scenario == "expired-network" ? -60 : 3600)},
        {"g", QJsonObject{{"r", "device"}, {"d", public_key}, {"i", "identity"}}}};
    const auto token =
        "acct1." +
        QJsonDocument(claims)
            .toJson(QJsonDocument::Compact)
            .toBase64(QByteArray::Base64UrlEncoding | QByteArray::OmitTrailingEquals) +
        ".test";
    const QJsonObject profile{{"server_host", "127.0.0.1"},
                              {"server_public_key", "node-key"},
                              {"token", QString::fromLatin1(token)}};
    save_credentials(root.path() + "/node-credentials.bin",
                     QJsonDocument(QJsonObject{{"key", QString::fromLatin1(key.toBase64())},
                                               {"profile", profile},
                                               {"device", "device"},
                                               {"origin", "https://81.70.85.232"}})
                         .toJson());
    AuthHttp http;
    MultiplayerService nodes(&http, root.path(), root.path() + "/missing-bridge");
    QStringList states;
    connect(&nodes, &MultiplayerService::changed, this,
            [&] { states.append(nodes.status().value("state").toString()); });
    nodes.restore();
    QTRY_COMPARE_WITH_TIMEOUT(http.requests.size(), 1, 5000);
    QCOMPARE(http.requests.last().url.path(), "/api/launcher/challenge");
    if (scenario == "cancel") {
      nodes.logout();
      http.answer({{"error", "account-device-inactive"}});
      QVERIFY(!nodes.status().value("authorizationExpired").toBool());
    } else if (scenario == "revoked" || scenario == "expired-network") {
      http.answer({{"error", scenario == "revoked" ? "account-device-inactive" : "timeout"}}, 503);
      QVERIFY(nodes.status().value("authorizationExpired").toBool());
    } else {
      http.answer(
          {{"message",
            QJsonObject{{"p", scenario == "renew" ? "buggcraft-launcher-refresh-v1" : "wrong"},
                        {"id", "device"},
                        {"i", "identity"},
                        {"o", http.requests.first().url.adjusted(QUrl::RemovePath).toString()},
                        {"nonce", "nonce"}}}});
      if (scenario == "renew") {
        QTRY_COMPARE_WITH_TIMEOUT(http.requests.size(), 2, 5000);
        QCOMPARE(http.requests.last().url.path(), "/api/launcher/refresh");
        QVERIFY(!QJsonDocument::fromJson(http.requests.last().body)
                     .object()["signature"]
                     .toString()
                     .isEmpty());
        http.answer({{"profile", profile}});
        QVERIFY(states.contains("connecting"));
        QTRY_COMPARE_WITH_TIMEOUT(nodes.status().value("state").toString(), "signedOut", 5000);
        QVERIFY(!nodes.status().value("authorizationExpired").toBool());
      } else {
        QVERIFY(nodes.status().value("authorizationExpired").toBool());
      }
    }
    QCOMPARE(nodes.status().value("state").toString(), "signedOut");
    nodes.shutdown();
    QTRY_VERIFY_WITH_TIMEOUT(!nodes.busy(), 5000);
#endif
  }
  void node_poll_invalid_response_stops_waiting_data() {
    QTest::addColumn<QJsonObject>("body");
    QTest::newRow("json-error-with-http-200") << QJsonObject{{"error", "authorization failed"}};
    QTest::newRow("unknown-state") << QJsonObject{{"status", "unexpected"}};
  }
  void node_poll_invalid_response_stops_waiting() {
    QFETCH(QJsonObject, body);
    QTemporaryDir root;
    AuthHttp http;
    BrowserProbe browser;
    MultiplayerService nodes(&http, root.path(), root.path() + "/missing-bridge");
    nodes.login();
    http.answer(
        {{"id", "device"},
         {"nonce", "nonce"},
         {"interval", 1},
         {"verification_uri",
          http.requests.first().url.resolved(QUrl("/account/access?launcher=device")).toString()}});
    QTRY_COMPARE_WITH_TIMEOUT(http.requests.size(), 2, 5000);
    http.answer(body);
    QCOMPARE(nodes.status().value("state").toString(), "signedOut");
    QVERIFY(!nodes.status().value("error").toString().isEmpty());
    nodes.shutdown();
    QTRY_VERIFY_WITH_TIMEOUT(!nodes.busy(), 5000);
  }
  void live_node_authorization() {
    if (!qEnvironmentVariableIsSet("BUGG_TEST_LIVE_NODE")) QSKIP("显式节点设备登录接口验收");
    HttpClient http;
    const auto origin =
        qEnvironmentVariable("BUGG_TEST_NODE_ORIGIN", MultiplayerService::default_origin());
    if (qEnvironmentVariableIsSet("BUGG_TEST_NODE_BROWSER_APPROVAL")) {
      // 显式人工联调：复用生产所有者，日志只打印授权链接和阶段，不打印配置/令牌。
      const auto certificate_path = qEnvironmentVariable("BUGG_TEST_NODE_CA");
      if (!certificate_path.isEmpty()) {
        const auto certificates = QSslCertificate::fromPath(certificate_path);
        QVERIFY(!certificates.isEmpty());
        auto tls = QSslConfiguration::defaultConfiguration();
        tls.addCaCertificates(certificates);
        QSslConfiguration::setDefaultConfiguration(tls);
      }
      QTemporaryDir cache;
      BrowserProbe browser;
      auto bridge = QCoreApplication::applicationDirPath() + "/native/bin/buggcraft-bridge";
#ifdef Q_OS_WIN
      bridge += ".exe";
#endif
      MultiplayerService nodes(&http, cache.path(), bridge);
      QString last_state;
      connect(&nodes, &MultiplayerService::changed, this, [&] {
        const auto state = nodes.status().value("state").toString();
        const auto trace = qEnvironmentVariable("BUGG_TEST_NODE_TRACE");
        if (!trace.isEmpty())
          write_json(trace,
                     {{"state", state},
                      {"verificationUrl", nodes.status().value("verificationUrl").toString()},
                      {"error", nodes.status().value("error").toString()}});
        if (state != last_state) {
          last_state = state;
          qInfo().noquote() << "NODE_STATE" << state;
        }
      });
      nodes.login(origin);
      QTRY_VERIFY_WITH_TIMEOUT(!browser.urls.isEmpty() || last_state == "signedOut", 20000);
      QVERIFY2(!browser.urls.isEmpty(), qPrintable(nodes.status().value("error").toString()));
      qInfo().noquote() << "NODE_APPROVAL_URL" << browser.urls.first().toString();
      QTRY_VERIFY_WITH_TIMEOUT(last_state != "authorizing", 600000);
      QTRY_VERIFY_WITH_TIMEOUT(last_state != "connecting", 90000);
      const auto state = last_state;
      const auto error = nodes.status().value("error").toString();
      if (state == "ready" && qEnvironmentVariableIsSet("BUGG_TEST_NODE_RENEW_QUEUE")) {
        QTRY_VERIFY_WITH_TIMEOUT(!nodes.status().value("loading").toBool(), 15000);
        const auto previous = nodes.node_;
        nodes.refresh({}, true);
        nodes.connect_profile();
        QTRY_VERIFY_WITH_TIMEOUT(nodes.node_ != previous, 30000);
        QTRY_VERIFY_WITH_TIMEOUT(!nodes.status().value("loading").toBool(), 15000);
        // Flush earlier background replies through the same queue.
        bool checked = false;
        nodes.bridge_.call(
            "bridge.initialize", {}, [&](const auto&, const auto&) { checked = true; },
            NativeBridge::Priority::Background);
        QTRY_VERIFY_WITH_TIMEOUT(checked, 15000);
        QVERIFY2(nodes.status().value("error").toString().isEmpty(),
                 qPrintable(nodes.status().value("error").toString()));
        qInfo() << "NODE_RENEW_QUEUE old background replies discarded";
      }
      if (state == "ready" && qEnvironmentVariableIsSet("BUGG_TEST_NODE_ROOM_FLOW")) {
        // 原生 bridge + 隔离真实节点；复用相同授权，不在测试里模拟房间快照。
        QSignalSpy joined(&nodes, &MultiplayerService::room_joined);
        QSignalSpy left(&nodes, &MultiplayerService::room_left);
        QSignalSpy social_completed(&nodes, &MultiplayerService::social_completed);
        QSignalSpy host_required(&nodes, &MultiplayerService::host_required);
        QSignalSpy room_command_completed(&nodes, &MultiplayerService::room_command_completed);
        const auto peer = qEnvironmentVariable("BUGG_TEST_NODE_PEER");
        if (!peer.isEmpty()) {
          // 同一节点夹具批准真实好友申请；启动器必须先解析旧版兼容短码，再签名提交。
          nodes.social("request", qEnvironmentVariable("BUGG_TEST_NODE_PEER_CODE"));
          QTRY_VERIFY_WITH_TIMEOUT(!nodes.status().value("socialBusy").toBool(), 15000);
          QVERIFY2(nodes.status().value("error").toString().isEmpty(),
                   qPrintable(nodes.status().value("error").toString()));
          QCOMPARE(social_completed.count(), 1);
          nodes.refresh();
          QTRY_VERIFY_WITH_TIMEOUT(!nodes.status().value("friends").toList().isEmpty(), 20000);
          QCOMPARE(
              nodes.status().value("friends").toList().first().toMap().value("account").toString(),
              peer);
          QTRY_VERIFY_WITH_TIMEOUT(
              nodes.status().value("friends").toList().first().toMap().value("online").toBool(),
              20000);
          QCOMPARE(nodes.status().value("friendCode").toString().size(), 14);
          nodes.invite_friend(peer);
          QCOMPARE(host_required.count(), 1);
          QCOMPARE(nodes.status().value("pendingInvites").toStringList(), QStringList{peer});
          nodes.invite_friend(peer);
          QCOMPARE(host_required.count(), 1);
          nodes.cancel_invites();
          QVERIFY(nodes.status().value("pendingInvites").toStringList().isEmpty());
        }
        QVariantMap options{{"instanceId", "native-test"},
                            {"game", QVariantMap{{"version", "1.21.1"}, {"loader", "fabric"}}}};
        nodes.create_room("", cache.path(), "NativeHost", options);
        QVERIFY(!nodes.status().value("roomBusy").toBool());
        QVERIFY(!nodes.status().value("error").toString().isEmpty());
        nodes.create_room("Preparation", cache.path(), "NativeHost", options);
        QTRY_VERIFY_WITH_TIMEOUT(!nodes.status().value("roomBusy").toBool(), 30000);
        QVERIFY2(nodes.status().contains("room"),
                 qPrintable(nodes.status().value("error").toString()));
        QVERIFY(!nodes.status().value("room").toMap().value("allowSharing").toBool());
        auto room = nodes.status().value("room").toMap();
        QCOMPARE(joined.count(), 1);
        QCOMPARE(room.value("role").toString(), "host");
        QCOMPARE(room.value("connectionMode").toString(), "local");
        QCOMPARE(room.value("availability").toString(), "waiting");
        QCOMPARE(room.value("instanceId").toString(), "native-test");
        QCOMPARE(room.value("game").toMap().value("version").toString(), "1.21.1");
        QVERIFY(!room.value("invite").toString().isEmpty());
        QTRY_VERIFY_WITH_TIMEOUT(
            !nodes.status().value("room").toMap().value("members").toList().isEmpty(), 15000);
        nodes.room_command(
            "configure", {{"title", "Updated room"}, {"public", true}, {"require_invite", false}});
        QTRY_COMPARE_WITH_TIMEOUT(room_command_completed.count(), 1, 15000);
        QTRY_COMPARE_WITH_TIMEOUT(nodes.status().value("room").toMap().value("title").toString(),
                                  QString("Updated room"), 15000);
        QVERIFY(nodes.status().value("room").toMap().value("isManager").toBool());
        QVERIFY(!nodes.status().value("room").toMap().value("members").toList().isEmpty());
        QSignalSpy sent(&nodes, &MultiplayerService::chat_sent);
        nodes.send_chat("Native room message");
        QTRY_COMPARE_WITH_TIMEOUT(sent.count(), 1, 15000);
        QTRY_VERIFY_WITH_TIMEOUT(!nodes.status().value("messages").toList().isEmpty(), 15000);
        QCOMPARE(nodes.status().value("messages").toList().last().toMap().value("text").toString(),
                 "Native room message");
        QTest::qWait(1200);  // 成员增量刷新不能清空连接状态或重复插入聊天。
        QCOMPARE(nodes.status().value("room").toMap().value("state").toString(), "online");
        QCOMPARE(nodes.status().value("messages").toList().size(), 1);
        if (!peer.isEmpty()) {
          nodes.invite_friend(peer);
          QVERIFY(!nodes.status().value("pendingInvites").toStringList().isEmpty());
        }
        nodes.leave_room();
        QCOMPARE(left.count(), 1);
        QVERIFY(!nodes.status().contains("room"));
        QVERIFY(nodes.status().value("pendingInvites").toStringList().isEmpty());
        // 立即离开后，迟到的 host 响应不能重新入房；之后仍能正常创建。
        nodes.create_room("Cancelled", cache.path(), "NativeHost", options);
        nodes.leave_room();
        QTest::qWait(2500);
        QVERIFY(!nodes.status().contains("room"));
        QCOMPARE(joined.count(), 1);
        options["public"] = true;
        options["requireInvite"] = false;
        nodes.create_room("Public room", cache.path(), "NativeHost", options);
        QTRY_VERIFY_WITH_TIMEOUT(!nodes.status().value("roomBusy").toBool(), 30000);
        QVERIFY2(nodes.status().contains("room"),
                 qPrintable(nodes.status().value("error").toString()));
        QCOMPARE(joined.count(), 2);
        nodes.leave_room();
        qInfo() << "ROOM_FLOW preparation/private/public/cancel/recreate passed";
        GameStatusServer open_world("NeoForge 1.21.1");
        QVERIFY(open_world.listen(QHostAddress::LocalHost));
        options["port"] = open_world.serverPort();
        nodes.create_room("Already open world", cache.path(), "NativeHost", options);
        QTRY_VERIFY_WITH_TIMEOUT(!nodes.status().value("roomBusy").toBool(), 30000);
        QVERIFY2(nodes.status().contains("room"),
                 qPrintable(nodes.status().value("error").toString()));
        QTRY_COMPARE_WITH_TIMEOUT(
            nodes.status().value("room").toMap().value("availability").toString(), QString("ready"),
            15000);
        room = nodes.status().value("room").toMap();
        QCOMPARE(joined.count(), 3);
        QCOMPARE(room.value("game").toMap().value("version").toString(), "1.21.1");
        QCOMPARE(room.value("game").toMap().value("protocol").toInt(), 767);
        QVERIFY(nodes.status().value("error").toString().isEmpty());
        nodes.leave_room();
        qInfo() << "ROOM_FLOW already-open world created/ready; canonical version retained";
      }
      nodes.shutdown();
      QTRY_VERIFY_WITH_TIMEOUT(!nodes.busy(), 15000);
      QVERIFY2(state == "ready", qPrintable(error));
      // 同一设备重开后必须通过真实 challenge/refresh 续期，不要求再次浏览器授权。
      const auto approvals = browser.urls.size();
      MultiplayerService reopened(&http, cache.path(), bridge);
      reopened.restore();
      QTRY_VERIFY_WITH_TIMEOUT(reopened.status().value("state").toString() == "ready" ||
                                   !reopened.status().value("error").toString().isEmpty(),
                               30000);
      QCOMPARE(reopened.status().value("state").toString(), "ready");
      QCOMPARE(browser.urls.size(), approvals);
      reopened.shutdown();
      QTRY_VERIFY_WITH_TIMEOUT(!reopened.busy(), 15000);
      return;
    }
    QSignalSpy responses(&http, &HttpClient::response);
    const auto key = create_device_key();
    HttpRequest request;
    request.url = QUrl(origin + "/api/launcher/start");
    QFile control_ca(":/bugg/assets/control/beijing-test-ca.pem");
    QVERIFY(control_ca.open(QIODevice::ReadOnly));
    if (origin == "https://81.70.85.232") request.ca_pem = control_ca.readAll();
    request.method = "POST";
    request.headers = {{"Content-Type", "application/json"}};
    request.body = QJsonDocument(QJsonObject{{"key", device_public_key(key)},
                                             {"name", "Bugg native verification"},
                                             {"remember", false}})
                       .toJson();
    http.request(request);
    QTRY_COMPARE_WITH_TIMEOUT(responses.count(), 1, 20000);
    QVERIFY2(responses.last()[2].toString().isEmpty(), qPrintable(responses.last()[2].toString()));
    const auto start = QJsonDocument::fromJson(responses.last()[1].toByteArray()).object();
    QVERIFY2(!start["id"].toString().isEmpty(), "节点没有返回设备请求 ID");
    QCOMPARE(start["verification_uri"].toString(),
             origin + "/account/access?launcher=" + start["id"].toString());
    const auto signature = sign_device_message(
        key, {{"p", "buggcraft-launcher-poll-v1"}, {"id", start["id"]}, {"nonce", start["nonce"]}});
    request.url = QUrl(origin + "/api/launcher/poll");
    request.body =
        QJsonDocument(QJsonObject{{"id", start["id"]}, {"signature", signature}}).toJson();
    http.request(request);
    QTRY_COMPARE_WITH_TIMEOUT(responses.count(), 2, 20000);
    QVERIFY2(responses.last()[2].toString().isEmpty(), qPrintable(responses.last()[2].toString()));
    QCOMPARE(
        QJsonDocument::fromJson(responses.last()[1].toByteArray()).object()["status"].toString(),
        "pending");
    if (request.ca_pem.isEmpty())
      return;  // Public origin uses system trust; legacy pin test is explicit.
    HttpRequest untrusted;
    untrusted.url = QUrl("https://81.70.85.232/api/status");
    HttpClient separate_http;
    QSignalSpy rejected(&separate_http, &HttpClient::response);
    separate_http.request(untrusted);
    QTRY_COMPARE_WITH_TIMEOUT(rejected.count(), 1, 20000);
    QVERIFY(!rejected.last()[2].toString().isEmpty());
  }
  void live_device_authorization() {
    if (!qEnvironmentVariableIsSet("BUGG_TEST_LIVE_AUTH")) QSKIP("显式微软设备码接口验收");
    QTemporaryDir root;
    HttpClient http;
    MicrosoftAccount account(&http, root.path() + "/credentials.bin");
    QSignalSpy state(&account, &AccountPort::authentication);
    account.begin();
    QTRY_VERIFY_WITH_TIMEOUT(
        !state.isEmpty() && (state.last()[0] == "waiting" || state.last()[0] == "failed"), 60000);
    QVERIFY2(state.last()[0] == "waiting", qPrintable(state.last()[2].toString()));
    QVERIFY(!state.last()[1].toString().isEmpty());
    account.cancel();
    QVERIFY(!account.busy());
  }
  void live_install_and_prepare() {
    if (!qEnvironmentVariableIsSet("BUGG_TEST_LIVE_INSTALL")) QSKIP("显式联网安装验收");
    const auto root = qEnvironmentVariable("BUGG_TEST_LIVE_ROOT");
    QVERIFY(!root.isEmpty());
    QFutureWatcher<QString> watcher;
    watcher.setFuture(QtConcurrent::run([root] {
      try {
        GameOperations operation(root + "/.minecraft", root, {"BUGG", "BMCLAPI", "官方"},
                                 std::make_shared<std::atomic_bool>(false),
                                 [](double value, const QString& detail) {
                                   qInfo().noquote() << QString::number(value, 'f', 2) << detail;
                                 });
        const auto loader = qEnvironmentVariable("BUGG_TEST_LOADER", "vanilla");
        const auto version = qEnvironmentVariable("BUGG_TEST_MC", "1.21.1");
        const auto loader_version = qEnvironmentVariable("BUGG_TEST_LOADER_VERSION");
        const auto id = qEnvironmentVariable(
            "BUGG_TEST_INSTANCE",
            version + '-' + loader + (loader_version.isEmpty() ? QString() : '-' + loader_version));
        if (!QFileInfo::exists(root + "/.minecraft/versions/" + id + '/' + id + ".json"))
          operation.install({{"name", id},
                             {"game", version},
                             {"loader", loader},
                             {"loaderVersion", loader_version}});
        const auto preferred = qEnvironmentVariable("BUGG_TEST_JAVA");
        const auto command = operation.prepare(
            id, 2048, {"BuggTest", "0123456789abcdef0123456789abcdef", {}, "offline"},
            {{"javaPath", preferred}});
        qInfo().noquote() << "Java executable:" << command.java;
        if (!QFileInfo::exists(command.java) || command.arguments.isEmpty())
          return QString("没有真实启动命令");
        if (!preferred.isEmpty() &&
            java_major(command.java, std::make_shared<std::atomic_bool>(false)) !=
                operation.load_version(id)["javaVersion"].toObject()["majorVersion"].toInt(8))
          return QString("未自动匹配兼容 Java");
        return QString();
      } catch (const std::exception& error) {
        return QString::fromUtf8(error.what());
      }
    }));
    QTRY_VERIFY_WITH_TIMEOUT(watcher.isFinished(), 1200000);
    QVERIFY2(watcher.result().isEmpty(), qPrintable(watcher.result()));
  }
  void live_launch_uses_same_runtime_and_clears_activity() {
    if (!qEnvironmentVariableIsSet("BUGG_TEST_LIVE_LAUNCH")) QSKIP("显式真实游戏进程验收");
    const auto root = qEnvironmentVariable("BUGG_TEST_LIVE_ROOT");
    QVERIFY(!root.isEmpty());
    HttpClient http;
    MicrosoftAccount account(&http, root + "/test-credentials.bin");
    GameRuntime runtime(root, root + "/.minecraft", &account);
    QSignalSpy initialized(&runtime, &GameRuntime::initialized);
    runtime.initialize();
    QTRY_COMPARE_WITH_TIMEOUT(initialized.count(), 1, 15000);
    const auto id = qEnvironmentVariable("BUGG_TEST_INSTANCE", "1.21.1-vanilla");
    runtime.launch(id, "offline:BuggTest");
    QVERIFY(runtime.activity().value("active").toBool());
    QTRY_VERIFY_WITH_TIMEOUT(runtime.launch_status().value("state") != "preparing", 180000);
    QCOMPARE(runtime.launch_status().value("state").toString(), "running");
    QVERIFY(!runtime.activity().value("active").toBool());
    const auto rendered = [&] {
      QFile log(root + "/.minecraft/versions/" + id + "/logs/launcher-game.log");
      if (!log.open(QIODevice::ReadOnly)) return false;
      const auto content = log.readAll();
      return content.contains("Created:") && content.contains("atlas");
    };
    const auto running = [&] { return runtime.launch_status().value("state") == "running"; };
    QTRY_VERIFY_WITH_TIMEOUT(rendered() || !running(), 120000);
    const bool reached_renderer = rendered();
    runtime.stop_game();
    QTRY_VERIFY_WITH_TIMEOUT((!QStringList{"running", "stopping"}.contains(
                                 runtime.launch_status().value("state").toString())),
                             15000);
    runtime.shutdown();
    QVERIFY2(reached_renderer, "真实游戏未完成渲染资源初始化，请查看隔离实例 launcher-game.log");
  }
};
}  // namespace bugg
QTEST_GUILESS_MAIN(bugg::RuntimeTest)
#include "runtime_test.moc"
