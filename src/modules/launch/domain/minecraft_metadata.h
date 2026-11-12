#ifndef BUGG_MODULES_LAUNCH_DOMAIN_MINECRAFT_METADATA_H_
#define BUGG_MODULES_LAUNCH_DOMAIN_MINECRAFT_METADATA_H_
#include <QJsonArray>
#include <QJsonObject>
#include <QVariantMap>

#include "contracts/game_runtime.h"

namespace bugg {
QString minecraft_os();
QString maven_path(const QString& coordinate);
/// 纯解析：实例列表和整合包导出共用版本/加载器描述；兼容原生元数据及 Maven 库坐标。
QVariantMap instance_descriptor(const QJsonObject& metadata);
bool rules_allow(const QJsonArray& rules, const QVariantMap& features = {});
QJsonObject merge_metadata(const QJsonObject& parent, const QJsonObject& child);
QJsonArray effective_libraries(const QJsonArray& libraries);
QStringList unique_classpath(const QStringList& paths);
/// 最后一步语义归一化；分别处理 JVM/game 参数，不能对整个 token 数组去重。
QStringList normalize_arguments(const QStringList& arguments, bool jvm);
struct LaunchCommand {
  QString java;
  QStringList arguments;
  QString directory;
  QString log_path;
};
/// 输入完整元数据、身份、房间/用户贡献；所有贡献合并后执行最终去重，不执行进程。
LaunchCommand build_launch_command(const QJsonObject& metadata, const QString& root,
                                   const QString& instance_id, const QString& java, int memory_mb,
                                   const GameIdentity& identity,
                                   const QVariantMap& contributions = {});
}  // namespace bugg
#endif
