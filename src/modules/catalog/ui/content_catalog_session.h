#ifndef BUGG_MODULES_CATALOG_UI_CONTENT_CATALOG_SESSION_H_
#define BUGG_MODULES_CATALOG_UI_CONTENT_CATALOG_SESSION_H_
#include <QtQml/qqmlregistration.h>

#include <QPointer>
#include <QTimer>

#include "bugg_presentation_export.h"
#include "contracts/content_catalog.h"
#include "modules/catalog/ui/content_list_model.h"

namespace bugg {
/// Window-owned selection/query presentation. Pages only compose controls;
/// this model retains successful values and rejects stale query generations.
class BUGG_PRESENTATION_EXPORT ContentCatalogSession : public QObject {
  Q_OBJECT
  QML_ELEMENT
  Q_PROPERTY(QObject* service READ service WRITE set_service NOTIFY service_changed)
  Q_PROPERTY(QVariantMap status READ status NOTIFY changed)
  Q_PROPERTY(QAbstractItemModel* results_model READ results_model CONSTANT)
  Q_PROPERTY(QAbstractItemModel* document_model READ document_model CONSTANT)
  Q_PROPERTY(bool active READ active WRITE set_active NOTIFY changed)
  Q_PROPERTY(bool detail_view READ detail_view WRITE set_detail_view NOTIFY changed)
  Q_PROPERTY(bool translation_enabled READ translation_enabled WRITE set_translation_enabled NOTIFY
                 changed)
 public:
  explicit ContentCatalogSession(QObject* parent = nullptr);
  ~ContentCatalogSession() override;
  QObject* service() const { return service_; }
  void set_service(QObject* service);
  QVariantMap status() const;
  QAbstractItemModel* results_model() { return &results_model_; }
  QAbstractItemModel* document_model() { return &document_model_; }
  bool active() const { return active_; }
  /// Visibility only; stops translation retry without discarding successful data.
  void set_active(bool active);
  bool detail_view() const { return detail_view_; }
  /// GUI route binding selects one detail or the visible result page; cancels stale lookup.
  void set_detail_view(bool detail);
  bool translation_enabled() const { return translated_; }
  /// Global preference; disabling cancels translation requests and retries.
  Q_INVOKABLE void set_translation_enabled(bool enabled);
  /// Detail-only original text view; list translation and settings remain unchanged.
  Q_INVOKABLE void set_original_text(bool original);
  /// Enter the shared directory; optional instance supplies compatibility filters.
  Q_INVOKABLE void browse(const QString& kind, const QString& query = {},
                          const QVariantMap& instance = {});
  /// GUI edits (query/gameVersion/loader/publisher), debounced for text input.
  Q_INVOKABLE void edit(const QString& key, const QString& value);
  Q_INVOKABLE void search(int page = 0);
  /// First entry follows the selected instance; revisiting preserves user filters.
  Q_INVOKABLE void ensure_context(const QVariantMap& instance);
  Q_INVOKABLE void load_categories();
  /// Restore search/detail filters to the actual installation target.
  Q_INVOKABLE void match_target();
  Q_INVOKABLE void open_project(const QString& id, const QVariantMap& instance = {});
  /// Change the target while retaining the open project; reload compatible versions.
  Q_INVOKABLE void select_target(const QVariantMap& instance);
  Q_INVOKABLE void select_version(const QString& id);
  /// Replan the selected shader release with the user's exact core choice.
  Q_INVOKABLE void select_shader_runtime(const QString& id);
  Q_INVOKABLE void version_page(int page);
  Q_INVOKABLE void cancel();
 signals:
  void service_changed();
  void changed();

 private:
  void apply_target(const QVariantMap& instance);
  void request(const QString& operation, const QVariantMap& extra = {});
  void accept(quint64 id, const QVariantMap& result);
  void translate(bool ensure = true);
  void update_models();
  QVariantMap display_project(const QVariantMap& project, bool original = false) const;
  QPointer<ContentCatalogPort> service_;
  QTimer debounce_;
  QTimer translation_retry_;
  ContentListModel results_model_, document_model_;
  QVariantMap translations_;
  QString translation_error_;
  QVariantMap filters_{{"kind", "mod"}, {"publisher", "CurseForge"},
                       {"query", ""},   {"gameVersion", ""},
                       {"loader", ""},  {"category", ""}};
  QVariantMap project_, version_, plan_, target_;
  QVariantList items_, versions_, categories_;
  QString error_, detail_error_, plan_error_, category_error_, category_context_;
  quint64 sequence_ = 0, search_id_ = 0, detail_id_ = 0, plan_id_ = 0, category_id_ = 0;
  quint64 translation_id_ = 0;
  int translation_attempts_ = 0;
  bool active_ = false, detail_view_ = true, translated_ = true, translation_pending_ = false;
  bool original_text_ = false;
  int page_ = 0, total_ = 0, version_page_ = 0, version_total_ = 0;
  bool more_ = false, versions_more_ = false;
};
}  // namespace bugg
#endif
