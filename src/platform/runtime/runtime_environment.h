#ifndef BUGG_PLATFORM_RUNTIME_RUNTIME_ENVIRONMENT_H_
#define BUGG_PLATFORM_RUNTIME_RUNTIME_ENVIRONMENT_H_
#include <QVariantMap>

#include "platform/files/game_files.h"
namespace bugg {
inline constexpr int kMinimumAutomaticMemoryMB = 2048;
/// 每次初始化/启动重新采样，不持久化 auto 的计算值。昂贵扫描仅在工作线程。
QVariantMap memory_snapshot();
/// 当前可用物理内存扣除系统预算，256 MiB 对齐；启动时重新采样。
int memory_limit_mb(const QVariantMap& snapshot);
/// 按活动模组数和房主本机承载人数估算堆上限；每次启动用新的系统快照计算。
int automatic_memory_mb(const QVariantMap& snapshot, int mod_count = 0, int hosted_players = 1);
/// 工作线程统一初始化/刷新快照，包含内存与已验证的 Java 候选。
QVariantMap environment_snapshot(const QString& portable_root, const Cancellation& cancelled);
QStringList java_candidates(const QString& portable_root, const Cancellation& cancelled);
int java_major(const QString& executable, const Cancellation& cancelled);
/// 自有辅助 Java 进程：工作线程等待，50ms 检查取消；超时/非零退出明确失败。
void run_java_tool(const QString& executable, const QStringList& arguments,
                   const QString& directory, const QString& log_path,
                   const Cancellation& cancelled);
}  // namespace bugg
#endif
