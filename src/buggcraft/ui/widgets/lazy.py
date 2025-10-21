from PySide6.QtCore import QTimer, QObject, Signal, Qt
from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget, QLabel, QFrame

class LazyGameLoader(QObject):
    """懒加载游戏列表管理器（无分页控件版）"""
    
    loading_started = Signal()
    loading_finished = Signal()
    items_added = Signal(int, int)  # 起始索引, 结束索引
    
    def __init__(self, games_content: QScrollArea, minecraft_versions, create_item_func, parent=None):
        """
        初始化懒加载管理器
        
        Args:
            games_content: QScrollArea对象，游戏内容区域
            minecraft_versions: 游戏数据列表
            create_item_func: 创建游戏项的函数
        """
        super().__init__(parent)
        self.games_content: QScrollArea = games_content
        self.minecraft_versions = minecraft_versions
        self.create_item_func = create_item_func
        self.loaded_count = 0
        self.batch_size = 20  # 每次加载的项目数量
        self.is_loading = False
        
        # 获取滚动区域和内容布局
        self.scroll_area = games_content
        self.container = self.scroll_area.widget()
        self.layout = self.container.layout()
        
        # 清除现有内容（保留布局）
        self.clear_existing_items()
        
        # 添加加载指示器
        self.add_loading_indicator()
        
        # 监听滚动事件
        self.scroll_area.verticalScrollBar().valueChanged.connect(self.check_scroll_position)
        
        # 初始加载
        QTimer.singleShot(100, self.load_initial_batch)
    
    def clear_existing_items(self):
        """清除现有项目，保留布局"""
        # 获取布局中的所有项目
        items_to_remove = []
        for i in range(self.layout.count()):
            item = self.layout.itemAt(i)
            widget = item.widget()
            if widget:
                items_to_remove.append(widget)
        
        # 移除项目
        for widget in items_to_remove:
            widget.setParent(None)
            widget.deleteLater()
    
    def add_loading_indicator(self):
        """添加加载指示器"""
        print('add_loading_indicator')
        self.loading_indicator = QLabel("加载中...")
        self.loading_indicator.setAlignment(Qt.AlignCenter)
        self.loading_indicator.setVisible(False)
        self.layout.addWidget(self.loading_indicator)
    
    def load_initial_batch(self):
        """加载初始批次"""
        self.loading_started.emit()
        self.load_next_batch()
    
    def load_next_batch(self):
        """加载下一批游戏"""
        if self.is_loading or self.loaded_count >= len(self.minecraft_versions):
            return
        
        print('load_next_batch', self.loaded_count)
        self.is_loading = True
        self.loading_indicator.setVisible(True)
        
        # 使用QTimer.singleShot模拟异步加载
        QTimer.singleShot(50, self._add_batch_items)
    
    def _add_batch_items(self):
        """实际添加批次项目"""
        start_idx = self.loaded_count
        end_idx = min(self.loaded_count + self.batch_size, len(self.minecraft_versions))
        # print('加载下一批游戏', start_idx, end_idx, len(self.minecraft_versions))
        
        for i in range(start_idx, end_idx):
            data = self.minecraft_versions[i]
            item = self.create_item_func(
                data["id"],
                f"{data['type']} {data['releaseTime']}",
                data.get('is_selected', False)
            )
            self.layout.insertWidget(self.layout.count() - 1, item)
            self.layout.insertSpacing(self.layout.count() - 1, 10)
        
        self.loaded_count = end_idx
        self.is_loading = False
        self.loading_indicator.setVisible(False)
        
        # 通知UI更新
        self.items_added.emit(start_idx, end_idx)
        self.loading_finished.emit()
    
    def check_scroll_position(self):
        """检查滚动位置，决定是否加载更多"""
        if self.is_loading or self.loaded_count >= len(self.minecraft_versions):
            return
        
        scroll_bar = self.scroll_area.verticalScrollBar()
        scroll_pos = scroll_bar.value()
        scroll_max = scroll_bar.maximum()
        
        # 当滚动到距离底部100像素以内时加载更多
        if scroll_pos >= scroll_max - 100:
            self.loading_started.emit()
            self.load_next_batch()
    
    def refresh_data(self, new_data):
        """刷新数据"""
        self.minecraft_versions = new_data
        self.loaded_count = 0
        self.clear_existing_items()
        self.add_loading_indicator()
        self.load_initial_batch()
