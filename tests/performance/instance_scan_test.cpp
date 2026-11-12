#include <QCryptographicHash>
#include <QElapsedTimer>
#include <QEventLoop>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QSignalSpy>
#include <QTemporaryDir>
#include <QTest>
#include <QTimer>
#include <stdexcept>

#include "modules/game_install/application/game_runtime.h"
#include "modules/settings/application/language_service.h"

namespace bugg {
class InstanceScanTest : public QObject {
  Q_OBJECT
 private slots:
  void index_reuse_is_scoped_and_does_not_hide_failed_reads() {
    QTemporaryDir root;
    const QJsonObject metadata{{"assetIndex", QJsonObject{{"id", "shared"}}}};
    const auto path = root.filePath("assets/indexes/shared.json");
    QHash<QString, QStringList> cache;
    QVERIFY(game_language_codes(root.path(), metadata, &cache).isEmpty());
    QVERIFY(cache.isEmpty());
    write_json(path, {{"objects", QJsonObject{{"minecraft/lang/fr_fr.json", QJsonObject{}}}}});
    const auto codes = game_language_codes(root.path(), metadata, &cache);
    QCOMPARE(codes, (QStringList{"en_us", "fr_fr"}));
    QCOMPARE(cache.size(), 1);
    QVERIFY(QFile::remove(path));
    QCOMPARE(game_language_codes(root.path(), metadata, &cache), codes);
    QVERIFY(game_language_codes(root.path(), metadata).isEmpty());
    cache.clear();
    QFile invalid(path);
    QVERIFY(invalid.open(QIODevice::WriteOnly));
    invalid.write("not-json");
    invalid.close();
    QVERIFY_EXCEPTION_THROWN(game_language_codes(root.path(), metadata, &cache),
                             std::runtime_error);
    QVERIFY(cache.isEmpty());
    write_json(path, {{"objects", QJsonObject{{"minecraft/lang/zh_cn.lang", QJsonObject{}}}}});
    QCOMPARE(game_language_codes(root.path(), metadata, &cache), (QStringList{"en_us", "zh_cn"}));
    QTemporaryDir other;
    write_json(other.filePath("assets/indexes/shared.json"),
               {{"objects", QJsonObject{{"minecraft/lang/ja_jp.json", QJsonObject{}}}}});
    QCOMPARE(game_language_codes(other.path(), metadata, &cache), (QStringList{"en_us", "ja_jp"}));
    QCOMPARE(cache.size(), 2);
  }

  void rescan_reads_changed_languages_and_isolates_game_roots() {
    QTemporaryDir portable;
    const auto first = portable.filePath("first");
    const auto second = portable.filePath("second");
    const QJsonObject metadata{{"id", "game"}, {"assetIndex", QJsonObject{{"id", "shared"}}}};
    for (const auto& root : {first, second})
      write_json(root + "/versions/game/game.json", metadata);
    write_json(first + "/assets/indexes/shared.json",
               {{"objects", QJsonObject{{"minecraft/lang/fr_fr.json", QJsonObject{}}}}});
    write_json(second + "/assets/indexes/shared.json",
               {{"objects", QJsonObject{{"minecraft/lang/ja_jp.lang", QJsonObject{}}}}});
    GameRuntime runtime(portable.path(), first, nullptr);
    QSignalSpy changed(&runtime, &GameRuntime::instances_changed);
    runtime.refresh_instances();
    QVERIFY(changed.wait(10000));
    QCOMPARE(runtime.instances().size(), 1);
    QCOMPARE(runtime.instances()[0].toMap().value("languages").toStringList(),
             (QStringList{"en_us", "fr_fr"}));
    write_json(first + "/assets/indexes/shared.json",
               {{"objects", QJsonObject{{"minecraft/lang/zh_cn.json", QJsonObject{}}}}});
    runtime.refresh_instances();
    QVERIFY(changed.wait(10000));
    QCOMPARE(runtime.instances()[0].toMap().value("languages").toStringList(),
             (QStringList{"en_us", "zh_cn"}));
    runtime.select_game_root(second);
    QVERIFY(changed.wait(10000));
    QCOMPARE(runtime.instances()[0].toMap().value("languages").toStringList(),
             (QStringList{"en_us", "ja_jp"}));
    runtime.shutdown();
    QTRY_VERIFY(!runtime.busy());
  }

