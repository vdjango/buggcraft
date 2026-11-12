#ifndef BUGG_SHELL_BACKDROP_PALETTE_H_
#define BUGG_SHELL_BACKDROP_PALETTE_H_
#include <QtQml/qqmlregistration.h>

#include <QColor>
#include <QHash>
#include <QObject>
#include <QUrl>

#include "bugg_presentation_export.h"

namespace bugg {
/// 图片呈现辅助；异步缩略取色，不拥有背景设置或网络请求。
class BUGG_PRESENTATION_EXPORT BackdropPalette : public QObject {
  Q_OBJECT
  QML_ELEMENT
  Q_PROPERTY(QUrl source READ source WRITE set_source NOTIFY source_changed)
  Q_PROPERTY(QColor averageColor READ average_color NOTIFY color_changed)
 public:
  explicit BackdropPalette(QObject* parent = nullptr) : QObject(parent) {}
  QUrl source() const { return source_; }
  QColor average_color() const { return color_; }
  /// GUI 设置本地/qrc URL；缓存命中立即发布，否则后台读取；失败保留旧色。
  void set_source(const QUrl& source);
 signals:
  void source_changed();
  void color_changed();

 private:
  QUrl source_;
  QColor color_{"#243D44"};
  QHash<QUrl, QColor> cache_;
  quint64 generation_ = 0;
};
}  // namespace bugg
#endif
