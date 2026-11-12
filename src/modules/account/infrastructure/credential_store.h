#ifndef BUGG_MODULES_ACCOUNT_INFRASTRUCTURE_CREDENTIAL_STORE_H_
#define BUGG_MODULES_ACCOUNT_INFRASTRUCTURE_CREDENTIAL_STORE_H_
#include <QByteArray>
#include <QString>
namespace bugg {
/// 工作线程调用；Windows DPAPI/macOS Keychain。无系统保护时不保存长期凭据。
QByteArray load_credentials(const QString& path);
void save_credentials(const QString& path, const QByteArray& payload);
}  // namespace bugg
#endif
