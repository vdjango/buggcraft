#ifndef BUGG_SHELL_PAGE_STATE_STORE_H_
#define BUGG_SHELL_PAGE_STATE_STORE_H_

#include <QtQml/qqmlregistration.h>

#include <QObject>
#include <QVariantMap>

#include "bugg_presentation_export.h"

namespace bugg {

/// 窗口级非敏感页面草稿；与 Loader 页面分离，不存业务结果或凭据，不做持久化。
class BUGG_PRESENTATION_EXPORT PageStateStore : public QObject {
  Q_OBJECT
  QML_ELEMENT
  Q_PROPERTY(QVariantMap values READ values NOTIFY values_changed)

 public:
  explicit PageStateStore(QObject* parent = nullptr) : QObject(parent) {}
  QVariantMap values() const { return values_; }
  /// GUI 线程：按稳定 page.field 键更新草稿；空键/相同值忽略，无 I/O 或取消副作用。
  /// value 只允许非敏感呈现数据；QJSValue 在边界转换为独立值，避免保留页面脚本对象。
  Q_INVOKABLE void set_value(const QString& key, const QVariant& value);

 signals:
  void values_changed();

 private:
  QVariantMap values_;
};

}  // namespace bugg

#endif  // BUGG_SHELL_PAGE_STATE_STORE_H_
