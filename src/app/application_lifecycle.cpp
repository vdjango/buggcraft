#include "app/application_lifecycle.h"

#include <QJsonDocument>
#include <QUuid>

#include "modules/account/application/microsoft_account.h"
#include "modules/catalog/application/content_catalog_service.h"
#include "modules/game_install/application/game_runtime.h"
#include "modules/multiplayer/application/multiplayer_service.h"
#include "modules/settings/application/language_service.h"
#include "modules/settings/ui/source_settings.h"
#include "modules/update/application/launcher_update_service.h"
#include "platform/diagnostics/diagnostic_log.h"
#include "platform/http/http_client.h"
namespace bugg {
namespace {
constexpr auto agreement_revision = "2026-11-14";
}
ApplicationLifecycle::ApplicationLifecycle(GameRuntime* runtime, MicrosoftAccount* account,
                                           SourceSettings* sources, QObject* parent)
    : QObject(parent), runtime_(runtime), account_(account), sources_(sources) {
  connect(runtime_, &GameRuntime::initialized, this,
          [this](const QString& error) { complete("runtime", error); });
  connect(account_, &MicrosoftAccount::restored, this,
          [this](const QString& error) { complete("identity", error); });
  connect(account_, &MicrosoftAccount::storage_error, this,
          [this](const QString& error) { capture_error("credentials", error); });
  connect(runtime_, &GameRuntime::drained, this, &ApplicationLifecycle::drain);
  draining_.setInterval(50);
  connect(&draining_, &QTimer::timeout, this, &ApplicationLifecycle::drain);
}
void ApplicationLifecycle::attach_multiplayer(MultiplayerService* service) {
  multiplayer_ = service;
  connect(service, &MultiplayerService::restored, this,
          [this](const QString& error) { complete("multiplayer", error); });
  connect(service, &MultiplayerService::drained, this, &ApplicationLifecycle::drain);
}
void ApplicationLifecycle::attach_content_catalog(ContentCatalogService* service) {
  content_catalog_ = service;
  connect(service, &ContentCatalogService::drained, this, &ApplicationLifecycle::drain);
}
void ApplicationLifecycle::attach_updates(LauncherUpdateService* service) {
  updates_ = service;
  connect(runtime_, &GameRuntime::settings_changed, this, [this] {
    if (phase_ != "ready") return;
    const auto channel = runtime_->preferences().value("updateChannel").toString();
    if (updates_->status().value("channel") != channel && updates_->set_channel(channel))
      updates_->check();
  });
  connect(service, &LauncherUpdateService::drained, this, &ApplicationLifecycle::drain);
  connect(service, &LauncherUpdateService::restart_requested, this,
          &ApplicationLifecycle::shutdown);
}
void ApplicationLifecycle::attach_languages(LanguageService* service) {
  languages_ = service;
  connect(service, &LanguageService::drained, this, &ApplicationLifecycle::drain);
}
void ApplicationLifecycle::attach_usage(HttpClient* http, const QUrl& endpoint) {
  if (!http || usage_http_ || phase_ != "setup") return;
  usage_http_ = http;
  usage_endpoint_ = endpoint;
  connect(http, &HttpClient::completed, this,
          [this](quint64 id, const QByteArray&, const QString&) {
            if (id == usage_request_) usage_request_ = 0;
          });
  connect(runtime_, &GameRuntime::settings_changed, this, [this] {
    if (!runtime_->preferences().value("anonymousUsage").toBool() && usage_request_) {
      usage_http_->cancel(usage_request_);
      usage_request_ = 0;
    }
  });
}
void ApplicationLifecycle::report_usage() {
  if (!usage_http_ || usage_reported_ || !runtime_->preferences().value("anonymousUsage").toBool())
    return;
  usage_reported_ = true;
  HttpRequest request;
  request.url = usage_endpoint_;
  request.method = "POST";
  request.headers["Content-Type"] = "application/json";
  request.total_ms = 5000;
  request.maximum_bytes = 1024;
  request.body = QJsonDocument(QJsonObject{{"visitor", runtime_->usage_identity()},
                                           {"event", QUuid::createUuid().toString(QUuid::Id128)}})
                     .toJson(QJsonDocument::Compact);
  usage_request_ = usage_http_->request(request);
}
QVariantMap ApplicationLifecycle::status() const {
  return {{"phase", phase_}, {"pending", pending_}, {"errors", errors_}, {"view", view_}};
}
void ApplicationLifecycle::notify(const QString& name, const QVariantMap& context) {
  record_diagnostic("application." + name, QJsonObject::fromVariantMap(context));
  emit hook(name, context);
  emit changed();
}
void ApplicationLifecycle::before_mount() {
  if (phase_ != "setup") return;
  notify("setup");
  phase_ = "mounting";
  notify("before_mount");
}
void ApplicationLifecycle::mounted() {
  if (mounted_ || phase_ != "mounting") return;
  mounted_ = true;
  notify("mounted");
  phase_ = "initializing";
  pending_ = {"runtime"};
  notify("initializing");
  runtime_->initialize();
}
void ApplicationLifecycle::accept_agreement() {
  if (phase_ != "awaiting_consent") return;
  if (!runtime_->set_preference("agreementRevision", QString::fromLatin1(agreement_revision)))
    return;
  initialize_services();
}
void ApplicationLifecycle::initialize_services() {
  phase_ = "initializing";
  pending_ = {"identity"};
  if (multiplayer_) pending_.append("multiplayer");
  notify("initializing_services");
  account_->restore();
  if (multiplayer_) multiplayer_->restore();
  if (updates_) {
    updates_->set_channel(runtime_->preferences().value("updateChannel").toString());
    updates_->check();
  }
}
void ApplicationLifecycle::complete(const QString& owner, const QString& error) {
  if (phase_ != "initializing") return;
  pending_.removeAll(owner);
  if (!error.isEmpty()) capture_error(owner, error);
  if (owner == "runtime") {
    if (runtime_->preferences().value("agreementRevision").toString() != agreement_revision) {
      phase_ = "awaiting_consent";
      notify("awaiting_consent");
    } else {
      initialize_services();
    }
    return;
  }
  if (pending_.isEmpty()) {
    phase_ = "ready";
    notify("ready");
    report_usage();
  } else
    emit changed();
}
void ApplicationLifecycle::update_view(const QString& key) {
  if (phase_ == "draining" || phase_ == "stopped" || key == view_) return;
  const QVariantMap context{{"from", view_}, {"to", key}};
  notify("before_update", context);
  view_ = key;
  QTimer::singleShot(0, this, [this, context] {
    if (phase_ != "draining" && phase_ != "stopped" && view_ == context.value("to"))
      notify("updated", context);
  });
}
void ApplicationLifecycle::set_presented(bool presented) {
  if (presented_ == presented || phase_ == "draining" || phase_ == "stopped") return;
  presented_ = presented;
  notify(presented ? "activated" : "deactivated", {{"view", view_}});
}
void ApplicationLifecycle::capture_error(const QString& owner, const QString& error) {
  errors_.append(owner + "：" + error);
  notify("error_captured", {{"owner", owner}, {"error", error}});
}
void ApplicationLifecycle::shutdown() {
  if (phase_ == "draining" || phase_ == "stopped") return;
  phase_ = "draining";
  notify("before_unmount");
  if (usage_http_ && usage_request_) {
    usage_http_->cancel(usage_request_);
    usage_request_ = 0;
  }
  account_->cancel();
  runtime_->shutdown();
  if (multiplayer_) multiplayer_->shutdown();
  if (content_catalog_) content_catalog_->shutdown();
  if (updates_) updates_->shutdown();
  if (languages_) languages_->shutdown();
  draining_.start();
  drain();
}
void ApplicationLifecycle::drain() {
  if ((languages_ && languages_->busy()) || (updates_ && updates_->busy()) ||
      (content_catalog_ && content_catalog_->busy()) || (multiplayer_ && multiplayer_->busy()) ||
      phase_ != "draining" || runtime_->busy() || account_->busy() ||
      sources_->status().value("saving").toBool())
    return;
  draining_.stop();
  phase_ = "stopped";
  notify("unmounted");
  emit quit_ready();
}
}  // namespace bugg
