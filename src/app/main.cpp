#include <QCommandLineParser>
#include <QFileInfo>
#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QQuickStyle>
#include <QQuickWindow>
#include <QScopeGuard>
#include <QTimer>
#include <QVariant>
#include <cstdio>

#include "app/application_lifecycle.h"
#include "modules/account/application/microsoft_account.h"
#include "modules/catalog/application/content_catalog_service.h"
#include "modules/catalog/application/game_catalog_service.h"
#include "modules/game_install/application/game_runtime.h"
#include "modules/multiplayer/application/multiplayer_service.h"
#include "modules/settings/application/language_service.h"
#include "modules/settings/ui/source_settings.h"
#include "modules/update/application/launcher_update_service.h"
#include "platform/diagnostics/diagnostic_log.h"
#include "platform/http/http_client.h"
#include "shell/desktop_environment.h"
#ifdef BUGG_SINGLE_FILE
#include <QFile>

#include "cli.hpp"
#endif

namespace {
QtMessageHandler previous_messages = nullptr;
void diagnostic_message(QtMsgType type, const QMessageLogContext& context, const QString& message) {
  static thread_local bool logging = false;
  if (!logging) {
    logging = true;
    const QString level = type == QtDebugMsg     ? "DEBUG"
                          : type == QtInfoMsg    ? "INFO"
                          : type == QtWarningMsg ? "WARN"
                          : type == QtFatalMsg   ? "FATAL"
                                                 : "ERROR";
    bugg::record_diagnostic(
        "launcher.message",
        {{"level", level},
         {"logger", QString::fromUtf8(context.category ? context.category : "launcher")},
         {"message", message.left(12000)}});
    logging = false;
  }
  if (previous_messages)
    previous_messages(type, context, message);
  else
    std::fprintf(stderr, "%s\n", qPrintable(bugg::redact_diagnostic(message)));
}
}  // namespace

