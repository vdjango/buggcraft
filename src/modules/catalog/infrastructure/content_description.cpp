#include "modules/catalog/infrastructure/content_description.h"

#include <QCoreApplication>
#include <QMap>
#include <QRegularExpression>
#include <QTextBlock>
#include <QTextCursor>
#include <QTextDocument>
#include <QTextDocumentFragment>
#include <QTextImageFormat>

namespace bugg {
QVariantList content_description(const QString& body, bool markdown, const QUrl& base) {
  QTextDocument document;
  QFont font;
  font.setPixelSize(14);
  document.setDefaultFont(font);
  document.setBaseUrl(base);
  const auto source = body.left(256 * 1024);
  QMap<QString, QString> image_links;
  if (markdown) {
    // Qt 6.8 drops the anchor of Markdown linked images. Recover just that
    // metadata before the existing document parser handles the actual article.
    static const QRegularExpression linked_image(
        R"(\[!\[[^\]\n]*\]\((https?://[^\s)]+)\)\]\((https?://[^\s)]+)\))");
    auto matches = linked_image.globalMatch(source);
    while (matches.hasNext() && image_links.size() < 32) {
      const auto match = matches.next();
      image_links[match.captured(1)] = match.captured(2);
    }
  }
  // Modrinth also publishes HTML descriptions in its Markdown field. Qt 6.8's
  // Markdown importer loses nested HTML containers; use its HTML importer for
  // those documents rather than returning an empty or incomplete description.
  if (!markdown || Qt::mightBeRichText(source))
    document.setHtml(source);
  else
    document.setMarkdown(source);
  QVariantList result;
  int start = 0, images = 0;
  const auto append_text = [&](int end) {
    if (end <= start) return;
    QTextCursor cursor(&document);
    cursor.setPosition(start);
    cursor.setPosition(end, QTextCursor::KeepAnchor);
    if (!cursor.selection().toPlainText().trimmed().isEmpty())
      result.append(QVariantMap{{"html", cursor.selection().toHtml()}});
  };
  for (auto block = document.begin(); block.isValid(); block = block.next())
    for (auto it = block.begin(); !it.atEnd(); ++it) {
      const auto fragment = it.fragment();
      if (!fragment.charFormat().isImageFormat()) continue;
      append_text(fragment.position());
      const auto format = fragment.charFormat().toImageFormat();
      const auto url = base.resolved(QUrl(format.name()));
      if (images < 32 && (url.scheme() == "https" || url.scheme() == "http")) {
        QVariantMap picture{{"image", url.toString()}};
        if (format.width() > 0) picture["width"] = format.width();
        if (format.height() > 0) picture["height"] = format.height();
        if (block.blockFormat().alignment().testFlag(Qt::AlignHCenter))
          picture["alignment"] = "center";
        else if (block.blockFormat().alignment().testFlag(Qt::AlignRight))
          picture["alignment"] = "right";
        const auto href = fragment.charFormat().anchorHref().isEmpty()
                              ? image_links.value(url.toString())
                              : fragment.charFormat().anchorHref();
        const auto link = base.resolved(QUrl(href));
        if (!href.isEmpty() && (link.scheme() == "https" || link.scheme() == "http"))
          picture["link"] = link.toString();
        result.append(picture);
        ++images;
      }
      start = fragment.position() + fragment.length();
    }
  append_text(document.characterCount() - 1);
  return result;
}
QString content_category_name(const QString& slug, const QString& fallback) {
  // These are display translations, never a second catalogue of category IDs.
  static const QMap<QString, const char*> names{{"adventure", "冒险"},
                                                {"categories", "内容类型"},
                                                {"resolutions", "分辨率"},
                                                {"features", "特色"},
                                                {"performance impact", "性能需求"},
                                                {"minecraft_server_meta", "服务器类型"},
                                                {"minecraft_server_gameplay", "服务器玩法"},
                                                {"minecraft_server_features", "服务器特色"},
                                                {"minecraft_server_community", "服务器社区"},
                                                {"blood-magic", "血魔法"},
                                                {"create", "机械动力"},
                                                {"integrated-dynamics", "集成动力"},
                                                {"galacticraft", "星系"},
                                                {"applied-energistics-2", "应用能源 2"},
                                                {"kubejs", "KubeJS 脚本"},
                                                {"addons-tinkers-construct", "匠魂附属"},
                                                {"addons-industrialcraft", "工业时代附属"},
                                                {"addons-buildcraft", "建筑工艺附属"},
                                                {"crafttweaker", "魔改工具"},
                                                {"addons-thermalexpansion", "热力膨胀附属"},
                                                {"modjam-2025", "模组创作活动 2025"},
                                                {"addons-forestry", "林业附属"},
                                                {"twilight-forest", "暮色森林"},
                                                {"addons-thaumcraft", "神秘时代附属"},
                                                {"twitch-integration", "直播联动"},
                                                {"refined-storage", "精致存储"},
                                                {"farmers-delight", "农夫乐事"},
                                                {"ftb-official-pack", "FTB 官方整合包"},
                                                {"mini-game", "小游戏"},
                                                {"rlcraft", "RLCraft 整合包"},
                                                {"adventure-rpg", "冒险 / RPG"},
                                                {"technology", "科技"},
                                                {"tech", "科技"},
                                                {"adventure-and-rpg", "冒险 / RPG"},
                                                {"combat-pvp", "PvP 战斗"},
                                                {"map-based", "地图"},
                                                {"horror", "恐怖"},
                                                {"expert", "专家"},
                                                {"vanilla", "原版风格"},
                                                {"world-mobs", "生物"},
                                                {"world-ores-resources", "矿物与资源"},
                                                {"mc-food", "食物"},
                                                {"utility-qol", "便利优化"},
                                                {"server-utility", "服务器工具"},
                                                {"map-information", "地图与信息"},
                                                {"technology-farming", "农业"},
                                                {"technology-automation", "自动化"},
                                                {"technology-genetics", "基因"},
                                                {"technology-player-transport", "交通运输"},
                                                {"technology-processing", "加工"},
                                                {"mc-addons", "附属模组"},
                                                {"mc-miscellaneous", "其他"},
                                                {"education", "教育"},
                                                {"creativemode", "创造模式"},
                                                {"mc-creator", "模组创作工具"},
                                                {"bug-fixes", "问题修复"},
                                                {"miscellaneous", "其他"},
                                                {"sixteen-x", "16× 分辨率"},
                                                {"thirty-two-x", "32× 分辨率"},
                                                {"sixty-four-x", "64× 分辨率"},
                                                {"one-twenty-eight-x", "128× 分辨率"},
                                                {"two-fifty-six-x", "256× 分辨率"},
                                                {"five-twelve-x-and-beyond", "512× 及以上"},
                                                {"photo-realistic", "写实"},
                                                {"traditional", "传统风格"},
                                                {"font-packs", "字体"},
                                                {"mod-support", "模组支持"},
                                                {"medieval", "中世纪"},
                                                {"modern", "现代"},
                                                {"steampunk", "蒸汽朋克"},
                                                {"data-packs", "数据包"},
                                                {"animated", "动画"},
                                                {"magic", "魔法"},
                                                {"worldgen", "世界生成"},
                                                {"world-gen", "世界生成"},
                                                {"world-biomes", "群系"},
                                                {"world-structures", "结构"},
                                                {"world-dimensions", "维度"},
                                                {"mobs", "生物"},
                                                {"food", "食物"},
                                                {"food-farming", "食物与农业"},
                                                {"storage", "存储"},
                                                {"storage-transport", "存储与物流"},
                                                {"transportation", "交通运输"},
                                                {"technology-energy", "能源"},
                                                {"technology-item-fluid-energy-transport", "物流"},
                                                {"equipment", "装备"},
                                                {"armor-weapons-tools", "装备与工具"},
                                                {"utility", "实用工具"},
                                                {"optimization", "优化"},
                                                {"performance", "性能优化"},
                                                {"decoration", "装饰"},
                                                {"cosmetic", "装饰"},
                                                {"library", "前置与 API"},
                                                {"library-api", "前置与 API"},
                                                {"game-mechanics", "游戏机制"},
                                                {"redstone", "红石"},
                                                {"social", "社交"},
                                                {"economy", "经济"},
                                                {"management", "管理"},
                                                {"minigame", "小游戏"},
                                                {"quests", "任务"},
                                                {"challenging", "硬核挑战"},
                                                {"hardcore", "硬核"},
                                                {"lightweight", "轻量"},
                                                {"small-light", "轻量"},
                                                {"extra-large", "大型"},
                                                {"kitchen-sink", "综合"},
                                                {"multiplayer", "多人"},
                                                {"combat", "战斗"},
                                                {"skyblock", "空岛"},
                                                {"exploration", "探索"},
                                                {"sci-fi", "科幻"},
                                                {"cursed", "恶搞"},
                                                {"realistic", "写实"},
                                                {"semi-realistic", "半写实"},
                                                {"vanilla-like", "原版风格"},
                                                {"simplistic", "简约"},
                                                {"themed", "主题"},
                                                {"models", "模型"},
                                                {"blocks", "方块"},
                                                {"items", "物品"},
                                                {"entities", "实体"},
                                                {"environment", "环境"},
                                                {"fonts", "字体"},
                                                {"gui", "界面"},
                                                {"audio", "音效"},
                                                {"locale", "语言"},
                                                {"modded", "模组支持"},
                                                {"tweaks", "细节调整"},
                                                {"atmosphere", "氛围"},
                                                {"bloom", "泛光"},
                                                {"cartoon", "卡通"},
                                                {"colored-lighting", "彩色光照"},
                                                {"fantasy", "幻想"},
                                                {"foliage", "植被"},
                                                {"path-tracing", "路径追踪"},
                                                {"pbr", "PBR 材质"},
                                                {"reflections", "反射"},
                                                {"shadows", "阴影"},
                                                {"screenshot", "摄影"},
                                                {"high", "高配置"},
                                                {"medium", "中等配置"},
                                                {"low", "低配置"},
                                                {"potato", "极低配置"}};
  const auto found = names.constFind(slug);
  return found == names.cend() ? fallback : QCoreApplication::translate("ContentCategory", *found);
}
}  // namespace bugg
