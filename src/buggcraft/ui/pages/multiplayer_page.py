# src/buggcraft/ui/pages/multiplayer_page.py
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                              QLineEdit, QPushButton, QScrollArea)
from PySide6.QtCore import Qt, Signal
from ..widgets.cards import QMCard
from .base_page import BasePage

class MultiplayerPage(BasePage):
    """联机大厅页面 - 继承BasePage"""
    
    # 定义信号
    server_selected = Signal(dict)  # 服务器选择信号
    
    def __init__(self, home_path, scale_ratio=1.0, parent=None):
        super().__init__(home_path, scale_ratio, parent)
        self.current_page = 1
        self.total_pages = 5
        self.servers = []  # 服务器列表
        self.init_ui()
        self.load_sample_servers()
    
    def on_page_activate(self):
        """当页面被激活时调用"""
        print("页面被激活")
    
    def on_page_deactivate(self):
        """当页面被隐藏时调用"""
        print("页面被隐藏")
    
    def init_ui(self):
        """初始化UI"""
        # 设置背景
        self.set_background('images/minecraft_bg.png')
        
        # 创建主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # 创建一个内容容器，添加内边距
        content_container = QWidget()
        content_layout = QVBoxLayout(content_container)
        content_layout.setContentsMargins(20, 20, 20, 20)
        
        # 标题
        title = QLabel("联机大厅")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #ffffff;")
        content_layout.addWidget(title)
        
        # 搜索栏
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("搜索服务器:"))
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("输入服务器名称或描述")
        self.search_input.setStyleSheet("background-color: rgba(255, 255, 255, 0.1); color: #ffffff;")
        search_layout.addWidget(self.search_input)
        
        self.search_btn = QPushButton("搜索")
        self.search_btn.clicked.connect(self.on_search)
        self.search_btn.setStyleSheet("""
            QPushButton {
                background-color: #4a4a4a;
                color: #ffffff;
                border: none;
                padding: 5px 10px;
            }
            QPushButton:hover {
                background-color: #5a5a5a;
            }
        """)
        search_layout.addWidget(self.search_btn)
        
        content_layout.addLayout(search_layout)
        
        # 服务器列表区域
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: transparent;
                border: none;
            }
            QScrollArea > QWidget > QWidget {
                background-color: transparent;
            }
        """)
        
        self.server_list_widget = QWidget()
        self.server_list_layout = QVBoxLayout(self.server_list_widget)
        self.server_list_layout.setAlignment(Qt.AlignTop)
        self.server_list_widget.setStyleSheet("background-color: transparent;")
        
        self.scroll_area.setWidget(self.server_list_widget)
        content_layout.addWidget(self.scroll_area)
        
        # 分页控件
        pagination_layout = QHBoxLayout()
        pagination_layout.addStretch()
        
        self.prev_btn = QPushButton("上一页")
        self.prev_btn.clicked.connect(self.prev_page)
        self.prev_btn.setStyleSheet("""
            QPushButton {
                background-color: #4a4a4a;
                color: #ffffff;
                border: none;
                padding: 5px 10px;
            }
            QPushButton:hover {
                background-color: #5a5a5a;
            }
            QPushButton:disabled {
                background-color: #333333;
                color: #888888;
            }
        """)
        pagination_layout.addWidget(self.prev_btn)
        
        self.page_label = QLabel("1/5")
        self.page_label.setStyleSheet("color: #ffffff; padding: 5px 10px;")
        pagination_layout.addWidget(self.page_label)
        
        self.next_btn = QPushButton("下一页")
        self.next_btn.clicked.connect(self.next_page)
        self.next_btn.setStyleSheet("""
            QPushButton {
                background-color: #4a4a4a;
                color: #ffffff;
                border: none;
                padding: 5px 10px;
            }
            QPushButton:hover {
                background-color: #5a5a5a;
            }
            QPushButton:disabled {
                background-color: #333333;
                color: #888888;
            }
        """)
        pagination_layout.addWidget(self.next_btn)
        
        pagination_layout.addStretch()
        content_layout.addLayout(pagination_layout)
        
        # 将内容容器添加到主布局
        main_layout.addWidget(content_container)
        
        # 更新分页状态
        self.update_pagination()
    
    def load_sample_servers(self):
        """加载示例服务器数据"""
        self.servers = [
            {"name": "Hypixel", "address": "mc.hypixel.net", "players": 45000, 
             "max_players": 50000, "ping": 120, 
             "description": "全球最大的我的世界服务器，提供多种小游戏和生存模式"},
            {"name": "Mineplex", "address": "mineplex.com", "players": 32000, 
             "max_players": 40000, "ping": 180, 
             "description": "经典小游戏服务器，拥有多种创意游戏模式"},
            {"name": "本地服务器", "address": "localhost:25565", "players": 5, 
             "max_players": 20, "ping": 5, 
             "description": "本地测试服务器，仅供开发使用"},
            {"name": "SkyBlock乐园", "address": "skyblock.com", "players": 15000, 
             "max_players": 20000, "ping": 90, 
             "description": "专注于SkyBlock模式的服务器，提供丰富的岛屿玩法"},
            {"name": "生存大陆", "address": "survivalworld.net", "players": 8000, 
             "max_players": 10000, "ping": 150, 
             "description": "纯净生存服务器，保留原版生存体验"},
        ]
        
        self.display_servers()
    
    def display_servers(self):
        """显示服务器列表"""
        # 清空现有服务器列表
        for i in reversed(range(self.server_list_layout.count())): 
            widget = self.server_list_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)
        
        # 添加服务器卡片
        for server in self.servers:
            card = QMCard(
                server["name"],
                server["address"],
                server["players"],
                server["max_players"],
                server["ping"],
                server["description"]
            )
            card.selected.connect(lambda s=server: self.select_server(s))
            self.server_list_layout.addWidget(card)
    
    def select_server(self, server):
        """选择服务器"""
        self.server_selected.emit(server)
    
    def on_search(self):
        """搜索服务器"""
        search_text = self.search_input.text().lower()
        if not search_text:
            # 如果搜索文本为空，显示所有服务器
            self.display_servers()
            return
        
        # 过滤服务器
        filtered_servers = [
            server for server in self.servers
            if search_text in server["name"].lower() or 
               search_text in server["description"].lower()
        ]
        
        # 清空现有服务器列表
        for i in reversed(range(self.server_list_layout.count())): 
            widget = self.server_list_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)
        
        # 添加过滤后的服务器卡片
        for server in filtered_servers:
            card = QMCard(
                server["name"],
                server["address"],
                server["players"],
                server["max_players"],
                server["ping"],
                server["description"]
            )
            card.selected.connect(lambda s=server: self.select_server(s))
            self.server_list_layout.addWidget(card)
    
    def prev_page(self):
        """上一页"""
        if self.current_page > 1:
            self.current_page -= 1
            self.update_pagination()
            # 这里可以添加加载对应页面数据的逻辑
    
    def next_page(self):
        """下一页"""
        if self.current_page < self.total_pages:
            self.current_page += 1
            self.update_pagination()
            # 这里可以添加加载对应页面数据的逻辑
    
    def update_pagination(self):
        """更新分页状态"""
        self.page_label.setText(f"{self.current_page}/{self.total_pages}")
        self.prev_btn.setEnabled(self.current_page > 1)
        self.next_btn.setEnabled(self.current_page < self.total_pages)
    
    def set_servers(self, servers):
        """设置服务器列表"""
        self.servers = servers
        self.display_servers()
    
    def add_server(self, server):
        """添加服务器"""
        self.servers.append(server)
        self.display_servers()
    
    def remove_server(self, server_name):
        """移除服务器"""
        self.servers = [s for s in self.servers if s["name"] != server_name]
        self.display_servers()
    
    def update_server(self, server_name, updated_server):
        """更新服务器信息"""
        for i, server in enumerate(self.servers):
            if server["name"] == server_name:
                self.servers[i] = updated_server
                break
        self.display_servers()
