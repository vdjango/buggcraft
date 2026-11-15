#include "shell/value_list_model.h"

namespace bugg {
int ValueListModel::rowCount(const QModelIndex& parent) const {
  return parent.isValid() ? 0 : rows_.size();
}
QVariant ValueListModel::data(const QModelIndex& index, int role) const {
  return index.isValid() && index.row() >= 0 && index.row() < rows_.size() && role == Qt::UserRole
             ? rows_[index.row()]
             : QVariant{};
}
QHash<int, QByteArray> ValueListModel::roleNames() const { return {{Qt::UserRole, "modelData"}}; }
void ValueListModel::reconcile(const QString& context, const QVariantList& rows) {
  if (context_ != context) {
    beginResetModel();
    context_ = context;
    rows_ = rows;
    endResetModel();
    emit rows_changed();
    return;
  }
  for (qsizetype row = 0; row < rows.size(); ++row) {
    const auto key = rows[row].toMap().value("id").toString();
    if (!key.isEmpty() && (row >= rows_.size() || rows_[row].toMap().value("id") != key)) {
      auto found = row;
      while (found < rows_.size() && rows_[found].toMap().value("id") != key) ++found;
      if (found < rows_.size()) {
        beginMoveRows({}, found, found, {}, row);
        rows_.move(found, row);
        endMoveRows();
      } else {
        beginInsertRows({}, row, row);
        rows_.insert(row, rows[row]);
        endInsertRows();
      }
    }
    if (row >= rows_.size()) break;
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
  emit rows_changed();
}
}  // namespace bugg
