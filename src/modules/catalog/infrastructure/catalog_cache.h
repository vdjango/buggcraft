#ifndef BUGG_MODULES_CATALOG_INFRASTRUCTURE_CATALOG_CACHE_H_
#define BUGG_MODULES_CATALOG_INFRASTRUCTURE_CATALOG_CACHE_H_

#include <QObject>
#include <optional>

#include "contracts/download_sources.h"
#include "contracts/game_catalog.h"

namespace bugg {

/// 归一化目录缓存；GUI 线程仅访问内存，文件和编解码由独立值任务完成。
/// 服务拥有此对象；空路径仅内存缓存，损坏/写入失败不阻断在线查询。
class CatalogCache final : public QObject {
  Q_OBJECT
 public:
  struct Record {
    QString key;
    CatalogResult result;
  };
  explicit CatalogCache(QString path = {}, QObject* parent = nullptr);
  bool ready() const { return ready_; }
  /// 同步纯内存查找；无记录返回 nullopt，成功空列表也是有效记录。
  std::optional<CatalogResult> lookup(const QString& key) const;
  /// 仅保存成功结果；最多 64 项，后台原子写，快速更新合并为最新快照。
  void store(const QString& key, const CatalogResult& result);
  /// 来源排序也参与身份，避免切源后误用其他策略的目录。
  static QString key(const QStringList& order, const CatalogQuery& query,
                     const QUrl& bugg_base = default_bugg_source());
  /// GUI 迁移后重定向唯一写入队列，保存当前最新快照。
  void relocate_storage(const QString& path);
 signals:
  void loaded();

 private:
  void save();
  QString path_;
  QVector<Record> records_;
  quint64 revision_ = 0;
  bool ready_ = true;
  bool saving_ = false;
};

}  // namespace bugg
#endif  // BUGG_MODULES_CATALOG_INFRASTRUCTURE_CATALOG_CACHE_H_
