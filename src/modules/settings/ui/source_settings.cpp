#include "modules/settings/ui/source_settings.h"

#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QFutureWatcher>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QSaveFile>
#include <QVariantList>
#include <QtConcurrent/QtConcurrentRun>

#include "contracts/download_sources.h"

namespace bugg {
namespace {
struct StoredSource {
  QStringList order;
  QString error;
  QUrl bugg_base = default_bugg_source();
};

QUrl source_origin(const QString& value) {
  auto url = QUrl(value.trimmed(), QUrl::StrictMode);
  if (!url.isValid() || url.host().isEmpty() ||
      (url.scheme() != "https" && url.scheme() != "http") || !url.userInfo().isEmpty() ||
      url.hasQuery() || url.hasFragment())
    return {};
  auto path = url.path();
  while (path.endsWith('/')) path.chop(1);
  url.setPath(path);
  return url;
}

bool valid_order(const QStringList& order) {
  return order.size() == supported_download_sources().size() &&
         resolve_sources(order, SourceCapability::MinecraftCatalog).error.isEmpty();
}
}  // namespace

SourceSettings::SourceSettings(QObject* parent, QString storage_path)
    : QObject(parent), storage_path_(std::move(storage_path)) {
  if (storage_path_.isEmpty()) return;
  loading_ = true;
  auto* watcher = new QFutureWatcher<StoredSource>(this);
  connect(watcher, &QFutureWatcher<StoredSource>::finished, this, [this, watcher] {
    const auto stored = watcher->result();
    watcher->deleteLater();
    loading_ = false;
    // 读取期间的新选择优先，不能让迟到的磁盘快照覆盖用户操作。
    if (revision_ == 0) {
      error_ = stored.error;
      const bool changed =
          (!stored.order.isEmpty() && stored.order != order_) || stored.bugg_base != bugg_base_;
      if (!stored.order.isEmpty() && stored.order != order_) {
        order_ = stored.order;
        emit source_order_changed();
      }
      bugg_base_ = stored.bugg_base;
      if (changed) emit configuration_changed();
    }
    emit status_changed();
  });
  watcher->setFuture(QtConcurrent::run([path = storage_path_] {
    QFile file(path);
    if (!file.exists()) return StoredSource{};
    if (!file.open(QIODevice::ReadOnly) || file.size() > 8192)
      return StoredSource{{}, QCoreApplication::translate("Bugg", "来源设置读取失败，暂用 BUGG")};
    const auto doc = QJsonDocument::fromJson(file.readAll());
    // 旧版单独的游戏源键只在读取时兼容，不保留第二份设置。
    const auto object = doc.object();
    QStringList order;
    if (object.contains("source_order")) {
      for (const auto& id : object.value("source_order").toArray()) order.append(id.toString());
    } else {
      const auto source =
          object.value("download_source").toString(object.value("game_source").toString());
      if (supported_download_sources().contains(source)) {
        order = supported_download_sources();
        order.removeAll(source);
        order.prepend(source);
      }
    }
    if (!valid_order(order))
      return StoredSource{{}, QCoreApplication::translate("Bugg", "来源设置无效，暂用 BUGG")};
    const auto base =
        source_origin(object.value("bugg_base_url").toString(default_bugg_source().toString()));
    if (base.isEmpty())
      return StoredSource{order,
                          QCoreApplication::translate("Bugg", "Bugg 源地址无效，暂用默认地址")};
    return StoredSource{order, {}, base};
  }));
}

QVariantMap SourceSettings::status() const {
  QVariantList options;
  for (const auto& source : order_)
    options.push_back(QVariantMap{{"id", source}, {"name", source}});
  return {{"order", order_},
          {"buggBaseUrl", bugg_base_.toString()},
          {"summary", order_.first() + QCoreApplication::translate("Bugg", " 优先")},
          {"options", options},
          {"loading", loading_},
          {"saving", saving_},
          {"error", error_}};
}

bool SourceSettings::set_source_order(const QStringList& order) {
  if (!valid_order(order)) return false;
  if (order_ == order) {
    if (!error_.isEmpty()) save();
    return true;
  }
  order_ = order;
  ++revision_;
  error_.clear();
  emit source_order_changed();
  emit configuration_changed();
  save();
  emit status_changed();
  return true;
}

bool SourceSettings::set_bugg_base_url(const QString& value) {
  const auto base = source_origin(value);
  if (base.isEmpty()) {
    error_ =
        QCoreApplication::translate("Bugg", "请输入完整的 HTTP(S) 源地址，不含查询参数或账号信息");
    emit status_changed();
    return false;
  }
  if (bugg_base_ == base) {
    if (!error_.isEmpty()) {
      error_.clear();
      save();
      emit status_changed();
    }
    return true;
  }
  bugg_base_ = base;
  ++revision_;
  error_.clear();
  emit configuration_changed();
  save();
  emit status_changed();
  return true;
}

bool SourceSettings::move_source(int index, int delta) {
  const int next = index + delta;
  if ((delta != -1 && delta != 1) || index < 0 || next < 0 || index >= order_.size() ||
      next >= order_.size())
    return false;
  auto order = order_;
  order.swapItemsAt(index, next);
  return set_source_order(order);
}

void SourceSettings::save() {
  if (storage_path_.isEmpty() || saving_) return;
  saving_ = true;
  const auto revision = revision_;
  auto* watcher = new QFutureWatcher<QString>(this);
  connect(watcher, &QFutureWatcher<QString>::finished, this, [this, watcher, revision] {
    error_ = watcher->result();
    watcher->deleteLater();
    saving_ = false;
    // 单一写入队列，快速切换合并为最后一份选择，旧保存不能覆盖新保存。
    if (revision != revision_) save();
    emit status_changed();
  });
  watcher->setFuture(QtConcurrent::run([path = storage_path_, order = order_, base = bugg_base_] {
    if (!QDir().mkpath(QFileInfo(path).absolutePath()))
      return QString(QCoreApplication::translate("Bugg", "无法创建来源设置目录"));
    QSaveFile file(path);
    const auto body = QJsonDocument(QJsonObject{{"version", 4},
                                                {"source_order", QJsonArray::fromStringList(order)},
                                                {"bugg_base_url", base.toString()}})
                          .toJson();
    if (!file.open(QIODevice::WriteOnly) || file.write(body) != body.size() || !file.commit())
      return QString(
          QCoreApplication::translate("Bugg", "来源已切换，但保存失败，请重新选择后重试"));
    return QString{};
  }));
}

void SourceSettings::relocate_storage(const QString& path) {
  storage_path_ = path;
  ++revision_;
  save();
}
}  // namespace bugg
