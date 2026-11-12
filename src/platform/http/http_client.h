#ifndef BUGG_PLATFORM_HTTP_HTTP_CLIENT_H_
#define BUGG_PLATFORM_HTTP_HTTP_CLIENT_H_

#include <QHash>
#include <QMap>
#include <QNetworkAccessManager>
#include <QObject>
#include <QPointer>
#include <QStringList>
#include <QUrl>

class QNetworkReply;

namespace bugg {

/// 正毫秒时限；生产默认允许镜像首次回源，测试可注入短时限。
struct HttpTimeouts {
  int idle_ms = 15000;
  int total_ms = 45000;
};

/// 请求机制，不包含来源策略。output_path 非空仅允许工作线程使用；校验后原子落盘。
struct HttpRequest {
  QUrl url;
  QByteArray method = "GET";
  QByteArray body;
  /// 仅此请求的显式信任锚；空值使用系统 CA，仍校验证书链、有效期与主机名。
  QByteArray ca_pem;
  QString input_path;
  QMap<QByteArray, QByteArray> headers;
  QStringList blocked_redirect_hosts;
  QString output_path;
  /// 非空才流式计算并核对 SHA-1；大小/响应上限始终按各自字段执行。
  QByteArray sha1;
  qint64 expected_size = -1;
  qint64 maximum_bytes = 8 * 1024 * 1024;
  int total_ms = 45000;
  /// Optional cold-origin first body allowance; after data arrives idle_ms applies.
  int first_byte_ms = 0;
  /// Known large files may use three same-origin byte ranges; callers may disable.
  bool parallel_ranges = true;
  /// Worker file GET with an explicit SHA-1/size may retain verified-identity partial bytes.
  bool resume = false;
  /// Internal range response contract; empty for normal requests.
  QByteArray expected_range;
};

/// 所在线程异步 HTTP 传输；仅提供网络机制，来源策略归调用方。
/// QObject 父子关系释放请求；cancel 先撤销订阅再 abort，不等待网络。
class HttpClient : public QObject {
  Q_OBJECT
 public:
  explicit HttpClient(QObject* parent = nullptr, HttpTimeouts timeouts = {});
  /// 接受 HTTP(S)，默认 15 秒无进展/45 秒总超时；8 MiB 上限；TLS 错误不会忽略。
  /// 返回客户端生成的 ID；所有成功/失败均在事件循环返回，不同步发信号。
  virtual quint64 get(const QUrl& url, const QStringList& blocked_redirect_hosts = {});
  /// 异步请求；错误响应仍返回有限 body 和状态码，供 OAuth 轮询。绝不记录凭据。
  /// cancel 撤销所有完成通知；落盘、哈希仅在工作线程调用。
  virtual quint64 request(const HttpRequest& request);
  virtual void cancel(quint64 request_id);
 signals:
  void completed(quint64 request_id, const QByteArray& body, const QString& error);
  void response(quint64 request_id, const QByteArray& body, const QString& error, int status);
  void progress(quint64 request_id, qint64 received, qint64 total);
  /// 连接/DNS/TLS/传输超时；供资源所有者短暂回避故障 origin。取消/HTTP/磁盘错误不发。
  void unreachable(const QUrl& url);
  /// Network interruption, including after HTTP 200; never integrity/disk failures.
  void transient_failure(quint64 request_id);
  /// Cached bytes restored for this attempt; not new network throughput.
  void resumed(quint64 request_id, qint64 bytes);

 private:
  void start_request(quint64 id, const HttpRequest& request);
  /// Worker file request, same cancellation/response ID; falls back if Range is refused.
  void ranged_request(quint64 id, const HttpRequest& request);
  QNetworkAccessManager manager_;
  HttpTimeouts timeouts_;
  QHash<quint64, QPointer<QNetworkReply>> pending_;
  QHash<quint64, QList<quint64>> range_children_;
  QHash<quint64, QObject*> range_scopes_;
  quint64 sequence_ = 0;
  QString diagnostic_id_;
};

}  // namespace bugg
#endif  // BUGG_PLATFORM_HTTP_HTTP_CLIENT_H_
