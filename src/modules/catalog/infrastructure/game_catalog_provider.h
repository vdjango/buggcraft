#ifndef BUGG_MODULES_CATALOG_INFRASTRUCTURE_GAME_CATALOG_PROVIDER_H_
#define BUGG_MODULES_CATALOG_INFRASTRUCTURE_GAME_CATALOG_PROVIDER_H_

#include <memory>
#include <vector>

#include "contracts/download_sources.h"
#include "contracts/game_catalog.h"

namespace bugg {

/// 来源协议适配器；无 QObject 状态、无 I/O，parse 可在工作线程调用。
/// 失败写 error；有效空列表保持 error 为空。新增来源只实现本接口并注册。
class GameCatalogProvider {
 public:
  virtual ~GameCatalogProvider() = default;
  virtual QString id() const = 0;
  virtual QStringList blocked_redirect_hosts() const = 0;
  virtual QUrl request_url(const CatalogQuery& query) const = 0;
  virtual CatalogResult parse(const CatalogQuery& query, const QByteArray& body) const = 0;
};

/// 按统一能力计划生成适配器队列；默认 BUGG/BMCLAPI/官方，无效输入返回空。
std::vector<std::shared_ptr<const GameCatalogProvider>> default_catalog_providers(
    const QStringList& order = supported_download_sources(), const CatalogQuery& query = {},
    const QUrl& bugg_base = default_bugg_source());

}  // namespace bugg
#endif  // BUGG_MODULES_CATALOG_INFRASTRUCTURE_GAME_CATALOG_PROVIDER_H_
