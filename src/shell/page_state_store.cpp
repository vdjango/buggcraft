#include "shell/page_state_store.h"

#include <QJSValue>

namespace bugg {

void PageStateStore::set_value(const QString& key, const QVariant& value) {
  const QVariant snapshot = value.metaType() == QMetaType::fromType<QJSValue>()
                                ? value.value<QJSValue>().toVariant()
                                : value;
  if (key.isEmpty() || (values_.contains(key) && values_.value(key) == snapshot)) return;
  values_.insert(key, snapshot);
  emit values_changed();
}

}  // namespace bugg
