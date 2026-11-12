#include "platform/security/device_key.h"

#include <QCryptographicHash>
#include <QJsonDocument>
#include <stdexcept>
#ifdef Q_OS_WIN
#define NOMINMAX
#include <windows.h>
#include <bcrypt.h>
#else
#include <openssl/ec.h>
#include <openssl/ecdsa.h>
#include <openssl/obj_mac.h>
#endif

namespace bugg {
namespace {
void validate(const QByteArray& key) {
  if (key.size() != 96) throw std::runtime_error("Invalid device key");
}
QString encode(const QByteArray& bytes) {
  return QString::fromLatin1(bytes.toBase64(QByteArray::Base64UrlEncoding | QByteArray::OmitTrailingEquals));
}
#ifdef Q_OS_WIN
struct Provider {
  BCRYPT_ALG_HANDLE algorithm = nullptr;
  BCRYPT_KEY_HANDLE key = nullptr;
  Provider() {
    if (BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_ECDSA_P256_ALGORITHM, nullptr, 0) < 0)
      throw std::runtime_error("Device signature unavailable");
  }
  ~Provider() {
    if (key) BCryptDestroyKey(key);
    if (algorithm) BCryptCloseAlgorithmProvider(algorithm, 0);
  }
};
#endif
}  // namespace
QByteArray canonical_json(const QJsonObject& message) {
  // QJsonObject 按 UTF-16 key 排序；此协议字段均为 ASCII。非 ASCII 值使用 JSON \u 转义。
  const auto text = QString::fromUtf8(QJsonDocument(message).toJson(QJsonDocument::Compact));
  QByteArray result;
  for (const auto ch : text) {
    if (ch.unicode() < 128) result += char(ch.unicode());
    else result += "\\u" + QByteArray::number(ch.unicode(), 16).rightJustified(4, '0');
  }
  return result;
}
QByteArray create_device_key() {
#ifdef Q_OS_WIN
  Provider provider;
  if (BCryptGenerateKeyPair(provider.algorithm, &provider.key, 256, 0) < 0 ||
      BCryptFinalizeKeyPair(provider.key, 0) < 0) throw std::runtime_error("Cannot generate device key");
  QByteArray blob(sizeof(BCRYPT_ECCKEY_BLOB) + 96, '\0');
  ULONG size = 0;
  if (BCryptExportKey(provider.key, nullptr, BCRYPT_ECCPRIVATE_BLOB,
                      reinterpret_cast<PUCHAR>(blob.data()), blob.size(), &size, 0) < 0)
    throw std::runtime_error("Cannot export device key");
  return blob.mid(sizeof(BCRYPT_ECCKEY_BLOB), 96);
#else
  auto* key = EC_KEY_new_by_curve_name(NID_X9_62_prime256v1);
  if (!key || EC_KEY_generate_key(key) != 1) { EC_KEY_free(key); throw std::runtime_error("Cannot generate device key"); }
  QByteArray point(65, '\0'), scalar(32, '\0');
  const auto count = EC_POINT_point2oct(EC_KEY_get0_group(key), EC_KEY_get0_public_key(key),
      POINT_CONVERSION_UNCOMPRESSED, reinterpret_cast<unsigned char*>(point.data()), point.size(), nullptr);
  const int size = BN_bn2binpad(EC_KEY_get0_private_key(key), reinterpret_cast<unsigned char*>(scalar.data()), 32);
  EC_KEY_free(key);
  if (count != 65 || size != 32) throw std::runtime_error("Cannot export device key");
  return point.mid(1) + scalar;
#endif
}
QJsonObject device_public_key(const QByteArray& key) {
  validate(key);
  return {{"kty", "EC"}, {"crv", "P-256"}, {"x", encode(key.left(32))}, {"y", encode(key.mid(32, 32))}};
}
QString sign_device_message(const QByteArray& key, const QJsonObject& message) {
  validate(key);
  auto digest = QCryptographicHash::hash(canonical_json(message), QCryptographicHash::Sha256);
  QByteArray signature(64, '\0');
#ifdef Q_OS_WIN
  Provider provider;
  const BCRYPT_ECCKEY_BLOB header{BCRYPT_ECDSA_PRIVATE_P256_MAGIC, 32};
  auto blob = QByteArray(reinterpret_cast<const char*>(&header), sizeof(header)) + key;
  if (BCryptImportKeyPair(provider.algorithm, nullptr, BCRYPT_ECCPRIVATE_BLOB, &provider.key,
                          reinterpret_cast<PUCHAR>(blob.data()), blob.size(), 0) < 0)
    throw std::runtime_error("Cannot load device key");
  ULONG size = 0;
  if (BCryptSignHash(provider.key, nullptr, reinterpret_cast<PUCHAR>(digest.data()), digest.size(),
                     reinterpret_cast<PUCHAR>(signature.data()), signature.size(), &size, 0) < 0 || size != 64)
    throw std::runtime_error("Cannot sign device message");
#else
  auto* value = EC_KEY_new_by_curve_name(NID_X9_62_prime256v1);
  auto* scalar = BN_bin2bn(reinterpret_cast<const unsigned char*>(key.constData() + 64), 32, nullptr);
  auto point = QByteArray(1, char(4)) + key.left(64);
  if (!value || !scalar || EC_KEY_set_private_key(value, scalar) != 1 ||
      EC_KEY_oct2key(value, reinterpret_cast<const unsigned char*>(point.constData()), point.size(), nullptr) != 1) {
    BN_clear_free(scalar); EC_KEY_free(value); throw std::runtime_error("Cannot load device key");
  }
  BN_clear_free(scalar);
  auto* signed_value = ECDSA_do_sign(reinterpret_cast<const unsigned char*>(digest.constData()), digest.size(), value);
  EC_KEY_free(value);
  if (!signed_value) throw std::runtime_error("Cannot sign device message");
  const BIGNUM *r, *s;
  ECDSA_SIG_get0(signed_value, &r, &s);
  BN_bn2binpad(r, reinterpret_cast<unsigned char*>(signature.data()), 32);
  BN_bn2binpad(s, reinterpret_cast<unsigned char*>(signature.data() + 32), 32);
  ECDSA_SIG_free(signed_value);
#endif
  return encode(signature);
}
}  // namespace bugg
