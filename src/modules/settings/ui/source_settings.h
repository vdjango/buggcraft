#ifndef BUGG_MODULES_SETTINGS_UI_SOURCE_SETTINGS_H_
#define BUGG_MODULES_SETTINGS_UI_SOURCE_SETTINGS_H_

#include <QtQml/qqmlregistration.h>

#include <QObject>
#include <QVariantMap>

#include "bugg_presentation_export.h"
#include "contracts/download_sources.h"

namespace bugg {

/// 窗口/应用级唯一下载源优先级；GUI 发命令，文件读写在线程池。
/// storage_path 由 app 注入便携路径；空路径用于无磁盘测试，不扫描用户目录。
class BUGG_PRESENTATION_EXPORT SourceSettings : public QObject {
  Q_OBJECT
  QML_ELEMENT
  Q_PROPERTY(QStringList source_order READ source_order NOTIFY source_order_changed)
  Q_PROPERTY(QVariantMap status READ status NOTIFY status_changed)
 public:
  explicit SourceSettings(QObject* parent = nullptr, QString storage_path = {});
  QStringList source_order() const { return order_; }
  QUrl bugg_base_url() const { return bugg_base_; }
  QVariantMap status() const;
  /// GUI：更新唯一基址并异步保存；非法 HTTP(S) URL 返回 false、保留原配置。
  Q_INVOKABLE bool set_bugg_base_url(const QString& value);
  /// 必须完整包含受支持来源且不重复；非法 false，同值 true 无重复保存。
  /// 立即更新顺序并排队持久化，保存失败通过 status.error 通知。
  Q_INVOKABLE bool set_source_order(const QStringList& order);
  /// 上下移动一个来源；delta 仅接受 -1/+1，越界 false，不改原配置。
  Q_INVOKABLE bool move_source(int index, int delta);
  /// GUI 迁移后重定向唯一写入队列，保存当前最新快照。
  void relocate_storage(const QString& path);
 signals:
  void source_order_changed();
  void configuration_changed();
  void status_changed();

 private:
  void save();
  QString storage_path_;
  QStringList order_ = supported_download_sources();
  QUrl bugg_base_ = default_bugg_source();
  QString error_;
  quint64 revision_ = 0;
  bool loading_ = false;
  bool saving_ = false;
};

}  // namespace bugg
#endif  // BUGG_MODULES_SETTINGS_UI_SOURCE_SETTINGS_H_
