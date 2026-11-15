#ifndef BUGG_SHELL_VALUE_LIST_MODEL_H_
#define BUGG_SHELL_VALUE_LIST_MODEL_H_
#include <qqmlregistration.h>

#include <QAbstractListModel>
#include <QVariantList>

#include "bugg_presentation_export.h"

namespace bugg {
/// GUI/session-owned value model. Same-context updates retain delegates and
/// scroll position; changing the query/project intentionally resets the view.
class BUGG_PRESENTATION_EXPORT ValueListModel : public QAbstractListModel {
  Q_OBJECT
  QML_ELEMENT
  Q_PROPERTY(QVariantList rows READ rows WRITE set_rows NOTIFY rows_changed)
 public:
  explicit ValueListModel(QObject* parent = nullptr) : QAbstractListModel(parent) {}
  QVariantList rows() const { return rows_; }
  /// GUI presentation only; reconcile snapshots without replacing the model.
  void set_rows(const QVariantList& rows) { reconcile(context_, rows); }
  int rowCount(const QModelIndex& parent = {}) const override;
  QVariant data(const QModelIndex& index, int role) const override;
  QHash<int, QByteArray> roleNames() const override;
  /// GUI thread only; no I/O, cancellation or external ownership.
  void reconcile(const QString& context, const QVariantList& rows);
 signals:
  void rows_changed();

 private:
  QString context_;
  QVariantList rows_;
};
}  // namespace bugg
#endif
