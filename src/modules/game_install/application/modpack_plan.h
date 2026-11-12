#ifndef BUGG_MODULES_GAME_INSTALL_APPLICATION_MODPACK_PLAN_H_
#define BUGG_MODULES_GAME_INSTALL_APPLICATION_MODPACK_PLAN_H_
#include <QJsonArray>
#include <QSet>
#include <QVariantMap>

#include "platform/files/game_files.h"
namespace bugg {
/// 三种归档格式只在此归一化；安装层不识别 UI 或发布平台。
struct ModpackPlan {
  QString format;
  QVariantMap specification;
  QJsonArray files;
  QStringList overrides;
  /// A self-contained client ZIP uses the same descriptor/commit transaction.
  QString client_prefix;
  QString client_id;
  QJsonObject client_metadata;
};
/// 工作线程只读预检，无安装副作用；无效/歧义清单、路径或版本抛异常。
ModpackPlan inspect_modpack(const QString& path, const Cancellation& cancelled);
/// Shared content-record validation and final digest checks for local packs,
/// room synchronization and online content. Worker-only; failures throw.
void validate_content_record(const QJsonObject& record, QSet<QString>& names);
void verify_content_file(const QString& path, const QJsonObject& record,
                         const Cancellation& cancelled);
}  // namespace bugg
#endif
