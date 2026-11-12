#include <QCryptographicHash>
#include <QDir>
#include <QElapsedTimer>
#include <QEventLoop>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QSignalSpy>
#include <QTcpServer>
#include <QTcpSocket>
#include <QTemporaryDir>
#include <QTest>
#include <QTimer>
#include <algorithm>

#include "modules/game_install/application/game_operations.h"
#include "modules/game_install/application/game_runtime.h"

namespace bugg {
namespace {
// Bounded loopback HTTP fixture; product HttpClient handles every actual request.
class PayloadServer : public QTcpServer {
 public:
  explicit PayloadServer(qint64 bytes) : bytes_(bytes), block_(256 * 1024, 'p') {
    connect(this, &QTcpServer::newConnection, this, [this] {
      while (hasPendingConnections()) {
        auto* socket = nextPendingConnection();
        auto remaining = std::make_shared<qint64>(bytes_);
        const auto pump = [this, socket, remaining] {
          while (*remaining && socket->bytesToWrite() < 512 * 1024) {
            const auto count = qMin<qint64>(*remaining, block_.size());
            socket->write(block_.constData(), count);
            *remaining -= count;
          }
          if (!*remaining) socket->disconnectFromHost();
        };
        connect(socket, &QTcpSocket::readyRead, socket, [this, socket, pump] {
          socket->readAll();
          if (socket->property("started").toBool()) return;
          socket->setProperty("started", true);
          socket->write("HTTP/1.1 200 OK\r\nContent-Length: " + QByteArray::number(bytes_) +
                        "\r\nConnection: close\r\n\r\n");
          connect(socket, &QTcpSocket::bytesWritten, socket, pump);
          pump();
        });
        connect(socket, &QTcpSocket::disconnected, socket, &QObject::deleteLater);
      }
    });
  }

