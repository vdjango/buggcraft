#include "modules/update/application/launcher_update_service.h"

#include <QCoreApplication>
#include <QDir>
#include <QFileInfo>
#include <QFutureWatcher>
#include <QJsonArray>
#include <QJsonDocument>
#include <QProcess>
#include <QSysInfo>
#include <QThread>
#include <QUrlQuery>
#include <QVersionNumber>
#include <QtConcurrent>
#include <utility>
#ifdef Q_OS_WIN
#include <windows.h>
#else
#include <signal.h>
#include <unistd.h>
#endif

namespace bugg {
namespace {
bool trusted_asset(const QUrl& url, const QUrl& endpoint) {
  return url.scheme() == endpoint.scheme() && url.host() == endpoint.host() &&
         url.port() == endpoint.port() && url.userInfo().isEmpty() && !url.hasFragment() &&
         url.path().startsWith("/api/launcher/assets/");
}
void update_failure(const QString& message) { throw std::runtime_error(message.toStdString()); }
QString installation_root() {
  const auto path = QCoreApplication::applicationDirPath();
#ifdef Q_OS_MACOS
  if (path.endsWith("/Contents/MacOS")) return path.chopped(15);
#endif
  return path;
}
bool start_update_process(const QString& executable, const QStringList& arguments = {},
                          const QString& root = {}) {
  QProcess process;
  process.setProgram(executable);
  process.setArguments(arguments);
  process.setWorkingDirectory(root);
#ifdef Q_OS_WIN
  process.setCreateProcessArgumentsModifier(
      [](QProcess::CreateProcessArguments* args) { args->flags |= CREATE_NO_WINDOW; });
#endif
  return process.startDetached();
}
}  // namespace
QString LauncherUpdateService::platform_id() {
  const auto arch = QSysInfo::currentCpuArchitecture();
#ifdef Q_OS_WIN
  return arch == "x86_64" ? "windows-x64" : "windows-arm64";
#elif defined(Q_OS_MACOS)
  return arch == "arm64" ? "macos-arm64" : "macos-x86_64";
#else
  return arch == "arm64" ? "linux-arm64" : "linux-x86_64";
#endif
}
LauncherUpdateService::LauncherUpdateService(HttpClient* http, QString cache, QObject* parent,
                                             QUrl endpoint)
    : QObject(parent), http_(http), cache_(std::move(cache)), endpoint_(std::move(endpoint)) {
  connect(http_, &HttpClient::response, this,
          [this](quint64 id, const QByteArray& bytes, const QString& error, int) {
            if (!request_ || id != request_ || closing_) return;
            request_ = 0;
            state_ = {{"state", "latest"}};
            const auto data = QJsonDocument::fromJson(bytes).object();
            if (!error.isEmpty() || !data.contains("update_available")) {
              state_ = {{"state", "error"},
                        {"error", error.isEmpty() ? tr("更新服务响应无效") : error}};
            } else if (data["update_available"].toBool()) {
              const auto version = data["version"].toString();
              const auto asset = data["asset"].toObject();
              const auto url = QUrl(asset["url"].toString());
              const auto hash = asset["sha256"].toString().toLatin1();
              const auto size = asset["size"].toInteger();
              if (QVersionNumber::fromString(version) <= QVersionNumber::fromString(BUGG_VERSION) ||
                  !trusted_asset(url, endpoint_) || size <= 0 || size > 1500000000 ||
                  hash.size() != 64 || QByteArray::fromHex(hash).toHex() != hash) {
                state_ = {{"state", "error"}, {"error", tr("更新包信息无效，请稍后重试")}};
              } else {
                release_ = {{"version", version},
                            {"asset", asset.toVariantMap()},
                            {"notes", data["notes"].toString().left(12000)}};
                state_ = {{"state", "available"},
                          {"automaticPackage", url.path().endsWith(".zip", Qt::CaseInsensitive)}};
                emit update_available(version);
              }
            }
            emit changed();
          });
}
QVariantMap LauncherUpdateService::status() const {
  auto result = state_;
  result["currentVersion"] = BUGG_VERSION;
  result["platform"] = platform_id();
  result["version"] = release_.value("version");
  result["notes"] = release_.value("notes");
  return result;
}
void LauncherUpdateService::check() {
  if (closing_ || request_ || working_ || state_.value("state") == "ready") return;
  release_.clear();
  auto url = endpoint_;
  QUrlQuery query;
  query.addQueryItem("current", BUGG_VERSION);
  query.addQueryItem("platform", platform_id());
  query.addQueryItem("channel", "stable");
  query.addQueryItem("runtime", "cpp");
  url.setQuery(query);
  HttpRequest request;
  request.url = url;
  request.maximum_bytes = 256 * 1024;
  request.headers["Cache-Control"] = "no-cache";
  request.blocked_redirect_hosts = {url.host()};
  request_ = http_->request(request);
  state_ = {{"state", "checking"}};
  emit changed();
}
void LauncherUpdateService::download() {
  if (closing_ || working_ || state_.value("state") != "available" ||
      !state_.value("automaticPackage").toBool())
    return;
  working_ = true;
  cancelled_ = std::make_shared<std::atomic_bool>(false);
  const auto cancelled = cancelled_;
  const auto release = release_;
  const auto cache = cache_;
  const auto root = installation_root();
  const auto executable = QDir(root).relativeFilePath(QCoreApplication::applicationFilePath());
  state_ = {{"state", "downloading"}, {"progress", -1}};
  emit changed();
  auto* watcher = new QFutureWatcher<QVariantMap>(this);
  connect(watcher, &QFutureWatcherBase::finished, this, [this, watcher, cancelled] {
    const auto result = watcher->result();
    watcher->deleteLater();
    working_ = false;
    if (!closing_) {
      state_ = {{"state", cancelled->load()          ? "available"
                          : result.contains("error") ? "error"
                                                     : "ready"},
                {"error", result.value("error")},
                {"automaticPackage", true}};
      plan_path_ = result.value("plan").toString();
      helper_ = result.value("helper").toString();
      emit changed();
    }
    emit drained();
  });
  const auto progress = [this, cancelled](double value, const QString& detail) {
    QMetaObject::invokeMethod(
        this,
        [this, cancelled, value, detail] {
          if (closing_ || cancelled->load() || !working_) return;
          state_["progress"] = value;
          state_["detail"] = detail;
          emit changed();
        },
        Qt::QueuedConnection);
  };
  watcher->setFuture(
      QtConcurrent::run([release, cache, root, executable, cancelled, progress]() -> QVariantMap {
        try {
          const auto asset = release.value("asset").toMap();
          const auto version = release.value("version").toString();
          // Version text never becomes a path; the verified digest scopes staging.
          const auto digest = asset.value("sha256").toByteArray();
          const auto folder = safe_path(cache, "updates/" + QString::fromLatin1(digest));
          const auto archive = folder + "/package.zip";
          ResourceClient resources({"官方"}, cancelled, progress);
          resources.fetch({{QUrl(asset.value("url").toString()),
                            archive,
                            {},
                            asset.value("size").toLongLong(),
                            {}}});
          if (file_digest(archive, "sha256", cancelled) != digest) {
            QFile::remove(archive);
            update_failure(QObject::tr("更新包校验失败，请重新下载"));
          }
          const auto manifest =
              QJsonDocument::fromJson(archive_read(archive, "bugg-update.json")).object();
          if (manifest["format"].toInt() != 1 || manifest["version"].toString() != version ||
              manifest["platform"].toString() != platform_id())
            update_failure(QObject::tr("此安装包不适用于当前原生启动器"));
          auto entries = archive_entries(archive, cancelled);
          entries.removeAll("bugg-update.json");
          QStringList files;
          for (const auto& name : entries) {
            if (name.endsWith('/')) continue;
            const auto top = name.section('/', 0, 0).toLower();
            if (top.startsWith('.') || top.endsWith(".cmd") || top == "versions" || top == "saves")
              update_failure(QObject::tr("更新包包含用户数据或启动入口"));
            files.append(name);
          }
          if (!files.contains(executable) || files.size() > 20000)
            update_failure(QObject::tr("更新包缺少启动程序"));
          const auto stage = folder + "/payload";
          archive_extract(archive, stage, "", {}, cancelled, true);
          // A separate copy runs the helper while payload files are moved into place.
          const auto helper_root = folder + "/helper";
          for (const auto& name : files) {
            const auto source = safe_path(root, name);
            const auto target = safe_path(helper_root, name);
            if (QFileInfo::exists(source) && !QFileInfo::exists(target))
              copy_file(source, target, cancelled);
          }
          const auto helper = safe_path(helper_root, executable);
          QFile::setPermissions(helper, QFile::permissions(safe_path(root, executable)));
          const auto plan = folder + "/install.json";
          write_json(plan, {{"target", root},
                            {"stage", stage},
                            {"backup", folder + "/previous"},
                            {"files", QJsonArray::fromStringList(files)},
                            {"executable", executable},
                            {"pid", QCoreApplication::applicationPid()}});
          return {{"plan", plan}, {"helper", helper}};
        } catch (const std::exception& error) {
          return {{"error", QString::fromUtf8(error.what())}};
        }
      }));
}
void LauncherUpdateService::install() {
  if (closing_ || working_ || state_.value("state") != "ready") return;
  if (!start_update_process(helper_, {"--apply-update", plan_path_})) {
    state_ = {{"state", "error"}, {"error", tr("无法启动更新程序，请重试")}};
    emit changed();
    return;
  }
  emit restart_requested();
}
void LauncherUpdateService::cancel() {
  if (request_) http_->cancel(std::exchange(request_, 0));
  if (cancelled_) cancelled_->store(true);
  if (!working_) {
    state_ = {{"state", "idle"}};
    emit changed();
  }
}
void LauncherUpdateService::shutdown() {
  closing_ = true;
  cancel();
}
int LauncherUpdateService::apply_staged(const QString& path) {
  const auto plan = read_json(path);
  const auto root = plan["target"].toString(), stage = plan["stage"].toString(),
             backup = plan["backup"].toString();
  QStringList moved, installed;
  try {
    const auto pid = plan["pid"].toInteger();
#ifdef Q_OS_WIN
    if (auto process = OpenProcess(SYNCHRONIZE, FALSE, static_cast<DWORD>(pid))) {
      const auto waited = WaitForSingleObject(process, 60000);
      CloseHandle(process);
      if (waited != WAIT_OBJECT_0) return 2;
    }
#else
    for (int elapsed = 0; pid > 0 && kill(pid, 0) == 0 && elapsed < 600; ++elapsed)
      QThread::msleep(100);
    if (pid > 0 && kill(pid, 0) == 0) return 2;
#endif
    for (const auto& item : plan["files"].toArray()) {
      const auto name = item.toString();
      const auto target = safe_path(root, name), source = safe_path(stage, name),
                 previous = safe_path(backup, name);
      QDir().mkpath(QFileInfo(target).absolutePath());
      QDir().mkpath(QFileInfo(previous).absolutePath());
      if (QFile::exists(target)) {
        if (!QFile::rename(target, previous)) update_failure("backup failed");
        moved.append(name);
      }
      if (!QFile::rename(source, target)) update_failure("replacement failed");
      installed.append(name);
    }
    const auto executable = safe_path(root, plan["executable"].toString());
    QFile::setPermissions(executable, QFile::permissions(executable) | QFile::ExeOwner |
                                          QFile::ExeGroup | QFile::ExeOther);
    if (!start_update_process(executable, {}, root)) update_failure("restart failed");
    return 0;
  } catch (...) {
    for (auto it = installed.crbegin(); it != installed.crend(); ++it)
      QFile::remove(safe_path(root, *it));
    for (auto it = moved.crbegin(); it != moved.crend(); ++it)
      QFile::rename(safe_path(backup, *it), safe_path(root, *it));
    write_json(QFileInfo(path).absolutePath() + "/failure.json",
               {{"error", "Update failed; previous files restored"}});
    return 1;
  }
}
}  // namespace bugg
