#include "modules/game_install/ui/install_catalog_session.h"

#include <QCoreApplication>
#include <QVariantList>
#include <algorithm>

namespace bugg {
namespace {
bool contains(const CatalogResult& result, const QString& id) {
  return std::any_of(result.entries.cbegin(), result.entries.cend(),
                     [&id](const CatalogEntry& item) { return item.id == id; });
}

QVariantList choices(const CatalogResult& result) {
  QVariantList values;
  for (const auto& item : result.entries)
    values.push_back(
        QVariantMap{{"id", item.id}, {"name", item.id}, {"caption", item.stable ? "" : "预发布"}});
  return values;
}

QString loader_key(const CatalogQuery& query) { return query.kind + "/" + query.game_version; }
}  // namespace

InstallCatalogSession::InstallCatalogSession(QObject* parent) : QObject(parent) {}
InstallCatalogSession::~InstallCatalogSession() { cancel(); }

void InstallCatalogSession::set_service(QObject* service) {
  auto* port = qobject_cast<GameCatalogPort*>(service);
  if (port == service_) return;
  cancel();
  if (service_) disconnect(service_, nullptr, this, nullptr);
  service_ = port;
  games_ = {};
  loaders_ = {};
  loader_catalogs_.clear();
  game_.clear();
  custom_game_ = false;
  loader_version_.clear();
  error_.clear();
  loader_error_.clear();
  attempted_ = false;
  if (service_) {
    connect(service_, &GameCatalogPort::finished, this, &InstallCatalogSession::accept);
    connect(service_, &GameCatalogPort::cached, this,
            [this](quint64 id, const CatalogResult& result) { apply(id, result, false); });
    connect(service_, &GameCatalogPort::source_changed, this,
            &InstallCatalogSession::report_source);
    connect(service_, &GameCatalogPort::source_selection_changed, this, [this] {
      games_ = {};
      loaders_ = {};
      loader_catalogs_.clear();
      loader_version_.clear();
      loader_error_.clear();
      if (attempted_)
        refresh();
      else
        emit status_changed();
    });
  }
  emit service_changed();
  emit status_changed();
}

QVariantMap InstallCatalogSession::status() const {
  const bool ready =
      contains(games_, game_) && (loader_ == "vanilla" || contains(loaders_, loader_version_));
  return {{"games", choices(games_)},
          {"loaders", choices(loaders_)},
          {"game", game_},
          {"loader", loader_},
          {"loaderVersion", loader_version_},
          {"loadingGames", game_request_ != 0 && games_.entries.isEmpty()},
          {"loadingLoaders", loader_request_ != 0 && loaders_.entries.isEmpty()},
          {"refreshing", game_request_ != 0 || loader_request_ != 0},
          {"error", error_},
          {"loaderError", loader_error_},
          {"source", games_.source},
          {"loaderSource", loaders_.source},
          {"instanceName", custom_name_ ? instance_name_ : suggested_name()},
          {"ready", ready}};
}

QString InstallCatalogSession::suggested_name() const {
  if (game_.isEmpty() || loader_ == "vanilla") return game_;
  return game_ + "-" + loader_ + (loader_version_.isEmpty() ? "" : "-" + loader_version_);
}

void InstallCatalogSession::ensure_loaded() {
  if (!game_request_) load_games(false);
  if (!game_.isEmpty() && loader_ != "vanilla") load_loaders();
}

void InstallCatalogSession::refresh() {
  cancel();
  load_games(true);
  if (loader_ != "vanilla") load_loaders(true);
}

void InstallCatalogSession::load_games(bool refresh) {
  attempted_ = true;
  error_.clear();
  if (!service_) {
    error_ = QCoreApplication::translate("Bugg", "游戏目录服务尚未接入");
  } else {
    game_request_ = ++sequence_;
    if (refresh)
      service_->refresh(game_request_, {"minecraft", {}});
    else
      service_->query(game_request_, {"minecraft", {}});
  }
  emit status_changed();
}

void InstallCatalogSession::select_game(const QString& id) {
  if (!contains(games_, id)) return;
  custom_game_ = true;
  if (id == game_) return;
  game_ = id;
  load_loaders();
}
void InstallCatalogSession::prepare_selection(const QString& game, const QString& loader) {
  if (game.isEmpty() ||
      !QStringList{"vanilla", "fabric", "forge", "neoforge", "quilt"}.contains(loader))
    return;
  custom_name_ = false;
  loader_ = loader;
  pending_game_ = game;
  if (contains(games_, game)) {
    game_ = game;
    custom_game_ = true;
    pending_game_.clear();
    load_loaders();
  } else {
    game_.clear();
    if (!game_request_) load_games(false);
  }
  emit status_changed();
}

void InstallCatalogSession::select_loader(const QString& kind) {
  static const QStringList kinds{"vanilla", "neoforge", "forge", "fabric", "quilt"};
  if (!kinds.contains(kind) || kind == loader_) return;
  loader_ = kind;
  load_loaders();
}

void InstallCatalogSession::select_loader_version(const QString& id) {
  if (!contains(loaders_, id)) return;
  auto& selection = loader_catalogs_[loader_key({loader_, game_})];
  selection.custom_version = true;
  if (id == loader_version_) return;
  loader_version_ = id;
  selection.version = id;
  emit status_changed();
}

void InstallCatalogSession::set_instance_name(const QString& name) {
  instance_name_ = name;
  custom_name_ = name != suggested_name();
  emit status_changed();
}

void InstallCatalogSession::retry_loaders() { load_loaders(true); }

void InstallCatalogSession::load_loaders(bool refresh) {
  loader_request_ = 0;
  const CatalogQuery query{loader_, game_};
  const auto view = loader_catalogs_.value(loader_key(query));
  loaders_ = view.result;
  loader_version_ = view.version;
  loader_error_ = view.result.error;
  if (service_ && !game_.isEmpty() && loader_ != "vanilla") {
    // 页面切换只改变当前组合；仍在获取的组合继续完成，切回来不重复发请求。
    for (auto it = loader_requests_.cbegin(); it != loader_requests_.cend(); ++it)
      if (it.value() == query) loader_request_ = it.key();
    if (loader_request_ && refresh) {
      service_->cancel(loader_request_);
      loader_requests_.remove(loader_request_);
      loader_request_ = 0;
    }
    if (!loader_request_) {
      loader_request_ = ++sequence_;
      loader_requests_.insert(loader_request_, query);
      if (refresh)
        service_->refresh(loader_request_, query);
      else
        service_->query(loader_request_, query);
    }
  }
  emit status_changed();
}

void InstallCatalogSession::accept(quint64 request_id, const CatalogResult& result) {
  apply(request_id, result, true);
}

void InstallCatalogSession::apply(quint64 request_id, const CatalogResult& result, bool final) {
  if (request_id == game_request_) {
    if (final) game_request_ = 0;
    error_ = result.error;
    if (error_.isEmpty()) {
      games_ = result;
      // 缓存只是预览：后台发现新版本时更新默认值，已手动选择的版本保留。
      const auto previous_game = game_;
      if (!pending_game_.isEmpty() && contains(games_, pending_game_)) {
        game_ = pending_game_;
        custom_game_ = true;
        pending_game_.clear();
      } else if (final && !pending_game_.isEmpty()) {
        error_ = tr("所需游戏版本未在目录中找到，请选择可用版本");
        pending_game_.clear();
      }
      if (!contains(games_, game_)) custom_game_ = false;
      if (!custom_game_) game_ = result.preferred;
      if (previous_game != game_) load_loaders();
    }
  } else if (loader_requests_.contains(request_id)) {
    const auto query = loader_requests_.value(request_id);
    if (final) loader_requests_.remove(request_id);
    auto& view = loader_catalogs_[loader_key(query)];
    if (result.error.isEmpty()) {
      view.result = result;
      if (!contains(result, view.version)) view.custom_version = false;
      if (!view.custom_version) view.version = result.preferred;
    }
    // 错误不清空成功快照，亦不能把其他组合的迟到结果放进当前列表。
    if (query != CatalogQuery{loader_, game_}) return;
    if (final) loader_request_ = 0;
    loaders_ = view.result;
    loader_version_ = view.version;
    loader_error_ = result.error;
  } else {
    return;
  }
  emit status_changed();
}

void InstallCatalogSession::report_source(quint64 request_id, const QString& source) {
  if (request_id == game_request_)
    games_.source = source;
  else if (request_id == loader_request_)
    loaders_.source = source;
  else
    return;
  emit status_changed();
}

void InstallCatalogSession::cancel() {
  const bool changed = game_request_ || loader_request_;
  if (service_) {
    if (game_request_) service_->cancel(game_request_);
    for (const auto id : loader_requests_.keys()) service_->cancel(id);
  }
  game_request_ = 0;
  loader_request_ = 0;
  loader_requests_.clear();
  if (changed) emit status_changed();
}

}  // namespace bugg
