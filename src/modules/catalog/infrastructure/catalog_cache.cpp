#include "modules/catalog/infrastructure/catalog_cache.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QFutureWatcher>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QSaveFile>
#include <QtConcurrent/QtConcurrentRun>
#include <algorithm>

#include "contracts/download_sources.h"

namespace bugg {
namespace {
constexpr qsizetype kMaxBytes = 8 * 1024 * 1024;
constexpr qsizetype kMaxRecords = 64;

QVector<CatalogCache::Record> read_cache(const QString& path) {
  QFile file(path);
  if (!file.open(QIODevice::ReadOnly) || file.size() > kMaxBytes) return {};
  const auto object = QJsonDocument::fromJson(file.readAll()).object();
  const auto records = object.value("records").toArray();
  if (object.value("version").toInt() != 1 || records.size() > kMaxRecords) return {};
  QVector<CatalogCache::Record> result;
  for (const auto& value : records) {
    const auto item = value.toObject();
    const auto entries = item.value("entries").toArray();
    CatalogResult catalog;
    catalog.source = item.value("source").toString();
    catalog.preferred = item.value("preferred").toString();
    const auto key = item.value("key").toString();
    if (key.isEmpty() || key.size() > 1024 || entries.size() > 10000 ||
        !supported_download_sources().contains(catalog.source))
      continue;
    bool valid = true;
    for (const auto& entry_value : entries) {
      const auto entry = entry_value.toObject();
      const auto id = entry.value("id").toString();
      if (id.isEmpty() || id.size() > 256) {
        valid = false;
        break;
      }
      catalog.entries.push_back({id, entry.value("stable").toBool(true),
                                 QUrl(entry.value("url").toString()),
                                 entry.value("sha1").toString()});
    }
    if (!catalog.entries.isEmpty() &&
        !std::any_of(catalog.entries.cbegin(), catalog.entries.cend(),
                     [&catalog](const auto& entry) { return entry.id == catalog.preferred; }))
      valid = false;
    if (valid) result.push_back({key, catalog});
  }
  return result;
}

bool write_cache(const QString& path, const QVector<CatalogCache::Record>& records) {
  QJsonArray values;
  for (const auto& record : records) {
    QJsonArray entries;
    for (const auto& entry : record.result.entries)
      entries.append(QJsonObject{{"id", entry.id},
                                 {"stable", entry.stable},
                                 {"url", entry.metadata_url.toString()},
                                 {"sha1", entry.sha1}});
    values.append(QJsonObject{{"key", record.key},
                              {"source", record.result.source},
                              {"preferred", record.result.preferred},
                              {"entries", entries}});
  }
  const auto body = QJsonDocument(QJsonObject{{"version", 1}, {"records", values}})
                        .toJson(QJsonDocument::Compact);
  if (body.size() > kMaxBytes || !QDir().mkpath(QFileInfo(path).absolutePath())) return false;
  QSaveFile file(path);
  return file.open(QIODevice::WriteOnly) && file.write(body) == body.size() && file.commit();
}
}  // namespace

CatalogCache::CatalogCache(QString path, QObject* parent)
    : QObject(parent), path_(std::move(path)), ready_(path_.isEmpty()) {
  if (ready_) return;
  auto* watcher = new QFutureWatcher<QVector<Record>>(this);
  connect(watcher, &QFutureWatcher<QVector<Record>>::finished, this, [this, watcher] {
    // 服务会等 loaded 再查询；仍保留读期间显式写入的较新值。
    const auto stored = watcher->result();
    watcher->deleteLater();
    for (const auto& record : stored)
      if (!lookup(record.key) && records_.size() < kMaxRecords) records_.append(record);
    ready_ = true;
    emit loaded();
    if (revision_) save();
  });
  watcher->setFuture(QtConcurrent::run([path = path_] { return read_cache(path); }));
}

QString CatalogCache::key(const QStringList& order, const CatalogQuery& query,
                          const QUrl& bugg_base) {
  return QString::fromUtf8(QJsonDocument(QJsonArray{QJsonArray::fromStringList(order), query.kind,
                                                    query.game_version, bugg_base.toString()})
                               .toJson(QJsonDocument::Compact));
}

std::optional<CatalogResult> CatalogCache::lookup(const QString& key) const {
  for (const auto& record : records_)
    if (record.key == key) return record.result;
  return std::nullopt;
}

void CatalogCache::store(const QString& key, const CatalogResult& result) {
  if (!result.error.isEmpty()) return;
  records_.erase(std::remove_if(records_.begin(), records_.end(),
                                [&key](const auto& record) { return record.key == key; }),
                 records_.end());
  records_.prepend({key, result});
  if (records_.size() > kMaxRecords) records_.resize(kMaxRecords);
  ++revision_;
  save();
}

void CatalogCache::save() {
  if (path_.isEmpty() || !ready_ || saving_) return;
  saving_ = true;
  const auto revision = revision_;
  auto* watcher = new QFutureWatcher<bool>(this);
  connect(watcher, &QFutureWatcher<bool>::finished, this, [this, watcher, revision] {
    if (!watcher->result())
      qWarning("Catalog cache could not be saved; online catalog remains usable");
    watcher->deleteLater();
    saving_ = false;
    if (revision != revision_) save();
  });
  watcher->setFuture(
      QtConcurrent::run([path = path_, records = records_] { return write_cache(path, records); }));
}

void CatalogCache::relocate_storage(const QString& path) {
  path_ = path;
  ++revision_;
  save();
}
}  // namespace bugg
