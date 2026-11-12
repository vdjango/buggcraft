#include "modules/catalog/infrastructure/game_catalog_provider.h"

#include <QCoreApplication>
#include <QHash>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QRegularExpression>
#include <QSet>
#include <QVersionNumber>
#include <QXmlStreamReader>
#include <algorithm>

#include "contracts/download_sources.h"
namespace bugg {
namespace {

bool stable_version(const QString& version) {
  return !version.contains(
      QRegularExpression("alpha|beta|snapshot|pre|rc", QRegularExpression::CaseInsensitiveOption));
}

// 比较数值主版本和预发布序号，避免 21.1.9 被排到 21.1.100 前面。
bool newer(const CatalogEntry& a, const CatalogEntry& b) {
  const auto av = QVersionNumber::fromString(a.id);
  const auto bv = QVersionNumber::fromString(b.id);
  const int order = QVersionNumber::compare(av, bv);
  if (order != 0) return order > 0;
  if (a.stable != b.stable) return a.stable;
  const auto tail_number = [](const QString& value) {
    return QRegularExpression("(\\d+)$").match(value).captured(1).toInt();
  };
  return tail_number(a.id) > tail_number(b.id);
}

// NeoForge 唯一的 MC 对应规则；26.x 必须包含补丁段，不能沿用 1.x 映射。
QString neo_prefix(const QString& game) {
  const auto v = QVersionNumber::fromString(game);
  if (v.toString() != game) return {};
  if (v.majorVersion() >= 26)
    return QString("%1.%2.%3.").arg(v.majorVersion()).arg(v.minorVersion()).arg(v.microVersion());
  if (v.majorVersion() == 1 &&
      (v.minorVersion() > 20 || (v.minorVersion() == 20 && v.microVersion() >= 2)))
    return QString("%1.%2.").arg(v.minorVersion()).arg(v.microVersion());
  return {};
}

class RemoteCatalogProvider final : public GameCatalogProvider {
 public:
  RemoteCatalogProvider(QString source, QUrl bugg_base)
      : source_(std::move(source)), bugg_base_(std::move(bugg_base)) {}
  QString id() const override { return source_; }
  QStringList blocked_redirect_hosts() const override {
    if (source_ != "BMCLAPI") return {};
    // 接受 BMCLAPI 分配的 HTTPS 分发节点；禁止重定向回发布者。
    return {"mojang.com",   "minecraft.net", "minecraftforge.net",
            "fabricmc.net", "quiltmc.org",   "neoforged.net"};
  }
  QUrl request_url(const CatalogQuery& query) const override {
    const bool mirror = source_ != "官方";
    const bool bugg = source_ == "BUGG";
    const auto game = QString::fromLatin1(QUrl::toPercentEncoding(query.game_version));
    const QString base = source_url(source_, {}, bugg_base_).toString();
    if (query.kind == "minecraft")
      return mirror ? QUrl(base + "/mc/game/version_manifest_v2.json")
                    : QUrl("https://piston-meta.mojang.com/mc/game/version_manifest_v2.json");
    if (query.kind == "fabric" || query.kind == "quilt") {
      const bool fabric = query.kind == "fabric";
      if (!fabric && source_ == "BMCLAPI") return QUrl(base + "/quilt-meta/v3/versions");
      const QString root =
          mirror ? base + (fabric ? "/fabric-meta" : "/quilt-meta")
                 : (fabric ? "https://meta.fabricmc.net" : "https://meta.quiltmc.org");
      return QUrl(root + (fabric ? "/v2" : "/v3") + "/versions/loader/" + game);
    }
    if (query.kind == "forge")
      return bugg     ? QUrl(base + "/maven/net/minecraftforge/forge/maven-metadata.xml")
             : mirror ? QUrl(base + "/forge/minecraft/" + game)
                      : QUrl(
                            "https://maven.minecraftforge.net/net/minecraftforge/forge/"
                            "maven-metadata.xml");
    if (query.kind == "neoforge") {
      if (source_ == "BMCLAPI") return QUrl(base + "/neoforge/list/" + game);
      const QString artifact = query.game_version == "1.20.1" ? "forge" : "neoforge";
      if (bugg)
        return QUrl(base + "/neoforge-maven/releases/net/neoforged/" + artifact +
                    "/maven-metadata.xml");
      return QUrl("https://maven.neoforged.net/releases/net/neoforged/" + artifact +
                  "/maven-metadata.xml");
    }
    return {};
  }

