#include "modules/launch/ui/launch_session.h"

#include <QCoreApplication>
#include <array>

namespace bugg {
namespace {
struct Step {
  const char* title;
  const char* detail;
  double progress;
};
const std::array<Step, 4> kSteps{{
    {QT_TRANSLATE_NOOP("Bugg", "正在确认游戏身份"),
     QT_TRANSLATE_NOOP("Bugg", "检查本次使用的游戏账号"), 0.08},
    {QT_TRANSLATE_NOOP("Bugg", "正在准备运行环境"),
     QT_TRANSLATE_NOOP("Bugg", "匹配适合这个版本的 Java"), 0.32},
    {QT_TRANSLATE_NOOP("Bugg", "正在检查游戏文件"),
     QT_TRANSLATE_NOOP("Bugg", "确认核心、加载器和运行库已就绪"), 0.66},
    {QT_TRANSLATE_NOOP("Bugg", "正在打开你的世界"),
     QT_TRANSLATE_NOOP("Bugg", "准备完成，正在等待游戏窗口"), 0.94},
}};
}  // namespace

LaunchSession::LaunchSession(QObject* parent) : QObject(parent) {
  timer_.setInterval(1700);
  connect(&timer_, &QTimer::timeout, this, &LaunchSession::advance);
}

void LaunchSession::set_service(QObject* service) {
  auto* port = qobject_cast<GameRuntimePort*>(service);
  if (service_ == port) return;
  if (service_) disconnect(service_, nullptr, this, nullptr);
  service_ = port;
  if (service_)
    connect(service_, &GameRuntimePort::launch_changed, this, [this](const QVariantMap& state) {
      status_ = state;
      emit status_changed();
    });
  emit status_changed();
}

QString LaunchSession::preflight() const {
  return identity_status_.value("ready").toBool()
             ? QString()
             : QCoreApplication::translate("Bugg", "请先选择游戏身份");
}

void LaunchSession::start(int index, const QVariantMap& contributions) {
  if (status_["state"] != "idle" && status_["state"] != "failed") return;
  // The same identity confirmation drives both the button and the launch entry.
  if (!preflight().isEmpty()) {
    emit identity_required();
    return;
  }
  if (index < 0 || index >= instances_.size()) {
    fail(QCoreApplication::translate("Bugg", "无法找到所选游戏，请重新选择"));
    return;
  }
  if (service_) {
    service_->launch(instances_[index].toMap().value("id").toString(),
                     identity_status_.value("selectedId").toString(), contributions);
    return;
  }
  if (!preview_enabled_) {
    fail(QCoreApplication::translate("Bugg", "游戏启动服务尚未接入，未创建游戏进程"));
    return;
  }
  index_ = index;
  step_ = 0;
  show_step();
  if (automatic_) timer_.start();
}

void LaunchSession::show(const QString& state, const QString& title, const QString& detail,
                         double progress, const QString& stage) {
  status_ = {{"state", state},
             {"title", title},
             {"detail", detail},
             {"progress", progress},
             {"stage", stage},
             {"preview", preview_enabled_},
             {"instanceName", index_ >= 0 && index_ < instances_.size()
                                  ? instances_[index_].toMap().value("name")
                                  : QVariant()}};
  emit status_changed();
}

void LaunchSession::show_step() {
  const auto& step = kSteps[step_];
  show("preparing", QCoreApplication::translate("Bugg", step.title),
       QCoreApplication::translate("Bugg", step.detail), step.progress,
       QString("%1 / %2").arg(step_ + 1).arg(kSteps.size()));
}

void LaunchSession::advance() {
  if (status_["state"] == "stopping") {
    finish();
  } else if (status_["state"] == "preparing") {
    if (++step_ < static_cast<int>(kSteps.size())) {
      show_step();
    } else {
      timer_.stop();
      show("running", QCoreApplication::translate("Bugg", "世界已就绪"),
           QCoreApplication::translate("Bugg", "启动流程演示完成，未运行真实游戏"), 1);
    }
  }
}

void LaunchSession::cancel() {
  if (service_) {
    service_->cancel_launch();
    return;
  }
  if (status_["state"] == "preparing" || status_["state"] == "failed") finish();
}

void LaunchSession::stop() {
  if (service_) {
    service_->stop_game();
    return;
  }
  if (status_["state"] != "running") return;
  show("stopping", QCoreApplication::translate("Bugg", "正在结束游戏"),
       QCoreApplication::translate("Bugg", "等待游戏退出后恢复选择"));
  if (automatic_) timer_.start(600);
}

void LaunchSession::finish() {
  timer_.stop();
  timer_.setInterval(1700);
  show("idle");
}

void LaunchSession::fail(const QString& reason) {
  timer_.stop();
  show("failed", QCoreApplication::translate("Bugg", "启动暂未完成"), reason);
}

}  // namespace bugg
