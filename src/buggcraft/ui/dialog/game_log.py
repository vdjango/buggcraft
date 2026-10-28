"""Bounded, filterable game output with escaped semantic syntax highlighting."""
import html
import re

from PySide6.QtCore import QAbstractListModel, QModelIndex, Property, Qt, Signal, Slot
from PySide6.QtWidgets import QFileDialog

from utils.clipboard import copy_text


LEVEL_COLORS = {'TRACE': '#8b91a7', 'DEBUG': '#a3a8be', 'INFO': '#7dc9eb',
                'WARN': '#f1ca79', 'ERROR': '#ff8f9c', 'FATAL': '#ff6f91'}
LEVELS = ['全部级别', '警告与错误', 'ERROR / FATAL', 'INFO', 'DEBUG / TRACE']
CATEGORIES = ['全部分类', '模组', '加载器', 'Java', '网络', '渲染', '游戏', '启动器']
ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')
LEVEL = re.compile(r'\b(TRACE|DEBUG|INFO|WARN(?:ING)?|ERROR|FATAL)\b', re.I)
TOKEN = re.compile(r'(?P<time>\b\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\b)'
                   r'|(?P<error>\b[\w.$]*(?:Exception|Error)\b|\bCaused by\b|\bFAILED\b)'
                   r'|(?P<url>https?://[^\s<>]+)'
                   r'|(?P<string>"[^"\r\n]*"|\x27[^\x27\r\n]*\x27)'
                   r'|(?P<namespace>\b[\w.-]+:[\w/.-]+\b)'
                   r'|(?P<number>\b\d+(?:\.\d+)*\b)')
TOKEN_COLORS = dict(time='#8397bf', error='#ff8f9c', url='#77d4db',
                    string='#a8d995', namespace='#c4a4ff', number='#e6bc7c')


def parse_line(text, previous=None):
    text = ANSI.sub('', str(text))
    # Launcher session labels precede every line, including Java stack frames.
    # Keep that label on screen but parse the original game output underneath.
    payload = re.sub(r'^\[游戏\s+\d+\s*·\s*[^\]]+\]\s*', '', text)
    match = LEVEL.search(payload[:240])
    continuation = bool(previous and not match and
                        re.match(r'^\s*(?:at |Caused by:|Suppressed:|\.\.\.)', payload))
    level = match.group(1).upper().replace('WARNING', 'WARN') if match else (
        previous['level'] if continuation else 'ERROR' if re.search(r'Exception|Error:', payload) else 'INFO')
    logger = ''
    if match:
        suffix = payload[match.end():]
        source = re.match(r'\]\s*\[([^\]]+)\]', suffix)
        if source:
            logger = source.group(1).rstrip(':').split('/')[0]
    if not logger:
        source = re.search(r'\[(?:[^\]]*/)?([^\]/]+)\]:', payload[:240])
        if source and not LEVEL.search(source.group(1)):
            logger = source.group(1)
    lower = (logger + ' ' + payload).lower()
    if continuation:
        category, logger = previous['category'], previous['logger']
    elif re.search(r'fabricloader|modlauncher|forge|neoforge|quilt.loader|loading.*mods|mixin', lower):
        category = '加载器'
    elif logger and not re.match(r'^(?:minecraft|mojang|net\.minecraft|com\.mojang|main|client|server|system)', logger, re.I):
        # A mod may log from the render/network thread. Its explicit logger
        # stays selectable as mod output regardless of that thread or message.
        category = '模组'
    elif re.search(r'opengl|glfw|renderer|render thread|shader|textures/atlas', lower):
        category = '渲染'
    elif re.search(r'netty|socket|connection|network|服务器|连接失败', lower):
        category = '网络'
    elif re.search(r'java\.|javax\.|jvm|outofmemory|虚拟机', lower):
        category = 'Java'
    elif re.search(r'\bmods?\b|模组', lower):
        category = '模组'
    elif re.search(r'buggcraft|启动器', lower):
        category = '启动器'
    else:
        category = '游戏'
    return dict(text=text, level=level, logger=logger or 'Minecraft', category=category)


def highlight(text):
    parts, start = [], 0
    for match in TOKEN.finditer(text):
        parts.append(html.escape(text[start:match.start()]))
        parts.append('<font color="' + TOKEN_COLORS[match.lastgroup] + '">' + html.escape(match.group()) + '</font>')
        start = match.end()
    parts.append(html.escape(text[start:]))
    return ''.join(parts)


