#include <QImage>
#include <QJSEngine>
#include <QJsonDocument>
#include <QSignalSpy>
#include <QTemporaryDir>
#include <QTest>

#include "modules/account/ui/identity_session.h"
#include "modules/launch/ui/launch_session.h"
#include "shell/backdrop_palette.h"
#include "shell/page_state_store.h"

class SessionTest : public QObject {
  Q_OBJECT

 private slots:
  void backdrop_palette_samples_local_images_and_ignores_obsolete_results() {
    QTemporaryDir directory;
    QImage image(32, 16, QImage::Format_ARGB32);
    image.fill(QColor(30, 120, 180));
    const auto first = QUrl::fromLocalFile(directory.filePath("first.png"));
    QVERIFY(image.save(first.toLocalFile()));
    bugg::BackdropPalette palette;
    palette.set_source(first);
    QTRY_COMPARE_WITH_TIMEOUT(palette.average_color(), QColor(30, 120, 180), 5000);
    image.fill(QColor(170, 80, 40));
    const auto second = QUrl::fromLocalFile(directory.filePath("second.png"));
    QVERIFY(image.save(second.toLocalFile()));
    palette.set_source(second);
    palette.set_source(first);  // 缓存立即恢复，较慢的旧 worker 不得覆盖。
    QTest::qWait(100);
    QCOMPARE(palette.average_color(), QColor(30, 120, 180));
    palette.set_source(QUrl::fromLocalFile(directory.filePath("missing.png")));
    QTest::qWait(100);
    QCOMPARE(palette.average_color(), QColor(30, 120, 180));
    palette.set_source(QUrl("https://example.invalid/image.png"));
    QCOMPARE(palette.average_color(), QColor(30, 120, 180));
  }
  void identity_confirmation_is_shared() {
    bugg::IdentitySession identity;
    bugg::LaunchSession launch;
    launch.setProperty("preview_enabled", true);
    launch.setProperty("automatic", false);
    launch.setProperty("instances", QVariantList{QVariantMap{{"name", "Test"}}});
    connect(&identity, &bugg::IdentitySession::status_changed, &launch,
            [&] { launch.setProperty("identity_status", identity.status()); });
    QSignalSpy required(&launch, &bugg::LaunchSession::identity_required);

    QVERIFY(!launch.can_start());
    QVERIFY(!launch.preflight().isEmpty());
    launch.start(0);  // Direct invocation must not bypass identity confirmation.
    launch.advance();
    QCOMPARE(required.count(), 1);
    QCOMPARE(launch.status()["state"].toString(), "idle");
    for (const auto& name :
         {"", "ab", "bad name", "name-with-dash", "abcdefghijklmnopq", "Valid\n"})
      QVERIFY(!identity.use_offline(name));
    QVERIFY(!launch.can_start());

    QVERIFY(identity.use_offline("Player_123"));
    QVERIFY(launch.can_start());
    QVERIFY(launch.preflight().isEmpty());
    launch.start(0);
    QCOMPARE(launch.status()["state"].toString(), "preparing");
    QCOMPARE(launch.status()["stage"].toString(), "1 / 4");
    launch.cancel();
    launch.advance();
    QCOMPARE(launch.status()["state"].toString(), "idle");
  }

  void canceled_authorization_preserves_identity() {
    bugg::IdentitySession identity;
    identity.setProperty("preview_enabled", true);
    identity.setProperty("automatic", false);
    QVERIFY(identity.use_offline("Original"));
    QSignalSpy committed(&identity, &bugg::IdentitySession::committed);
    identity.begin_microsoft();
    identity.complete_microsoft();
    identity.cancel_microsoft();
    identity.finish_microsoft();
    QCOMPARE(committed.count(), 0);
    QCOMPARE(identity.status()["name"].toString(), "Original");
    QVERIFY(identity.status()["microsoftName"].toString().isEmpty());
    identity.begin_microsoft();
    identity.complete_microsoft();
    identity.finish_microsoft();
    QCOMPARE(committed.count(), 1);
    QCOMPARE(identity.status()["name"].toString(), "BuggPlayer");
    QVERIFY(identity.status()["caption"].toString().contains(QStringLiteral("模拟")));
    QVERIFY(identity.use_offline("AnotherPlayer"));
    QCOMPARE(identity.status()["microsoftName"].toString(), "BuggPlayer");
    const auto before_switch = committed.count();
    identity.begin_microsoft();
    QCOMPARE(committed.count(), before_switch + 1);
    QCOMPARE(identity.status()["name"].toString(), "BuggPlayer");
    QCOMPARE(identity.status()["kind"].toString(), "microsoft");
    QCOMPARE(identity.status()["authState"].toString(), "idle");
    QVERIFY(identity.status()["code"].toString().isEmpty());
    QCOMPARE(identity.status()["offlineName"].toString(), "AnotherPlayer");
    identity.finish_microsoft();
    QCOMPARE(committed.count(), before_switch + 1);  // No second authorization or late commit.
  }

