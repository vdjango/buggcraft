#include "modules/settings/application/language_service.h"

#include <QCoreApplication>
#include <QFile>
#include <QFileInfo>
#include <QFutureWatcher>
#include <QJsonDocument>
#include <QLocale>
#include <QRegularExpression>
#include <QSaveFile>
#include <QtConcurrent>
#include <algorithm>

#include "platform/files/game_files.h"

static void initialize_language_resources() {
  static const bool initialized = [] {
    Q_INIT_RESOURCE(bugg_languages);
    return true;
  }();
  Q_UNUSED(initialized);
}

namespace bugg {
namespace {
QJsonObject language_resource(const QString& name) {
  initialize_language_resources();
  QFile file(":/bugg/assets/i18n/" + name + ".json");
  if (!file.open(QIODevice::ReadOnly)) return {};
  return QJsonDocument::fromJson(file.readAll()).object();
}
const QJsonObject& language_names() {
  static const auto names = language_resource("languages");
  return names;
}
const QJsonObject& language_packs() {
  static const auto packs = language_resource("packs")["packs"].toObject();
  return packs;
}
}  // namespace
QStringList game_language_codes(const QString& root, const QJsonObject& metadata,
                                QHash<QString, QStringList>* cache) {
  const auto index =
      metadata["assetIndex"].toObject()["id"].toString(metadata["assets"].toString());
  if (index.isEmpty()) return {};
  const auto path = safe_path(root, "assets/indexes/" + index + ".json");
  if (cache) {
    const auto found = cache->constFind(path);
    if (found != cache->cend()) return found.value();
  }
  if (!QFileInfo::exists(path)) return {};
  const auto objects = read_json(path)["objects"].toObject();
  QStringList result{"en_us"};
  for (auto it = objects.begin(); it != objects.end(); ++it) {
    if (!it.key().startsWith("minecraft/lang/") ||
        !(it.key().endsWith(".json") || it.key().endsWith(".lang")))
      continue;
    const auto code = QFileInfo(it.key()).completeBaseName();
    if (code != "deprecated" && !result.contains(code)) result.append(code);
  }
  if (result.size() == 1) result.clear();
  if (cache) cache->insert(path, result);
  return result;
}
void apply_game_options(const QString& root, const QString& instance_id,
                        const QJsonObject& metadata, const QVariantMap& settings) {
  if (!settings.contains("language") && !settings.contains("fullscreen")) return;
  auto code = settings.value("language", "en_us").toString();
  const auto available = game_language_codes(root, metadata);
  if (!available.isEmpty() && !available.contains(code)) code = "en_us";
  const auto path = safe_path(root, "versions/" + instance_id + "/options.txt");
  QFile existing(path);
  QByteArray original;
  if (existing.exists()) {
    if (!existing.open(QIODevice::ReadOnly) || existing.size() > 4 * 1024 * 1024)
      throw std::runtime_error(
          QCoreApplication::translate("Bugg", "无法读取游戏选项").toStdString());
    original = existing.readAll();
    existing.close();
  }
  QMap<QByteArray, QByteArray> changes;
  if (settings.contains("language")) changes["lang"] = code.toUtf8();
  if (settings.contains("fullscreen"))
    changes["fullscreen"] = settings.value("fullscreen").toBool() ? "true" : "false";
  QByteArray data;
  auto remaining = changes;
  for (auto line : original.split('\n')) {
    if (line.endsWith('\r')) line.chop(1);
    const auto at = line.indexOf(':');
    const auto key = at < 0 ? QByteArray() : line.left(at);
    if (changes.contains(key)) {
      if (remaining.contains(key)) {
        data += key + ':' + remaining.take(key) + '\n';
      }
    } else if (!line.isEmpty())
      data += line + '\n';
  }
  for (auto it = remaining.begin(); it != remaining.end(); ++it)
    data += it.key() + ':' + it.value() + '\n';
  if (data == original) return;
  QSaveFile output(path);
  if (!output.open(QIODevice::WriteOnly) || output.write(data) != data.size() || !output.commit())
    throw std::runtime_error(QCoreApplication::translate("Bugg", "无法保存游戏选项").toStdString());
}
LanguageService::LanguageService(QObject* parent, QString cache, QUrl assets)
    : QObject(parent),
      cache_(cache.isEmpty() ? portable_cache_root(QCoreApplication::applicationDirPath())
                             : std::move(cache)),
      assets_(std::move(assets)) {
  initialize_language_resources();
}
LanguageService::~LanguageService() {
  if (cancelled_) cancelled_->store(true);
  if (translator_) QCoreApplication::removeTranslator(translator_.get());
}
bool LanguageService::known_language(const QString& code) {
  initialize_language_resources();
  return code == "zh_cn" || (language_names().contains(code) && language_packs().contains(code));
}
bool LanguageService::set_code(const QString& code) {
  if (closing_ || !known_language(code)) return false;
  if (working_ && requested_ == code && !cancelled_->load()) return true;
  requested_ = code;
  const auto generation = ++generation_;
  if (cancelled_) cancelled_->store(true);
  if (code == code_ || code == "zh_cn") {
    state_ = {{"state", "idle"}};
    if (code != code_) {
      if (translator_) QCoreApplication::removeTranslator(translator_.get());
      translator_.reset();
      translator_data_.clear();
      code_ = code;
      emit changed();
    }
    emit download_changed();
    return true;
  }
  state_ = {{"state", "loading"}};
  emit download_changed();
  // One active worker; a new selection replaces only the pending intent.
  if (working_) return true;
  working_ = true;
  cancelled_ = std::make_shared<std::atomic_bool>(false);
  const auto cancelled = cancelled_;
  const auto cache = cache_;
  const auto pack = language_packs()[code].toObject();
  const auto version = language_resource("packs")["version"].toString();
  const auto url = assets_.resolved(QUrl(version + '/' + pack["file"].toString()));
  auto* watcher = new QFutureWatcher<QVariantMap>(this);
  connect(
      watcher, &QFutureWatcherBase::finished, this, [this, watcher, generation, code, cancelled] {
        const auto result = watcher->result();
        watcher->deleteLater();
        working_ = false;
        if (!closing_ && generation == generation_ && !cancelled->load()) {
          auto data = result.value("data").toByteArray();
          auto replacement = std::make_unique<QTranslator>();
          if (data.isEmpty() ||
              !replacement->load(reinterpret_cast<const uchar*>(data.constData()), data.size())) {
            state_ = {{"state", "error"},
                      {"error", result.value("error", tr("语言包无效，请重试"))}};
          } else {
            QCoreApplication::installTranslator(replacement.get());
            if (translator_) QCoreApplication::removeTranslator(translator_.get());
            translator_ = std::move(replacement);
            translator_data_ = std::move(data);
            code_ = code;
            state_ = {{"state", "idle"}};
            emit changed();
          }
          emit download_changed();
        } else if (!closing_ && requested_ != code_) {
          set_code(requested_);
        }
        emit drained();
      });
  watcher->setFuture(QtConcurrent::run([pack, url, cache, cancelled]() -> QVariantMap {
    try {
      const auto digest = pack["sha256"].toString().toLatin1();
      const auto size = pack["size"].toInteger();
      if (size <= 0 || size > 256 * 1024 || digest.size() != 64)
        throw std::runtime_error("Invalid built-in language manifest");
      const auto path = safe_path(cache, "languages/" + QString::fromLatin1(digest) + ".qm");
      ResourceClient resources({"官方"}, cancelled, [](double, const QString&) {});
      resources.fetch({{url, path, pack["sha1"].toString().toLatin1(), size, {}}});
      if (file_digest(path, "sha256", cancelled) != digest) {
        QFile::remove(path);
        throw std::runtime_error("Language pack checksum mismatch");
      }
      QFile file(path);
      if (!file.open(QIODevice::ReadOnly) || file.size() != size)
        throw std::runtime_error("Cannot read verified language pack");
      const auto data = file.readAll();
      QTranslator validation;
      if (!validation.load(reinterpret_cast<const uchar*>(data.constData()), data.size())) {
        file.close();
        QFile::remove(path);
        throw std::runtime_error("Invalid language pack");
      }
      check_cancelled(cancelled);
      return {{"data", data}};
    } catch (const std::exception&) {
      return {{"error",
               QCoreApplication::translate("LanguageService", "语言包下载失败，请检查网络后重试")}};
    }
  }));
  return true;
}
QVariantMap LanguageService::status() const {
  auto result = state_;
  result["requestedCode"] = requested_;
  return result;
}
void LanguageService::retry() { set_code(requested_); }
void LanguageService::cancel() {
  ++generation_;
  if (cancelled_) cancelled_->store(true);
  requested_ = code_;
  state_ = {{"state", "idle"}};
  emit download_changed();
}
void LanguageService::shutdown() {
  closing_ = true;
  cancel();
}
void LanguageService::relocate_storage(const QString& cache) {
  if (cache == cache_) return;
  const auto selection = requested_;
  cancel();
  cache_ = cache;
  if (selection != code_) set_code(selection);
}
bool LanguageService::complete() const { return code_ == "zh_cn" || bool(translator_); }
bool LanguageService::right_to_left() const {
  return QLocale(code_).textDirection() == Qt::RightToLeft;
}
void LanguageService::set_game_codes(const QStringList& codes) {
  if (game_codes_ == codes) return;
  game_codes_ = codes;
  emit languages_changed();
}
QVariantList LanguageService::options() const {
  QStringList codes{"zh_cn"};
  for (const auto& code : language_names().keys())
    if (language_packs().contains(code)) codes.append(code);
  std::sort(codes.begin(), codes.end(), [](const QString& a, const QString& b) {
    const QStringList preferred{"zh_cn", "en_us", "zh_tw", "zh_hk"};
    const auto rank = [&preferred](const QString& code) {
      const int at = preferred.indexOf(code);
      return at < 0 ? 4 : at;
    };
    return rank(a) == rank(b) ? a < b : rank(a) < rank(b);
  });
  QVariantList result;
  for (const auto& code : codes) {
    const auto entry = language_names().value(code).toObject();
    result.append(QVariantMap{
        {"id", code},
        {"name",
         entry["name"].toString(code) +
             (entry["region"].toString().isEmpty() ? "" : " · " + entry["region"].toString())},
        {"caption", QString()}});
  }
  return result;
}
}  // namespace bugg
