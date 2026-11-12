#ifndef BUGG_MODULES_SETTINGS_APPLICATION_LANGUAGE_SERVICE_H_
#define BUGG_MODULES_SETTINGS_APPLICATION_LANGUAGE_SERVICE_H_
#include <QHash>
#include <QJsonObject>
#include <QTranslator>
#include <QVariantList>
#include <memory>

#include "modules/game_install/infrastructure/resource_client.h"

namespace bugg {
/// 工作线程读取已安装资产索引；空列表表示尚无可用索引，不能假定游戏不支持其他语言。
/// cache 可选，仅限同一工作线程的一次扫描；按完整安全路径复用成功结果，下次扫描丢弃。
QStringList game_language_codes(const QString& root, const QJsonObject& metadata,
                                QHash<QString, QStringList>* cache = nullptr);
/// 工作线程、原子更新 options.txt；保留未知设置，按当前游戏支持范围回退语言。
void apply_game_options(const QString& root, const QString& instance_id,
                        const QJsonObject& metadata, const QVariantMap& settings);

/// 应用唯一译文所有者；后台校验/下载单个版本固定的 QM，GUI 成功后原位重译。
/// 失败保留当前语言；退出须经 shutdown/drained，不在 GUI 等待网络或工作线程。
class LanguageService : public QObject {
  Q_OBJECT
  Q_PROPERTY(QString code READ code NOTIFY changed)
  Q_PROPERTY(QVariantList options READ options NOTIFY languages_changed)
  Q_PROPERTY(QStringList game_codes READ game_codes WRITE set_game_codes NOTIFY languages_changed)
  Q_PROPERTY(bool right_to_left READ right_to_left NOTIFY changed)
  Q_PROPERTY(bool complete READ complete NOTIFY changed)
  Q_PROPERTY(QVariantMap status READ status NOTIFY download_changed)
 public:
  explicit LanguageService(QObject* parent = nullptr, QString cache = {},
                           QUrl assets = QUrl("https://download.bugg.icu/api/launcher/assets/"));
  ~LanguageService() override;
  QString code() const { return code_; }
  QVariantList options() const;
  QStringList game_codes() const { return game_codes_; }
  bool right_to_left() const;
  bool complete() const;
  /// GUI 接受选择后异步获取；true 表示已接受，成功以 code/changed 为准。
  Q_INVOKABLE bool set_code(const QString& code);
  Q_INVOKABLE void set_game_codes(const QStringList& codes);
  QVariantMap status() const;
  Q_INVOKABLE void retry();
  Q_INVOKABLE void cancel();
  void relocate_storage(const QString& cache);
  void shutdown();
  bool busy() const { return working_; }
  static bool known_language(const QString& code);
 signals:
  void changed();
  void languages_changed();
  void download_changed();
  void drained();

 private:
  QString code_ = "zh_cn";
  QStringList game_codes_;
  std::unique_ptr<QTranslator> translator_;
  QByteArray translator_data_;
  QString cache_, requested_ = "zh_cn";
  QUrl assets_;
  QVariantMap state_{{"state", "idle"}};
  Cancellation cancelled_;
  quint64 generation_ = 0;
  bool working_ = false, closing_ = false;
};
}  // namespace bugg
#endif
