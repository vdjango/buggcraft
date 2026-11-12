#include "modules/catalog/infrastructure/content_provider.h"

#include <QCoreApplication>
#include <QCryptographicHash>
#include <QDateTime>
#include <QEventLoop>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QRegularExpression>
#include <QSet>
#include <QTimer>
#include <QUrlQuery>
#include <QUuid>
#include <QVersionNumber>
#include <algorithm>
#include <stdexcept>

#include "modules/catalog/infrastructure/content_description.h"
#include "platform/http/http_client.h"

static void initialize_shader_catalog() { Q_INIT_RESOURCE(bugg_shader_catalog); }

namespace bugg {
namespace {
[[noreturn]] void fail(const QString& message) { throw std::runtime_error(message.toStdString()); }
const QMap<QString, int> classes{
    {"mod", 6}, {"resourcepack", 12}, {"shader", 6552}, {"modpack", 4471}};
const QMap<QString, int> loaders{{"forge", 1}, {"fabric", 4}, {"quilt", 5}, {"neoforge", 6}};
QString identifier(const QVariant& value) {
  const auto id = value.toString();
  static const QRegularExpression valid("\\A[A-Za-z0-9_-]{1,96}\\z");
  if (!valid.match(id).hasMatch()) fail(QCoreApplication::translate("Bugg", "内容标识无效"));
  return id;
}
QStringList strings(const QJsonArray& values) {
  QStringList result;
  for (const auto& value : values) result.append(value.toString());
  return result;
}
QVariantMap translation_field(QString text, const QString& field, const QString& format = "plain") {
  text.replace("\r\n", "\n").replace('\r', '\n');
  const QJsonObject canonical{{"schema", "mc-text-v1"},
                              {"field", field},
                              {"source_language", "und"},
                              {"format", format},
                              {"text", text}};
  return {{"field", field},
          {"source_hash",
           "sha256:" + QString::fromLatin1(QCryptographicHash::hash(QJsonDocument(canonical).toJson(
                                                                        QJsonDocument::Compact),
                                                                    QCryptographicHash::Sha256)
                                               .toHex())}};
}
class ContentProvider {
 public:
  ContentProvider(QStringList order, ContentEndpoints endpoints,
                  std::shared_ptr<std::atomic_bool> cancelled)
      : order_(std::move(order)),
        endpoints_(std::move(endpoints)),
        cancelled_(std::move(cancelled)) {}
  QVariantMap run(const QVariantMap& query) {
    const auto publisher = query.value("publisher", "CurseForge").toString();
    const auto kind = query.value("kind", "mod").toString();
    if (!classes.contains(kind) || !QStringList{"CurseForge", "Modrinth"}.contains(publisher))
      fail(QCoreApplication::translate("Bugg", "不支持的内容类型或平台"));
    const auto operation = query.value("operation", "search").toString();
    if (operation == "bindings") {
      const auto targets = query.value("targets").toStringList();
      if (!order_.contains("BUGG") || targets.isEmpty() || targets.size() > 32)
        return {{"items", QVariantList{}}};
      HttpRequest request;
      request.url = source_url("BUGG", "/v1/catalog/dependency-bindings", endpoints_.bugg_base);
      QUrlQuery params;
      params.addQueryItem("targets", targets.join(','));
      params.addQueryItem("game", query.value("gameVersion").toString());
      params.addQueryItem("loader", query.value("loader").toString());
      request.url.setQuery(params);
      request.total_ms = 5000;
      const auto result = QJsonDocument::fromJson(exchange(request)).object();
      if (result["schema"] != "bugg-dependency-bindings-v1") fail("Invalid dependency bindings");
      return result.toVariantMap();
    }
    if (operation == "translations") return translations(query);
    if (operation == "categories") return categories(publisher, kind);
    if (operation == "search") return search(query, publisher, kind);
    auto selected_project = query.value("projectId");
    if (operation == "artifact" && publisher == "Modrinth" &&
        selected_project.toString().isEmpty()) {
      const auto release =
          get(publisher, "/version/" + identifier(query.value("versionId"))).toObject();
      selected_project = release["project_id"].toString();
    }
    const auto project_id = identifier(selected_project);
    if (operation == "detail") {
      auto result = versions(query, publisher, kind, project_id);
      result["project"] = project(publisher, kind, project_id, true);
      return result;
    }
    if (operation == "versions") return versions(query, publisher, kind, project_id);
    if (operation == "artifact") {
      const auto version =
          one_version(publisher, kind, project_id, identifier(query.value("versionId")));
      if (!compatible(version, query, kind) || !version.value("available").toBool())
        fail(QCoreApplication::translate("Bugg", "所选文件不兼容目标游戏"));
      auto files = version.value("files").toList();
      QVariantList primary;
      for (const auto& value : files)
        if (value.toMap().value("primary").toBool()) primary.append(value);
      if (primary.isEmpty() && !files.isEmpty()) primary.append(files.first());
      if (primary.size() != 1) fail("invalid_primary_file");
      auto file = primary.first().toMap();
      file["publisher"] = publisher;
      file["projectId"] = project_id;
      file["versionId"] = version.value("id");
      file["versionName"] = version.value("name");
      file["dependencies"] = version.value("dependencies");
      file["kind"] = kind;
      return {{"kind", kind}, {"files", QVariantList{file}}};
    }
    if (operation == "plan") {
      const auto version_id = identifier(query.value("versionId"));
      auto version = one_version(publisher, kind, project_id, version_id);
      QVariantList plan;
      QVariantList missing;
      QSet<QString> resolving;
      QHash<QString, QString> chosen;
      QVariantMap support;
      auto target = query;
      // The selected release is identified explicitly. Pagination belongs to
      // the original content listing, not to any core or dependency listing.
      target["offset"] = 0;
      if (kind == "shader") {
        if (target.value("gameVersion").toString().isEmpty())
          target["gameVersion"] = version.value("gameVersions").toStringList().value(0);
        if (!loaders.contains(target.value("loader").toString())) target["loader"] = "fabric";
        target["shaderLoaders"] = version.value("loaders");
        support = shader_support(target, resolving, chosen, plan, missing);
      }
      resolve(target, publisher, kind, project_id, version, resolving, chosen, plan, missing);
      const bool verified_core = std::any_of(plan.begin(), plan.end(), [](const QVariant& value) {
        return value.toMap().value("verifiedCore").toBool();
      });
      if ((kind == "shader" || verified_core) && !missing.isEmpty())
        fail(QCoreApplication::translate("Bugg", "光影的必要依赖未能匹配，请重试或更换目标游戏"));
      std::stable_partition(plan.begin(), plan.end(), [](const QVariant& item) {
        return !item.toMap().value("dependency").toBool();
      });
      return {{"files", plan},
              {"version", version},
              {"publisher", publisher},
              {"kind", kind},
              {"query", query},
              {"shaderSupport", support},
              {"missingDependencies", missing}};
    }
    fail(QCoreApplication::translate("Bugg", "不支持的内容查询"));
  }

