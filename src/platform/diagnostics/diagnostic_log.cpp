#include "platform/diagnostics/diagnostic_log.h"

#include <QCoreApplication>
#include <QDateTime>
#include <QDir>
#include <QFile>
#include <QJsonDocument>
#include <QMutex>
#include <QMutexLocker>
#include <QRegularExpression>
#include <QSaveFile>
#include <QUuid>
#include <deque>

namespace bugg {
namespace {
struct Journal {
  QMutex mutex;
  std::deque<QByteArray> events;
  qsizetype bytes = 0;
  quint64 dropped = 0;
  const QString session = QUuid::createUuid().toString(QUuid::WithoutBraces);
};
Journal& journal() {
  static Journal value;
  return value;
}
}  // namespace

QString diagnostic_url(const QUrl& url) {
  return url.adjusted(QUrl::RemoveUserInfo | QUrl::RemoveQuery | QUrl::RemoveFragment)
      .toString(QUrl::FullyEncoded);
}

QString redact_diagnostic(QString text) {
  static const QRegularExpression urls(R"(https?://[^\s"<>]+)");
  auto matches = urls.globalMatch(text);
  QList<QPair<qsizetype, QPair<qsizetype, QString>>> replacements;
  while (matches.hasNext()) {
    const auto match = matches.next();
    replacements.append(
        {match.capturedStart(), {match.capturedLength(), diagnostic_url(QUrl(match.captured()))}});
  }
  for (auto it = replacements.crbegin(); it != replacements.crend(); ++it)
    text.replace(it->first, it->second.first, it->second.second);
  static const QRegularExpression secrets(
      R"((?i)((?:--)?(?:access[_-]?token|refresh[_-]?token|client[_-]?secret|password|passwd|authorization|x-api-key|device[_-]?code|user[_-]?code|session[_-]?token)\s*["']?\s*[:= ]\s*["']?)(?:Bearer\s+)?[^\s,"'\}\]]+)");
  text.replace(secrets, "\\1<redacted>");
  static const QRegularExpression bearer(R"((?i)Bearer\s+[^\s,"']+)");
  text.replace(bearer, "Bearer <redacted>");
  const auto home = QDir::homePath();
  if (!home.isEmpty()) {
    text.replace(home, "<home>", Qt::CaseInsensitive);
    text.replace(QDir::toNativeSeparators(home), "<home>", Qt::CaseInsensitive);
  }
  return text;
}

void record_diagnostic(const QString& event, const QJsonObject& fields) {
  auto object = fields;
  object["event"] = event;
  object["utc"] = QDateTime::currentDateTimeUtc().toString(Qt::ISODateWithMs);
  // Callers supply allowlisted fields; clipping keeps malformed remote data bounded.
  auto bytes = QJsonDocument(object).toJson(QJsonDocument::Compact);
  if (bytes.size() > 16384) return;
  bytes.append('\n');
  auto& state = journal();
  QMutexLocker lock(&state.mutex);
  state.bytes += bytes.size();
  state.events.push_back(std::move(bytes));
  while (state.bytes > 2 * 1024 * 1024 || state.events.size() > 8192) {
    state.bytes -= state.events.front().size();
    state.events.pop_front();
    ++state.dropped;
  }
}

QByteArray diagnostic_snapshot() {
  auto& state = journal();
  QMutexLocker lock(&state.mutex);
  auto result = QJsonDocument(QJsonObject{{"event", "journal"},
                                          {"session", state.session},
                                          {"dropped", qint64(state.dropped)}})
                    .toJson(QJsonDocument::Compact);
  result.append('\n');
  result.reserve(result.size() + state.bytes);
  for (const auto& line : state.events) result.append(line);
  return result;
}

void checkpoint_diagnostics(const QString& cache_root) {
  static QMutex file_mutex;
  QMutexLocker lock(&file_mutex);
  const auto bytes = diagnostic_snapshot();
  const auto path = cache_root + "/logs/downloads.jsonl";
  if (!QDir().mkpath(cache_root + "/logs")) return;
  QFile old(path);
  if (old.open(QIODevice::ReadOnly) && old.size() <= 2 * 1024 * 1024 + 1024) {
    const auto header = old.readLine(1024);
    if (QJsonDocument::fromJson(header).object().value("session") !=
        QJsonDocument::fromJson(bytes.first(bytes.indexOf('\n') + 1)).object().value("session")) {
      QSaveFile previous(cache_root + "/logs/downloads.previous.jsonl");
      const auto content = header + old.readAll();
      if (previous.open(QIODevice::WriteOnly) && previous.write(content) == content.size())
        previous.commit();
    }
  }
  old.close();
  QSaveFile output(path);
  if (output.open(QIODevice::WriteOnly) && output.write(bytes) == bytes.size()) output.commit();
}
}  // namespace bugg
