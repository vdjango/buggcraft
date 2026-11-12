#ifndef BUGG_CONTRACTS_ROOM_CONTENT_H_
#define BUGG_CONTRACTS_ROOM_CONTENT_H_
#include <QJsonObject>
#include <QString>
#include <atomic>
#include <functional>
#include <memory>
namespace bugg {
/// 安装工作线程调用，底层在 GUI 排队原生 RPC；取消/会话失效抛异常，不在 GUI 等待。
using RoomContentRequest = std::function<QJsonObject(const QString&, QJsonObject,
                                                     const std::shared_ptr<std::atomic_bool>&)>;
}  // namespace bugg
#endif
