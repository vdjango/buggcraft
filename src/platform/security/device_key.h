#ifndef BUGG_PLATFORM_SECURITY_DEVICE_KEY_H_
#define BUGG_PLATFORM_SECURITY_DEVICE_KEY_H_
#include <QByteArray>
#include <QJsonObject>
namespace bugg {
/// P-256 原生设备密钥；仅 account 所有者持有私钥。key 为 x/y/d 各 32 字节。
QByteArray create_device_key();
QJsonObject device_public_key(const QByteArray& key);
/// 节点协议规定的排序 ASCII JSON / SHA-256 / ECDSA r||s；失败抛异常，无磁盘和网络。
QString sign_device_message(const QByteArray& key, const QJsonObject& message);
QByteArray canonical_json(const QJsonObject& message);
}  // namespace bugg
#endif
