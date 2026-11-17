#include "server_list.h"

#include <QDataStream>
#include <QFile>
#include <QSaveFile>
#include <stdexcept>

namespace bugg {
namespace {
class NbtCursor {
 public:
  QByteArray bytes;
  qsizetype position = 0;
  explicit NbtCursor(QByteArray value) : bytes(std::move(value)) {}
  QByteArray take(qsizetype count) {
    if (count < 0 || count > bytes.size() - position)
      throw std::runtime_error("Invalid servers.dat");
    const auto result = bytes.mid(position, count);
    position += count;
    return result;
  }
  quint64 number(int size) {
    quint64 result = 0;
    for (unsigned char byte : take(size)) result = (result << 8) | byte;
    return result;
  }
  QByteArray text() { return take(number(2)); }
  void skip(int tag, int depth = 0) {
    if (depth > 32) throw std::runtime_error("servers.dat nesting exceeds limit");
    if (tag >= 1 && tag <= 6) {
      const int sizes[] = {0, 1, 2, 4, 8, 4, 8};
      take(sizes[tag]);
    } else if (tag == 8)
      text();
    else if (tag == 7 || tag == 11 || tag == 12) {
      const auto count = number(4);
      if (count > 4 * 1024 * 1024) throw std::runtime_error("servers.dat array exceeds limit");
      take(count * (tag == 7 ? 1 : tag == 11 ? 4 : 8));
    } else if (tag == 9) {
      const auto child = number(1), count = number(4);
      if (count > 10000 || (!child && count)) throw std::runtime_error("Invalid server list");
      for (quint64 i = 0; i < count; ++i) skip(child, depth + 1);
    } else if (tag == 10) {
      for (int i = 0; i < 10000; ++i) {
        const auto child = number(1);
        if (!child) return;
        text();
        skip(child, depth + 1);
      }
      throw std::runtime_error("servers.dat compound exceeds limit");
    } else
      throw std::runtime_error("Unknown servers.dat tag");
  }
};
QByteArray modified_utf8(QString value) {
  // Java's NBT strings use DataOutput.writeUTF, including surrogate pairs.
  QByteArray bytes;
  for (QChar character : value) {
    const auto unit = character.unicode();
    if (unit > 0 && unit < 128)
      bytes += char(unit);
    else if (unit < 2048) {
      bytes += char(192 | (unit >> 6));
      bytes += char(128 | (unit & 63));
    } else {
      bytes += char(224 | (unit >> 12));
      bytes += char(128 | ((unit >> 6) & 63));
      bytes += char(128 | (unit & 63));
    }
  }
  return bytes;
}
void text(QDataStream& stream, const QByteArray& value) {
  if (value.size() > 65535) throw std::runtime_error("Server name exceeds limit");
  stream << quint16(value.size());
  stream.writeRawData(value.data(), value.size());
}
}  // namespace
void save_room_server(const QString& directory, const QString& title, const QString& address) {
  if (!address.startsWith("127.0.0.1:") || address.section(':', -1).toInt() < 1 ||
      address.section(':', -1).toInt() > 65535)
    throw std::runtime_error("Invalid room address");
  const auto path = directory + "/servers.dat";
  QFile input(path);
  QByteArray extra;
  QList<QByteArray> servers;
  if (input.exists()) {
    if (input.size() > 4 * 1024 * 1024 || !input.open(QIODevice::ReadOnly))
      throw std::runtime_error("Cannot read servers.dat");
    NbtCursor cursor(input.readAll());
    if (cursor.number(1) != 10) throw std::runtime_error("Invalid servers.dat root");
    cursor.text();
    bool found = false;
    while (true) {
      const auto begin = cursor.position;
      const auto tag = cursor.number(1);
      if (!tag) break;
      const auto key = cursor.text();
      if (key == "servers") {
        if (found || tag != 9) throw std::runtime_error("Invalid servers.dat list");
        found = true;
        const auto child = cursor.number(1), count = cursor.number(4);
        if (count > 10000 || (child != 10 && !(child == 0 && count == 0)))
          throw std::runtime_error("Server list exceeds limit");
        for (quint64 i = 0; i < count; ++i) {
          const auto start = cursor.position;
          bool managed = false;
          QByteArray name, ip;
          while (true) {
            const auto type = cursor.number(1);
            if (!type) break;
            const auto key = cursor.text();
            if (key == "buggRoom" && type == 1)
              managed = cursor.number(1) == 1;
            else if (key == "name" && type == 8)
              name = cursor.text();
            else if (key == "ip" && type == 8)
              ip = cursor.text();
            else
              cursor.skip(type);
          }
          // Minecraft rewrites known fields and drops extension tags on exit.
          managed = managed || (name.startsWith("BUGG · ") && ip.startsWith("127.0.0.1:"));
          if (!managed) servers.append(cursor.bytes.mid(start, cursor.position - start));
        }
      } else {
        cursor.skip(tag);
        extra += cursor.bytes.mid(begin, cursor.position - begin);
      }
    }
    if (cursor.position != cursor.bytes.size())
      throw std::runtime_error("Trailing servers.dat data");
  }
  QByteArray room;
  QDataStream entry(&room, QIODevice::WriteOnly);
  entry << quint8(8);
  text(entry, "name");
  text(entry, modified_utf8("BUGG · " + title.left(80)));
  entry << quint8(8);
  text(entry, "ip");
  text(entry, address.toUtf8());
  entry << quint8(1);
  text(entry, "buggRoom");
  entry << quint8(1) << quint8(0);
  servers.prepend(room);
  QByteArray bytes;
  QDataStream output(&bytes, QIODevice::WriteOnly);
  output << quint8(10) << quint16(0) << quint8(9);
  text(output, "servers");
  output << quint8(10) << quint32(servers.size());
  for (const auto& server : servers) output.writeRawData(server.data(), server.size());
  output.writeRawData(extra.data(), extra.size());
  output << quint8(0);
  input.close();
  QSaveFile saved(path);
  if (!saved.open(QIODevice::WriteOnly) || saved.write(bytes) != bytes.size() || !saved.commit())
    throw std::runtime_error("Cannot save room server entry");
}
}  // namespace bugg
