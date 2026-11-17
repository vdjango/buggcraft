#ifndef BUGG_MODULES_LAUNCH_DOMAIN_SERVER_LIST_H_
#define BUGG_MODULES_LAUNCH_DOMAIN_SERVER_LIST_H_
#include <QString>
namespace bugg {
/// Worker-only atomic upsert. Preserves unrelated/unknown NBT data; malformed input throws.
void save_room_server(const QString& directory, const QString& title, const QString& address);
}  // namespace bugg
#endif