 private:
  void check() const {
    if (cancelled_ && cancelled_->load())
      fail(QCoreApplication::translate("Bugg", "内容查询已取消"));
  }
  QByteArray exchange(const HttpRequest& request) {
    check();
    QEventLoop loop;
    QTimer timer;
    QByteArray bytes;
    QString error;
    const auto id = http_.request(request);
    const auto connection =
        QObject::connect(&http_, &HttpClient::response, &loop,
                         [&](quint64 current, const QByteArray& body, const QString& failure, int) {
                           if (current != id) return;
                           bytes = body;
                           error = failure;
                           loop.quit();
                         });
    QObject::connect(&timer, &QTimer::timeout, &loop, [&] {
      if (cancelled_ && cancelled_->load()) {
        http_.cancel(id);
        loop.quit();
      }
    });
    timer.start(50);
    loop.exec();
    QObject::disconnect(connection);
    check();
    if (!error.isEmpty()) fail(error);
    return bytes;
  }
  QJsonObject translation_json(const QString& path, const QJsonObject& payload,
                               const QByteArray& token = {}) {
    HttpRequest request;
    request.url = source_url("BUGG", "/v1/" + path, endpoints_.bugg_base);
    request.method = "POST";
    request.body = QJsonDocument(payload).toJson(QJsonDocument::Compact);
    request.headers["Content-Type"] = "application/json";
    if (!token.isEmpty()) {
      request.headers["Authorization"] = "Bearer " + token;
      request.headers["Idempotency-Key"] = QUuid::createUuid().toByteArray(QUuid::Id128);
    }
    QJsonParseError error;
    const auto document = QJsonDocument::fromJson(exchange(request), &error);
    if (error.error != QJsonParseError::NoError || !document.isObject())
      fail(QCoreApplication::translate("Bugg", "译文响应格式错误"));
    return document.object();
  }
  QVariantMap translations(const QVariantMap& query) {
    QJsonArray items;
    QHash<QString, QVariantMap> projects;
    for (const auto& value : query.value("items").toList()) {
      if (items.size() >= 20) break;
      const auto project = value.toMap();
      const auto id = identifier(project.value("id"));
      const auto fields = QJsonArray::fromVariantList(project.value("translationFields").toList());
      if (fields.isEmpty() || projects.contains(id)) continue;
      const auto provider = project.value("publisher").toString().toLower();
      if (provider != "modrinth" && provider != "curseforge") continue;
      projects[id] = project;
      items.append(QJsonObject{{"request_id", id},
                               {"resource", QJsonObject{{"provider", provider},
                                                        {"project_id", id},
                                                        {"entity_type", "project"},
                                                        {"entity_id", id}}},
                               {"fields", fields}});
    }
    QVariantMap translated;
    if (items.isEmpty()) return {{"translations", translated}};
    QJsonObject payload{
        {"target_language", "zh-Hans"}, {"profile", "minecraft-v1"}, {"items", items}};
    const auto resolved = translation_json("translations:resolve", payload)["results"].toArray();
    if (resolved.size() != items.size()) fail("Incomplete translation response");
    QJsonArray needed;
    bool pending = false;
    for (qsizetype index = 0; index < items.size(); ++index) {
      const auto expected = items[index].toObject();
      const auto item = resolved[index].toObject();
      if (item["resource"] != expected["resource"] || item["request_id"] != expected["request_id"])
        fail("Invalid translation resource identity");
      const auto id = expected["request_id"].toString();
      const auto fields = expected["fields"].toArray();
      QJsonArray missing;
      QVariantMap values;
      QSet<QString> accepted;
      for (const auto& value : item["fields"].toArray()) {
        const auto field = value.toObject();
        const auto name = field["field"].toString();
        QJsonObject wanted;
        for (const auto& candidate : fields)
          if (candidate.toObject()["field"] == name) wanted = candidate.toObject();
        if (wanted.isEmpty() || accepted.contains(name) ||
            field["requested_source_hash"] != wanted["source_hash"])
          fail("Invalid translation field identity");
        accepted.insert(name);
        if (field["is_current"].isBool() && !field["is_current"].toBool()) continue;
        if (field["state"] != "ready" || !field["matches_request"].toBool() ||
            !field["is_current"].toBool()) {
          if (field["state"] != "failed" && field["state"] != "blocked") {
            pending = true;
            missing.append(wanted);
          }
          continue;
        }
        auto translation = field["translation"].toObject();
        if (!translation.contains("text")) {
          const auto digest = translation["artifact"].toObject()["artifact_sha256"].toString();
          static const QRegularExpression valid("\\A[a-f0-9]{64}\\z");
          if (!valid.match(digest).hasMatch()) fail("Invalid translation artifact identity");
          HttpRequest request;
          request.url = source_url("BUGG", "/v1/artifacts/" + digest, endpoints_.bugg_base);
          const auto bytes = exchange(request);
          translation = QJsonDocument::fromJson(bytes).object();
          if (QCryptographicHash::hash(bytes, QCryptographicHash::Sha256).toHex() !=
                  digest.toLatin1() ||
              translation["source_hash"] != wanted["source_hash"] ||
              translation["resource"] != expected["resource"] || translation["field"] != name ||
              translation["target_language"] != "zh-Hans" ||
              translation["profile"] != "minecraft-v1")
            fail("Invalid translation artifact content");
        }
        const auto format = translation["format"].toString();
        if (!translation["text"].isString() ||
            !QStringList{"plain", "markdown", "html"}.contains(format))
          fail("Invalid translation text");
        const auto text = translation["text"].toString();
        if (name == "summary") values["description"] = text;
        if (name == "body")
          values["body"] = content_description(text, format != "html",
                                               QUrl(projects[id].value("website").toString()));
      }
      if (accepted.size() != fields.size()) fail("Incomplete translation fields");
      if (!values.isEmpty()) translated[id] = values;
      if (!missing.isEmpty()) {
        auto ensure = expected;
        ensure["fields"] = missing;
        needed.append(ensure);
      }
    }
    QVariantMap result{{"translations", translated}, {"pending", pending}};
    if (!needed.isEmpty() && query.value("ensure").toBool()) {
      result["_ensured"] = true;
      auto token = endpoints_.translation_token;
      auto expires = endpoints_.translation_token_expires;
      if (token.isEmpty() || expires <= QDateTime::currentSecsSinceEpoch()) {
        const auto session =
            translation_json("sessions/anonymous", {{"client_id", "bugg-native-launcher"}});
        token = session["access_token"].toString().toUtf8();
        expires = QDateTime::currentSecsSinceEpoch() +
                  qBound(0, session["expires_in"].toInt() - 60, 3540);
        if (token.isEmpty()) fail("Missing anonymous translation session");
      }
      payload["items"] = needed;
      payload["purpose"] = query.value("detail").toBool() ? "detail" : "visible_list";
      try {
        translation_json("translations:ensure", payload, token);
      } catch (const std::exception&) {
        check();
        result["ensureError"] = true;
      }
      result["_translationToken"] = token;
      result["_translationExpires"] = expires;
    }
    return result;
  }
  QJsonValue get(const QString& publisher, const QString& path, const QUrlQuery& parameters = {}) {
    check();
    const auto cache_key = publisher + "|" + path + "?" + parameters.toString(QUrl::FullyEncoded);
    if (metadata_cache_.contains(cache_key)) return metadata_cache_.value(cache_key);
    const auto capability = publisher == "CurseForge" ? SourceCapability::CurseForgeContent
                                                      : SourceCapability::ModrinthContent;
    const auto plan = resolve_sources(order_, capability);
    if (!plan.error.isEmpty()) fail(plan.error);
    QStringList errors;
    QList<QUrl> visited;
    for (const auto& route : plan.routes) {
      const auto base = publisher == "Modrinth" ? endpoints_.modrinth : endpoints_.curseforge;
      if (publisher == "CurseForge" && route.actual == "官方" &&
          endpoints_.curseforge_key.isEmpty() && path != "/categories") {
        errors.append(QCoreApplication::translate("Bugg", "CurseForge 官方接口未配置授权"));
        continue;
      }
      QUrl url = route.actual == "BUGG"
                     ? source_url("BUGG", "/v1/catalog/" + publisher.toLower() + path,
                                  endpoints_.bugg_base)
                     : QUrl(base.toString() + path);
      url.setQuery(parameters);
      if (visited.contains(url)) continue;
      visited.append(url);
      HttpRequest request;
      request.url = url;
      if (optional_search_) request.total_ms = 5000;
      request.maximum_bytes = 8 * 1024 * 1024;
      request.headers["Accept"] = "application/json";
      if (publisher == "CurseForge" && route.actual == "官方")
        request.headers["x-api-key"] = endpoints_.curseforge_key;
      QByteArray bytes;
      QString error;
      try {
        bytes = exchange(request);
      } catch (const std::exception& failure) {
        check();
        error = QString::fromUtf8(failure.what());
      }
      QJsonParseError parse;
      const auto document = QJsonDocument::fromJson(bytes, &parse);
      if (error.isEmpty() && parse.error == QJsonParseError::NoError && !document.isNull()) {
        const auto result =
            document.isArray() ? QJsonValue(document.array()) : QJsonValue(document.object());
        metadata_cache_[cache_key] = result;
        return result;
      }
      errors.append(error.isEmpty() ? QCoreApplication::translate("Bugg", "内容元数据格式错误")
                                    : error);
    }
    fail(QCoreApplication::translate("Bugg", "获取内容失败：") + errors.join(" · "));
  }
  QVariantMap normalize_project(const QJsonObject& item, const QString& publisher,
                                const QString& kind) {
    const bool mr = publisher == "Modrinth";
    if (mr && item["project_type"].toString() != kind)
      fail(QCoreApplication::translate("Bugg", "项目与所选内容类型不符"));
    if (!mr && (item["gameId"].toInt() != 432 || item["classId"].toInt() != classes.value(kind)))
      fail(QCoreApplication::translate("Bugg", "项目与所选内容类型不符"));
    QStringList authors;
    for (const auto& value : item["authors"].toArray())
      authors.append(value.toObject()["name"].toString());
    const auto id = mr ? item["project_id"].toString(item["id"].toString())
                       : QString::number(item["id"].toInteger());
    const auto summary = item[mr ? "description" : "summary"].toString();
    return {
        {"id", identifier(id)},
        {"publisher", publisher},
        {"kind", kind},
        {"title", item[mr ? "title" : "name"].toString()},
        {"description", summary},
        {"translationFields",
         summary.isEmpty() ? QVariantList{} : QVariantList{translation_field(summary, "summary")}},
        {"author", mr ? item["author"].toString() : authors.join(", ")},
        {"icon",
         mr ? item["icon_url"].toString() : item["logo"].toObject()["thumbnailUrl"].toString()},
        {"downloads", item[mr ? "downloads" : "downloadCount"].toDouble()},
        {"website", mr ? "https://modrinth.com/" + kind + '/' + item["slug"].toString(id)
                       : item["links"].toObject()["websiteUrl"].toString()}};
  }
  QVariantMap project(const QString& publisher, const QString& kind, const QString& id,
                      bool details = false) {
    const auto data = get(publisher, publisher == "Modrinth" ? "/project/" + id : "/mods/" + id);
    const auto item =
        publisher == "Modrinth" ? data.toObject() : data.toObject()["data"].toObject();
    const auto actual = kind.isEmpty()
                            ? (publisher == "Modrinth" ? item["project_type"].toString()
                                                       : classes.key(item["classId"].toInt()))
                            : kind;
    if (!classes.contains(actual)) fail(QCoreApplication::translate("Bugg", "不支持的依赖类型"));
    auto result = normalize_project(item, publisher, actual);
    if (details) {
      QString body = item["body"].toString();
      if (publisher == "CurseForge") {
        try {
          body = get(publisher, "/mods/" + id + "/description").toObject()["data"].toString();
        } catch (const std::exception& error) {
          check();
          result["bodyError"] = QString::fromUtf8(error.what());
        }
      }
      result["body"] = content_description(body, publisher == "Modrinth",
                                           QUrl(result.value("website").toString()));
      if (!body.isEmpty()) {
        auto fields = result.value("translationFields").toList();
        fields.append(
            translation_field(body, "body", publisher == "Modrinth" ? "markdown" : "html"));
        result["translationFields"] = fields;
      }
      QVariantList gallery;
      for (const auto& value :
           item[publisher == "Modrinth" ? "gallery" : "screenshots"].toArray()) {
        const auto picture = value.toObject();
        const QUrl url(picture["url"].toString());
        if (gallery.size() < 12 && url.scheme() == "https")
          gallery.append(
              QVariantMap{{"image", url.toString()}, {"title", picture["title"].toString()}});
      }
      result["gallery"] = gallery;
    }
    return result;
  }
  QVariantMap categories(const QString& publisher, const QString& kind) {
    const bool mr = publisher == "Modrinth";
    QUrlQuery parameters;
    if (!mr) {
      parameters.addQueryItem("gameId", "432");
    }
    const auto value = get(publisher, mr ? "/tag/category" : "/categories", parameters);
    const auto values = mr ? value.toArray() : value.toObject()["data"].toArray();
    QHash<qint64, QString> parent_names;
    if (!mr)
      for (const auto& value : values) {
        const auto item = value.toObject();
        if (!item["isClass"].toBool())
          parent_names.insert(
              item["id"].toInteger(),
              content_category_name(item["slug"].toString(), item["name"].toString()));
      }
    QSet<qint64> branches;
    if (!mr)
      for (const auto& value : values) {
        const auto parent = value.toObject()["parentCategoryId"].toInteger();
        if (parent_names.contains(parent)) branches.insert(parent);
      }
    QVariantList result;
    for (const auto& value : values) {
      const auto item = value.toObject();
      if (mr ? item["project_type"].toString() != kind
             : item["classId"].toInt() != classes.value(kind) || item["isClass"].toBool())
        continue;
      const auto slug = item[mr ? "name" : "slug"].toString();
      const auto name = mr ? slug : item["name"].toString();
      auto label = content_category_name(slug, name);
      const auto general = QCoreApplication::translate("Bugg", "内容类型");
      auto group = mr ? content_category_name(item["header"].toString(), general)
                      : parent_names.value(item["parentCategoryId"].toInteger(), general);
      if (!mr && branches.contains(item["id"].toInteger())) {
        group = label;
        label = QCoreApplication::translate("Bugg", "全部%1").arg(label);
      }
      result.append(QVariantMap{
          {"id", mr ? slug : QString::number(item["id"].toInteger())},
          {"name", label},
          {"group", group},
          {"groupOrder", group == general ? 0 : 1},
          {"optionOrder", !mr && branches.contains(item["id"].toInteger()) ? 0 : 1},
          {"slug", slug},
          {"parentId", mr ? QString{} : QString::number(item["parentCategoryId"].toInteger())}});
      if (result.size() >= 256) break;
    }
    std::stable_sort(result.begin(), result.end(), [](const QVariant& left, const QVariant& right) {
      const auto a = left.toMap(), b = right.toMap();
      if (a.value("groupOrder") != b.value("groupOrder"))
        return a.value("groupOrder").toInt() < b.value("groupOrder").toInt();
      const auto group =
          QString::localeAwareCompare(a.value("group").toString(), b.value("group").toString());
      if (group != 0) return group < 0;
      if (a.value("optionOrder") != b.value("optionOrder"))
        return a.value("optionOrder").toInt() < b.value("optionOrder").toInt();
      return QString::localeAwareCompare(a.value("name").toString(), b.value("name").toString()) <
             0;
    });
    return {{"categories", result}};
  }
  QVariantMap search(const QVariantMap& query, const QString& publisher, const QString& kind) {
    const int offset = qBound(0, query.value("offset").toInt(), 10000);
    QUrlQuery params;
    if (publisher == "Modrinth") {
      params.addQueryItem("query", query.value("query").toString().left(200));
      params.addQueryItem("limit", "20");
      params.addQueryItem("offset", QString::number(offset));
      QJsonArray facets;
      facets.append(QJsonArray{"project_type:" + kind});
      if (!query.value("category").toString().isEmpty())
        facets.append(QJsonArray{"categories:" + identifier(query.value("category"))});
      if (!query.value("gameVersion").toString().isEmpty())
        facets.append(QJsonArray{"versions:" + query.value("gameVersion").toString()});
      if ((kind == "mod" || kind == "modpack") &&
          loaders.contains(query.value("loader").toString()))
        facets.append(QJsonArray{"categories:" + query.value("loader").toString()});
      params.addQueryItem("facets",
                          QString::fromUtf8(QJsonDocument(facets).toJson(QJsonDocument::Compact)));
      params.addQueryItem("index",
                          query.value("query").toString().isEmpty() ? "downloads" : "relevance");
    } else {
      params.addQueryItem("gameId", "432");
      params.addQueryItem("classId", QString::number(classes.value(kind)));
      params.addQueryItem("searchFilter", query.value("query").toString().left(200));
      params.addQueryItem("pageSize", "20");
      params.addQueryItem("index", QString::number(offset));
      params.addQueryItem("sortField", "2");
      params.addQueryItem("sortOrder", "desc");
      filters(params, query, false, kind);
    }
    const auto category = query.value("category").toString();
    if (publisher == "CurseForge" && !category.isEmpty())
      params.addQueryItem("categoryId", identifier(category));
    const auto data =
        get(publisher, publisher == "Modrinth" ? "/search" : "/mods/search", params).toObject();
    const auto entries = data[publisher == "Modrinth" ? "hits" : "data"];
    if (!entries.isArray()) fail(QCoreApplication::translate("Bugg", "内容搜索结果无效"));
    const auto values = entries.toArray();
    const int total = publisher == "Modrinth" ? data["total_hits"].toInt()
                                              : data["pagination"].toObject()["totalCount"].toInt();
    QVariantList items;
    for (int i = 0; i < qMin(20, int(values.size())); ++i)
      items.append(normalize_project(values[i].toObject(), publisher, kind));
    return {{"items", items},
            {"total", total},
            {"offset", offset},
            {"hasMore", offset + values.size() < qMin(total, 10000)},
            {"publisher", publisher}};
  }

