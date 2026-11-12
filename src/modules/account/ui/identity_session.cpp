#include "modules/account/ui/identity_session.h"

#include <QClipboard>
#include <QCoreApplication>
#include <QDesktopServices>
#include <QGuiApplication>
#include <QRegularExpression>
#include <QUrl>

namespace bugg {

IdentitySession::IdentitySession(QObject* parent) : QObject(parent) {
  timer_.setSingleShot(true);
  connect(&timer_, &QTimer::timeout, this, &IdentitySession::finish_microsoft);
}

void IdentitySession::set_service(QObject* service) {
  auto* port = qobject_cast<AccountPort*>(service);
  if (service_ == port) return;
  if (service_) disconnect(service_, nullptr, this, nullptr);
  service_ = port;
  if (service_) {
    connect(service_, &AccountPort::authentication, this, &IdentitySession::set_auth);
    connect(service_, &AccountPort::profile_ready, this, [this](const QString& name) {
      select(name, "microsoft", QCoreApplication::translate("Bugg", "微软账号 · Java 版"),
             explicit_login_ || preferred_id_.isEmpty() || preferred_id_.startsWith("microsoft:"));
      explicit_login_ = false;
    });
  }
  emit status_changed();
}

bool IdentitySession::use_offline(const QString& name) {
  static const QRegularExpression pattern("\\A[A-Za-z0-9_]{3,16}\\z");
  if (!pattern.match(name).hasMatch()) {
    set_auth("idle", {}, QCoreApplication::translate("Bugg", "名称需要 3–16 位字母、数字或下划线"));
    return false;
  }
  select(name, "offline", QStringLiteral("离线身份"));
  return true;
}

bool IdentitySession::activate_profile(const QString& id) {
  for (const auto& value : status_.value("profiles").toList()) {
    const auto profile = value.toMap();
    if (profile.value("id").toString() == id) {
      select(profile.value("name").toString(), profile.value("kind").toString(),
             profile.value("caption").toString());
      return true;
    }
  }
  return false;
}

QVariantMap IdentitySession::saved_state() const {
  QStringList offline;
  for (const auto& value : status_.value("profiles").toList()) {
    const auto profile = value.toMap();
    if (profile.value("kind") == "offline") offline.append(profile.value("name").toString());
  }
  return {{"offline", offline}, {"selectedId", preferred_id_.isEmpty() ? status_.value("selectedId") : preferred_id_}};
}
void IdentitySession::restore_state(const QVariantMap& state) {
  const auto selected = state.value("selectedId").toString();
  preferred_id_ = selected;
  static const QRegularExpression pattern("\\A[A-Za-z0-9_]{3,16}\\z");
  for (const auto& name : state.value("offline").toStringList()) {
    if (pattern.match(name).hasMatch())
      select(name, "offline", QCoreApplication::translate("Bugg", "离线身份"), false);
  }
  if (!selected.isEmpty()) activate_profile(selected);
  preferred_id_ = selected;
  emit status_changed();
}
void IdentitySession::select(const QString& name, const QString& kind, const QString& caption, bool activate) {
  const QString id = name.isEmpty() ? QString() : kind + ":" + name;
  if (activate) {
  preferred_id_ = id;
  status_["name"] = name;
  status_["kind"] = kind;
  status_["caption"] = caption;
  status_["initials"] = name.isEmpty() ? "?" : name.left(1).toUpper();
  status_["ready"] = !name.isEmpty();
  status_["selectedId"] = id;
  }
  auto profiles = status_.value("profiles").toList();
  if (!id.isEmpty()) {
    const QVariantMap profile{{"id", id},
                              {"name", name},
                              {"kind", kind},
                              {"caption", caption},
                              {"initials", name.left(1).toUpper()}};
    bool found = false;
    for (auto& value : profiles) {
      if (value.toMap().value("id").toString() == id) {
        value = profile;
        found = true;
        break;
      }
    }
    if (!found) profiles.append(profile);
  }
  status_["profiles"] = profiles;
  if (kind == "microsoft") {
    status_["microsoftName"] = name;
    status_["microsoftCaption"] = caption;
  } else if (kind == "offline") {
    status_["offlineName"] = name;
  }
  if (activate) {
    set_auth("idle");
    emit committed();
  } else emit status_changed();
}

void IdentitySession::set_auth(const QString& state, const QString& code, const QString& error) {
  timer_.stop();
  status_["authState"] = state;
  status_["code"] = code;
  status_["error"] = error;
  emit status_changed();
}

void IdentitySession::begin_microsoft() {
  const QString name = status_.value("microsoftName").toString();
  if (!name.isEmpty()) {
    select(name, "microsoft", status_.value("microsoftCaption").toString());
    return;
  }
  if (service_) {
    explicit_login_ = true;
    service_->begin();
  }
  else if (preview_enabled_)
    set_auth("waiting", "BUGG-DEMO");
  else
    set_auth("idle", {}, QCoreApplication::translate("Bugg", "微软登录服务尚未接入"));
}

void IdentitySession::complete_microsoft() {
  if (service_ && status_["authState"] == "waiting") {
    QGuiApplication::clipboard()->setText(status_["code"].toString());
    QDesktopServices::openUrl(QUrl("https://www.microsoft.com/link"));
    return;
  }
  if (!preview_enabled_ || status_["authState"] != "waiting") return;
  set_auth("authorizing", "BUGG-DEMO");
  if (automatic_) timer_.start(650);
}

void IdentitySession::finish_microsoft() {
  if (preview_enabled_ && status_["authState"] == "authorizing")
    select("BuggPlayer", "microsoft", QStringLiteral("微软账号 · 模拟登录"));
}

void IdentitySession::cancel_microsoft() {
  explicit_login_ = false;
  if (service_ && status_["authState"] != "idle") service_->cancel();
  if (status_["authState"] != "idle") set_auth("idle");
}

void IdentitySession::logout_microsoft() {
  if (service_) service_->logout();
  auto profiles = status_.value("profiles").toList();
  profiles.removeIf(
      [](const QVariant& value) { return value.toMap().value("kind").toString() == "microsoft"; });
  status_["profiles"] = profiles;
  status_["microsoftName"] = "";
  status_["microsoftCaption"] = "";
  if (status_["kind"] == "microsoft") {
    const QString offline = status_.value("offlineName").toString();
    select(offline, offline.isEmpty() ? "" : "offline",
           offline.isEmpty() ? QString() : QStringLiteral("离线身份"));
  } else {
    set_auth("idle");
  }
}

}  // namespace bugg
