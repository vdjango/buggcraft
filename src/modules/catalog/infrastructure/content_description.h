#ifndef BUGG_MODULES_CATALOG_INFRASTRUCTURE_CONTENT_DESCRIPTION_H_
#define BUGG_MODULES_CATALOG_INFRASTRUCTURE_CONTENT_DESCRIPTION_H_
#include <QUrl>
#include <QVariantList>

namespace bugg {
/// Worker-only Qt document conversion. No network or image decoding; bounded
/// text/image blocks are consumed by the virtualized shared document control.
QVariantList content_description(const QString& body, bool markdown, const QUrl& base);
/// Translate actual upstream slugs only; unknown categories retain their name.
QString content_category_name(const QString& slug, const QString& fallback);
}  // namespace bugg
#endif