 private:
  qint64 bytes_;
  QByteArray block_;
};
QByteArray payload_hash(qint64 bytes, QCryptographicHash::Algorithm algorithm) {
  const QByteArray block(256 * 1024, 'p');
  QCryptographicHash hash(algorithm);
  while (bytes) {
    const auto count = qMin<qint64>(bytes, block.size());
    hash.addData(QByteArrayView(block.constData(), count));
    bytes -= count;
  }
  return hash.result().toHex();
}
}  // namespace
class WorkloadTest : public QObject {
  Q_OBJECT
 private slots:
  void export_selection_keeps_payloads_and_optional_saves() {
    QTemporaryDir root;
    QVERIFY(root.isValid());
    const auto instance = root.filePath("versions/game");
    write_json(instance + "/game.json", {{"id", "game"}, {"mainClass", "Main"}});
    const QStringList paths{
        "mods/a.jar",   "config/nested/a.json", "resourcepacks/a.zip",   "shaderpacks/a.zip",
        "options.txt",  "optionsof.txt",        "saves/world/level.dat", "logs/latest.log",
        "natives/a.dll"};
    for (const auto& path : paths) {
      QDir().mkpath(QFileInfo(instance + '/' + path).absolutePath());
      QFile file(instance + '/' + path);
      QVERIFY(file.open(QIODevice::WriteOnly));
      QCOMPARE(file.write(path.toUtf8()), path.toUtf8().size());
    }
    for (const bool saves : {false, true}) {
      const auto output = root.filePath(saves ? "with-saves.buggpack" : "without-saves.buggpack");
      GameOperations operations(root.path(), root.path(), {}, {}, [](double, const QString&) {});
      operations.export_pack("game", output, false, saves);
      const auto manifest = QJsonDocument::fromJson(archive_read(output, "buggcraft.pack.json"))
                                .object()["files"]
                                .toArray();
      QCOMPARE(manifest.size(), saves ? 7 : 6);
      QCOMPARE(archive_entries(output, {}).size(), manifest.size() + 1);
      for (const auto& value : manifest) {
        const auto record = value.toObject();
        const auto path = record["path"].toString();
        QVERIFY(!path.startsWith("logs/") && !path.startsWith("natives/"));
        QVERIFY(saves || !path.startsWith("saves/"));
        const auto payload = archive_read(output, "files/" + path);
        QCOMPARE(payload, path.toUtf8());
        QCOMPARE(record["sha1"].toString().toLatin1(),
                 QCryptographicHash::hash(payload, QCryptographicHash::Sha1).toHex());
        QCOMPARE(record["sha256"].toString().toLatin1(),
                 QCryptographicHash::hash(payload, QCryptographicHash::Sha256).toHex());
      }
      // The shared archive writer must still refuse to overwrite existing output.
      QVERIFY_EXCEPTION_THROWN(operations.export_pack("game", output, false, saves),
                               std::runtime_error);
    }
  }
  void export_progress_is_bounded_and_cancellation_stays_atomic() {
    QTemporaryDir root;
    QVERIFY(root.isValid());
    const auto instance = root.filePath("versions/game");
    write_json(instance + "/game.json", {{"id", "game"}, {"mainClass", "Main"}});
    QDir().mkpath(instance + "/mods");
    constexpr int files = 128;
    for (int i = 0; i < files; ++i) {
      QFile file(instance + "/mods/" + QString::number(i));
      QVERIFY(file.open(QIODevice::WriteOnly));
      QCOMPARE(file.write(QByteArray(1024, 'a')), 1024);
    }
    QList<double> updates;
    QElapsedTimer clock;
    clock.start();
    GameOperations operations(root.path(), root.path(), {}, {},
                              [&](double progress, const QString&) { updates.append(progress); });
    operations.export_pack("game", root.filePath("complete.buggpack"), false, false);
    QVERIFY(updates.first() < 0);
    QCOMPARE(updates.last(), 1.0);
    QVERIFY(std::any_of(updates.begin(), updates.end(),
                        [](double value) { return value >= 0 && value < 1; }));
    // First update, mode transition, completion plus at most one update/100 ms.
    QVERIFY(updates.size() <= 3 + clock.elapsed() / 100);
    auto cancelled = std::make_shared<std::atomic_bool>(false);
    GameOperations cancel_operations(root.path(), root.path(), {}, cancelled,
                                     [&](double progress, const QString&) {
                                       if (progress >= 0) cancelled->store(true);
                                     });
    const auto cancelled_output = root.filePath("cancelled.buggpack");
    QVERIFY_EXCEPTION_THROWN(cancel_operations.export_pack("game", cancelled_output, false, false),
                             std::runtime_error);
    QVERIFY(cancelled->load());
    QVERIFY(!QFileInfo::exists(cancelled_output));
    QCOMPARE(QDir(instance + "/mods").entryList(QDir::Files).size(), files);
  }
  void http_without_digest_preserves_size_limits_and_atomic_output() {
    QTemporaryDir root;
    QVERIFY(root.isValid());
    constexpr qint64 bytes = 1024 * 1024;
    PayloadServer server(bytes);
    QVERIFY(server.listen(QHostAddress::LocalHost));
    HttpClient client;
    QSignalSpy response(&client, &HttpClient::response);
    for (int pass = 0; pass < 3; ++pass) {
      HttpRequest request;
      request.url = QUrl(QString("http://127.0.0.1:%1/payload").arg(server.serverPort()));
      request.output_path = root.filePath(QString::number(pass));
      request.expected_size = pass == 1 ? bytes + 1 : bytes;
      request.maximum_bytes = pass == 2 ? bytes - 1 : bytes;
      if (pass) {
        QFile original(request.output_path);
        QVERIFY(original.open(QIODevice::WriteOnly));
        QCOMPARE(original.write("original"), 8);
      }
      client.request(request);
      QVERIFY(response.wait(10000));
      if (!pass) {
        QVERIFY(response.last()[2].toString().isEmpty());
        QCOMPARE(file_digest(request.output_path, "sha256", {}),
                 payload_hash(bytes, QCryptographicHash::Sha256));
      } else {
        QVERIFY(!response.last()[2].toString().isEmpty());
        QFile original(request.output_path);
        QVERIFY(original.open(QIODevice::ReadOnly));
        QCOMPARE(original.readAll(), QByteArray("original"));
      }
    }
  }
  void prepare_export_fixtures() {
    const auto fixture = qEnvironmentVariable("BUGG_WORKLOAD_FIXTURE");
    if (fixture.isEmpty()) QSKIP("Set BUGG_WORKLOAD_FIXTURE and explicitly run this slot");
    for (const auto& name : {QString("small"), QString("excluded"), QString("many")}) {
      const auto instance = fixture + '/' + name + "/versions/game";
      write_json(instance + "/game.json", {{"id", "game"}, {"mainClass", "Main"}});
      const int files = name == "many" ? 1000 : 20;
      QDir().mkpath(instance + "/mods");
      for (int i = 0; i < files; ++i) {
        QFile file(instance + "/mods/" + QString::number(i) + ".jar");
        QVERIFY(file.open(QIODevice::WriteOnly));
        QCOMPARE(file.write(QByteArray(1024, char('a' + i % 20))), 1024);
      }
      if (name == "excluded") {
        for (const auto& folder : {"saves", "logs", "natives"}) {
          for (int shard = 0; shard < 32; ++shard) {
            const auto directory = instance + '/' + folder + '/' + QString::number(shard);
            QDir().mkpath(directory);
            for (int i = 0; i < 128; ++i) {
              QFile file(directory + '/' + QString::number(i));
              QVERIFY(file.open(QIODevice::WriteOnly));
              QCOMPARE(file.write("excluded"), 8);
            }
          }
        }
      }
    }
  }
  void measured_workload_data() {
    QTest::addColumn<QString>("kind");
    QTest::addColumn<int>("files");
    QTest::addColumn<qint64>("bytes");
    QTest::addColumn<int>("excluded");
    QTest::newRow("export-small") << QString("small") << 20 << qint64(20 * 1024) << 0;
    QTest::newRow("export-excluded") << QString("excluded") << 20 << qint64(20 * 1024) << 12288;
    QTest::newRow("export-many") << QString("many") << 1000 << qint64(1000 * 1024) << 0;
    QTest::newRow("http-body-8MiB") << QString("body") << 1 << qint64(8 * 1048576) << 0;
    QTest::newRow("http-file-64MiB") << QString("file") << 1 << qint64(64 * 1048576) << 0;
    QTest::newRow("http-sha1-64MiB") << QString("sha1") << 1 << qint64(64 * 1048576) << 0;
  }
  void measured_workload() {
    const auto report = qEnvironmentVariable("BUGG_WORKLOAD_REPORT");
    if (report.isEmpty()) QSKIP("Set BUGG_WORKLOAD_REPORT for native A/B workloads");
    QFETCH(QString, kind);
    QFETCH(int, files);
    QFETCH(qint64, bytes);
    QFETCH(int, excluded);
    QTemporaryDir portable;
    QVERIFY(portable.isValid());
    double elapsed = 0;
    int events = 0;
    QByteArray output_hash;
    if (QStringList{"small", "excluded", "many"}.contains(kind)) {
      const auto root = qEnvironmentVariable("BUGG_WORKLOAD_FIXTURE") + '/' + kind;
      QVERIFY(QFileInfo::exists(root + "/versions/game/game.json"));
      GameRuntime runtime(portable.path(), root, nullptr);
      QSignalSpy changed(&runtime, &GameRuntime::instances_changed);
      runtime.refresh_instances();
      QVERIFY(changed.wait(10000));
      QEventLoop loop;
      QTimer timeout;
      timeout.setSingleShot(true);
      connect(&timeout, &QTimer::timeout, &loop, &QEventLoop::quit);
      connect(&runtime, &GameRuntime::tasks_changed, &loop, [&] {
        ++events;
        if (!runtime.tasks().isEmpty() && QStringList{"done", "failed"}.contains(
                                              runtime.tasks()[0].toMap().value("state").toString()))
          loop.quit();
      });
      // Full product queue and GUI delivery; first export warms source/ZIP paths.
      for (int pass = 0; pass < 2; ++pass) {
        const auto output = portable.filePath(QString::number(pass) + ".buggpack");
        events = 0;
        timeout.start(30000);
        QElapsedTimer clock;
        clock.start();
        runtime.export_pack("game", output, false, false);
        loop.exec();
        elapsed = clock.nsecsElapsed() / 1e6;
        QVERIFY(timeout.isActive());
        timeout.stop();
        QCOMPARE(runtime.tasks()[0].toMap().value("state").toString(), "done");
        auto manifest =
            QJsonDocument::fromJson(archive_read(output, "buggcraft.pack.json")).object();
        auto records = manifest["files"].toArray().toVariantList();
        QCOMPARE(records.size(), files);
        std::sort(records.begin(), records.end(), [](const auto& a, const auto& b) {
          return a.toMap().value("path").toString() < b.toMap().value("path").toString();
        });
        manifest["files"] = QJsonArray::fromVariantList(records);
        output_hash =
            QCryptographicHash::hash(QJsonDocument(manifest).toJson(QJsonDocument::Compact),
                                     QCryptographicHash::Sha256)
                .toHex();
        QCOMPARE(archive_entries(output, {}).size(), files + 1);
        QCOMPARE(archive_read(output, "files/mods/0.jar"), QByteArray(1024, 'a'));
        QTRY_VERIFY_WITH_TIMEOUT(!runtime.busy(), 10000);
      }
      runtime.shutdown();
      QTRY_VERIFY(!runtime.busy());
    } else {
      PayloadServer server(bytes);
      QVERIFY(server.listen(QHostAddress::LocalHost));
      HttpClient client;
      HttpRequest request;
      request.url = QUrl(QString("http://127.0.0.1:%1/payload").arg(server.serverPort()));
      request.maximum_bytes = bytes + 1;
      request.expected_size = bytes;
      if (kind == "sha1") request.sha1 = payload_hash(bytes, QCryptographicHash::Sha1);
      const auto expected = payload_hash(bytes, QCryptographicHash::Sha256);
      QSignalSpy response(&client, &HttpClient::response);
      for (int pass = 0; pass < 2; ++pass) {
        if (kind != "body") request.output_path = portable.filePath(QString::number(pass));
        QElapsedTimer clock;
        clock.start();
        client.request(request);
        QVERIFY(response.wait(30000));
        elapsed = clock.nsecsElapsed() / 1e6;
        QVERIFY2(response.last()[2].toString().isEmpty(),
                 qPrintable(response.last()[2].toString()));
        output_hash = kind == "body" ? QCryptographicHash::hash(response.last()[1].toByteArray(),
                                                                QCryptographicHash::Sha256)
                                           .toHex()
                                     : file_digest(request.output_path, "sha256", {});
        QCOMPARE(output_hash, expected);
      }
    }
    write_json(report + '-' + QString::fromLatin1(QTest::currentDataTag()) + ".json",
               {{"scenario", QString::fromLatin1(QTest::currentDataTag())},
                {"files", files},
                {"bytes", double(bytes)},
                {"excluded", excluded},
                {"workMs", elapsed},
                {"progressEvents", events},
                {"outputHash", QString::fromLatin1(output_hash)}});
  }
};
}  // namespace bugg
QTEST_GUILESS_MAIN(bugg::WorkloadTest)
#include "workload_test.moc"