  void filters(QUrlQuery& params, const QVariantMap& query, bool mr, const QString& kind) {
    const auto game = query.value("gameVersion").toString();
    const auto loader = query.value("loader").toString();
    const auto array = [](const QString& value) {
      return QString::fromUtf8(QJsonDocument(QJsonArray{value}).toJson(QJsonDocument::Compact));
    };
    if (!game.isEmpty())
      params.addQueryItem(mr ? "game_versions" : "gameVersion", mr ? array(game) : game);
    if ((kind == "mod" || kind == "modpack") && loaders.contains(loader))
      params.addQueryItem(mr ? "loaders" : "modLoaderType",
                          mr ? array(loader) : QString::number(loaders.value(loader)));
  }
  QVariantMap normalize_version(const QJsonObject& item, const QString& publisher,
                                const QString& kind, const QString& project_id) {
    const bool mr = publisher == "Modrinth";
    const auto id =
        identifier(mr ? item["id"].toVariant() : QVariant(QString::number(item["id"].toInteger())));
    QVariantList files;
    if (mr) {
      if (item["project_id"].toString() != project_id)
        fail(QCoreApplication::translate("Bugg", "版本不属于所选项目"));
      for (const auto& value : item["files"].toArray())
        files.append(value.toObject().toVariantMap());
    } else {
      if (QString::number(item["modId"].toInteger()) != project_id)
        fail(QCoreApplication::translate("Bugg", "文件不属于所选项目"));
      QString sha1;
      for (const auto& hash : item["hashes"].toArray())
        if (hash.toObject()["algo"].toInt() == 1) sha1 = hash.toObject()["value"].toString();
      const auto url = curseforge_file_url(item["id"].toInteger(), item["fileName"].toString(),
                                           item["downloadUrl"].toString());
      files.append(QVariantMap{{"url", url},
                               {"filename", item["fileName"].toString()},
                               {"size", item["fileLength"].toInteger()},
                               {"hashes", QVariantMap{{"sha1", sha1}}},
                               {"primary", true}});
    }
    QVariantList dependencies;
    for (const auto& value : item["dependencies"].toArray()) {
      const auto dep = value.toObject();
      const auto type = mr                                 ? dep["dependency_type"].toString()
                        : dep["relationType"].toInt() == 3 ? "required"
                        : dep["relationType"].toInt() == 5 ? "incompatible"
                                                           : "optional";
      dependencies.append(QVariantMap{{"type", type},
                                      {"projectId", mr ? dep["project_id"].toString()
                                                       : QString::number(dep["modId"].toInteger())},
                                      {"versionId", dep["version_id"].toString()}});
    }
    QStringList game_versions, loader_names;
    for (const auto& tag : strings(item[mr ? "game_versions" : "gameVersions"].toArray())) {
      if (loaders.contains(tag.toLower()) ||
          kind == "shader" && QStringList{"iris", "optifine"}.contains(tag.toLower()))
        loader_names.append(tag.toLower());
      else
        game_versions.append(tag);
    }
    if (mr) loader_names = strings(item["loaders"].toArray());
    const bool available =
        mr || (!item["isServerPack"].toBool() && !item["isEarlyAccessContent"].toBool() &&
               item["isAvailable"].toBool(true));
    return {{"id", id},
            {"projectId", project_id},
            {"publisher", publisher},
            {"kind", kind},
            {"name", item[mr ? "name" : "displayName"].toString()},
            {"channel", mr                                 ? item["version_type"].toString()
                        : item["releaseType"].toInt() == 1 ? QString("release")
                                                           : QString("beta")},
            {"gameVersions", game_versions},
            {"loaders", loader_names},
            {"files", files},
            {"dependencies", dependencies},
            {"available", available}};
  }
  bool compatible(const QVariantMap& version, const QVariantMap& query, const QString& kind) {
    const auto game = query.value("gameVersion").toString();
    const auto loader = query.value("loader").toString();
    return compatibility_error(version, query).isEmpty() &&
           (game.isEmpty() || version.value("gameVersions").toStringList().contains(game)) &&
           (!(kind == "mod" || kind == "modpack") || loader.isEmpty() ||
            version.value("loaders").toStringList().contains(loader));
  }
  // Exceptions have an exact publisher release identity and an upstream source.
  // Never infer compatibility from a filename, a numeric MC range, or "latest".
  QString compatibility_error(const QVariantMap& version, const QVariantMap& query) {
    for (const auto& entry : shader_manifest_["compatibilityRules"].toArray()) {
      const auto rule = entry.toObject();
      if (rule["publisher"].toString() != version.value("publisher").toString() ||
          rule["projectId"].toString() != version.value("projectId").toString() ||
          rule["versionId"].toString() != version.value("id").toString() ||
          rule["gameVersion"].toString() != query.value("gameVersion").toString() ||
          rule["loader"].toString() != query.value("loader").toString())
        continue;
      const auto minimum = QVersionNumber::fromString(rule["minLoaderVersion"].toString());
      const auto actual = QVersionNumber::fromString(query.value("loaderVersion").toString());
      if (!minimum.isNull() && !actual.isNull() && QVersionNumber::compare(actual, minimum) >= 0)
        return rule["reason"].toString();
    }
    return {};
  }
  void source_dependencies(QVariantList& versions, const QString& publisher) {
    if (versions.isEmpty() || !source_releases_available_ || !order_.contains("BUGG")) return;
    QJsonArray identities;
    for (const auto& value : versions) {
      const auto version = value.toMap();
      identities.append(QJsonObject{{"provider", publisher.toLower()},
                                    {"project_id", version.value("projectId").toString()},
                                    {"release_id", version.value("id").toString()}});
    }
    try {
      HttpRequest request;
      request.url = source_url("BUGG", "/api/v1/dependency-releases/query", endpoints_.bugg_base);
      request.method = "POST";
      request.total_ms = 5000;
      request.headers["Content-Type"] = "application/json";
      request.body =
          QJsonDocument(QJsonObject{{"releases", identities}}).toJson(QJsonDocument::Compact);
      const auto response = QJsonDocument::fromJson(exchange(request)).object();
      const auto items = response["items"].toArray();
      if (response["schema"] != "bugg-dependency-releases-v1" || items.size() != versions.size()) {
        source_releases_available_ = false;
        return;
      }
      for (qsizetype i = 0; i < items.size(); ++i) {
        const auto item = items[i].toObject();
        if (item["identity"].toObject() != identities[i].toObject()) continue;
        auto version = versions[i].toMap();
        const auto files = version.value("files").toList();
        for (const auto& snapshot : item["snapshots"].toArray()) {
          const auto observation = snapshot.toObject()["observation"].toObject();
          const auto algorithm = observation["algorithm"].toString();
          const auto digest = observation["digest"].toString();
          bool same_file = false;
          for (const auto& file : files)
            same_file |= file.toMap().value("hashes").toMap().value(algorithm).toString().compare(
                             digest, Qt::CaseInsensitive) == 0 &&
                         !digest.isEmpty();
          if (!same_file) continue;
          const auto verified = snapshot.toObject()["verified_sha256"].toString();
          if (verified.size() == 64) {
            auto files = version.value("files").toList();
            for (auto& value : files) {
              auto file = value.toMap();
              auto hashes = file.value("hashes").toMap();
              if (hashes.value(algorithm).toString().compare(digest, Qt::CaseInsensitive) == 0) {
                hashes["sha256"] = verified;
                file["hashes"] = hashes;
                value = file;
              }
            }
            version["files"] = files;
          }
          QVariantList dependencies;
          for (const auto& entry : observation["dependencies"].toArray()) {
            const auto dep = entry.toObject();
            const bool mr = publisher == "Modrinth";
            const auto type = mr                                 ? dep["dependency_type"].toString()
                              : dep["relationType"].toInt() == 3 ? "required"
                              : dep["relationType"].toInt() == 5 ? "incompatible"
                                                                 : "optional";
            dependencies.append(
                QVariantMap{{"type", type},
                            {"projectId", mr ? dep["project_id"].toString()
                                             : QString::number(dep["modId"].toInteger())},
                            {"versionId", dep["version_id"].toString()}});
          }
          version["dependencies"] = dependencies;
          version["dependencySource"] = "bugg";
          versions[i] = version;
          break;
        }
      }
    } catch (const std::exception&) {
      check();
      source_releases_available_ = false;
    }
  }
  QVariantMap versions(const QVariantMap& query, const QString& publisher, const QString& kind,
                       const QString& project_id) {
    const bool mr = publisher == "Modrinth";
    QUrlQuery params;
    filters(params, query, mr, kind);
    const int offset = qBound(0, query.value("offset").toInt(), 10000);
    if (!mr) {
      params.addQueryItem("pageSize", "20");
      params.addQueryItem("index", QString::number(offset));
    }
    QJsonValue data;
    try {
      data = get(publisher,
                 mr ? "/project/" + project_id + "/version" : "/mods/" + project_id + "/files",
                 params);
    } catch (const std::exception&) {
      check();
      if (kind != "mod" || !order_.contains("BUGG") ||
          query.value("gameVersion").toString().isEmpty() ||
          !loaders.contains(query.value("loader").toString()))
        throw;
      HttpRequest request;
      request.url = source_url("BUGG", "/api/v1/dependency-releases/catalog", endpoints_.bugg_base);
      request.method = "POST";
      request.total_ms = 5000;
      request.headers["Content-Type"] = "application/json";
      request.body =
          QJsonDocument(QJsonObject{{"provider", publisher.toLower()},
                                    {"project_id", project_id},
                                    {"game_version", query.value("gameVersion").toString()},
                                    {"loader", query.value("loader").toString()},
                                    {"offset", offset}})
              .toJson(QJsonDocument::Compact);
      const auto stored = QJsonDocument::fromJson(exchange(request)).object();
      if (stored["schema"] != "bugg-dependency-catalog-v1")
        fail(QCoreApplication::translate("Bugg", "版本目录暂不可用"));
      QVariantList items;
      for (const auto& entry : stored["items"].toArray()) {
        const auto raw = entry.toObject()["observation"].toObject()["publisher_data"].toObject();
        const auto version = normalize_version(raw, publisher, kind, project_id);
        if (compatible(version, query, kind) && version.value("available").toBool())
          items.append(version);
      }
      source_dependencies(items, publisher);
      return {{"versions", items},
              {"offset", offset},
              {"total", stored["total"].toInt()},
              {"hasMore", stored["has_more"].toBool()},
              {"partial", true}};
    }
    const auto array = mr ? data : data.toObject()["data"];
    if (!array.isArray()) fail(QCoreApplication::translate("Bugg", "内容版本列表无效"));
    QVariantList items;
    QString rejected_reason;
    const auto values = array.toArray();
    const int begin = mr ? qMin(offset, int(values.size())) : 0;
    const int end = mr ? qMin(begin + 20, int(values.size())) : int(values.size());
    for (int i = begin; i < end; ++i) {
      auto version = normalize_version(values[i].toObject(), publisher, kind, project_id);
      if (compatible(version, query, kind) && version.value("available").toBool())
        items.append(version);
      else if (rejected_reason.isEmpty())
        rejected_reason = compatibility_error(version, query);
    }
    if (kind == "mod") source_dependencies(items, publisher);
    const int total =
        mr ? int(values.size()) : data.toObject()["pagination"].toObject()["totalCount"].toInt();
    return {{"versions", items},
            {"offset", offset},
            {"total", total},
            {"compatibilityError", items.isEmpty() ? rejected_reason : QString{}},
            {"hasMore", offset + (end - begin) < total}};
  }
  QVariantMap one_version(const QString& publisher, const QString& kind, const QString& project_id,
                          const QString& id) {
    if (kind == "mod" && source_releases_available_ && order_.contains("BUGG")) {
      try {
        HttpRequest request;
        request.url = source_url("BUGG", "/api/v1/dependency-releases/query", endpoints_.bugg_base);
        request.method = "POST";
        request.total_ms = 5000;
        request.headers["Content-Type"] = "application/json";
        const QJsonObject identity{
            {"provider", publisher.toLower()}, {"project_id", project_id}, {"release_id", id}};
        request.body = QJsonDocument(QJsonObject{{"releases", QJsonArray{identity}}})
                           .toJson(QJsonDocument::Compact);
        const auto result = QJsonDocument::fromJson(exchange(request)).object();
        const auto items = result["items"].toArray();
        if (result["schema"] == "bugg-dependency-releases-v1" && items.size() == 1 &&
            items[0].toObject()["identity"].toObject() == identity) {
          for (const auto& entry : items[0].toObject()["snapshots"].toArray()) {
            const auto observation = entry.toObject()["observation"].toObject();
            const auto raw = observation["publisher_data"].toObject();
            if (raw.isEmpty()) continue;
            auto candidate = normalize_version(raw, publisher, kind, project_id);
            if (candidate.value("id").toString() != id) continue;
            bool matches = false;
            for (const auto& file : candidate.value("files").toList())
              matches |=
                  !observation["digest"].toString().isEmpty() &&
                  file.toMap()
                          .value("hashes")
                          .toMap()
                          .value(observation["algorithm"].toString())
                          .toString()
                          .compare(observation["digest"].toString(), Qt::CaseInsensitive) == 0;
            if (matches) {
              QVariantList values{candidate};
              source_dependencies(values, publisher);
              return values.first().toMap();
            }
          }
        } else {
          source_releases_available_ = false;
        }
      } catch (const std::exception&) {
        check();
        source_releases_available_ = false;
      }
    }
    const auto value =
        get(publisher,
            publisher == "Modrinth" ? "/version/" + id : "/mods/" + project_id + "/files/" + id);
    auto version = normalize_version(
        publisher == "Modrinth" ? value.toObject() : value.toObject()["data"].toObject(), publisher,
        kind, project_id);
    if (kind == "mod") {
      QVariantList values{version};
      source_dependencies(values, publisher);
      version = values.first().toMap();
    }
    return version;
  }
  QJsonObject shader_manifest() {
    if (!shader_manifest_.isEmpty()) return shader_manifest_;
    HttpRequest request;
    request.url = source_url("BUGG", "/v1/catalog/shader-runtimes", endpoints_.bugg_base);
    QJsonObject manifest;
    try {
      manifest = QJsonDocument::fromJson(exchange(request)).object();
    } catch (const std::exception&) {
      check();
    }
    if (manifest["schema"] != "bugg-shader-support-v1") {
      initialize_shader_catalog();
      QFile local(":/bugg/shader-runtimes.json");
      if (local.open(QIODevice::ReadOnly))
        manifest = QJsonDocument::fromJson(local.readAll()).object();
    }
    const auto runtimes = manifest["runtimes"].toArray();
    if (manifest["schema"] != "bugg-shader-support-v1" || runtimes.isEmpty() ||
        runtimes.size() > 8 || manifest["compatibilityRules"].toArray().size() > 128)
      fail(QCoreApplication::translate("Bugg", "光影核心清单暂不可用，请重试"));
    shader_manifest_ = manifest;
    return manifest;
  }
  QVariantMap shader_support(const QVariantMap& query, QSet<QString>& resolving,
                             QHash<QString, QString>& chosen, QVariantList& plan,
                             QVariantList& missing) {
    const auto runtimes = shader_manifest()["runtimes"].toArray();
    const auto shader_loaders = query.value("shaderLoaders").toStringList();
    if (!shader_loaders.isEmpty() && !shader_loaders.contains("iris"))
      fail(QCoreApplication::translate(
          "Bugg", "此光影文件未声明支持 Iris，不能自动搭配 Iris/Oculus；请选择支持的光影版本"));
    auto target = query;
    const auto loader = query.value("loader").toString().isEmpty()
                            ? QString("fabric")
                            : query.value("loader").toString();
    target["loader"] = loader;
    if (query.value("gameVersion").toString().isEmpty())
      fail(QCoreApplication::translate("Bugg", "请先选择目标游戏，再匹配光影核心"));
    const auto installed_hash = query.value("shaderRuntimeHash").toString();
    QVariantMap installed;
    if (!installed_hash.isEmpty()) {
      static const QRegularExpression hash("\\A[a-f0-9]{40}\\z");
      if (!hash.match(installed_hash).hasMatch()) fail("Invalid shader runtime hash");
      const auto installed_cf_project = query.value("shaderRuntimeCurseForgeProject").toString();
      if (!installed_cf_project.isEmpty()) {
        bool known = false;
        for (const auto& value : runtimes)
          known |= value.toObject()["curseforgeProjectId"].toString() == installed_cf_project;
        if (!known) fail("Unknown shader runtime project");
        installed = one_version("CurseForge", "mod", identifier(installed_cf_project),
                                identifier(query.value("shaderRuntimeCurseForgeVersion")));
      } else {
        const auto raw = get("Modrinth", "/version_file/" + installed_hash).toObject();
        installed =
            normalize_version(raw, "Modrinth", "mod", identifier(raw["project_id"].toVariant()));
      }
      bool matches = false;
      for (const auto& file : installed.value("files").toList())
        matches |= file.toMap().value("hashes").toMap().value("sha1").toString() == installed_hash;
      if (!matches) fail(QCoreApplication::translate("Bugg", "无法核验已有光影核心，请检查该文件"));
    }
    QString rejected_reason;
    QVariantList choices;
    QVariantMap selected_support;
    QVariantList selected_plan, selected_missing;
    QHash<QString, QString> selected_chosen;
    QSet<QString> selected_resolving;
    bool incomplete = false;
    const auto requested = query.value("shaderRuntimeChoice").toString();
    for (const auto& value : runtimes) {
      const auto candidate = value.toObject().toVariantMap();
      if (!candidate.value("loaders").toStringList().contains(loader)) continue;
      auto provider = candidate.value("publisher").toString();
      if (provider != "Modrinth") fail("Unsupported shader runtime publisher");
      auto project_id = identifier(candidate.value("projectId"));
      QVariantList available;
      if (!installed.isEmpty()) {
        if (installed.value("publisher") == "CurseForge") {
          if (installed.value("projectId") != candidate.value("curseforgeProjectId")) continue;
          provider = "CurseForge";
          project_id = installed.value("projectId").toString();
        } else if (installed.value("projectId") != project_id) {
          continue;
        }
        const auto reason = compatibility_error(installed, target);
        if (!reason.isEmpty()) fail(reason);
        if (!compatible(installed, target, "mod"))
          fail(QCoreApplication::translate("Bugg",
                                           "已有光影核心不兼容当前游戏或加载器，请先处理冲突"));
        available.append(installed);
      } else {
        const QList<QPair<QString, QString>> sources{
            {provider, project_id},
            {"CurseForge", candidate.value("curseforgeProjectId").toString()}};
        for (const auto& source : sources) {
          if (source.second.isEmpty()) continue;
          optional_search_ = source.first == "CurseForge";
          QSet<QString> seen;
          for (int page = 0; page < 50; ++page) {
            try {
              auto page_query = target;
              page_query["offset"] = page * 20;
              const auto listing =
                  versions(page_query, source.first, "mod", identifier(source.second));
              incomplete |= listing.value("partial").toBool();
              if (rejected_reason.isEmpty())
                rejected_reason = listing.value("compatibilityError").toString();
              for (const auto& item : listing.value("versions").toList()) {
                const auto id = item.toMap().value("id").toString();
                if (!seen.contains(id)) available.append(item);
                seen.insert(id);
              }
              if (!listing.value("hasMore").toBool()) break;
              if (page == 49) incomplete = true;
            } catch (const std::exception&) {
              check();
              incomplete = true;
              break;
            }
          }
          optional_search_ = false;
        }
        if (available.isEmpty()) continue;
      }
      // An empty platform list does not prove that the JAR has no dependencies.
      if (available.size() > 1) {
        QVariantList ordered;
        for (const bool require_dependencies : {true, false})
          for (int i = 0; i < available.size(); ++i) {
            bool has_required = false;
            for (const auto& item : available.at(i).toMap().value("dependencies").toList())
              has_required |= item.toMap().value("type") == "required";
            if (has_required == require_dependencies) ordered.append(available.at(i));
          }
        available = ordered;
      }
      for (const auto& entry : available) {
        auto version = entry.toMap();
        provider = version.value("publisher").toString();
        project_id = version.value("projectId").toString();
        const auto choice_id = provider + "/" + project_id + "/" + version.value("id").toString();
        version["title"] = candidate.value("name");
        const auto old_resolving = resolving;
        const auto old_chosen = chosen;
        const auto old_plan = plan;
        const auto old_missing = missing;
        const auto old_dependency_count = dependency_count_;
        QString failure;
        try {
          resolve(target, provider, "mod", project_id, version, resolving, chosen, plan, missing);
          if (missing.size() != old_missing.size()) {
            const auto dependency = missing.at(old_missing.size()).toMap();
            failure = QCoreApplication::translate("Bugg", "光影核心的必要依赖未能匹配：") +
                      dependency.value("title").toString() + " — " +
                      dependency.value("reason").toString();
          }
        } catch (const std::exception& error) {
          check();
          failure = QString::fromUtf8(error.what());
        }
        if (!failure.isEmpty()) {
          if (rejected_reason.isEmpty()) rejected_reason = failure;
          if (requested == choice_id) rejected_reason = failure;
        } else {
          for (auto index = old_plan.size(); index < plan.size(); ++index) {
            auto file = plan[index].toMap();
            file["dependency"] = true;
            file["prerequisite"] = true;
            plan[index] = file;
          }
          const auto review = shader_review(target, plan.mid(old_plan.size()), provider, project_id,
                                            version.value("id").toString());
          const auto review_state = review.value("state").toString();
          if (review_state == "unavailable") {
            resolving = old_resolving;
            chosen = old_chosen;
            plan = old_plan;
            missing = old_missing;
            dependency_count_ = old_dependency_count;
            rejected_reason = review.value("note").toString();
            continue;
          }
          const bool dependency_unknown = version.value("dependencies").toList().isEmpty();
          choices.append(QVariantMap{{"id", choice_id},
                                     {"name", candidate.value("name").toString() + " · " +
                                                  version.value("name").toString()},
                                     {"publisher", provider},
                                     {"status", review_state == "available" ? "reviewed_available"
                                                : dependency_unknown        ? "dependency_unknown"
                                                                            : "declared"}});
          if ((requested.isEmpty() && (selected_support.isEmpty() ||
                                       review_state == "available" &&
                                           selected_support.value("reviewState") != "available")) ||
              requested == choice_id) {
            selected_support = {{"id", candidate.value("id")},
                                {"name", candidate.value("name")},
                                {"version", version.value("name")},
                                {"loader", loader},
                                {"choice", choice_id},
                                {"reviewState", review_state},
                                {"runtimes", runtimes.toVariantList()},
                                {"installed", !installed.isEmpty()}};
            selected_plan = plan;
            selected_missing = missing;
            selected_chosen = chosen;
            selected_resolving = resolving;
          }
        }
        resolving = old_resolving;
        chosen = old_chosen;
        plan = old_plan;
        missing = old_missing;
        dependency_count_ = old_dependency_count;
      }
      if (!installed.isEmpty()) break;
    }
    if (!selected_support.isEmpty()) {
      selected_support["choices"] = choices;
      selected_support["choicesIncomplete"] = incomplete;
      resolving = selected_resolving;
      chosen = selected_chosen;
      plan = selected_plan;
      missing = selected_missing;
      return selected_support;
    }
    if (!requested.isEmpty() && rejected_reason.isEmpty())
      fail(QCoreApplication::translate("Bugg", "所选光影核心版本不在当前候选中"));
    if (!rejected_reason.isEmpty()) fail(rejected_reason);
    fail(QCoreApplication::translate("Bugg",
                                     "当前游戏版本与加载器暂无可用的光影核心，请更换目标游戏"));
  }
  QVariantMap shader_review(const QVariantMap& query, const QVariantList& plan,
                            const QString& publisher, const QString& project,
                            const QString& release) {
    if (!order_.contains("BUGG")) return {};
    if (!shader_reviews_loaded_) {
      shader_reviews_loaded_ = true;
      try {
        HttpRequest request;
        request.url = source_url("BUGG", "/api/v1/shader-compatibility", endpoints_.bugg_base);
        QUrlQuery params;
        params.addQueryItem("game_version", query.value("gameVersion").toString());
        params.addQueryItem("loader", query.value("loader").toString());
        params.addQueryItem("loader_version", query.value("loaderVersion").toString());
        request.url.setQuery(params);
        request.total_ms = 5000;
        const auto result = QJsonDocument::fromJson(exchange(request)).object();
        if (result["schema"] == "bugg-shader-compatibility-v1")
          shader_reviews_ = result["items"].toArray();
      } catch (const std::exception&) {
        check();
      }
    }
    QSet<QString> actual;
    QString core_hash;
    for (const auto& value : plan) {
      const auto file = value.toMap();
      const auto digest = file.value("hashes").toMap().value("sha256").toString();
      if (digest.size() != 64) return {};
      actual.insert(file.value("publisher").toString().toLower() + "/" +
                    file.value("projectId").toString() + "/" + file.value("versionId").toString() +
                    "/" + digest);
      if (file.value("publisher") == publisher && file.value("projectId") == project &&
          file.value("versionId") == release)
        core_hash = digest;
    }
    if (core_hash.isEmpty()) return {};
    const auto file_key = [](const QJsonObject& file) {
      return file["provider"].toString() + "/" + file["project_id"].toString() + "/" +
             file["release_id"].toString() + "/" + file["sha256"].toString();
    };
    for (const auto& value : shader_reviews_) {
      const auto review = value.toObject();
      if (review["game_version"].toString() != query.value("gameVersion").toString() ||
          review["loader"].toString() != query.value("loader").toString() ||
          review["loader_version"].toString() != query.value("loaderVersion").toString())
        continue;
      const auto core = review["core"].toObject();
      if (core["provider"].toString() != publisher.toLower() ||
          core["project_id"].toString() != project || core["release_id"].toString() != release ||
          core["sha256"].toString() != core_hash)
        continue;
      QSet<QString> expected{file_key(core)};
      for (const auto& dep : review["dependencies"].toArray())
        expected.insert(file_key(dep.toObject()));
      if (actual == expected) return review.toVariantMap();
    }
    return {};
  }
  QVariantMap core_release(QVariantMap version, const QVariantMap& query) {
    const auto publisher = version.value("publisher").toString();
    QString counterpart;
    bool known = false;
    for (const auto& entry : shader_manifest()["runtimes"].toArray()) {
      const auto runtime = entry.toObject();
      const auto project = publisher == "Modrinth" ? runtime["projectId"].toString()
                                                   : runtime["curseforgeProjectId"].toString();
      if (project != version.value("projectId").toString()) continue;
      known = true;
      counterpart = runtime["projectId"].toString();
      break;
    }
    if (!known) return version;
    version["verifiedCore"] = true;
    if (publisher != "CurseForge" || counterpart.isEmpty()) return version;
    QString digest;
    for (const auto& value : version.value("files").toList()) {
      const auto file = value.toMap();
      if (file.value("primary").toBool())
        digest = file.value("hashes").toMap().value("sha1").toString();
    }
    if (digest.isEmpty()) return version;
    QJsonObject raw;
    try {
      raw = get("Modrinth", "/version_file/" + digest).toObject();
    } catch (const std::exception&) {
      check();
      return version;
    }
    auto mapped = normalize_version(raw, "Modrinth", "mod", counterpart);
    bool matches = false;
    for (const auto& value : mapped.value("files").toList())
      matches |= value.toMap().value("hashes").toMap().value("sha1").toString() == digest;
    if (!matches || mapped.value("projectId").toString() != counterpart)
      fail(QCoreApplication::translate("Bugg", "跨平台光影核心文件身份不一致"));
    const auto error = compatibility_error(mapped, query);
    if (!error.isEmpty()) fail(error);
    QVariantList dependencies;
    for (const auto& value : mapped.value("dependencies").toList()) {
      auto dependency = value.toMap();
      dependency["publisher"] = "Modrinth";
      dependencies.append(dependency);
    }
    const bool has_required = std::any_of(
        dependencies.begin(), dependencies.end(),
        [](const QVariant& value) { return value.toMap().value("type") == "required"; });
    if (has_required) version["dependencies"] = dependencies;
    return version;
  }
  void resolve(const QVariantMap& query, const QString& publisher, const QString& kind,
               const QString& project_id, const QVariantMap& candidate, QSet<QString>& resolving,
               QHash<QString, QString>& chosen, QVariantList& plan, QVariantList& missing) {
    check();
    const auto version = kind == "mod" ? core_release(candidate, query) : candidate;
    const auto version_id = version.value("id").toString();
    if (chosen.contains(project_id)) {
      if (chosen.value(project_id) != version_id)
        fail(QCoreApplication::translate("Bugg", "必要依赖版本冲突"));
      return;
    }
    if (plan.size() + resolving.size() >= 128)
      fail(QCoreApplication::translate("Bugg", "内容依赖数量过多"));
    const auto compatibility = compatibility_error(version, query);
    if (!compatibility.isEmpty()) fail(compatibility);
    if (!compatible(version, query, kind) || !version.value("available").toBool())
      fail(QCoreApplication::translate("Bugg", "所选版本不兼容当前游戏或不可下载"));
    const auto dependencies = version.value("dependencies").toList();
    for (const auto& value : dependencies)
      if (value.toMap().value("type") == "incompatible" &&
          chosen.contains(value.toMap().value("projectId").toString()))
        fail(QCoreApplication::translate("Bugg", "内容依赖之间不兼容"));
    for (const auto& file : plan)
      for (const auto& value : file.toMap().value("dependencies").toList())
        if (value.toMap().value("type") == "incompatible" &&
            value.toMap().value("projectId").toString() == project_id)
          fail(QCoreApplication::translate("Bugg", "内容依赖之间不兼容"));
    QVariantList primary;
    const auto files = version.value("files").toList();
    for (const auto& file : files)
      if (file.toMap().value("primary").toBool()) primary.append(file);
    if (primary.isEmpty() && !files.isEmpty()) primary.append(files.first());
    if (primary.size() != 1) fail(QCoreApplication::translate("Bugg", "内容没有唯一主文件"));
    auto entry = primary.first().toMap();
    entry["projectId"] = project_id;
    entry["versionId"] = version_id;
    entry["kind"] = kind;
    entry["publisher"] = publisher;
    entry["title"] = version.value("title", version.value("name"));
    if (project_id == query.value("projectId").toString() &&
        !query.value("projectTitle").toString().isEmpty())
      entry["title"] = query.value("projectTitle");
    entry["versionName"] = version.value("name");
    entry["gameVersions"] = version.value("gameVersions");
    entry["loaders"] = version.value("loaders");
    entry["dependencies"] = dependencies;
    if (version.value("verifiedCore").toBool()) entry["verifiedCore"] = true;
    entry["dependency"] = project_id != query.value("projectId").toString();
    plan.append(entry);
    chosen[project_id] = version_id;
    resolving.insert(project_id);
    for (const auto& item :
         kind == "modpack" ? QVariantList{} : version.value("dependencies").toList()) {
      const auto dep = item.toMap();
      if (dep.value("type") != "required") continue;
      const auto dependency_publisher = dep.value("publisher", publisher).toString();
      auto dep_project = dep.value("projectId").toString();
      const auto pinned = dep.value("versionId").toString();
      QString title = dep_project.isEmpty() ? pinned : dep_project;
      try {
        if (++dependency_count_ > 128)
          fail(QCoreApplication::translate("Bugg", "必要依赖解析已达到 128 项上限"));
        QVariantMap dependency;
        if (dependency_publisher == "Modrinth" && !pinned.isEmpty()) {
          if (!dep_project.isEmpty()) {
            dependency = one_version(dependency_publisher, "mod", identifier(dep_project),
                                     identifier(pinned));
          } else {
            const auto value =
                get(dependency_publisher, "/version/" + identifier(pinned)).toObject();
            dep_project = identifier(value["project_id"].toVariant());
            dependency = normalize_version(value, dependency_publisher, "mod", dep_project);
            QVariantList observed{dependency};
            source_dependencies(observed, dependency_publisher);
            dependency = observed.first().toMap();
          }
        }
        dep_project = identifier(dep_project);
        if (pinned.isEmpty() && chosen.contains(dep_project)) continue;
        const auto detail = project(dependency_publisher, {}, dep_project);
        title = detail.value("title").toString();
        const auto dependency_kind = detail.value("kind").toString();
        bool found = false;
        QString last_error;
        for (int page = 0; page < 50 && !found; ++page) {
          auto page_query = query;
          page_query["offset"] = page * 20;
          const auto listing =
              dependency.isEmpty()
                  ? versions(page_query, dependency_publisher, dependency_kind, dep_project)
                  : QVariantMap{{"versions", QVariantList{dependency}}, {"hasMore", false}};
          for (const auto& item : listing.value("versions").toList()) {
            auto candidate = item.toMap();
            candidate["title"] = detail.value("title");
            const auto old_resolving = resolving;
            const auto old_chosen = chosen;
            const auto old_plan = plan;
            const auto old_missing = missing;
            const auto old_count = dependency_count_;
            try {
              resolve(query, dependency_publisher, dependency_kind, dep_project, candidate,
                      resolving, chosen, plan, missing);
              if (missing.size() == old_missing.size()) {
                found = true;
                break;
              }
              last_error = missing.last().toMap().value("reason").toString();
            } catch (const std::exception& error) {
              check();
              last_error = QString::fromUtf8(error.what());
            }
            resolving = old_resolving;
            chosen = old_chosen;
            plan = old_plan;
            missing = old_missing;
            dependency_count_ = old_count;
          }
          if (!listing.value("hasMore").toBool()) break;
        }
        if (!found)
          fail(last_error.isEmpty()
                   ? QCoreApplication::translate("Bugg", "必要依赖没有兼容版本：") +
                         detail.value("title").toString()
                   : last_error);
      } catch (const std::exception& error) {
        check();
        missing.append(QVariantMap{{"publisher", dependency_publisher},
                                   {"projectId", dep_project},
                                   {"versionId", pinned},
                                   {"title", title},
                                   {"reason", QString::fromUtf8(error.what())}});
        if (dependency_count_ > 128) break;
      }
    }
    resolving.remove(project_id);
  }
  QStringList order_;
  ContentEndpoints endpoints_;
  std::shared_ptr<std::atomic_bool> cancelled_;
  // The source can spend up to 35 seconds fetching uncached publisher metadata.
  // Keep cancellation immediate while allowing that bounded first response.
  HttpClient http_{nullptr, {40000, 45000}};
  int dependency_count_ = 0;
  QJsonObject shader_manifest_;
  QJsonArray shader_reviews_;
  bool shader_reviews_loaded_ = false;
  bool source_releases_available_ = true;
  bool optional_search_ = false;
  QHash<QString, QJsonValue> metadata_cache_;
};
}  // namespace
QVariantMap request_content(const QVariantMap& query, const QStringList& order,
                            const ContentEndpoints& endpoints,
                            const std::shared_ptr<std::atomic_bool>& cancelled) {
  return ContentProvider(order, endpoints, cancelled).run(query);
}
}  // namespace bugg
