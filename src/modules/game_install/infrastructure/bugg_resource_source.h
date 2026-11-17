#ifndef BUGG_BUGG_RESOURCE_SOURCE_H_
#define BUGG_BUGG_RESOURCE_SOURCE_H_
#include "modules/game_install/infrastructure/resource_source_provider.h"
namespace bugg {
class BuggResourceSource final : public ResourceSourceProvider {
 public:
  QString id() const override { return "BUGG"; }
  QList<QUrl> urls(const QUrl& official, const QUrl& bugg_base) const override;
};
}  // namespace bugg
#endif
