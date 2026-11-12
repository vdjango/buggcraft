#ifndef BUGG_MODULES_CATALOG_UI_CONTENT_LIST_MODEL_H_
#define BUGG_MODULES_CATALOG_UI_CONTENT_LIST_MODEL_H_
#include <QAbstractListModel>
#include <QVariantList>

#include "bugg_presentation_export.h"

namespace bugg {
/// GUI/session-owned value model. Same-context updates retain delegates and
/// scroll position; changing the query/project intentionally resets the view.
class BUGG_PRESENTATION_EXPORT ContentListModel : public QAbstractListModel {
  Q_OBJECT
 public:
  explicit ContentListModel(QObject* parent = nullptr) : QAbstractListModel(parent) {}
  int rowCount(const QModelIndex& parent = {}) const override;
  QVariant data(const QModelIndex& index, int role) const override;
  QHash<int, QByteArray> roleNames() const override;
  /// GUI thread only; no I/O, cancellation or external ownership.
  void reconcile(const QString& context, const QVariantList& rows);

 private:
  QString context_;
  QVariantList rows_;
};
}  // namespace bugg
#endif
