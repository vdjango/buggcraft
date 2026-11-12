#include "modules/catalog/ui/content_list_model.h"

namespace bugg {
int ContentListModel::rowCount(const QModelIndex& parent) const {
  return parent.isValid() ? 0 : rows_.size();
}
QVariant ContentListModel::data(const QModelIndex& index, int role) const {
  return index.isValid() && index.row() >= 0 && index.row() < rows_.size() && role == Qt::UserRole
             ? rows_[index.row()]
             : QVariant{};
}
QHash<int, QByteArray> ContentListModel::roleNames() const { return {{Qt::UserRole, "modelData"}}; }
void ContentListModel::reconcile(const QString& context, const QVariantList& rows) {
  if (context_ != context) {
    beginResetModel();
    context_ = context;
    rows_ = rows;
    endResetModel();
    return;
  }
  const auto shared = qMin(rows_.size(), rows.size());
  for (qsizetype row = 0; row < shared; ++row) {
    if (rows_[row] == rows[row]) continue;
    rows_[row] = rows[row];
    emit dataChanged(index(row), index(row), {Qt::UserRole});
  }
  if (rows_.size() > rows.size()) {
    beginRemoveRows({}, rows.size(), rows_.size() - 1);
    rows_.erase(rows_.begin() + rows.size(), rows_.end());
    endRemoveRows();
  } else if (rows_.size() < rows.size()) {
    beginInsertRows({}, rows_.size(), rows.size() - 1);
    for (qsizetype row = rows_.size(); row < rows.size(); ++row) rows_.append(rows[row]);
    endInsertRows();
  }
}
}  // namespace bugg