  void measured_scan_data() {
    QTest::addColumn<int>("instances");
    QTest::addColumn<int>("indexes");
    QTest::newRow("single") << 1 << 1;
    QTest::newRow("shared-40") << 40 << 1;
    QTest::newRow("shared-40-4-indexes") << 40 << 4;
    QTest::newRow("distinct-8") << 8 << 8;
  }
  void measured_scan() {
    const auto report = qEnvironmentVariable("BUGG_SCAN_REPORT");
    if (report.isEmpty()) QSKIP("Set BUGG_SCAN_REPORT to measure the production scan");
    QFETCH(int, instances);
    QFETCH(int, indexes);
    QTemporaryDir portable;
    QVERIFY(portable.isValid());
    const auto root = portable.filePath("game");
    QJsonObject objects;
    const QJsonObject record{{"hash", QString(40, 'a')}, {"size", 1024}};
    for (int i = 0; i < 4096; ++i)
      objects.insert(QString("minecraft/sounds/fixture-%1.ogg").arg(i), record);
    objects.insert("minecraft/lang/fr_fr.json", record);
    objects.insert("minecraft/lang/zh_cn.json", record);
    for (int i = 0; i < indexes; ++i)
      write_json(root + "/assets/indexes/" + QString::number(i) + ".json", {{"objects", objects}});
    for (int i = 0; i < instances; ++i) {
      const auto id = QString("fixture-%1").arg(i, 3, 10, QChar('0'));
      write_json(root + "/versions/" + id + '/' + id + ".json",
                 {{"id", id}, {"assetIndex", QJsonObject{{"id", QString::number(i % indexes)}}}});
    }
    GameRuntime runtime(portable.path(), root, nullptr);
    QEventLoop loop;
    QTimer timeout;
    timeout.setSingleShot(true);
    connect(&runtime, &GameRuntime::instances_changed, &loop, &QEventLoop::quit);
    connect(&timeout, &QTimer::timeout, &loop, &QEventLoop::quit);
    // Fixture generation and one full warm-up are outside the measured interval.
    runtime.refresh_instances();
    timeout.start(20000);
    loop.exec();
    QVERIFY(timeout.isActive());
    timeout.stop();
    QCOMPARE(runtime.instances().size(), instances);
    const auto expected = runtime.instances();
    timeout.start(20000);
    QElapsedTimer clock;
    clock.start();
    runtime.refresh_instances();
    loop.exec();
    const double elapsed = clock.nsecsElapsed() / 1e6;
    QVERIFY(timeout.isActive());
    timeout.stop();
    QCOMPARE(runtime.instances(), expected);
    for (const auto& instance : runtime.instances())
      QCOMPARE(instance.toMap().value("languages").toStringList(),
               (QStringList{"en_us", "fr_fr", "zh_cn"}));
    auto normalized = runtime.instances();
    for (auto& instance : normalized) {
      auto fields = instance.toMap();
      fields.remove("directory");  // Each process owns a different temporary root.
      instance = fields;
    }
    const auto output_hash =
        QCryptographicHash::hash(
            QJsonDocument::fromVariant(normalized).toJson(QJsonDocument::Compact),
            QCryptographicHash::Sha256)
            .toHex();
    runtime.shutdown();
    QVERIFY(!runtime.busy());
    const QString scenario = QString::fromLatin1(QTest::currentDataTag());
    write_json(report + '-' + scenario + ".json",
               {{"scenario", scenario},
                {"instances", instances},
                {"indexes", indexes},
                {"indexBytes", double(QFileInfo(root + "/assets/indexes/0.json").size())},
                {"scanMs", elapsed},
                {"outputHash", QString::fromLatin1(output_hash)},
                {"qt", qVersion()}});
  }
};
}  // namespace bugg
QTEST_GUILESS_MAIN(bugg::InstanceScanTest)
#include "instance_scan_test.moc"
