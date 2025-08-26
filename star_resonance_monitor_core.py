# star_resonance_monitor_core.py

import logging
import time
from typing import Dict, List, Any, Optional, Callable

from logging_config import get_logger
from module_parser import ModuleParser
from module_optimizer import ModuleOptimizer, ModuleCategory
from packet_capture import PacketCapture

logger = get_logger(__name__)

class StarResonanceMonitor:
    """星痕共鸣监控器"""

    def __init__(self, interface_name: str, category: str = "攻击", attributes: List[str] = None, 
                 on_data_captured_callback: Optional[Callable] = None,
                 progress_callback: Optional[Callable[[str], None]] = None): # 添加进度回调
        self.interface_name = interface_name
        self.initial_category = category
        self.initial_attributes = attributes or []
        self.on_data_captured_callback = on_data_captured_callback
        self.progress_callback = progress_callback # 保存回调函数
        
        self.is_running = False
        self.captured_modules: Optional[List[Any]] = None

        self.packet_capture = PacketCapture(self.interface_name)
        self.module_parser = ModuleParser()
        self.module_optimizer = ModuleOptimizer()

    def start_monitoring(self):
        self.is_running = True
        print("=== 星痕共鸣模组监控器启动 by 伊咪塔 \n")
        print("=== 本程序开源地址： https://github.com/amoeet/StarResonanceAutoMod \n")
        print(f"初始模组类型: {self.initial_category}\n")
        if self.initial_attributes:
            print(f"初始属性筛选: {', '.join(self.initial_attributes)}\n")
        else:
            print("初始属性筛选: 无\n")
        print(f"网络接口名称: {self.interface_name}\n")

        self.packet_capture.start_capture(self._on_sync_container_data)
        print("监控已启动，请换线、重新登录或切换角色以便获取模组信息...\n")

    def stop_monitoring(self):
        if not self.is_running:
            return
        self.is_running = False
        self.packet_capture.stop_capture()
        print("=== 监控已停止 ===")

    def _on_sync_container_data(self, data: Dict[str, Any]):
        try:
            v_data = data.get('v_data')
            if v_data:
                print("捕获到模组数据，开始解析...")
                all_modules = self.module_parser.parse_module_info(v_data)
                
                if all_modules:
                    # 仅在第一次捕获时存储数据并触发回调
                    if self.captured_modules is None:
                        self.captured_modules = all_modules
                        print(f"成功解析并存储 {len(self.captured_modules)} 个模组。")
                        
                        # 执行初始筛选
                        self.rescreen_modules(self.initial_category, self.initial_attributes)
                        
                        # 通知GUI启用“重新筛选”按钮
                        if self.on_data_captured_callback:
                            self.on_data_captured_callback()
                    else:
                        print("已捕获模组数据，忽略后续数据包。如需更新请重启监控。")
                else:
                    print("数据包中未找到有效的模组信息。")
        except Exception as e:
            logger.error(f"处理数据包失败: {e}")

    def has_captured_data(self) -> bool:
        """检查是否已捕获并存储了模组数据"""
        return self.captured_modules is not None

    def rescreen_modules(self, category: str, attributes: List[str]):
        """使用新的筛选条件对已捕获的数据进行重新优化"""
        if not self.has_captured_data():
            print("错误：没有可供重新筛选的模组数据。")
            return

        print(f"\n--- 开始使用新条件重新筛选 ---")
        print(f"模组类型: {category}")
        print(f"优先属性: {', '.join(attributes) if attributes else '无'}")
        
        category_map = {
            "攻击": ModuleCategory.ATTACK, "守护": ModuleCategory.GUARDIAN,
            "辅助": ModuleCategory.SUPPORT, "全部": ModuleCategory.All
        }
        target_category = category_map.get(category, ModuleCategory.All)
        
        # 调用优化器，并传递进度回调函数
        self.module_optimizer.optimize_and_display(
            self.captured_modules, 
            target_category, 
            top_n=20, 
            prioritized_attrs=attributes,
            progress_callback=self.progress_callback
        )