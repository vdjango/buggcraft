#include "backdrop_palette.h"

#include <QFutureWatcher>
#include <QImageReader>
#include <QtConcurrent/QtConcurrentRun>

namespace bugg {
void BackdropPalette::set_source(const QUrl& source) {
  if (source_ == source) return;
  source_ = source;
  const auto generation = ++generation_;
  emit source_changed();
  if (cache_.contains(source)) {
    color_ = cache_.value(source);
    emit color_changed();
    return;
  }
  if (!source.isLocalFile() && source.scheme() != "qrc") return;
  const auto path = source.isLocalFile() ? source.toLocalFile() : ':' + source.path();
  auto* watcher = new QFutureWatcher<QColor>(this);
  connect(watcher, &QFutureWatcher<QColor>::finished, this, [this, watcher, source, generation] {
    const auto color = watcher->result();
    watcher->deleteLater();
    if (!color.isValid()) return;
    if (cache_.size() >= 32) cache_.clear();
    cache_.insert(source, color);
    if (generation != generation_) return;
    color_ = color;
    emit color_changed();
  });
  watcher->setFuture(QtConcurrent::run([path] {
    QImageReader reader(path);
    reader.setAutoTransform(true);
    if (reader.size().isValid())
      reader.setScaledSize(reader.size().scaled(32, 32, Qt::KeepAspectRatio));
    const auto original = reader.read();
    if (original.isNull()) return QColor{};
    const auto image = original.scaled(32, 32, Qt::KeepAspectRatio, Qt::SmoothTransformation);
    if (image.isNull()) return QColor{};
    qint64 red = 0, green = 0, blue = 0, weight = 0;
    for (int y = 0; y < image.height(); ++y)
      for (int x = 0; x < image.width(); ++x) {
        const auto pixel = image.pixelColor(x, y);
        red += pixel.red() * pixel.alpha();
        green += pixel.green() * pixel.alpha();
        blue += pixel.blue() * pixel.alpha();
        weight += pixel.alpha();
      }
    return weight ? QColor(red / weight, green / weight, blue / weight) : QColor{};
  }));
}
}  // namespace bugg
