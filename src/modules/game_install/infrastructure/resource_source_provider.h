#ifndef BUGG_RESOURCE_SOURCE_PROVIDER_H_
#define BUGG_RESOURCE_SOURCE_PROVIDER_H_

#include <QList>
#include <QString>
#include <QUrl>

namespace bugg {
/// Pure protocol adaptation. No network, configuration, retry or mutable state.
/// Unknown resources return an empty list; callers own capability/fallback order.
class ResourceSourceProvider {
 public:
  virtual ~ResourceSourceProvider() = default;
  virtual QString id() const = 0;
  virtual QList<QUrl> urls(const QUrl& official, const QUrl& bugg_base) const = 0;
};
/// Immutable registered adapters, safe to use from any worker.
const ResourceSourceProvider* resource_source_provider(const QString& id);
}  // namespace bugg
#endif
