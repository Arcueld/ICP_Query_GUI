import sys
import asyncio
import os
import json
import yaml
import ymicp

from datetime import datetime
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QGridLayout, QLabel, QLineEdit, 
                             QPushButton, QTextEdit, QTabWidget, QGroupBox,
                             QComboBox, QCheckBox, QSpinBox, QMessageBox,
                             QProgressBar, QSplitter, QTableWidget, QTableWidgetItem,
                             QHeaderView, QStatusBar,
                             QFileDialog, QDialog, QMenu)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QUrl
from PyQt5.QtGui import QDesktopServices
from load_config import config

class QueryWorker(QThread):
    result_ready = pyqtSignal(dict)
    progress_update = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    
    def __init__(self, query_type, query_text):
        super().__init__()
        self.query_type = query_type
        self.query_text = query_text
        self.icp = None
        
    def run(self):
        try:
            self.icp = ymicp.beian()
            
            if self.query_type == "APP":
                result = asyncio.run(self.icp.ymApp(self.query_text))
            elif self.query_type == "网站":
                result = asyncio.run(self.icp.ymWeb(self.query_text))
            elif self.query_type == "小程序":
                result = asyncio.run(self.icp.ymMiniApp(self.query_text))
            elif self.query_type == "快应用":
                result = asyncio.run(self.icp.ymKuaiApp(self.query_text))
            elif self.query_type == "黑名单APP":
                result = asyncio.run(self.icp.bymApp(self.query_text))
            elif self.query_type == "黑名单网站":
                result = asyncio.run(self.icp.bymWeb(self.query_text))
            elif self.query_type == "黑名单小程序":
                result = asyncio.run(self.icp.bymMiniApp(self.query_text))
            elif self.query_type == "黑名单快应用":
                result = asyncio.run(self.icp.bymKuaiApp(self.query_text))
            else:
                result = {"code": 400, "message": "不支持的查询类型"}
            
            self.result_ready.emit(result)
            
        except Exception as e:
            self.error_occurred.emit(f"查询失败: {str(e)}")
        finally:
            if self.icp:
                asyncio.run(self.icp.cleanup())

class BatchQueryWorker(QThread):
    result_ready = pyqtSignal(dict)
    progress_update = pyqtSignal(str, int, int)
    error_occurred = pyqtSignal(str)
    
    def __init__(self, query_type, query_targets):
        super().__init__()
        self.query_type = query_type
        self.query_targets = query_targets
        self.icp = None
        self.batch_results = []
        
    def run(self):
        try:
            self.icp = ymicp.beian()
            
            total_targets = len(self.query_targets)
            successful_queries = 0
            failed_queries = 0
            
            for i, target in enumerate(self.query_targets):
                try:
                    if self.query_type == "APP":
                        result = asyncio.run(self.icp.ymApp(target))
                    elif self.query_type == "网站":
                        result = asyncio.run(self.icp.ymWeb(target))
                    elif self.query_type == "小程序":
                        result = asyncio.run(self.icp.ymMiniApp(target))
                    elif self.query_type == "快应用":
                        result = asyncio.run(self.icp.ymKuaiApp(target))
                    elif self.query_type == "黑名单APP":
                        result = asyncio.run(self.icp.bymApp(target))
                    elif self.query_type == "黑名单网站":
                        result = asyncio.run(self.icp.bymWeb(target))
                    elif self.query_type == "黑名单小程序":
                        result = asyncio.run(self.icp.bymMiniApp(target))
                    elif self.query_type == "黑名单快应用":
                        result = asyncio.run(self.icp.bymKuaiApp(target))
                    else:
                        result = {"code": 400, "message": "不支持的查询类型"}
                    
                    query_result = {
                        "target": target,
                        "result": result,
                        "success": result.get("code") == 200,
                        "index": i
                    }
                    self.batch_results.append(query_result)
                    
                    if result.get("code") == 200:
                        successful_queries += 1
                    else:
                        failed_queries += 1
                        
                except Exception as e:
                    query_result = {
                        "target": target,
                        "result": {"code": 500, "message": f"查询失败: {str(e)}"},
                        "success": False,
                        "index": i
                    }
                    self.batch_results.append(query_result)
                    failed_queries += 1
            
            summary_result = self._generate_summary_result(successful_queries, failed_queries)
            self.result_ready.emit(summary_result)
            
        except Exception as e:
            self.error_occurred.emit(f"批量查询失败: {str(e)}")
        finally:
            if self.icp:
                asyncio.run(self.icp.cleanup())
    
    def _generate_summary_result(self, successful_queries, failed_queries):
        all_data = []
        for query_result in self.batch_results:
            if query_result["success"] and query_result["result"].get("params", {}).get("list"):
                for item in query_result["result"]["params"]["list"]:
                    item["_query_target"] = query_result["target"]
                    item["_query_index"] = query_result["index"]
                    all_data.append(item)
        
        summary = {
            "code": 200,
            "msg": "批量查询完成",
            "success": True,
            "params": {
                "total_queries": len(self.query_targets),
                "successful_queries": successful_queries,
                "failed_queries": failed_queries,
                "total_results": len(all_data),
                "list": all_data if all_data else [],
                "batch_results": self.batch_results
            }
        }
        return summary

