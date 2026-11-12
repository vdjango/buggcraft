#include <QCoreApplication>
#include <QDateTime>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QRegularExpression>
#include <QSysInfo>
#include <QTemporaryDir>
#include <QUrl>
#include <QXmlStreamReader>
#include <algorithm>

#include "modules/game_install/application/game_runtime.h"
#include "platform/diagnostics/diagnostic_log.h"

namespace bugg {
namespace {
using LogVisitor = std::function<void(QString, QString, QString, QString, QString)>;

// Read a bounded tail on the existing worker. Log4j XML events and plaintext
// multiline exceptions stay single records, preserving level/logger/thread.
int visit_debug_log(const QString& path, const Cancellation& cancelled, const LogVisitor& visit) {
  QFile file(path);
  if (!file.open(QIODevice::ReadOnly)) return 0;
  constexpr qint64 limit = 256 * 1024;
  if (file.size() > limit) {
    file.seek(file.size() - limit);
    file.readLine();
  }
  const auto text = QString::fromUtf8(file.read(limit));
  int count = 0;
  if (text.contains("<log4j:Event")) {
    qsizetype offset = 0;
    while ((offset = text.indexOf("<log4j:Event", offset)) >= 0) {
      check_cancelled(cancelled);
      const auto end = text.indexOf("</log4j:Event>", offset);
      if (end < 0) break;  // Appending an incomplete event is normal; read next time.
      QXmlStreamReader xml(text.mid(offset, end + 14 - offset));
      xml.setNamespaceProcessing(false);
      offset = end + 14;
      if (!xml.readNextStartElement()) continue;
      const auto attributes = xml.attributes();
      const auto level = attributes.value("level").toString();
      const auto logger = attributes.value("logger").toString();
      const auto thread = attributes.value("thread").toString();
      const auto time = QDateTime::fromMSecsSinceEpoch(attributes.value("timestamp").toLongLong())
                            .toString(Qt::ISODateWithMs);
      QString message;
      while (!xml.atEnd()) {
        xml.readNext();
        if (xml.isStartElement() &&
            (xml.qualifiedName() == "log4j:Message" || xml.qualifiedName() == "log4j:Throwable")) {
          if (!message.isEmpty()) message += '\n';
          message += xml.readElementText(QXmlStreamReader::IncludeChildElements);
        }
      }
      if (!xml.hasError() && !message.isEmpty()) {
        visit(level, time, message, logger, thread);
        ++count;
      }
    }
    return count;
  }
  static const QRegularExpression header(
      R"(^\[([^\]]+)\]\s+\[([^\]]+)/(TRACE|DEBUG|INFO|WARN|ERROR|FATAL)\](?:\s+\[([^\]]+)\])?:?\s?(.*)$)");
  QString level = "INFO", time, logger, thread, message;
  const auto flush = [&] {
    if (message.isEmpty()) return;
    visit(level, time, message, logger, thread);
    ++count;
    message.clear();
  };
  for (const auto& line : text.split('\n')) {
    check_cancelled(cancelled);
    const auto match = header.match(line);
    if (match.hasMatch()) {
      flush();
      level = match.captured(3);
      time = file.fileTime(QFileDevice::FileModificationTime).date().toString(Qt::ISODate) + 'T' +
             match.captured(1);
      logger = match.captured(4);
      thread = match.captured(2);
      message = match.captured(5);
    } else if (message.size() < 12288) {
      if (!message.isEmpty()) message += '\n';
      message += line;
    }
  }
  flush();
  return count;
}
}  // namespace
void GameRuntime::refresh_debug_log(const QString& module, const QString& level,
                                    const QString& search, const QString& logger) {
  if (closing_ || initializing_ || debug_log_.value("busy").toBool()) return;
  debug_log_["busy"] = true;
  emit debug_log_changed();
  const auto selected = preferences().value("selectedInstance").toString();
  run_file_work(
      [module, level, logger, search = search.left(256), root = game_root_, cache = cache_root_,
       selected, active = launch_id_](const Cancellation& cancelled) {
        QVariantList entries;
        QStringList modules, loggers;
        const auto append = [&](QString origin, QString severity, QString utc, QString message,
                                QString record_logger = {}, QString thread = {}) {
          if (!modules.contains(origin)) modules.append(origin);
          static const QRegularExpression mod_pattern(R"((?:for|from) mod ['"]?([a-zA-Z0-9_.-]+))");
          const auto mod = mod_pattern.match(message).captured(1);
          for (const auto& name : {record_logger, mod})
            if (!name.isEmpty() && !loggers.contains(name)) loggers.append(name);
          const auto searchable = message + ' ' + record_logger + ' ' + thread + ' ' + mod;
          if ((!module.isEmpty() && module != origin) || (!level.isEmpty() && level != severity) ||
              (!logger.isEmpty() && logger != record_logger && logger != mod) ||
              (!search.isEmpty() && !searchable.contains(search, Qt::CaseInsensitive)))
            return;
          entries.append(QVariantMap{{"module", origin},
                                     {"level", severity},
                                     {"time", utc},
                                     {"logger", record_logger},
                                     {"thread", thread},
                                     {"mod", mod},
                                     {"message", redact_diagnostic(message.left(12288))}});
        };
        for (const auto& line : diagnostic_snapshot().split('\n')) {
          check_cancelled(cancelled);
          const auto event = QJsonDocument::fromJson(line).object();
          if (!event.contains("event")) continue;
          const auto name = event.value("event").toString();
          const auto status = event.value("status").toInt();
          const auto state = event.value("state").toString();
          const auto severity =
              !event.value("error").toString().isEmpty() || state == "failed" || status >= 400
                  ? QString("ERROR")
              : name.contains("retry")   ? QString("WARN")
              : name.endsWith("attempt") ? QString("DEBUG")
                                         : QString("INFO");
          append(name.section('.', 0, 0), severity, event.value("utc").toString(),
                 QString::fromUtf8(line));
        }
        const auto tail = [&](const QString& origin, const QString& path) {
          return visit_debug_log(
              path, cancelled,
              [&](auto severity, auto time, auto message, auto record_logger, auto thread) {
                append(origin, severity, time, message, record_logger, thread);
              });
        };
        tail("installer", cache + "/logs/install.log");
        const auto instance = active.isEmpty() ? selected : active;
        if (!instance.isEmpty()) {
          const auto directory = safe_path(root, "versions/" + instance);
          if (!tail("game", directory + "/logs/launcher-game.log"))
            tail("game", directory + "/logs/latest.log");
        }
        modules.sort();
        loggers.sort();
        std::stable_sort(entries.begin(), entries.end(), [](const QVariant& a, const QVariant& b) {
          return QDateTime::fromString(a.toMap().value("time").toString(), Qt::ISODateWithMs) <
                 QDateTime::fromString(b.toMap().value("time").toString(), Qt::ISODateWithMs);
        });
        if (entries.size() > 500) entries = entries.mid(entries.size() - 500);
        return QVariantMap{{"entries", entries},
                           {"modules", modules},
                           {"loggers", loggers},
                           {"instance", instance}};
      },
      [this](const QVariantMap& result) {
        debug_log_ = result;
        debug_log_["busy"] = false;
        emit debug_log_changed();
      });
}
void GameRuntime::export_diagnostics(const QString& url) {
  if (closing_ || initializing_ || diagnostics_status_.value("busy").toBool()) return;
  const QUrl destination(url);
  const auto path = destination.isLocalFile() ? destination.toLocalFile() : url;
  if (!QFileInfo(path).isAbsolute()) {
    emit notice(QCoreApplication::translate("Bugg", "请选择诊断 ZIP 的保存位置"));
    return;
  }
  diagnostics_status_ = {{"busy", true}};
  emit diagnostics_changed();
  QJsonArray tasks;
  for (const auto& value : tasks_) {
    const auto task = value.toMap();
    QJsonObject summary;
    for (const auto* key : {"id", "kind", "name", "state", "detail", "progress"})
      summary[key] = QJsonValue::fromVariant(task.value(key));
    tasks.append(summary);
    if (tasks.size() == 40) break;
  }
  const QJsonObject overview{{"version", QCoreApplication::applicationVersion()},
                             {"qt", qVersion()},
                             {"os", QSysInfo::prettyProductName()},
                             {"architecture", QSysInfo::currentCpuArchitecture()},
                             {"utc", QDateTime::currentDateTimeUtc().toString(Qt::ISODateWithMs)},
                             {"source_order", QJsonArray::fromStringList(source_order_)},
                             {"bugg_origin", diagnostic_url(bugg_base_)},
                             {"concurrency_per_group", preferences().value("concurrency").toInt()},
                             {"launch_state", launch_status_.value("state").toString()},
                             {"tasks", tasks}};
  const auto selected = preferences().value("selectedInstance").toString();
  run_file_work(
      [path, overview, cache = cache_root_, root = game_root_, selected,
       active = launch_id_](const Cancellation& cancelled) {
        QMap<QString, QByteArray> entries;
        entries["diagnostics.json"] =
            redact_diagnostic(QString::fromUtf8(QJsonDocument(overview).toJson())).toUtf8();
        entries["network-current.jsonl"] = diagnostic_snapshot();
        const auto add_log = [&](const QString& name, const QString& file_path) {
          check_cancelled(cancelled);
          QFile file(file_path);
          if (!file.open(QIODevice::ReadOnly)) return;
          constexpr qint64 limit = 1024 * 1024;
          if (file.size() > limit) file.seek(file.size() - limit);
          const auto text = redact_diagnostic(QString::fromUtf8(file.read(limit)));
          entries[name] = text.toUtf8();
        };
        add_log("network-last-checkpoint.jsonl", cache + "/logs/downloads.jsonl");
        add_log("network-previous.jsonl", cache + "/logs/downloads.previous.jsonl");
        add_log("installer.log", cache + "/logs/install.log");
        QStringList instances{active, selected};
        instances.removeAll(QString());
        instances.removeDuplicates();
        for (int i = 0; i < instances.size(); ++i) {
          const auto directory = safe_path(root, "versions/" + instances[i]);
          add_log(QString("game-%1-launcher.log").arg(i), directory + "/logs/launcher-game.log");
          add_log(QString("game-%1-latest.log").arg(i), directory + "/logs/latest.log");
        }
        entries["README.txt"] =
            "Bugg diagnostics (UTF-8). Network journal is bounded to 2 MiB; log tails to 1 MiB.\n"
            "Includes current session, last checkpoint, previous session when available.\n"
            "No account store, full settings, request bodies, auth headers, saves or mod files.\n"
            "URLs omit credentials/query/fragment. Review game log text before sharing publicly.\n";
        archive_write(path, {}, entries, cancelled, [](int, int) {});
        return QVariantMap{{"path", path}};
      },
      [this](const QVariantMap& result) {
        diagnostics_status_ = result;
        diagnostics_status_["busy"] = false;
        emit diagnostics_changed();
        emit notice(result.contains("error")
                        ? result.value("error").toString()
                        : QCoreApplication::translate("Bugg", "诊断日志已导出"));
      });
}
}  // namespace bugg
