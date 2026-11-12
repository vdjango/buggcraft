#ifndef BUGG_TESTS_LANGUAGE_ASSET_SERVER_H_
#define BUGG_TESTS_LANGUAGE_ASSET_SERVER_H_
#include <QCoreApplication>
#include <QFile>
#include <QTcpServer>
#include <QTcpSocket>
#include <QTimer>
#include <QUrl>
namespace bugg {
// Serves the actual build sidecars; corruption/delay exercise the same download path.
class LanguageAssetServer : public QTcpServer {
 public:
  int requests = 0, delay_ms = 0;
  bool corrupt = false;
  QStringList paths;
  LanguageAssetServer() {
    connect(this, &QTcpServer::newConnection, this, [this] {
      while (hasPendingConnections()) {
        auto* socket = nextPendingConnection();
        connect(socket, &QTcpSocket::readyRead, socket, [this, socket] {
          auto request = socket->property("request").toByteArray() + socket->readAll();
          socket->setProperty("request", request);
          if (!request.contains("\r\n\r\n") || socket->property("answered").toBool()) return;
          socket->setProperty("answered", true);
          const auto path = QString::fromLatin1(request.split(' ').value(1));
          paths.append(path);
          ++requests;
          const auto name = path.section('/', -1);
          QFile file(QCoreApplication::applicationDirPath() + "/language-assets/" + name);
          const bool valid = name.startsWith("Bugg-language-") && !name.contains("..") &&
                             file.open(QIODevice::ReadOnly);
          auto data = valid ? file.readAll() : QByteArray("missing");
          if (corrupt && !data.isEmpty()) data[data.size() / 2] ^= 1;
          QTimer::singleShot(delay_ms, socket, [socket, data, valid] {
            if (socket->state() != QAbstractSocket::ConnectedState) return;
            socket->write(QByteArray(valid ? "HTTP/1.1 200 OK\r\n" : "HTTP/1.1 404 Missing\r\n") +
                          "Content-Length: " + QByteArray::number(data.size()) +
                          "\r\nConnection: close\r\n\r\n" + data);
            socket->disconnectFromHost();
          });
        });
        connect(socket, &QTcpSocket::disconnected, socket, &QObject::deleteLater);
      }
    });
  }
  QUrl origin() const { return QUrl("http://127.0.0.1:" + QString::number(serverPort()) + '/'); }
};
}  // namespace bugg
#endif
