#ifndef BUGG_BMCLAPI_RESOURCE_SOURCE_H_
#define BUGG_BMCLAPI_RESOURCE_SOURCE_H_
#include "modules/game_install/infrastructure/resource_source_provider.h"
namespace bugg {
class BmclapiResourceSource final : public ResourceSourceProvider {
 public:
  QString id() const override { return "BMCLAPI"; }
  QList<QUrl> urls(const QUrl& official, const QUrl& bugg_base) const override;
};
}  // namespace bugg
#endif
