#include "modules/catalog/ui/content_catalog_session.h"

#include <QHash>
#include <QJsonDocument>
#include <QSet>

namespace bugg {
namespace {
QString translation_field_hash(const QVariantMap& project, const QString& name) {
  for (const auto& value : project.value("translationFields").toList()) {
    const auto field = value.toMap();
    if (field.value("field").toString() == name) return field.value("source_hash").toString();
  }
  return {};
}
}  // namespace
ContentCatalogSession::ContentCatalogSession(QObject* parent) : QObject(parent) {
  connect(this, &ContentCatalogSession::changed, this, &ContentCatalogSession::update_models);
  debounce_.setSingleShot(true);
  debounce_.setInterval(320);
  connect(&debounce_, &QTimer::timeout, this, [this] { search(); });
  translation_retry_.setSingleShot(true);
  translation_retry_.setInterval(1000);
  connect(&translation_retry_, &QTimer::timeout, this, [this] { translate(false); });
}
void ContentCatalogSession::update_models() {
  QVariantList displayed;
  for (const auto& value : items_) displayed.append(display_project(value.toMap()));
  results_model_.reconcile(
      QString::fromUtf8(QJsonDocument::fromVariant(filters_).toJson(QJsonDocument::Compact)) + '/' +
          QString::number(page_),
      displayed);
  const auto project = display_project(project_, detail_view_ && original_text_);
  auto body = project.value("body").toList();
  body.append(project.value("gallery").toList());
  document_model_.reconcile(
      filters_.value("publisher").toString() + '/' + project.value("id").toString(), body);
}
ContentCatalogSession::~ContentCatalogSession() { cancel(); }
void ContentCatalogSession::set_service(QObject* service) {
  if (service == service_) return;
  cancel();
  if (service_) disconnect(service_, nullptr, this, nullptr);
  service_ = qobject_cast<ContentCatalogPort*>(service);
  if (service_) {
    connect(service_, &ContentCatalogPort::finished, this, &ContentCatalogSession::accept);
    connect(service_, &ContentCatalogPort::source_selection_changed, this, [this] {
      cancel();
      translations_.clear();
      category_context_.clear();
      load_categories();
      project_.remove("body");
      project_.remove("bodyError");
      version_page(version_page_);
      search(page_);
    });
  }
  emit service_changed();
  emit changed();
}
QVariantMap ContentCatalogSession::status() const {
  auto result = filters_;
  QString compatibility, advice;
  const bool mod = filters_.value("kind") == "mod";
  const bool shader = filters_.value("kind") == "shader";
  const auto loader = target_.value("loader").toString().toLower();
  const bool missing_loader = (mod || shader) && !target_.isEmpty() &&
                              (loader.isEmpty() || loader == "vanilla" || loader == "minecraft");
  const auto required_loaders = version_.value("loaders").toStringList();
  if (filters_.value("kind") != "modpack") {
    if (target_.isEmpty()) {
      compatibility = "noTarget";
      advice = tr("选择一个游戏后，自动匹配它的版本与加载器");
    } else if (missing_loader) {
      compatibility = "missingLoader";
      advice = shader ? tr("为当前游戏补装加载器、光影核心及依赖，保留存档和设置")
                      : tr("这个游戏尚未安装模组加载器，可创建兼容游戏并安装此模组");
    } else if (!version_.isEmpty() && (!version_.value("gameVersions")
                                            .toStringList()
                                            .contains(target_.value("version").toString()) ||
                                       (mod && !required_loaders.contains(loader)))) {
      compatibility = "incompatible";
      advice = tr("所选文件与目标游戏不兼容，请恢复匹配筛选或选择其他游戏");
    } else if (!version_.isEmpty()) {
      compatibility = "compatible";
      advice = tr("兼容当前游戏");
    }
  }
  QVariantList displayed;
  for (const auto& value : items_) displayed.append(display_project(value.toMap()));
  const QVariantMap values{
      {"items", displayed},
      {"page", page_},
      {"total", total_},
      {"hasMore", more_},
      {"loading", search_id_ != 0 || debounce_.isActive()},
      {"error", error_},
      {"project", display_project(project_, detail_view_ && original_text_)},
      {"translated", translated_ && !(detail_view_ && original_text_)},
      {"translationEnabled", translated_},
      {"translationLoading", translation_id_ != 0},
      {"translationPending", translation_pending_},
      {"translationError", translation_error_},
      {"versions", versions_},
      {"version", version_},
      {"versionPage", version_page_},
      {"versionTotal", version_total_},
      {"versionsMore", versions_more_},
      {"detailLoading", detail_id_ != 0},
      {"detailError", detail_error_},
      {"plan", plan_},
      {"planning", plan_id_ != 0},
      {"planError", plan_error_},
      {"available", !service_.isNull()},
      {"target", target_},
      {"compatibility", compatibility},
      {"compatibilityAdvice", advice},
      {"missingLoader", missing_loader},
      {"suggestedLoader", shader ? plan_.value("shaderSupport").toMap().value("loader").toString()
                          : mod  ? required_loaders.value(0)
                                 : QString("vanilla")},
      {"suggestedGame",
       version_.value("gameVersions").toStringList().contains(target_.value("version").toString())
           ? target_.value("version").toString()
           : version_.value("gameVersions").toStringList().value(0)},
      {"categories", categories_},
      {"categoryError", category_error_},
      {"categoriesLoading", category_id_ != 0}};
  for (auto it = values.begin(); it != values.end(); ++it) result[it.key()] = it.value();
  return result;
}
QVariantMap ContentCatalogSession::display_project(const QVariantMap& project,
                                                   bool original) const {
  auto result = project;
  if (translated_ && !original) {
    const auto values = translations_.value(project.value("id").toString()).toMap();
    for (auto it = values.begin(); it != values.end(); ++it) result[it.key()] = it.value();
    result["hasTranslation"] = !values.isEmpty();
    result["translatedSummary"] = values.contains("description");
    result["translatedBody"] = values.contains("body");
  }
  return result;
}
void ContentCatalogSession::set_active(bool active) {
  if (active_ == active) return;
  active_ = active;
  if (!active) {
    translation_retry_.stop();
    if (translation_id_ && service_) service_->cancel(translation_id_);
    translation_id_ = 0;
  } else {
    translate();
  }
  emit changed();
}
void ContentCatalogSession::set_translation_enabled(bool enabled) {
  if (translated_ == enabled) return;
  translated_ = enabled;
  translation_retry_.stop();
  if (translation_id_ && service_) service_->cancel(translation_id_);
  translation_id_ = 0;
  if (enabled) translate();
  emit changed();
}
void ContentCatalogSession::set_detail_view(bool detail) {
  if (detail_view_ == detail) return;
  detail_view_ = detail;
  original_text_ = false;
  translation_retry_.stop();
  if (translation_id_ && service_) service_->cancel(translation_id_);
  translation_id_ = 0;
  translate();
  emit changed();
}
void ContentCatalogSession::set_original_text(bool original) {
  if (original_text_ == original) return;
  original_text_ = original;
  translation_retry_.stop();
  if (translation_id_ && service_) service_->cancel(translation_id_);
  translation_id_ = 0;
  if (!original) translate();
  emit changed();
}
void ContentCatalogSession::translate(bool ensure) {
  if (!active_ || !translated_ || (detail_view_ && original_text_) || !service_ || translation_id_)
    return;
  const auto visible = detail_view_ && !project_.isEmpty() ? QVariantList{project_} : items_;
  QVariantList items;
  for (const auto& value : visible) {
    const auto item = value.toMap();
    if (item.value("translationFields").toList().isEmpty()) continue;
    items.append(QVariantMap{{"id", item.value("id")},
                             {"publisher", item.value("publisher")},
                             {"website", item.value("website")},
                             {"translationFields", item.value("translationFields")}});
  }
  if (items.isEmpty()) return;
  if (ensure) translation_attempts_ = 0;
  translation_error_.clear();
  translation_pending_ = false;
  request("translations", {{"items", items}, {"detail", detail_view_}, {"ensure", ensure}});
}
void ContentCatalogSession::browse(const QString& kind, const QString& query,
                                   const QVariantMap& instance) {
  if (!QStringList{"mod", "resourcepack", "shader", "modpack"}.contains(kind)) return;
  cancel();
  translations_.clear();
  filters_["kind"] = kind;
  filters_["category"] = "";
  filters_["query"] = query;
  apply_target(instance);
  items_.clear();
  project_.clear();
  versions_.clear();
  version_.clear();
  plan_.clear();
  load_categories();
  search();
}
void ContentCatalogSession::ensure_context(const QVariantMap& instance) {
  if (target_ != instance) {
    browse(filters_.value("kind").toString(), filters_.value("query").toString(), instance);
  } else {
    load_categories();
    if (items_.isEmpty() && !search_id_) search();
  }
}
void ContentCatalogSession::load_categories() {
  const auto context =
      filters_.value("publisher").toString() + '/' + filters_.value("kind").toString();
  if (category_context_ == context && (category_id_ || !categories_.isEmpty())) return;
  if (category_id_ && service_) service_->cancel(category_id_);
  category_id_ = 0;
  category_context_ = context;
  categories_.clear();
  category_error_.clear();
  request("categories");
}
void ContentCatalogSession::match_target() {
  apply_target(target_);
  if (project_.isEmpty())
    search();
  else
    version_page(0);
}
void ContentCatalogSession::edit(const QString& key, const QString& value) {
  if (!filters_.contains(key) || filters_.value(key).toString() == value || key == "kind") return;
  filters_[key] = value;
  if (search_id_ && service_) service_->cancel(search_id_);
  search_id_ = 0;
  if (detail_id_ && service_) service_->cancel(detail_id_);
  detail_id_ = 0;
  if (plan_id_ && service_) service_->cancel(plan_id_);
  plan_id_ = 0;
  plan_.clear();
  versions_.clear();
  version_.clear();
  project_.clear();
  translations_.clear();
  translation_retry_.stop();
  if (translation_id_ && service_) service_->cancel(translation_id_);
  translation_id_ = 0;
  if (key == "publisher") {
    filters_["category"] = "";
    load_categories();
  }
  debounce_.start();
  emit changed();
}
void ContentCatalogSession::request(const QString& operation, const QVariantMap& extra) {
  if (!service_) {
    error_ = tr("内容服务尚未接入");
    emit changed();
    return;
  }
  auto query = filters_;
  query["operation"] = operation;
  for (auto it = extra.begin(); it != extra.end(); ++it) query[it.key()] = it.value();
  auto& id = operation == "search"         ? search_id_
             : operation == "translations" ? translation_id_
             : operation == "plan"         ? plan_id_
             : operation == "categories"   ? category_id_
                                           : detail_id_;
  if (id) service_->cancel(id);
  id = ++sequence_;
  service_->query(id, query);
  emit changed();
}
void ContentCatalogSession::search(int page) {
  debounce_.stop();
  page_ = qMax(0, page);
  error_.clear();
  translations_.clear();
  translation_retry_.stop();
  if (translation_id_ && service_) service_->cancel(translation_id_);
  translation_id_ = 0;
  request("search", {{"offset", page_ * 20}});
}
void ContentCatalogSession::open_project(const QString& id, const QVariantMap& instance) {
  if (search_id_ || debounce_.isActive()) return;
  if (!instance.isEmpty() && (target_.isEmpty() || target_.value("id") != instance.value("id")) &&
      filters_.value("kind") != "modpack")
    apply_target(instance);
  for (const auto& value : items_) {
    const auto item = value.toMap();
    if (item.value("id") != id) continue;
    project_ = item;
    original_text_ = false;
    translation_retry_.stop();
    if (translation_id_ && service_) service_->cancel(translation_id_);
    translation_id_ = 0;
    versions_.clear();
    version_.clear();
    plan_.clear();
    detail_error_.clear();
    plan_error_.clear();
    version_page_ = 0;
    if (plan_id_ && service_) service_->cancel(plan_id_);
    plan_id_ = 0;
    request("detail", {{"projectId", id}, {"offset", 0}});
    return;
  }
}
void ContentCatalogSession::version_page(int page) {
  if (project_.isEmpty()) return;
  if (plan_id_ && service_) service_->cancel(plan_id_);
  plan_id_ = 0;
  plan_.clear();
  version_.clear();
  versions_.clear();
  plan_error_.clear();
  version_page_ = qMax(0, page);
  detail_error_.clear();
  request(!project_.contains("body") || project_.contains("bodyError") ? "detail" : "versions",
          {{"projectId", project_.value("id")}, {"offset", version_page_ * 20}});
}
void ContentCatalogSession::apply_target(const QVariantMap& instance) {
  target_ = instance;
  filters_["gameVersion"] = instance.value("version", "");
  filters_["loaderVersion"] = instance.value("loaderVersion", "");
  const auto loader = instance.value("loader").toString().toLower();
  filters_["loader"] = loader == "minecraft" || loader == "vanilla" ? "" : loader;
}
void ContentCatalogSession::select_target(const QVariantMap& instance) {
  if (target_ == instance) return;
  if (search_id_ && service_) service_->cancel(search_id_);
  search_id_ = 0;
  debounce_.stop();
  apply_target(instance);
  versions_.clear();
  version_.clear();
  plan_.clear();
  plan_error_.clear();
  if (plan_id_ && service_) service_->cancel(plan_id_);
  plan_id_ = 0;
  if (project_.isEmpty())
    search();
  else
    version_page(0);
}
void ContentCatalogSession::select_version(const QString& id) {
  for (const auto& value : versions_) {
    const auto version = value.toMap();
    if (version.value("id") != id) continue;
    version_ = version;
    plan_.clear();
    plan_error_.clear();
    request("plan", {{"projectId", project_.value("id")},
                     {"versionId", id},
                     {"projectTitle", project_.value("title")}});
    return;
  }
}
void ContentCatalogSession::select_shader_runtime(const QString& id) {
  if (filters_.value("kind") != "shader" || version_.isEmpty()) return;
  const auto choices = plan_.value("shaderSupport").toMap().value("choices").toList();
  for (const auto& value : choices) {
    if (value.toMap().value("id").toString() != id) continue;
    plan_.clear();
    plan_error_.clear();
    request("plan", {{"projectId", project_.value("id")},
                     {"versionId", version_.value("id")},
                     {"projectTitle", project_.value("title")},
                     {"shaderRuntimeChoice", id}});
    return;
  }
}
void ContentCatalogSession::accept(quint64 id, const QVariantMap& result) {
  if (id == category_id_ && id) {
    category_id_ = 0;
    category_error_ = result.value("error").toString();
    if (category_error_.isEmpty()) categories_ = result.value("categories").toList();
  } else if (id == search_id_ && id) {
    search_id_ = 0;
    error_ = result.value("error").toString();
    if (error_.isEmpty()) {
      items_ = result.value("items").toList();
      total_ = result.value("total").toInt();
      more_ = result.value("hasMore").toBool();
      if (!detail_view_ || project_.isEmpty()) translate();
    }
  } else if (id == detail_id_ && id) {
    detail_id_ = 0;
    detail_error_ = result.value("error").toString();
    if (detail_error_.isEmpty()) {
      if (result.contains("project")) {
        auto detail = result.value("project").toMap();
        if (detail.value("author").toString().isEmpty())
          detail["author"] = project_.value("author");
        const auto previous_summary = translation_field_hash(project_, "summary");
        project_ = detail;
        // A list's current summary is already validated. Keep it visible while
        // the detail body is resolved instead of flashing the original again.
        auto translated = translations_.value(detail.value("id").toString()).toMap();
        translated.remove("body");
        if (previous_summary.isEmpty() ||
            previous_summary != translation_field_hash(detail, "summary"))
          translated.remove("description");
        translations_[detail.value("id").toString()] = translated;
        translation_retry_.stop();
        if (translation_id_ && service_) service_->cancel(translation_id_);
        translation_id_ = 0;
        translate();
      }
      versions_ = result.value("versions").toList();
      detail_error_ = result.value("compatibilityError").toString();
      version_total_ = result.value("total").toInt();
      versions_more_ = result.value("hasMore").toBool();
      if (!versions_.isEmpty()) select_version(versions_.first().toMap().value("id").toString());
    }
  } else if (id == plan_id_ && id) {
    plan_id_ = 0;
    plan_error_ = result.value("error").toString();
    if (plan_error_.isEmpty()) plan_ = result;
  } else if (id == translation_id_ && id) {
    translation_id_ = 0;
    translation_error_ = result.value("error").toString();
    translation_pending_ = result.value("pending").toBool();
    const auto values = result.value("translations").toMap();
    for (auto it = values.begin(); it != values.end(); ++it) {
      auto merged = translations_.value(it.key()).toMap();
      const auto fields = it.value().toMap();
      for (auto field = fields.begin(); field != fields.end(); ++field)
        merged[field.key()] = field.value();
      translations_[it.key()] = merged;
    }
    if (active_ && translated_ && translation_error_.isEmpty()) {
      if (!translation_pending_)
        translation_retry_.start(30000);
      else {
        ++translation_attempts_;
        translation_retry_.start(translation_attempts_ < 4    ? 1000
                                 : translation_attempts_ < 12 ? 5000
                                                              : 30000);
      }
    }
  } else
    return;
  emit changed();
}
void ContentCatalogSession::cancel() {
  debounce_.stop();
  translation_retry_.stop();
  translation_pending_ = false;
  if (service_)
    for (const auto id : {search_id_, detail_id_, plan_id_, category_id_, translation_id_})
      if (id) service_->cancel(id);
  search_id_ = detail_id_ = plan_id_ = category_id_ = 0;
  translation_id_ = 0;
}
}  // namespace bugg
