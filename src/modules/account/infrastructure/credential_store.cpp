#include "modules/account/infrastructure/credential_store.h"

#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QSaveFile>
#include <stdexcept>
#ifdef Q_OS_WIN
#define NOMINMAX
#include <windows.h>
// wincrypt.h 依赖 windows.h 中的 Win32 类型，不能交换顺序。
#include <wincrypt.h>
#elif defined(Q_OS_MACOS)
#include <Security/Security.h>
#endif
namespace bugg {
QByteArray load_credentials(const QString& path) {
#ifdef Q_OS_WIN
  QFile file(path);
  if (!file.exists()) return {};
  if (!file.open(QIODevice::ReadOnly) || file.size() > 1024 * 1024)
    throw std::runtime_error(QCoreApplication::translate("Bugg", "无法读取安全凭据").toStdString());
  auto encrypted = file.readAll();
  DATA_BLOB input{DWORD(encrypted.size()), reinterpret_cast<BYTE*>(encrypted.data())}, output{};
  if (!CryptUnprotectData(&input, nullptr, nullptr, nullptr, nullptr, CRYPTPROTECT_UI_FORBIDDEN,
                          &output))
    throw std::runtime_error(
        QCoreApplication::translate("Bugg", "凭据无法在当前系统解密，请重新登录").toStdString());
  const QByteArray result(reinterpret_cast<const char*>(output.pbData), output.cbData);
  SecureZeroMemory(output.pbData, output.cbData);
  LocalFree(output.pbData);
  return result;
#elif defined(Q_OS_MACOS)
  const auto key = QFileInfo(path).absoluteFilePath().toUtf8();
  void* data = nullptr;
  UInt32 length = 0;
  const auto status = SecKeychainFindGenericPassword(nullptr, 4, "Bugg", key.size(),
                                                     key.constData(), &length, &data, nullptr);
  if (status == errSecItemNotFound) return {};
  if (status != errSecSuccess)
    throw std::runtime_error(QCoreApplication::translate("Bugg", "钥匙串读取失败").toStdString());
  const QByteArray result(static_cast<const char*>(data), length);
  SecKeychainItemFreeContent(nullptr, data);
  return result;
#else
  Q_UNUSED(path);
  return {};
#endif
}
void save_credentials(const QString& path, const QByteArray& payload) {
#ifdef Q_OS_WIN
  if (payload.isEmpty()) {
    if (QFileInfo::exists(path) && !QFile::remove(path))
      throw std::runtime_error(
          QCoreApplication::translate("Bugg", "无法清除安全凭据").toStdString());
    return;
  }
  DATA_BLOB input{DWORD(payload.size()),
                  reinterpret_cast<BYTE*>(const_cast<char*>(payload.constData()))},
      output{};
  if (!CryptProtectData(&input, L"Bugg Microsoft refresh credential", nullptr, nullptr, nullptr,
                        CRYPTPROTECT_UI_FORBIDDEN, &output))
    throw std::runtime_error(
        QCoreApplication::translate("Bugg", "系统无法保护凭据，未写入明文").toStdString());
  const QByteArray encrypted(reinterpret_cast<const char*>(output.pbData), output.cbData);
  LocalFree(output.pbData);
  QDir().mkpath(QFileInfo(path).absolutePath());
  QSaveFile file(path);
  if (!file.open(QIODevice::WriteOnly) || file.write(encrypted) != encrypted.size() ||
      !file.commit())
    throw std::runtime_error(QCoreApplication::translate("Bugg", "安全凭据保存失败").toStdString());
#elif defined(Q_OS_MACOS)
  const auto key = QFileInfo(path).absoluteFilePath().toUtf8();
  SecKeychainItemRef item = nullptr;
  const auto found = SecKeychainFindGenericPassword(nullptr, 4, "Bugg", key.size(), key.constData(),
                                                    nullptr, nullptr, &item);
  OSStatus status;
  if (found == errSecSuccess) {
    status = payload.isEmpty() ? SecKeychainItemDelete(item)
                               : SecKeychainItemModifyAttributesAndData(
                                     item, nullptr, payload.size(), payload.constData());
    CFRelease(item);
  } else if (payload.isEmpty())
    return;
  else
    status = SecKeychainAddGenericPassword(nullptr, 4, "Bugg", key.size(), key.constData(),
                                           payload.size(), payload.constData(), nullptr);
  if (status != errSecSuccess)
    throw std::runtime_error(QCoreApplication::translate("Bugg", "钥匙串保存失败").toStdString());
#else
  Q_UNUSED(path);
  if (!payload.isEmpty())
    throw std::runtime_error(
        QCoreApplication::translate("Bugg", "本系统尚未接入安全凭据存储，本次登录仅在当前进程有效")
            .toStdString());
#endif
}
}  // namespace bugg