int main(int argc, char* argv[]) {
#ifdef BUGG_SINGLE_FILE
  if (argc == 2 && QByteArray(argv[1]) == "--licenses") {
    QFile notices(":/bugg/licenses.txt");
    if (!notices.open(QIODevice::ReadOnly)) return 1;
    const auto text = notices.readAll();
    if (std::fwrite(text.constData(), 1, text.size(), stdout) != static_cast<size_t>(text.size()))
      return 1;
    return bridge::run_cli(argc, argv);
  }
  // Dispatch before constructing Qt's GUI: same file, isolated native worker.
  if (argc >= 2 && QByteArray(argv[1]) == "--native-bridge") return bridge::run_cli(argc, argv);
#endif
  if (argc == 3 && QByteArray(argv[1]) == "--apply-update") {
    QCoreApplication helper(argc, argv);
    return bugg::LauncherUpdateService::apply_staged(QString::fromLocal8Bit(argv[2]));
  }
  QGuiApplication app(argc, argv);
  QCoreApplication::setApplicationName("Bugg");
  QCoreApplication::setApplicationVersion(BUGG_VERSION);
  QCoreApplication::setOrganizationName("Buggcraft");
  QQuickStyle::setStyle("Basic");
  QCommandLineParser parser;
  parser.addHelpOption();
  parser.addOption({"theme", "Initial UI size: panel, small, classic or large.", "theme", "small"});
  parser.addOption({"page", "Open a preview subpage.", "route"});
  parser.addOption({"capture", "Save a preview PNG, then exit.", "path"});
  parser.process(app);
  previous_messages = qInstallMessageHandler(diagnostic_message);
  const auto restore_messages = qScopeGuard([] { qInstallMessageHandler(previous_messages); });

  bugg::DesktopEnvironment desktop;
  bugg::HttpClient http;
  auto portable = QCoreApplication::applicationDirPath();
#ifdef Q_OS_MACOS
  // User data stays beside the application, outside the signed app bundle.
  if (portable.endsWith(".app/Contents/MacOS"))
    portable = QFileInfo(portable.chopped(15)).absolutePath();
#endif
  const auto cache = bugg::portable_cache_root(portable);
  bugg::GameCatalogService catalog(&http, bugg::supported_download_sources(), nullptr,
                                   cache + "/catalog-cache.json");
  bugg::SourceSettings sources(nullptr, cache + "/source-settings.json");
  bugg::ContentCatalogService content_catalog;
  bugg::MicrosoftAccount account(&http, cache + "/credentials.bin");
  bugg::GameRuntime runtime(portable, portable + "/.minecraft", &account);
  bugg::LauncherUpdateService updates(&http, cache);
  runtime.set_content_request(content_catalog.requester());
  QObject::connect(&runtime, &bugg::GameRuntime::shader_feedback_submitted, &content_catalog,
                   &bugg::ContentCatalogPort::feedback_changed);
  QObject::connect(&content_catalog, &bugg::ContentCatalogPort::source_selection_changed, &runtime,
                   [&] { runtime.set_content_request(content_catalog.requester()); });
#ifdef BUGG_SINGLE_FILE
  const auto bridge = QCoreApplication::applicationFilePath();
#elif defined(Q_OS_WIN)
  const auto bridge = portable + "/native/bin/buggcraft-bridge.exe";
#else
  const auto bridge = QCoreApplication::applicationDirPath() + "/native/bin/buggcraft-bridge";
#endif
  bugg::MultiplayerService multiplayer(&http, cache, bridge);
  QObject::connect(&runtime, &bugg::GameRuntime::feedback_prepared, &multiplayer,
                   &bugg::MultiplayerService::submit_feedback);
  QObject::connect(&multiplayer, &bugg::MultiplayerService::feedback_finished, &runtime,
                   &bugg::GameRuntime::release_feedback);
  runtime.set_room_content_request(
      [&multiplayer](const auto& method, auto parameters, const auto& cancelled) {
        return multiplayer.content_request(method, parameters, cancelled);
      });
  QObject::connect(&multiplayer, &bugg::MultiplayerService::sync_requested, &runtime,
                   &bugg::GameRuntime::install);
  QObject::connect(&runtime, &bugg::GameRuntime::room_prepared, &multiplayer,
                   &bugg::MultiplayerService::content_ready);
  QObject::connect(&multiplayer, &bugg::MultiplayerService::instance_check_requested, &runtime,
                   &bugg::GameRuntime::check_room);
  QObject::connect(&runtime, &bugg::GameRuntime::room_checked, &multiplayer,
                   &bugg::MultiplayerService::content_checked);
  QObject::connect(&multiplayer, &bugg::MultiplayerService::content_invalidated, &runtime,
                   &bugg::GameRuntime::cancel_room);
  QObject::connect(&runtime, &bugg::GameRuntime::room_progress, &multiplayer,
                   &bugg::MultiplayerService::preparation_progress);
  QObject::connect(&runtime, &bugg::GameRuntime::launch_changed, &multiplayer,
                   &bugg::MultiplayerService::launch_progress);
  QObject::connect(&runtime, &bugg::GameRuntime::cache_root_changed, &app, [&] {
    const auto path = runtime.cache_root();
    sources.relocate_storage(path + "/source-settings.json");
    catalog.relocate_storage(path + "/catalog-cache.json");
    account.relocate_storage(path + "/credentials.bin");
    multiplayer.relocate_storage(path);
    updates.relocate_storage(path);
  });
  bugg::LanguageService languages(nullptr, cache);
  QObject::connect(&runtime, &bugg::GameRuntime::cache_root_changed, &languages,
                   [&] { languages.relocate_storage(runtime.cache_root()); });
  bugg::ApplicationLifecycle lifecycle(&runtime, &account, &sources);
  lifecycle.attach_usage(&http);
  lifecycle.attach_updates(&updates);
  lifecycle.attach_languages(&languages);
  lifecycle.attach_multiplayer(&multiplayer);
  lifecycle.attach_content_catalog(&content_catalog);
  QObject::connect(&sources, &bugg::SourceSettings::configuration_changed, &runtime, [&] {
    const auto order = sources.source_order();
    const auto base = sources.bugg_base_url();
    runtime.select_sources(order, base);
    catalog.select_sources(order, base);
    content_catalog.select_sources(order, base);
  });
  QQmlApplicationEngine engine;
  QObject::connect(&languages, &bugg::LanguageService::changed, &engine, [&] {
    app.setLayoutDirection(languages.right_to_left() ? Qt::RightToLeft : Qt::LeftToRight);
    engine.retranslate();
  });
  QObject::connect(&runtime, &bugg::GameRuntime::settings_changed, &languages, [&] {
    if (lifecycle.phase() == "ready")
      languages.set_code(runtime.preferences().value("language").toString());
  });
  QObject::connect(&lifecycle, &bugg::ApplicationLifecycle::changed, &languages, [&] {
    if (lifecycle.phase() == "ready")
      languages.set_code(runtime.preferences().value("language").toString());
  });
#ifdef BUGG_SINGLE_FILE
  engine.setImportPathList({"qrc:/qt/qml", "qrc:/qt-project.org/imports"});
#else
  engine.addImportPath(QCoreApplication::applicationDirPath() + "/qml");
#endif
  engine.setInitialProperties(
      {{"desktopEnvironment", QVariant::fromValue(&desktop)},
       {"sourceSettings", QVariant::fromValue(static_cast<QObject*>(&sources))},
       {"catalogService", QVariant::fromValue(static_cast<QObject*>(&catalog))},
       {"contentService", QVariant::fromValue(static_cast<QObject*>(&content_catalog))},
       {"updateService", QVariant::fromValue(static_cast<QObject*>(&updates))},
       {"accountService", QVariant::fromValue(static_cast<QObject*>(&account))},
       {"gameRuntime", QVariant::fromValue(static_cast<QObject*>(&runtime))},
       {"multiplayerService", QVariant::fromValue(static_cast<QObject*>(&multiplayer))},
       {"languageService", QVariant::fromValue(static_cast<QObject*>(&languages))},
       {"applicationLifecycle", QVariant::fromValue(static_cast<QObject*>(&lifecycle))}});
  QObject::connect(
      &engine, &QQmlApplicationEngine::objectCreationFailed, &app,
      []() { QCoreApplication::exit(1); }, Qt::QueuedConnection);
  lifecycle.before_mount();
  engine.loadFromModule("Bugg", "Main");
  if (engine.rootObjects().isEmpty()) return 1;
  auto* window = qobject_cast<QQuickWindow*>(engine.rootObjects().first());
  QObject::connect(window, &QQuickWindow::frameSwapped, &lifecycle,
                   &bugg::ApplicationLifecycle::mounted, Qt::QueuedConnection);
  QObject::connect(&lifecycle, &bugg::ApplicationLifecycle::quit_ready, &app,
                   &QCoreApplication::quit);
  app.setQuitOnLastWindowClosed(false);
  auto* controller = window->findChild<QObject*>("windowController");
  if (parser.isSet("theme")) {
    QMetaObject::invokeMethod(controller, "selectTheme", Q_ARG(QVariant, parser.value("theme")));
    QObject::connect(&runtime, &bugg::GameRuntime::initialized, controller,
                     [controller, theme = parser.value("theme")] {
                       QMetaObject::invokeMethod(controller, "selectTheme", Q_ARG(QVariant, theme));
                     });
  }
  if (parser.isSet("page")) {
    QTimer::singleShot(600, window, [window, route = parser.value("page")] {
      QMetaObject::invokeMethod(window->findChild<QObject*>("toolContent"), "openToolPage",
                                Q_ARG(QVariant, 0), Q_ARG(QVariant, route));
    });
  }
  int capture_exit_code = 0;
  QTimer capture_timer;
  if (parser.isSet("capture")) {
    capture_timer.setSingleShot(true);
    QObject::connect(&lifecycle, &bugg::ApplicationLifecycle::changed, &capture_timer, [&] {
      if ((lifecycle.phase() == "awaiting_consent" || lifecycle.phase() == "ready") &&
          !capture_timer.isActive())
        capture_timer.start(600);
    });
    QObject::connect(&capture_timer, &QTimer::timeout, window,
                     [window, &lifecycle, &capture_exit_code, path = parser.value("capture")] {
                       capture_exit_code = window->grabWindow().save(path) ? 0 : 1;
                       lifecycle.shutdown();
                     });
    QTimer::singleShot(30000, window, [&] {
      capture_exit_code = 1;
      lifecycle.shutdown();
    });
  }
  const auto exit_code = app.exec();
  return exit_code ? exit_code : capture_exit_code;
}
