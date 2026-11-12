#ifndef BUGG_MODULES_CATALOG_INFRASTRUCTURE_CONTENT_PROVIDER_H_
#define BUGG_MODULES_CATALOG_INFRASTRUCTURE_CONTENT_PROVIDER_H_
#include <QUrl>

#include "contracts/content_catalog.h"
#include "contracts/download_sources.h"

namespace bugg {
/// Explicit endpoints permit isolated contract tests; production uses the
/// single configured Bugg origin and publisher APIs. The API key stays in C++.
struct ContentEndpoints {
  QUrl bugg_base{default_bugg_source()};
  QUrl curseforge{"https://api.curseforge.com/v1"};
  QUrl modrinth{"https://api.modrinth.com/v2"};
  QByteArray curseforge_key;
  // Short-lived anonymous translation session, owned by ContentCatalogService.
  QByteArray translation_token;
  qint64 translation_token_expires = 0;
};
/// Worker-only metadata/required-dependency resolver, bounded HTTP and JSON.
/// No downloads, disk access, UI state or global cache; failures throw.
QVariantMap request_content(const QVariantMap& query, const QStringList& order,
                            const ContentEndpoints& endpoints,
                            const std::shared_ptr<std::atomic_bool>& cancelled);
}  // namespace bugg
#endif
