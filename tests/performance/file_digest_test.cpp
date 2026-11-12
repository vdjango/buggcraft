#include <QCryptographicHash>
#include <QElapsedTimer>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QSysInfo>
#include <QTemporaryDir>
#include <QTest>
#include <algorithm>

#include "platform/files/game_files.h"

namespace bugg {
namespace {
// Benchmark control: the previous production loop, retained only here for a fair A/B comparison.
QByteArray previous_digest(const QString& path, QCryptographicHash::Algorithm algorithm) {
  QFile file(path);
  if (!file.open(QIODevice::ReadOnly)) throw std::runtime_error("Cannot open fixture");
  QCryptographicHash hash(algorithm);
  while (!file.atEnd()) {
    check_cancelled({});
    const auto block = file.read(1024 * 1024);
    if (block.isEmpty() && file.error() != QFile::NoError) throw std::runtime_error("Read failed");
    hash.addData(block);
  }
  return hash.result().toHex();
}
}  // namespace

class FileDigestTest : public QObject {
  Q_OBJECT
 private slots:
  void all_algorithms_match_known_bytes_and_block_boundaries() {
    QTemporaryDir root;
    QVERIFY(root.isValid());
    const auto path = root.filePath("content.bin");
    const QList<QByteArray> algorithms{"sha1", "sha256", "sha512", "sha1"};
    for (const int size : {0, 3, 1024 * 1024 - 1, 1024 * 1024 + 1, 3 * 1024 * 1024 + 17}) {
      QByteArray bytes(size, Qt::Uninitialized);
      for (int i = 0; i < size; ++i) bytes[i] = char((i * 17 + i / 257) % 256);
      QFile file(path);
      QVERIFY(file.open(QIODevice::WriteOnly));
      QCOMPARE(file.write(bytes), size);
      file.close();
      const auto result = file_digests(path, algorithms, {});
      QCOMPARE(result.size(), 3);
      QCOMPARE(result.value("sha1"),
               QCryptographicHash::hash(bytes, QCryptographicHash::Sha1).toHex());
      QCOMPARE(result.value("sha256"),
               QCryptographicHash::hash(bytes, QCryptographicHash::Sha256).toHex());
      QCOMPARE(result.value("sha512"),
               QCryptographicHash::hash(bytes, QCryptographicHash::Sha512).toHex());
      QCOMPARE(file_digest(path, "sha256", {}), result.value("sha256"));
    }
  }

  void cancellation_and_invalid_input_return_no_partial_digest() {
    QTemporaryDir root;
    const auto path = root.filePath("content.bin");
    QFile file(path);
    QVERIFY(file.open(QIODevice::WriteOnly));
    file.write("abc");
    file.close();
    const auto cancelled = std::make_shared<std::atomic_bool>(true);
    QVERIFY_EXCEPTION_THROWN(file_digests(path, {"sha1", "sha256"}, cancelled), std::runtime_error);
    QVERIFY_EXCEPTION_THROWN(file_digests(path, {}, {}), std::runtime_error);
    QVERIFY_EXCEPTION_THROWN(file_digests(path, {"sha1", "md5"}, {}), std::runtime_error);
    QVERIFY_EXCEPTION_THROWN(file_digests(root.filePath("absent"), {"sha1"}, {}),
                             std::runtime_error);
  }

  void paired_performance_report() {
    const auto output = qEnvironmentVariable("BUGG_PERFORMANCE_REPORT");
    if (output.isEmpty()) QSKIP("Set BUGG_PERFORMANCE_REPORT to run the measured A/B benchmark");
    QTemporaryDir root;
    QVERIFY(root.isValid());
    QByteArray block(1024 * 1024, Qt::Uninitialized);
    for (int i = 0; i < block.size(); ++i) block[i] = char((i * 13 + i / 251) % 256);
    QJsonArray scenarios;
    for (const auto& name :
         {QString("export-large"), QString("verify-large"), QString("export-many")}) {
      const int count = name == "export-many" ? 400 : 1;
      const int blocks = count == 1 ? 128 : 1;
      const int block_size = count == 1 ? block.size() : 64 * 1024;
      QStringList paths;
      for (int index = 0; index < count; ++index) {
        const auto path = root.filePath(name + QString::number(index));
        QFile file(path);
        QVERIFY(file.open(QIODevice::WriteOnly));
        for (int i = 0; i < blocks; ++i)
          QCOMPARE(file.write(block.constData(), block_size), block_size);
        paths.append(path);
      }
      QList<QByteArray> algorithms{"sha1", "sha256"};
      if (name == "verify-large") algorithms.append("sha512");
      const auto before = [&] {
        QList<QMap<QByteArray, QByteArray>> results;
        for (const auto& path : paths) {
          QMap<QByteArray, QByteArray> result;
          for (const auto& algorithm : algorithms)
            result[algorithm] =
                previous_digest(path, algorithm == "sha1"     ? QCryptographicHash::Sha1
                                      : algorithm == "sha256" ? QCryptographicHash::Sha256
                                                              : QCryptographicHash::Sha512);
          results.append(result);
        }
        return results;
      };
      const auto after = [&] {
        QList<QMap<QByteArray, QByteArray>> results;
        for (const auto& path : paths) results.append(file_digests(path, algorithms, {}));
        return results;
      };
      // Fixture generation and warm-up are outside timing. All timed outputs are compared.
      const auto expected = before();
      QCOMPARE(after(), expected);
      QJsonArray before_ms, after_ms;
      for (int iteration = 0; iteration < 9; ++iteration) {
        for (int pass = 0; pass < 2; ++pass) {
          const bool old = (iteration + pass) % 2 == 0;
          QElapsedTimer clock;
          clock.start();
          const auto actual = old ? before() : after();
          const double elapsed = clock.nsecsElapsed() / 1e6;
          QCOMPARE(actual, expected);
          (old ? before_ms : after_ms).append(elapsed);
        }
      }
      const auto bytes = qint64(count) * blocks * block_size;
      scenarios.append(QJsonObject{{"scenario", name},
                                   {"files", count},
                                   {"inputBytes", bytes},
                                   {"algorithms", QJsonArray::fromStringList([&] {
                                      QStringList values;
                                      for (const auto& algorithm : algorithms)
                                        values.append(QString::fromLatin1(algorithm));
                                      return values;
                                    }())},
                                   {"beforeMs", before_ms},
                                   {"afterMs", after_ms},
                                   {"beforeReadBytes", bytes * algorithms.size()},
                                   {"afterReadBytes", bytes},
                                   {"beforeOpens", count * algorithms.size()},
                                   {"afterOpens", count}});
    }
    write_json(output, {{"qt", qVersion()},
                        {"system", QSysInfo::prettyProductName()},
                        {"architecture", QSysInfo::currentCpuArchitecture()},
                        {"build", "Release"},
                        {"cache", "warm OS file cache; alternating order; 9 paired samples"},
                        {"scenarios", scenarios}});
  }
};
}  // namespace bugg
QTEST_GUILESS_MAIN(bugg::FileDigestTest)
#include "file_digest_test.moc"