  CatalogResult parse(const CatalogQuery& query, const QByteArray& body) const override {
    CatalogResult result;
    result.source = id();
    QSet<QString> seen;
    const auto append = [&](const QString& version, bool stable, const QUrl& url = {},
                            const QString& sha1 = {}) {
      if (version.isEmpty() || seen.contains(version)) return;
      seen.insert(version);
      result.entries.push_back({version, stable, url, sha1});
    };
    if (source_ != "BMCLAPI" && (query.kind == "forge" || query.kind == "neoforge")) {
      QXmlStreamReader xml(body);
      bool metadata = false;
      const QString prefix = query.kind == "forge" || query.game_version == "1.20.1"
                                 ? query.game_version + "-"
                                 : neo_prefix(query.game_version);
      while (!xml.atEnd()) {
        xml.readNext();
        if (!xml.isStartElement()) continue;
        if (xml.name() == "metadata") metadata = true;
        if (xml.name() != "version") continue;
        const QString raw = xml.readElementText();
        if (prefix.isEmpty() || !raw.startsWith(prefix) ||
            raw.contains("snapshot", Qt::CaseInsensitive))
          continue;
        const QString version =
            raw.contains('-') && (query.kind == "forge" || query.game_version == "1.20.1")
                ? raw.mid(prefix.size())
                : raw;
        append(version, stable_version(version));
      }
      if (xml.hasError() || !metadata)
        result.error = QCoreApplication::translate("Bugg", "加载器目录不是有效的 Maven 元数据");
    } else {
      QJsonParseError error;
      const auto doc = QJsonDocument::fromJson(body, &error);
      if (error.error != QJsonParseError::NoError) {
        result.error = QCoreApplication::translate("Bugg", "目录数据格式错误");
        return result;
      }
      if (query.kind == "minecraft") {
        const auto root = doc.object();
        if (!root.value("versions").isArray() || !root.value("latest").isObject()) {
          result.error = QCoreApplication::translate("Bugg", "游戏目录缺少版本清单");
          return result;
        }
        result.preferred = root.value("latest").toObject().value("release").toString();
        for (const auto item : root.value("versions").toArray()) {
          const auto entry = item.toObject();
          if (entry.value("type").toString() != "release") continue;
          const QUrl url(entry.value("url").toString());
          if (url.scheme() != "https") continue;
          append(entry.value("id").toString(), true, url, entry.value("sha1").toString());
        }
        if (result.entries.empty() || !seen.contains(result.preferred))
          result.error = QCoreApplication::translate("Bugg", "游戏目录缺少最新正式版");
      } else if (query.kind == "quilt" && source_ == "BMCLAPI") {
        const auto root = doc.object();
        if (!root.value("loader").isArray() || !root.value("hashed").isArray()) {
          result.error = QCoreApplication::translate("Bugg", "Quilt 镜像目录缺少加载器或游戏映射");
          return result;
        }
        const auto mappings = root.value("hashed").toArray();
        const bool compatible =
            std::any_of(mappings.begin(), mappings.end(), [&](const auto& item) {
              return item.toObject().value("version").toString() == query.game_version;
            });
        if (compatible) {
          for (const auto item : root.value("loader").toArray()) {
            const auto version = item.toObject().value("version").toString();
            append(version, stable_version(version));
          }
          if (result.entries.isEmpty())
            result.error = QCoreApplication::translate("Bugg", "Quilt 镜像目录未包含有效版本");
        }
      } else {
        if (!doc.isArray()) {
          result.error = QCoreApplication::translate("Bugg", "加载器目录不是版本数组");
          return result;
        }
        for (const auto item : doc.array()) {
          const auto entry = item.toObject();
          if (query.kind == "fabric" || query.kind == "quilt") {
            const QString mapping = query.kind == "fabric" ? "intermediary" : "hashed";
            if (entry.value(mapping).toObject().value("version").toString() != query.game_version)
              continue;
            const auto loader = entry.value("loader").toObject();
            const QString version = loader.value("version").toString();
            append(version, loader.value("stable").toBool(stable_version(version)));
          } else {
            if (entry.value("mcversion").toString() != query.game_version) continue;
            const QString version = entry.value("version").toString();
            append(version, stable_version(version));
          }
        }
        if (!doc.array().isEmpty() && result.entries.isEmpty())
          result.error = QCoreApplication::translate("Bugg", "目录响应未包含匹配的加载器数据");
      }
    }
    if (query.kind != "minecraft") {
      std::stable_sort(result.entries.begin(), result.entries.end(), newer);
      const auto preferred = std::find_if(result.entries.begin(), result.entries.end(),
                                          [](const CatalogEntry& entry) { return entry.stable; });
      if (!result.entries.empty())
        result.preferred =
            preferred == result.entries.end() ? result.entries.front().id : preferred->id;
    }
    return result;
  }

 private:
  QString source_;
  QUrl bugg_base_;
};

}  // namespace

std::vector<std::shared_ptr<const GameCatalogProvider>> default_catalog_providers(
    const QStringList& order, const CatalogQuery& query, const QUrl& bugg_base) {
  static const QHash<QString, SourceCapability> capabilities{
      {"minecraft", SourceCapability::MinecraftCatalog},
      {"forge", SourceCapability::ForgeCatalog},
      {"neoforge", SourceCapability::NeoForgeCatalog},
      {"fabric", SourceCapability::FabricCatalog},
      {"quilt", SourceCapability::QuiltCatalog}};
  if (!capabilities.contains(query.kind)) return {};
  const auto plan = resolve_sources(order, capabilities.value(query.kind));
  if (!plan.error.isEmpty()) return {};
  std::vector<std::shared_ptr<const GameCatalogProvider>> providers;
  for (const auto& route : plan.routes)
    providers.push_back(std::make_shared<RemoteCatalogProvider>(route.actual, bugg_base));
  return providers;
}

}  // namespace bugg
