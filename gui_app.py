import tkinter
import customtkinter as ctk
import threading
from typing import Optional, Dict
import queue
import logging
import sys

# 假设这些工具和核心类与GUI文件在同一目录下
from network_interface_util import get_network_interfaces
from star_resonance_monitor_core import StarResonanceMonitor
from logging_config import setup_logging # 导入日志设置

# 创建一个自定义日志处理器，将日志消息发送到队列
class QueueHandler(logging.Handler):
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        self.log_queue.put(self.format(record))

# 创建一个自定义流对象，将print内容重定向到队列
class StreamToQueue:
    def __init__(self, text_queue):
        self.text_queue = text_queue

    def write(self, text):
        self.text_queue.put(text)

    def flush(self):
        # 这个函数必须存在，即使它什么也不做
        pass

class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        # --- 窗口设置 ---
        self.title("星痕共鸣模组筛选器 V2.1 by：伊咪塔")
        self.geometry("800x650") # 稍微增加高度以容纳新控件
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        # --- 全局变量 ---
        self.monitor_thread: Optional[threading.Thread] = None
        self.monitor_instance: Optional[StarResonanceMonitor] = None
        self.interfaces = get_network_interfaces()
        self.interface_map = {f"{i}: {iface.get('description', iface['name'])}": iface['name'] 
                              for i, iface in enumerate(self.interfaces)}
        
        # --- UI 布局 ---
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # -- 创建主框架 --
        self.main_frame = ctk.CTkFrame(self)
        self.main_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        self.main_frame.grid_columnconfigure(1, weight=1)

        # -- 网络接口选择 --
        self.label_interface = ctk.CTkLabel(self.main_frame, text="选择网络接口:")
        self.label_interface.grid(row=0, column=0, padx=10, pady=5, sticky="w")
        
        self.interface_menu = ctk.CTkOptionMenu(self.main_frame, values=list(self.interface_map.keys()))
        self.interface_menu.grid(row=0, column=1, padx=10, pady=5, sticky="ew")

        # -- 模组类型选择 --
        self.label_category = ctk.CTkLabel(self.main_frame, text="选择模组类型:")
        self.label_category.grid(row=1, column=0, padx=10, pady=5, sticky="w")
        
        self.category_menu = ctk.CTkOptionMenu(self.main_frame, values=["攻击", "守护", "辅助", "全部"])
        self.category_menu.grid(row=1, column=1, padx=10, pady=5, sticky="ew")

        # ==================================================================
        # VVVVVVVVVVVVVVVVVVVVVV 代码重构区域 VVVVVVVVVVVVVVVVVVVVVVV
        # ==================================================================

        # -- 属性筛选输入框 --
        self.label_attributes = ctk.CTkLabel(self.main_frame, text="筛选属性 (用空格隔开):")
        self.label_attributes.grid(row=2, column=0, padx=10, pady=5, sticky="w")
        
        self.attributes_entry = ctk.CTkEntry(self.main_frame, placeholder_text="可手动输入或从下方选择预设")
        self.attributes_entry.grid(row=2, column=1, padx=10, pady=5, sticky="ew")

        # -- 新增：属性预设下拉菜单 --
        self.label_presets = ctk.CTkLabel(self.main_frame, text="选择预设组合:")
        self.label_presets.grid(row=3, column=0, padx=10, pady=5, sticky="w")

        # 定义预设组合
        self.attribute_presets: Dict[str, str] = {
            "手动输入 / 清空": "",
            "神盾骑士": "抵御魔法 抵御物理 暴击专注",
            "雷影剑士": "敏捷加持 特攻伤害 精英打击 暴击专注",
            "冰魔导师": "智力加持 特攻伤害 精英打击 施法专注 暴击专注 幸运专注",
            "青岚骑士": "力量加持 特攻伤害 精英打击 攻速专注",
            "森语者": "智力加持 特攻治疗加持 专精治疗加持 幸运专注",
            "巨刃守护者": "抵御魔法 抵御物理",
            "神射手": "敏捷加持 特攻伤害 精英打击 攻速专注",
            "灵魂乐手": "智力加持 特攻治疗加持 专精治疗加持 攻速专注 幸运专注",
            "全部": "力量加持 敏捷加持 智力加持 特攻伤害 精英打击 特攻治疗加持 专精治疗加持 施法专注 攻速专注 暴击专注 幸运专注 抵御魔法 抵御物理",
            "输出职业": "力量加持 敏捷加持 智力加持 特攻伤害 精英打击 施法专注 攻速专注 暴击专注 幸运专注",
            "防御辅助": "力量加持 敏捷加持 智力加持 特攻治疗加持 专精治疗加持 施法专注 攻速专注 暴击专注 幸运专注 抵御魔法 抵御物理",
        }

        self.preset_menu = ctk.CTkOptionMenu(
            self.main_frame, 
            values=list(self.attribute_presets.keys()),
            command=self.update_attributes_from_preset # 绑定选择事件
        )
        self.preset_menu.grid(row=3, column=1, padx=10, pady=5, sticky="ew")
        self.preset_menu.set("手动输入 / 清空") # 设置默认显示值

        # ==================================================================
        # ^^^^^^^^^^^^^^^^^^^^^^ 代码重构区域 ^^^^^^^^^^^^^^^^^^^^^^^
        # ==================================================================

        # -- 控制按钮 --
        self.control_frame = ctk.CTkFrame(self.main_frame)
        # 将控制按钮框架下移一行以容纳新增的下拉菜单
        self.control_frame.grid(row=4, column=0, columnspan=2, pady=10)

        self.start_button = ctk.CTkButton(self.control_frame, text="开始监控", command=self.start_monitoring)
        self.start_button.pack(side="left", padx=10)

        self.stop_button = ctk.CTkButton(self.control_frame, text="停止监控", command=self.stop_monitoring, state="disabled")
        self.stop_button.pack(side="left", padx=10)

        # -- 日志输出框 --
        self.log_textbox = ctk.CTkTextbox(self, state="disabled", wrap="word")
        self.log_textbox.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")

        # --- 设置日志队列 ---
        self.log_queue = queue.Queue()
        
        # --- 设置日志系统 ---
        logger = logging.getLogger()
        logger.setLevel(logging.INFO)
        logger.addHandler(QueueHandler(self.log_queue))

        # --- 重定向标准输出 ---
        sys.stdout = StreamToQueue(self.log_queue)

        # --- 开始队列轮询 ---
        self.after(100, self.poll_log_queue)

    def update_attributes_from_preset(self, selection: str):
        """当用户从预设下拉菜单中选择一项时，更新上方的文本输入框"""
        preset_string = self.attribute_presets.get(selection, "")
        self.attributes_entry.delete(0, "end") # 清空当前内容
        self.attributes_entry.insert(0, preset_string) # 插入新内容

    def poll_log_queue(self):
        """每100ms检查一次队列，并用新消息更新UI"""
        while True:
            try:
                record = self.log_queue.get(block=False)
                
                self.log_textbox.configure(state="normal")
                self.log_textbox.insert("end", record)
                self.log_textbox.see("end")
                self.log_textbox.configure(state="disabled")

            except queue.Empty:
                break
        
        self.after(100, self.poll_log_queue)

    def start_monitoring(self):
        selected_interface_display = self.interface_menu.get()
        if not selected_interface_display:
            logging.error("错误：请先选择一个网络接口！")
            return
        
        interface_name = self.interface_map[selected_interface_display]
        category = self.category_menu.get()
        attributes_str = self.attributes_entry.get().strip()
        attributes = attributes_str.split() if attributes_str else []

        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("1.0", "end")
        self.log_textbox.configure(state="disabled")

        self.monitor_instance = StarResonanceMonitor(
            interface_name=interface_name,
            category=category,
            attributes=attributes,
        )
        
        self.monitor_thread = threading.Thread(target=self.monitor_instance.start_monitoring, daemon=True)
        self.monitor_thread.start()

        # 禁用所有输入控件
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.interface_menu.configure(state="disabled")
        self.category_menu.configure(state="disabled")
        self.attributes_entry.configure(state="disabled")
        self.preset_menu.configure(state="disabled") # 同样禁用预设菜单
        
    def stop_monitoring(self):
        if self.monitor_instance:
            self.monitor_instance.stop_monitoring()
        
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=1.0)

        self.monitor_instance = None
        self.monitor_thread = None

        # 恢复所有输入控件
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.interface_menu.configure(state="normal")
        self.category_menu.configure(state="normal")
        self.attributes_entry.configure(state="normal")
        self.preset_menu.configure(state="normal") # 恢复预设菜单
        
    def on_closing(self):
        """处理窗口关闭事件"""
        self.stop_monitoring()
        self.destroy()

if __name__ == "__main__":
    setup_logging(debug_mode=True)
    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("blue")
    
    app = App()
    app.mainloop()