  void microsoft_logout_clears_only_its_session() {
    bugg::IdentitySession identity;
    identity.setProperty("preview_enabled", true);
    identity.setProperty("automatic", false);
    identity.begin_microsoft();
    identity.complete_microsoft();
    identity.finish_microsoft();
    identity.logout_microsoft();
    QVERIFY(!identity.status()["ready"].toBool());
    QVERIFY(identity.status()["name"].toString().isEmpty());
    QCOMPARE(identity.status()["initials"].toString(), "?");
    QVERIFY(identity.status()["microsoftName"].toString().isEmpty());
    identity.finish_microsoft();
    QVERIFY(!identity.status()["ready"].toBool());

    QVERIFY(identity.use_offline("LocalPlayer"));
    identity.begin_microsoft();
    identity.complete_microsoft();
    identity.finish_microsoft();
    identity.logout_microsoft();
    QCOMPARE(identity.status()["name"].toString(), "LocalPlayer");
    QCOMPARE(identity.status()["kind"].toString(), "offline");
    QVERIFY(identity.status()["ready"].toBool());
    identity.begin_microsoft();  // Logout must require authorization again.
    QCOMPARE(identity.status()["authState"].toString(), "waiting");
    identity.complete_microsoft();
    identity.logout_microsoft();
    identity.finish_microsoft();
    QCOMPARE(identity.status()["name"].toString(), "LocalPlayer");
    QVERIFY(identity.status()["microsoftName"].toString().isEmpty());
    identity.logout_microsoft();  // Idempotent even when offline and already cleared.
    QCOMPARE(identity.status()["name"].toString(), "LocalPlayer");
  }

  void existing_launch_lifecycle() {
    bugg::LaunchSession launch;
    launch.setProperty("preview_enabled", true);
    launch.setProperty("automatic", false);
    launch.setProperty("identity_status", QVariantMap{{"ready", true}});
    launch.setProperty("instances", QVariantList{QVariantMap{{"name", "Test"}}});
    launch.start(0);
    launch.start(1);  // Duplicate requests cannot change the captured instance.
    QCOMPARE(launch.status()["instanceName"].toString(), "Test");
    for (int step = 0; step < 4; ++step) launch.advance();
    QCOMPARE(launch.status()["state"].toString(), "running");
    launch.stop();
    QCOMPARE(launch.status()["state"].toString(), "stopping");
    launch.advance();
    QCOMPARE(launch.status()["state"].toString(), "idle");
    launch.start(0);
    launch.fail("Test failure");
    QCOMPARE(launch.status()["detail"].toString(), "Test failure");
    launch.start(0);
    QCOMPARE(launch.status()["state"].toString(), "preparing");
    launch.cancel();
    QCOMPARE(launch.status()["state"].toString(), "idle");
  }
  void default_services_never_fake_success() {
    bugg::IdentitySession identity;
    identity.begin_microsoft();
    identity.complete_microsoft();
    identity.finish_microsoft();
    QVERIFY(!identity.status()["ready"].toBool());
    QCOMPARE(identity.status()["authState"].toString(), "idle");
    QVERIFY(!identity.status()["error"].toString().isEmpty());
    bugg::LaunchSession launch;
    launch.setProperty("identity_status", QVariantMap{{"ready", true}});
    launch.setProperty("instances", QVariantList{QVariantMap{{"name", "Test"}}});
    launch.start(0);
    launch.advance();
    QCOMPARE(launch.status()["state"].toString(), "failed");
    QVERIFY(!launch.status()["preview"].toBool());
  }

  void profiles_share_selection_and_logout() {
    bugg::IdentitySession identity;
    identity.setProperty("preview_enabled", true);
    identity.setProperty("automatic", false);
    QVERIFY(identity.use_offline("FirstPlayer"));
    QVERIFY(identity.use_offline("SecondPlayer"));
    QVERIFY(identity.use_offline("FirstPlayer"));
    QCOMPARE(identity.status()["profiles"].toList().size(), 2);
    QVERIFY(identity.activate_profile("offline:SecondPlayer"));
    QCOMPARE(identity.status()["name"].toString(), "SecondPlayer");
    QVERIFY(!identity.activate_profile("missing"));
    QCOMPARE(identity.status()["name"].toString(), "SecondPlayer");
    identity.begin_microsoft();
    identity.complete_microsoft();
    identity.finish_microsoft();
    QCOMPARE(identity.status()["profiles"].toList().size(), 3);
    identity.logout_microsoft();
    QCOMPARE(identity.status()["profiles"].toList().size(), 2);
    QVERIFY(!identity.activate_profile("microsoft:BuggPlayer"));
  }

  void offline_identity_survives_json_roundtrip() {
    bugg::IdentitySession original;
    QVERIFY(original.use_offline("PortablePlayer"));
    const auto json = QJsonDocument::fromVariant(original.saved_state()).toJson();
    bugg::IdentitySession restored;
    restored.restore_state(QJsonDocument::fromJson(json).toVariant().toMap());
    QVERIFY(restored.status().value("ready").toBool());
    QCOMPARE(restored.status().value("name").toString(), "PortablePlayer");
    QCOMPARE(restored.status().value("profiles").toList().size(), 1);
  }

  void drafts_outlive_page_and_deduplicate_notifications() {
    bugg::PageStateStore state;
    QSignalSpy changed(&state, &bugg::PageStateStore::values_changed);
    state.set_value("search.query", "ender");
    state.set_value("search.query", "ender");
    state.set_value("", "ignored");
    QCOMPARE(changed.count(), 1);
    QCOMPARE(state.values()["search.query"].toString(), "ender");
    state.set_value("search.query", "");
    QCOMPARE(changed.count(), 2);
    QVERIFY(state.values()["search.query"].toString().isEmpty());
    {
      QJSEngine engine;
      state.set_value("appearance.backgrounds",
                      QVariant::fromValue(engine.evaluate("['file:///scene.png']")));
      state.set_value("appearance.backgrounds",
                      QVariant::fromValue(engine.evaluate("['file:///scene.png']")));
      QCOMPARE(changed.count(), 3);
    }
    // 页面脚本引擎销毁后仍是独立快照；相同内容的不同数组只通知一次。
    QCOMPARE(state.values()["appearance.backgrounds"].toList(),
             QVariantList{QString("file:///scene.png")});
  }
};

QTEST_GUILESS_MAIN(SessionTest)
#include "session_test.moc"