class ConfigDialog(QDialog):
    config_saved = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("配置管理")
        self.setFixedSize(600, 500)
        self.init_ui()
        self.load_config()
        
    def init_ui(self):
        layout = QVBoxLayout()
        
        proxy_group = QGroupBox("代理配置")
        proxy_layout = QGridLayout()
        
        proxy_layout.addWidget(QLabel("启用静态代理:"), 0, 0)
        self.static_proxy_enable = QCheckBox()
        proxy_layout.addWidget(self.static_proxy_enable, 0, 1)
        
        proxy_layout.addWidget(QLabel("代理类型:"), 1, 0)
        self.proxy_type = QComboBox()
        self.proxy_type.addItems(["http", "https"])
        proxy_layout.addWidget(self.proxy_type, 1, 1)
        
        proxy_layout.addWidget(QLabel("代理地址:"), 2, 0)
        self.proxy_host = QLineEdit()
        proxy_layout.addWidget(self.proxy_host, 2, 1)
        
        proxy_layout.addWidget(QLabel("代理端口:"), 3, 0)
        self.proxy_port = QSpinBox()
        self.proxy_port.setRange(1, 65535)
        proxy_layout.addWidget(self.proxy_port, 3, 1)
        
        proxy_layout.addWidget(QLabel("用户名:"), 4, 0)
        self.proxy_username = QLineEdit()
        proxy_layout.addWidget(self.proxy_username, 4, 1)
        
        proxy_layout.addWidget(QLabel("密码:"), 5, 0)
        self.proxy_password = QLineEdit()
        self.proxy_password.setEchoMode(QLineEdit.Password)
        proxy_layout.addWidget(self.proxy_password, 5, 1)
        
        proxy_group.setLayout(proxy_layout)
        layout.addWidget(proxy_group)
        
        captcha_group = QGroupBox("验证码配置")
        captcha_layout = QGridLayout()
        
        captcha_layout.addWidget(QLabel("重试次数:"), 0, 0)
        self.captcha_retry = QSpinBox()
        self.captcha_retry.setRange(1, 10)
        captcha_layout.addWidget(self.captcha_retry, 0, 1)
        
        captcha_layout.addWidget(QLabel("重试延迟(秒):"), 1, 0)
        self.captcha_delay = QSpinBox()
        self.captcha_delay.setRange(1, 10)
        captcha_layout.addWidget(self.captcha_delay, 1, 1)
        
        captcha_group.setLayout(captcha_layout)
        layout.addWidget(captcha_group)
        
        query_group = QGroupBox("查询配置")
        query_layout = QGridLayout()
        
        query_layout.addWidget(QLabel("默认页面大小:"), 0, 0)
        self.page_size = QSpinBox()
        self.page_size.setRange(1, 100)
        self.page_size.setValue(20)
        query_layout.addWidget(self.page_size, 0, 1)
        
        query_layout.addWidget(QLabel("(每页返回的记录数，建议10-50)"), 0, 2)
        
        query_group.setLayout(query_layout)
        layout.addWidget(query_group)
        
        button_layout = QHBoxLayout()
        self.save_btn = QPushButton("保存配置")
        self.cancel_btn = QPushButton("取消")
        button_layout.addWidget(self.save_btn)
        button_layout.addWidget(self.cancel_btn)
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
        
        self.save_btn.clicked.connect(self.save_config)
        self.cancel_btn.clicked.connect(self.reject)
        
        self.proxy_host.textChanged.connect(self.validate_proxy_config)
        self.proxy_port.valueChanged.connect(self.validate_proxy_config)
        
    def load_config(self):
        try:
            static_proxy = getattr(config.proxy, 'static_proxy', object())
            self.static_proxy_enable.setChecked(getattr(static_proxy, 'enable', False))
            self.proxy_type.setCurrentText(getattr(static_proxy, 'type', 'http'))
            self.proxy_host.setText(getattr(static_proxy, 'host', ''))
            self.proxy_port.setValue(getattr(static_proxy, 'port', 8080))
            self.proxy_username.setText(getattr(static_proxy, 'username', ''))
            self.proxy_password.setText(getattr(static_proxy, 'password', ''))
            
            captcha = getattr(config, 'captcha', object())
            self.captcha_retry.setValue(getattr(captcha, 'captcha_retry_times', 5))
            self.captcha_delay.setValue(getattr(captcha, 'proxy_retry_delay', 1))
            
            query = getattr(config, 'query', object())
            self.page_size.setValue(getattr(query, 'default_page_size', 20))
            
        except Exception as e:
            QMessageBox.warning(self, "警告", f"加载配置失败: {str(e)}")
    
    def save_config(self):
        try:
            config_file = "config.yml"
            if not os.path.exists(config_file):
                QMessageBox.critical(self, "错误", f"配置文件 {config_file} 不存在")
                return
                
            with open(config_file, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f)
            
            if 'proxy' not in config_data:
                config_data['proxy'] = {}
            if 'static_proxy' not in config_data['proxy']:
                config_data['proxy']['static_proxy'] = {}
                
            config_data['proxy']['static_proxy']['enable'] = self.static_proxy_enable.isChecked()
            config_data['proxy']['static_proxy']['type'] = self.proxy_type.currentText()
            config_data['proxy']['static_proxy']['host'] = self.proxy_host.text()
            config_data['proxy']['static_proxy']['port'] = self.proxy_port.value()
            config_data['proxy']['static_proxy']['username'] = self.proxy_username.text()
            config_data['proxy']['static_proxy']['password'] = self.proxy_password.text()
            
            # 更新验证码配置
            if 'captcha' not in config_data:
                config_data['captcha'] = {}
            config_data['captcha']['captcha_retry_times'] = self.captcha_retry.value()
            config_data['captcha']['proxy_retry_delay'] = self.captcha_delay.value()
            
            # 更新查询配置
            if 'query' not in config_data:
                config_data['query'] = {}
            config_data['query']['default_page_size'] = self.page_size.value()
            
            # 保存配置文件
            with open(config_file, 'w', encoding='utf-8') as f:
                yaml.dump(config_data, f, default_flow_style=False, allow_unicode=True, indent=2)
            
            # 重新加载配置
            self.reload_config()
            
            # 发送配置保存信号
            self.config_saved.emit()
            
            QMessageBox.information(self, "成功", "配置已保存并立即生效！")
            self.accept()
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存配置失败: {str(e)}")
    
    def validate_proxy_config(self):
        """验证代理配置"""
        if self.static_proxy_enable.isChecked():
            host = self.proxy_host.text().strip()
            port = self.proxy_port.value()
            
            if not host:
                self.save_btn.setEnabled(False)
                return
                
            if port <= 0 or port > 65535:
                self.save_btn.setEnabled(False)
                return
                
        self.save_btn.setEnabled(True)

