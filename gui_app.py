# gui_app.py

import tkinter
import customtkinter as ctk
import threading
from typing import Optional, Dict, List
import queue
import logging
import sys

from network_interface_util import get_network_interfaces
from star_resonance_monitor_core import StarResonanceMonitor
from logging_config import setup_logging

# --- 日志队列处理器 (不变) ---
class QueueHandler(logging.Handler):
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        self.log_queue.put(self.format(record))

# --- 标准输出流重定向到队列 (不变) ---
class StreamToQueue:
    def __init__(self, text_queue):
        self.text_queue = text_queue

    def write(self, text):
        self.text_queue.put(text)

    def flush(self):
        pass

class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("星痕共鸣模组筛选器 V2.4 by：伊咪塔")
        self.geometry("800x700") # 为状态栏增加高度
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        self.monitor_thread: Optional[threading.Thread] = None
        self.monitor_instance: Optional[StarResonanceMonitor] = None
        self.interfaces = get_network_interfaces()
        self.interface_map = {f"{i}: {iface.get('description', iface['name'])}": iface['name'] 
                              for i, iface in enumerate(self.interfaces)}
        
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1) # 日志文本框行

        self.main_frame = ctk.CTkFrame(self)
        self.main_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        self.main_frame.grid_columnconfigure(1, weight=1)

        self.label_interface = ctk.CTkLabel(self.main_frame, text="选择网络接口:")
        self.label_interface.grid(row=0, column=0, padx=10, pady=5, sticky="w")
        self.interface_menu = ctk.CTkOptionMenu(self.main_frame, values=list(self.interface_map.keys()))
        self.interface_menu.grid(row=0, column=1, padx=10, pady=5, sticky="ew")

        self.label_category = ctk.CTkLabel(self.main_frame, text="选择模组类型:")
        self.label_category.grid(row=1, column=0, padx=10, pady=5, sticky="w")
        self.category_menu = ctk.CTkOptionMenu(self.main_frame, values=["攻击", "守护", "辅助", "全部"])
        self.category_menu.grid(row=1, column=1, padx=10, pady=5, sticky="ew")

        self.label_attributes = ctk.CTkLabel(self.main_frame, text="筛选属性 (用空格隔开):")
        self.label_attributes.grid(row=2, column=0, padx=10, pady=5, sticky="w")
        self.attributes_entry = ctk.CTkEntry(self.main_frame, placeholder_text="可手动输入或从下方选择预设，留空则不进行筛选")
        self.attributes_entry.grid(row=2, column=1, padx=10, pady=5, sticky="ew")

        self.label_attributes = ctk.CTkLabel(self.main_frame, text="推荐的组合里只出现以上筛选属性，建议填入所有可以容忍的属性")
        self.label_attributes.grid(row=3, column=1, padx=10, pady=5, sticky="w")

        self.label_presets = ctk.CTkLabel(self.main_frame, text="选择预设筛选属性:")
        self.label_presets.grid(row=4, column=0, padx=10, pady=5, sticky="w")
        
        self.attribute_presets: Dict[str, str] = {
            "手动输入 / 清空": "",
            "神盾骑士": "抵御魔法 抵御物理 暴击专注",
            "雷影剑士": "敏捷加持 特攻伤害 精英打击 暴击专注",
            "冰魔导师": "智力加持 特攻伤害 精英打击 施法专注 暴击专注 幸运专注",
            "青岚骑士": "力量加持 特攻伤害 精英打击 攻速专注",
            "森语者": "智力加持 特攻治疗加持 专精治疗加持 幸运专注",
            "巨刃守护者": "力量加持 抵御魔法 抵御物理 暴击专注 幸运专注",
            "神射手": "敏捷加持 特攻伤害 精英打击 攻速专注",
            "灵魂乐手": "智力加持 特攻治疗加持 专精治疗加持 攻速专注 幸运专注",
            "全部": "极-伤害叠加 极-灵活身法 极-生命凝聚 极-急救措施 极-生命波动 极-生命汲取 极-全队幸暴 极-绝境守护 力量加持 敏捷加持 智力加持 特攻伤害 精英打击 特攻治疗加持 专精治疗加持 施法专注 攻速专注 暴击专注 幸运专注 抵御魔法 抵御物理",
            "输出职业": "力量加持 敏捷加持 智力加持 特攻伤害 精英打击 施法专注 攻速专注 暴击专注 幸运专注",
            "防御辅助": "力量加持 敏捷加持 智力加持 特攻治疗加持 专精治疗加持 施法专注 攻速专注 暴击专注 幸运专注 抵御魔法 抵御物理",
        }

        self.preset_menu = ctk.CTkOptionMenu(
            self.main_frame, values=list(self.attribute_presets.keys()),
            command=self.update_attributes_from_preset
        )
        self.preset_menu.grid(row=4, column=1, padx=10, pady=5, sticky="ew")
        self.preset_menu.set("手动输入 / 清空")

        self.control_frame = ctk.CTkFrame(self.main_frame)
        self.control_frame.grid(row=5, column=0, columnspan=2, pady=10)

        self.start_button = ctk.CTkButton(self.control_frame, text="开始监控", command=self.start_monitoring)
        self.start_button.pack(side="left", padx=10)

        self.stop_button = ctk.CTkButton(self.control_frame, text="停止监控", command=self.stop_monitoring, state="disabled")
        self.stop_button.pack(side="left", padx=10)
        
        self.rescreen_button = ctk.CTkButton(self.control_frame, text="重新筛选", command=self.rescreen_results, state="disabled")
        self.rescreen_button.pack(side="left", padx=10)



        # --- 修改开始 ---
        # 1. 定义一个更适合中文阅读的粗体字
        #    - "Microsoft YaHei UI" 是 Windows 下常用的清晰中文字体
        #    - 16 是字体大小
        #    - "bold" 是加粗效果
        log_font = ("Microsoft YaHei UI", 18, "bold")

        # 2. 在创建 CtkTextbox 时应用字体和行间距
        #    - font=log_font 应用上面定义的字体
        #    - spacing3=8 在每行下方增加 8 像素的间距 (您可以按需调整)
        self.log_textbox = ctk.CTkTextbox(self, state="disabled", wrap="word", font=log_font, spacing3=4)
        # --- 修改结束 ---
        self.log_textbox.grid(row=1, column=0, padx=10, pady=(0, 5), sticky="nsew")
 

        # --- 新增状态栏 ---
        self.status_frame = ctk.CTkFrame(self, height=30)
        self.status_frame.grid(row=2, column=0, padx=10, pady=(0, 10), sticky="ew")
        self.status_label = ctk.CTkLabel(self.status_frame, text="状态: 空闲", anchor="w")
        self.status_label.pack(side="left", padx=10, pady=2)

        self.log_queue = queue.Queue()
        logger_instance = logging.getLogger()
        logger_instance.setLevel(logging.INFO)
        logger_instance.addHandler(QueueHandler(self.log_queue))
        sys.stdout = StreamToQueue(self.log_queue)

        # --- 新增进度更新队列 ---
        self.progress_queue = queue.Queue()
        self.after(100, self.poll_queues)

    def update_attributes_from_preset(self, selection: str):
        preset_string = self.attribute_presets.get(selection, "")
        self.attributes_entry.delete(0, "end")
        self.attributes_entry.insert(0, preset_string)

    def poll_queues(self):
        # 合并处理两个队列
        # 处理日志队列
        while True:
            try:
                record = self.log_queue.get(block=False)
                self.log_textbox.configure(state="normal")
                self.log_textbox.insert("end", record)
                self.log_textbox.see("end")
                self.log_textbox.configure(state="disabled")
            except queue.Empty:
                break
        
        # 处理进度队列
        while True:
            try:
                message = self.progress_queue.get(block=False)
                self.status_label.configure(text=f"状态: {message}")
            except queue.Empty:
                break
                
        self.after(100, self.poll_queues)

    def progress_callback(self, message: str):
        """线程安全地将进度消息放入队列。"""
        self.progress_queue.put(message)

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
        self.status_label.configure(text="状态: 正在启动监控...")

        self.monitor_instance = StarResonanceMonitor(
            interface_name=interface_name,
            category=category,
            attributes=attributes,
            on_data_captured_callback=self.enable_rescreening,
            progress_callback=self.progress_callback # 传递回调函数
        )
        
        self.monitor_thread = threading.Thread(target=self.monitor_instance.start_monitoring, daemon=True)
        self.monitor_thread.start()

        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.interface_menu.configure(state="disabled")
        self.category_menu.configure(state="normal")
        self.attributes_entry.configure(state="normal")
        self.preset_menu.configure(state="normal")
        self.rescreen_button.configure(state="disabled")
        self.status_label.configure(text="状态: 正在监控游戏数据...")

    def stop_monitoring(self):
        if self.monitor_instance:
            self.monitor_instance.stop_monitoring()
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=1.0)

        self.monitor_instance = None
        self.monitor_thread = None

        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.interface_menu.configure(state="normal")
        self.rescreen_button.configure(state="disabled")
        self.status_label.configure(text="状态: 空闲")

    def rescreen_results(self):
        """重新筛选已有数据"""
        if not self.monitor_instance or not self.monitor_instance.has_captured_data():
            logging.warning("没有可供筛选的已捕获模组数据。")
            return
        
        category = self.category_menu.get()
        attributes_str = self.attributes_entry.get().strip()
        attributes = attributes_str.split() if attributes_str else []
        
        logging.info("=== 用户请求使用新的筛选条件进行重新筛选... ===")
        
        threading.Thread(
            target=self.monitor_instance.rescreen_modules,
            args=(category, attributes),
            daemon=True
        ).start()
    
    def enable_rescreening(self):
        """回调函数，用于启用“重新筛选”按钮"""
        self.rescreen_button.configure(state="normal")
        self.status_label.configure(text="状态: 数据已捕获，可以重新筛选。")
        
    def on_closing(self):
        self.stop_monitoring()
        self.destroy()

if __name__ == "__main__":
    import multiprocessing
    # 为 PyInstaller 等打包工具添加多进程支持
    multiprocessing.freeze_support() 
    
    setup_logging(debug_mode=True)
    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("blue")
    app = App()
    app.mainloop()