class GameLogModel(QAbstractListModel):
    changed = Signal()
    roles = {Qt.UserRole + i: name.encode() for i, name in enumerate(
        ('lineNumber', 'body', 'severity', 'tint', 'category', 'logger'), 1)}

    def __init__(self, parent):
        super().__init__(parent)
        self.entries, self.visible_rows = [], []
        self.query = self.error = self.notice = ''
        self.level_index = self.category_index = 0
        self.logger_filter = '全部来源'
        self.regex = self.paused = False
        self.follow = True
        self.sequence = 0

    def roleNames(self):
        return self.roles

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.visible_rows)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.visible_rows):
            return None
        row = self.visible_rows[index.row()]
        key = self.roles.get(role, b'').decode()
        return dict(lineNumber=row['number'], body=highlight(row['text']), severity=row['level'],
                    tint=LEVEL_COLORS[row['level']], category=row['category'], logger=row['logger']).get(key)

    @Property('QVariantMap', notify=changed)
    def view(self):
        return dict(total=len(self.entries), shown=len(self.visible_rows), levels=LEVELS, categories=CATEGORIES,
                    loggers=['全部来源'] + sorted({row['logger'] for row in self.entries}),
                    errors=sum(row['level'] in ('ERROR', 'FATAL') for row in self.entries),
                    warnings=sum(row['level'] == 'WARN' for row in self.entries), error=self.error,
                    notice=self.notice, paused=self.paused, follow=self.follow)

    def append(self, lines):
        for raw in lines:
            for line in str(raw).splitlines() or ['']:
                row = parse_line(line, self.entries[-1] if self.entries else None)
                self.sequence += 1
                self.entries.append(dict(row, number=self.sequence))
        del self.entries[:-5000]
        if not self.paused:
            self.refilter()
        else:
            self.changed.emit()

    def refilter(self):
        self.error = ''
        pattern = None
        if self.query and self.regex:
            try:
                pattern = re.compile(self.query, re.I)
            except re.error as exc:
                self.error = '正则表达式无效：' + str(exc)
        allowed = [None, {'WARN', 'ERROR', 'FATAL'}, {'ERROR', 'FATAL'},
                   {'INFO'}, {'DEBUG', 'TRACE'}][self.level_index]
        category = CATEGORIES[self.category_index]
        rows = []
        for row in self.entries:
            if allowed and row['level'] not in allowed:
                continue
            if self.category_index and row['category'] != category:
                continue
            if self.logger_filter != '全部来源' and row['logger'] != self.logger_filter:
                continue
            if self.error or self.query and not (pattern.search(row['text']) if pattern else
                                                  self.query.casefold() in row['text'].casefold()):
                continue
            rows.append(row)
        self.beginResetModel()
        self.visible_rows = rows
        self.endResetModel()
        self.changed.emit()

    @Slot(str)
    def search(self, value):
        self.query = value
        self.refilter()

    @Slot(int)
    def selectLevel(self, index):
        if 0 <= index < len(LEVELS):
            self.level_index = index
            self.refilter()

    @Slot(int)
    def selectCategory(self, index):
        if 0 <= index < len(CATEGORIES):
            self.category_index = index
            self.refilter()

    @Slot(str)
    def selectLogger(self, value):
        self.logger_filter = value
        self.refilter()

    @Slot(bool)
    def useRegex(self, value):
        self.regex = value
        self.refilter()

    @Slot()
    def togglePaused(self):
        self.paused = not self.paused
        if not self.paused:
            self.refilter()
        else:
            self.changed.emit()

    @Slot(bool)
    def setFollow(self, value):
        self.follow = value
        self.changed.emit()

    def filtered_text(self):
        return '\n'.join(row['text'] for row in self.visible_rows)

    @Slot()
    def copyVisible(self):
        copy_text(self, self.filtered_text(), lambda: self._notice('已复制筛选结果'),
                  lambda: self._notice('复制失败，请重试'))

    def _notice(self, value):
        self.notice = value
        self.changed.emit()

    @Slot()
    def saveVisible(self):
        path, _ = QFileDialog.getSaveFileName(self.parent(), '导出筛选日志', 'minecraft-filtered.log',
                                             '日志 (*.log);;文本 (*.txt)')
        if path:
            try:
                from pathlib import Path
                Path(path).write_text(self.filtered_text() + '\n', encoding='utf-8')
                self._notice('已导出筛选结果')
            except OSError as exc:
                self._notice('导出失败：' + str(exc))