class AboutDialog(QDialog):
    """自定义关于对话框，支持超链接"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("关于")
        self.setFixedSize(400, 200)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout()
        
        # 标题
        title_label = QLabel("ICP_Query_GUI v1.0")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; margin: 10px;")
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)
        
        original_label = QLabel('<a href="https://github.com/HG-ha">原作者: HG-ha</a>')
        original_label.setOpenExternalLinks(True)
        original_label.setStyleSheet("margin: 5px; color: #0066cc;")
        original_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(original_label)
        
        fork_label = QLabel('<a href="https://github.com/Arcueld">二开: Arcueld</a>')
        fork_label.setOpenExternalLinks(True)
        fork_label.setStyleSheet("margin: 5px; color: #0066cc;")
        fork_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(fork_label)
        
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        close_btn.setStyleSheet("margin: 10px; padding: 5px 20px;")
        layout.addWidget(close_btn)
        
        self.setLayout(layout)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ICP备案查询工具 v1.0")
        self.setGeometry(100, 100, 1000, 700)
        self.query_history_cache = []
        self.init_ui()
        self.init_status_bar()
        self.init_style()
        self.update_page_size_display()
        
    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout()
        
        query_group = QGroupBox("ICP备案查询")
        query_layout = QGridLayout()
        
        query_layout.addWidget(QLabel("查询类型:"), 0, 0)
        self.query_type = QComboBox()
        self.query_type.addItems([
            "APP", "网站", "小程序", "快应用",
            "黑名单APP", "黑名单网站", "黑名单小程序", "黑名单快应用"
        ])
        query_layout.addWidget(self.query_type, 0, 1)
        
        query_layout.addWidget(QLabel("查询内容:"), 1, 0)
        self.query_input = QTextEdit()
        self.query_input.setPlaceholderText("请输入要查询的APP名称、域名或公司名称...\n支持批量查询，每行一个查询目标")
        self.query_input.setMaximumHeight(100)
        self.query_input.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        query_layout.addWidget(self.query_input, 1, 1)
        
        self.page_size_label = QLabel("页面大小: 20")
        query_layout.addWidget(self.page_size_label, 1, 2)
        
        batch_hint = QLabel("支持批量查询：每行一个目标")
        batch_hint.setStyleSheet("color: #666; font-size: 12px;")
        query_layout.addWidget(batch_hint, 1, 3)
        
        self.query_btn = QPushButton("开始查询")
        self.query_btn.clicked.connect(self.start_query)
        query_layout.addWidget(self.query_btn, 1, 4)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        query_layout.addWidget(self.progress_bar, 2, 0, 1, 5)
        
        query_group.setLayout(query_layout)
        main_layout.addWidget(query_group)
        
        # 创建分割器
        splitter = QSplitter(Qt.Horizontal)
        
        # 左侧：查询历史
        history_widget = QWidget()
        history_layout = QVBoxLayout()
        
        history_group = QGroupBox("查询历史")
        history_layout.addWidget(history_group)
        
        self.history_list = QTableWidget()
        self.history_list.setColumnCount(4)
        self.history_list.setHorizontalHeaderLabels(["时间", "类型", "内容", "状态"])
        self.history_list.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        self.history_list.setSelectionBehavior(QTableWidget.SelectRows)
        self.history_list.setSelectionMode(QTableWidget.SingleSelection)

        self.history_list.itemDoubleClicked.connect(self.on_history_double_clicked)

        self.history_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.history_list.customContextMenuRequested.connect(self.show_history_context_menu)
        history_layout.addWidget(self.history_list)
        
        history_widget.setLayout(history_layout)
        splitter.addWidget(history_widget)
        
        result_widget = QWidget()
        result_layout = QVBoxLayout()
        
        result_tabs = QTabWidget()
        
        structured_tab = QWidget()
        structured_layout = QVBoxLayout()
        
        self.result_table = QTableWidget()
        self.result_table.setColumnCount(4)
        self.result_table.setHorizontalHeaderLabels(["字段", "值", "类型", "说明"])
        self.result_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        structured_layout.addWidget(self.result_table)
        
        structured_tab.setLayout(structured_layout)
        result_tabs.addTab(structured_tab, "结构化结果")
        
        # 原始结果
        raw_tab = QWidget()
        raw_layout = QVBoxLayout()
        
        self.raw_result = QTextEdit()
        self.raw_result.setPlaceholderText("原始JSON结果将显示在这里...")
        raw_layout.addWidget(self.raw_result)
        
        raw_tab.setLayout(raw_layout)
        result_tabs.addTab(raw_tab, "原始JSON")
        
        result_widget.setLayout(result_layout)
        result_layout.addWidget(result_tabs)
        
        splitter.addWidget(result_widget)
        splitter.setSizes([300, 700])
        
        main_layout.addWidget(splitter)
        
        # 工具栏
        toolbar_layout = QHBoxLayout()
        
        self.config_btn = QPushButton("配置管理")
        self.config_btn.clicked.connect(self.show_config)
        toolbar_layout.addWidget(self.config_btn)
        
        self.export_btn = QPushButton("导出结果")
        self.export_btn.clicked.connect(self.export_results)
        toolbar_layout.addWidget(self.export_btn)
        
        self.clear_btn = QPushButton("清空结果")
        self.clear_btn.clicked.connect(self.clear_results)
        toolbar_layout.addWidget(self.clear_btn)
        
        self.about_btn = QPushButton("关于")
        self.about_btn.clicked.connect(self.show_about)
        toolbar_layout.addWidget(self.about_btn)
        
        toolbar_layout.addStretch()
        main_layout.addLayout(toolbar_layout)
        
        central_widget.setLayout(main_layout)
        
    def init_status_bar(self):
        """初始化状态栏"""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪")
        
        # 添加连接状态显示
        self.connection_status = QLabel("连接状态: 未知")
        self.status_bar.addPermanentWidget(self.connection_status)
        
    def init_style(self):
        """初始化样式 - 使用默认样式"""
        pass
        
    def update_page_size_display(self):
        """更新页面大小显示"""
        try:
            page_size = getattr(getattr(config, 'query', object()), 'default_page_size', 20)
            self.page_size_label.setText(f"页面大小: {page_size}")
        except:
            self.page_size_label.setText("页面大小: 20")
        
    def start_query(self):
        """开始查询"""
        query_text = self.query_input.toPlainText().strip()
        if not query_text:
            QMessageBox.warning(self, "警告", "请输入查询内容")
            return
            
        query_type = self.query_type.currentText()
        
        # 解析查询目标（支持批量查询）
        query_targets = [line.strip() for line in query_text.split('\n') if line.strip()]
        
        if not query_targets:
            QMessageBox.warning(self, "警告", "请输入有效的查询内容")
            return
        
        # 如果是单个查询，使用原有逻辑
        if len(query_targets) == 1:
            self._start_single_query(query_type, query_targets[0])
        else:
            # 批量查询
            self._start_batch_query(query_type, query_targets)
    
    def _start_single_query(self, query_type, query_text):
        """单个查询"""
        # 添加到历史记录
        self.add_to_history(query_type, query_text, "查询中...")
        
        # 禁用查询按钮
        self.query_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # 不确定进度
        
        # 启动查询线程
        self.query_worker = QueryWorker(query_type, query_text)
        self.query_worker.result_ready.connect(self.on_query_result)
        self.query_worker.progress_update.connect(self.on_progress_update)
        self.query_worker.error_occurred.connect(self.on_query_error)
        self.query_worker.start()
    
    def _start_batch_query(self, query_type, query_targets):
        """批量查询"""
        # 添加到历史记录
        batch_text = f"批量查询({len(query_targets)}个目标)"
        self.add_to_history(query_type, batch_text, "批量查询中...")
        
        # 禁用查询按钮
        self.query_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, len(query_targets))
        self.progress_bar.setValue(0)
        
        # 启动批量查询线程
        self.batch_worker = BatchQueryWorker(query_type, query_targets)
        self.batch_worker.result_ready.connect(self.on_batch_query_result)
        self.batch_worker.progress_update.connect(self.on_batch_progress_update)
        self.batch_worker.error_occurred.connect(self.on_batch_query_error)
        self.batch_worker.start()
        
    def add_to_history(self, query_type, query_text, status, result=None):
        """添加到查询历史"""
        current_time = datetime.now().strftime("%H:%M:%S")
        row = self.history_list.rowCount()
        self.history_list.insertRow(row)
        
        self.history_list.setItem(row, 0, QTableWidgetItem(current_time))
        self.history_list.setItem(row, 1, QTableWidgetItem(query_type))
        self.history_list.setItem(row, 2, QTableWidgetItem(query_text))
        self.history_list.setItem(row, 3, QTableWidgetItem(status))
        
        # 保存到缓存
        history_item = {
            'time': current_time,
            'type': query_type,
            'content': query_text,
            'status': status,
            'result': result
        }
        self.query_history_cache.append(history_item)
        
    def on_history_double_clicked(self, item):
        """双击历史记录时从缓存中获取结果"""
        row = item.row()
        
        # 检查缓存中是否有对应的结果
        if row < len(self.query_history_cache):
            history_item = self.query_history_cache[row]
            
            # 检查是否有结果数据
            if history_item.get('result') and history_item.get('status') == '成功':
                # 从缓存中获取结果
                result = history_item['result']
                
                # 显示原始结果
                self.raw_result.setPlainText(json.dumps(result, ensure_ascii=False, indent=2))
                
                # 解析并显示结构化结果
                self.display_structured_result(result)
                
                # 更新状态栏
                self.status_bar.showMessage("已从历史记录中加载结果")
                self.connection_status.setText("连接状态: 正常")
                
                return
        
        # 如果没有缓存结果，则重新查询
        query_type = self.history_list.item(row, 1).text()
        query_text = self.history_list.item(row, 2).text()
        
        # 设置查询类型和内容
        self.query_type.setCurrentText(query_type)
        self.query_input.setText(query_text)
        
        # 自动开始查询
        self.start_query()
        
    def show_history_context_menu(self, position):
        """显示历史记录右键菜单"""
        if self.history_list.itemAt(position) is None:
            return
            
        # 创建右键菜单
        context_menu = QMenu(self)
        
        # 重新查询
        re_query_action = context_menu.addAction("重新查询")
        re_query_action.triggered.connect(self.re_query_selected)
        
        # 复制查询内容
        copy_action = context_menu.addAction("复制查询内容")
        copy_action.triggered.connect(self.copy_query_text)
        
        # 删除记录
        context_menu.addSeparator()
        delete_action = context_menu.addAction("删除记录")
        delete_action.triggered.connect(self.delete_selected_history)
        
        # 显示菜单
        context_menu.exec_(self.history_list.mapToGlobal(position))
        
    def re_query_selected(self):
        """重新查询选中的记录"""
        current_row = self.history_list.currentRow()
        if current_row >= 0:
            # 先尝试从缓存加载
            if current_row < len(self.query_history_cache):
                history_item = self.query_history_cache[current_row]
                if history_item.get('result') and history_item.get('status') == '成功':
                    # 从缓存加载结果
                    result = history_item['result']
                    self.raw_result.setPlainText(json.dumps(result, ensure_ascii=False, indent=2))
                    self.display_structured_result(result)
                    self.status_bar.showMessage("已从历史记录中加载结果")
                    return
            
            # 如果没有缓存结果，则重新查询
            query_type = self.history_list.item(current_row, 1).text()
            query_text = self.history_list.item(current_row, 2).text()
            
            self.query_type.setCurrentText(query_type)
            self.query_input.setText(query_text)
            self.start_query()
            
    def copy_query_text(self):
        """复制查询内容到剪贴板"""
        current_row = self.history_list.currentRow()
        if current_row >= 0:
            query_text = self.history_list.item(current_row, 2).text()
            clipboard = QApplication.clipboard()
            clipboard.setText(query_text)
            self.status_bar.showMessage("查询内容已复制到剪贴板")
            
    def delete_selected_history(self):
        """删除选中的历史记录"""
        current_row = self.history_list.currentRow()
        if current_row >= 0:
            reply = QMessageBox.question(self, "确认删除", "确定要删除这条历史记录吗？",
                                       QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.history_list.removeRow(current_row)
                # 同时删除缓存中的记录
                if current_row < len(self.query_history_cache):
                    del self.query_history_cache[current_row]
                self.status_bar.showMessage("历史记录已删除")
        
    def on_query_result(self, result):
        """处理查询结果"""
        self.progress_bar.setVisible(False)
        self.query_btn.setEnabled(True)
        
        # 更新历史记录状态和结果
        if self.history_list.rowCount() > 0:
            last_row = self.history_list.rowCount() - 1
            self.history_list.setItem(last_row, 3, QTableWidgetItem("成功"))
            
            # 更新缓存中的结果
            if len(self.query_history_cache) > 0:
                self.query_history_cache[-1]['status'] = "成功"
                self.query_history_cache[-1]['result'] = result
        
        # 显示原始结果
        self.raw_result.setPlainText(json.dumps(result, ensure_ascii=False, indent=2))
        
        # 解析并显示结构化结果
        self.display_structured_result(result)
        
        self.status_bar.showMessage("查询完成")
        self.connection_status.setText("连接状态: 正常")
        
    def on_progress_update(self, message):
        """更新进度"""
        self.status_bar.showMessage(message)
        
    def on_query_error(self, error_msg):
        """处理查询错误"""
        self.progress_bar.setVisible(False)
        self.query_btn.setEnabled(True)
        
        # 更新历史记录状态
        if self.history_list.rowCount() > 0:
            last_row = self.history_list.rowCount() - 1
            self.history_list.setItem(last_row, 3, QTableWidgetItem("失败"))
        
        self.status_bar.showMessage("查询失败")
        self.connection_status.setText("连接状态: 异常")
        
        QMessageBox.critical(self, "查询错误", error_msg)
    
    def on_batch_query_result(self, result):
        """处理批量查询结果"""
        self.progress_bar.setVisible(False)
        self.query_btn.setEnabled(True)
        
        # 更新历史记录状态和结果
        if self.history_list.rowCount() > 0:
            last_row = self.history_list.rowCount() - 1
            self.history_list.setItem(last_row, 3, QTableWidgetItem("成功"))
            
            # 更新缓存中的结果
            if len(self.query_history_cache) > 0:
                self.query_history_cache[-1]['status'] = "成功"
                self.query_history_cache[-1]['result'] = result
        
        # 显示原始结果
        self.raw_result.setPlainText(json.dumps(result, ensure_ascii=False, indent=2))
        
        # 解析并显示结构化结果
        self.display_structured_result(result)
        
        self.status_bar.showMessage("批量查询完成")
        self.connection_status.setText("连接状态: 正常")
    
    def on_batch_progress_update(self, message, current, total):
        """更新批量查询进度"""
        self.progress_bar.setValue(current)
        self.status_bar.showMessage(message)
    
    def on_batch_query_error(self, error_msg):
        """处理批量查询错误"""
        self.progress_bar.setVisible(False)
        self.query_btn.setEnabled(True)
        
        # 更新历史记录状态
        if self.history_list.rowCount() > 0:
            last_row = self.history_list.rowCount() - 1
            self.history_list.setItem(last_row, 3, QTableWidgetItem("失败"))
        
        self.status_bar.showMessage("批量查询失败")
        self.connection_status.setText("连接状态: 异常")
        
        QMessageBox.critical(self, "批量查询错误", error_msg)
        
    def display_structured_result(self, result):
        """显示结构化结果"""
        self.result_table.setRowCount(0)
        
        if not isinstance(result, dict):
            return
        
        if result.get('code') == 404 or result.get('success') == False:
            # 404或查询失败，不显示任何内容
            return
        
        # 检查是否有params.list数据
        if 'params' in result and isinstance(result['params'], dict) and 'list' in result['params']:
            data_list = result['params']['list']
            if isinstance(data_list, list) and len(data_list) > 0:
                # 解析list中的数据
                self.parse_data_list(data_list)
                return
            else:
                return
        
        # 如果没有list数据，检查是否是成功的结果
        if result.get('success', False) and result.get('code', 0) == 200:
            # 成功但没有数据，不显示任何内容
            return
        
        # 其他情况不显示任何内容
        return
    
    def parse_data_list(self, data_list):
        """解析数据列表 - 每行一个数据项，只显示重要信息"""
        # 检查是否是批量查询结果（包含_query_target字段）
        is_batch_result = any(item.get('_query_target') for item in data_list if isinstance(item, dict))
        
        if is_batch_result:
            # 批量查询结果，显示查询目标
            self.result_table.setColumnCount(4)
            self.result_table.setHorizontalHeaderLabels(["查询目标", "域名", "单位名称", "备案号"])
        else:
            # 单个查询结果
            self.result_table.setColumnCount(3)
            self.result_table.setHorizontalHeaderLabels(["域名", "单位名称", "备案号"])
        
        row = 0
        for i, item in enumerate(data_list):
            if not isinstance(item, dict):
                continue
                
            self.result_table.insertRow(row)
            col = 0
            
            # 如果是批量查询结果，先显示查询目标
            if is_batch_result:
                query_target = item.get('_query_target', '')
                self.result_table.setItem(row, col, QTableWidgetItem(str(query_target)))
                col += 1
            
            # 域名
            domain = item.get('domain', '')
            self.result_table.setItem(row, col, QTableWidgetItem(str(domain)))
            col += 1
            
            # 单位名称
            unit_name = item.get('unitName', '')
            self.result_table.setItem(row, col, QTableWidgetItem(str(unit_name)))
            col += 1
            
            # 备案号（显示主体备案号）
            main_licence = item.get('mainLicence', '')
            self.result_table.setItem(row, col, QTableWidgetItem(str(main_licence)))
            
            row += 1
    
            
        
    def show_config(self):
        """显示配置对话框"""
        config_dialog = ConfigDialog(self)
        # 连接配置保存信号
        config_dialog.config_saved.connect(self.on_config_saved)
        if config_dialog.exec_() == QDialog.Accepted:
            self.status_bar.showMessage("配置已更新")
            self.update_page_size_display()
    
    def on_config_saved(self):
        """配置保存后的处理"""
        # 更新页面大小显示
        self.update_page_size_display()
        # 更新状态栏
        self.status_bar.showMessage("配置已重新加载")
        
    def export_results(self):
        """导出结果"""
        if self.result_table.rowCount() == 0:
            QMessageBox.warning(self, "警告", "没有可导出的结果")
            return
            
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出结果", f"icp_query_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
            "Excel文件 (*.xlsx);;所有文件 (*)"
        )
        
        if file_path:
            try:
                self._export_to_excel(file_path)
                QMessageBox.information(self, "成功", f"结果已导出到: {file_path}")
                
            except Exception as e:
                QMessageBox.critical(self, "错误", f"导出失败: {str(e)}")
    
    def _export_to_excel(self, file_path):
        """导出到Excel文件"""
        from openpyxl import Workbook
        from openpyxl.styles import Font, Alignment, PatternFill
        from openpyxl.utils import get_column_letter
        
        # 创建工作簿
        wb = Workbook()
        
        # 删除默认工作表
        wb.remove(wb.active)
        
        # 创建查询结果工作表
        ws_results = wb.create_sheet("查询结果")
        self._write_results_to_sheet(ws_results)
        
        # 创建查询历史工作表
        ws_history = wb.create_sheet("查询历史")
        self._write_history_to_sheet(ws_history)
        
        # 保存文件
        wb.save(file_path)
    
    def _write_results_to_sheet(self, ws):
        """写入查询结果到工作表"""
        # 设置表头
        headers = []
        for col in range(self.result_table.columnCount()):
            header_item = self.result_table.horizontalHeaderItem(col)
            if header_item:
                headers.append(header_item.text())
            else:
                headers.append(f"列{col+1}")
        
        # 写入表头
        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=header)
            cell.font = Font(bold=True)
            cell.fill = PatternFill(start_color="CCCCCC", end_color="CCCCCC", fill_type="solid")
            cell.alignment = Alignment(horizontal="center", vertical="center")
        
        # 写入数据
        for row in range(self.result_table.rowCount()):
            for col in range(self.result_table.columnCount()):
                item = self.result_table.item(row, col)
                if item:
                    ws.cell(row=row+2, column=col+1, value=item.text())
        
        # 自动调整列宽
        for col in range(1, len(headers) + 1):
            column_letter = get_column_letter(col)
            max_length = 0
            for row in range(1, ws.max_row + 1):
                cell_value = ws[f"{column_letter}{row}"].value
                if cell_value:
                    max_length = max(max_length, len(str(cell_value)))
            ws.column_dimensions[column_letter].width = min(max_length + 2, 50)
    
    def _write_history_to_sheet(self, ws):
        """写入查询历史到工作表"""
        # 设置表头
        headers = ["时间", "类型", "内容", "状态"]
        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=header)
            cell.font = Font(bold=True)
            cell.fill = PatternFill(start_color="CCCCCC", end_color="CCCCCC", fill_type="solid")
            cell.alignment = Alignment(horizontal="center", vertical="center")
        
        # 写入历史数据
        for row in range(self.history_list.rowCount()):
            for col in range(self.history_list.columnCount()):
                item = self.history_list.item(row, col)
                if item:
                    ws.cell(row=row+2, column=col+1, value=item.text())
        
        # 自动调整列宽
        for col in range(1, len(headers) + 1):
            column_letter = get_column_letter(col)
            max_length = 0
            for row in range(1, ws.max_row + 1):
                cell_value = ws[f"{column_letter}{row}"].value
                if cell_value:
                    max_length = max(max_length, len(str(cell_value)))
            ws.column_dimensions[column_letter].width = min(max_length + 2, 50)
        
    def clear_results(self):
        """清空结果"""
        self.result_table.setRowCount(0)
        self.raw_result.clear()
        self.history_list.setRowCount(0)
        # 清空缓存
        self.query_history_cache.clear()
        self.status_bar.showMessage("结果已清空")
        
    def show_about(self):
        """显示关于对话框"""
        about_dialog = AboutDialog(self)
        about_dialog.exec_()

def main():
    """主函数"""
    app = QApplication(sys.argv)
    
    # 设置应用样式
    app.setStyle('Fusion')
    
    # 创建主窗口
    window = MainWindow()
    window.show()
    
    # 运行应用
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
