#ifndef BUGG_PLATFORM_DIAGNOSTICS_DIAGNOSTIC_LOG_H_
#define BUGG_PLATFORM_DIAGNOSTICS_DIAGNOSTIC_LOG_H_

#include <QJsonObject>
#include <QUrl>

namespace bugg {
/// No I/O. Removes credentials, query and fragment, retaining the resource route.
QString diagnostic_url(const QUrl& url);
/// Bounded diagnostic text only; never use this as permission to log credentials.
QString redact_diagnostic(QString text);
/// Thread-safe 2 MiB process journal; fields must exclude bodies and credentials.
void record_diagnostic(const QString& event, const QJsonObject& fields = {});
/// Thread-safe UTF-8 JSONL snapshot, including session and dropped-event counts.
QByteArray diagnostic_snapshot();
/// Worker-only atomic checkpoint (current + previous session, each <= 2 MiB).
/// Best effort: logging must never fail a download or settings save.
void checkpoint_diagnostics(const QString& cache_root);
}  // namespace bugg
#endif
