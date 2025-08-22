"""
核心逻辑模块
"""
import logging
import time
from typing import Dict, List, Any

# 假设这些模块与原始文件在同一目录下
from logging_config import setup_logging, get_logger
from module_parser import ModuleParser
from packet_capture import PacketCapture
from network_interface_util import get_network_interfaces

# 获取日志器
logger = get_logger(__name__)


class StarResonanceMonitor:
    """星痕共鸣监控器"""

    def __init__(self, interface_name: str, category: str = "攻击", attributes: List[str] = None, log_callback=None):
        """
        初始化监控器

        Args:
            interface_name: 选定的网络接口名称 (e.g., 'eth0')
            category: 模组类型（攻击/守护/辅助）
            attributes: 要筛选的属性词条列表
            log_callback: 用于将日志消息传递给GUI的回调函数
        """
        self.interface_name = interface_name
        self.category = category
        self.attributes = attributes or []
        self.is_running = False
        self.log_callback = log_callback

        # 初始化组件
        self.packet_capture = PacketCapture(self.interface_name)
        self.module_parser = ModuleParser() # 将回调传递给解析器

        # 统计数据
        self.stats = {
            'start_time': None
        }

    def _log(self, message: str, level: str = 'info'):
        """通过回调记录日志，以便在GUI中显示"""
        if self.log_callback:
            self.log_callback(message)
        
        # 也可以同时记录到文件
        if level == 'info':
            logger.info(message)
        elif level == 'error':
            logger.error(message)

    def start_monitoring(self):
        """开始监控"""
        self.is_running = True
        self.stats['start_time'] = time.time()

        self._log("=== 星痕共鸣监控器启动 ===")
        self._log(f"模组类型: {self.category}")
        if self.attributes:
            self._log(f"属性筛选: {', '.join(self.attributes)}")
        else:
            self._log("属性筛选: 无 (将解析所有符合类型的模组)")
        self._log(f"网络接口名称: {self.interface_name}")

        # 启动抓包
        self.packet_capture.start_capture(self._on_sync_container_data)
        self._log("监控已启动，请重新登录游戏并选择角色...")
        self._log("当模组数据被捕获和解析后，结果会显示在这里。")


    def stop_monitoring(self):
        """停止监控"""
        if not self.is_running:
            return
        self.is_running = False
        self.packet_capture.stop_capture()
        self._log("=== 监控已停止 ===")

    def _on_sync_container_data(self, data: Dict[str, Any]):
        """处理SyncContainerData数据包"""
        try:
            v_data = data.get('v_data')
            if v_data:
                # 解析模组信息
                self.module_parser.parse_module_info(v_data, category=self.category, attributes=self.attributes)
        except Exception as e:
            self._log(f"处理数据包失败: {e}", level='error')

# 注意：原始的 main() 函数和 argparse 部分已被移除
# GUI 应用将负责处理用户输入和启动监控器