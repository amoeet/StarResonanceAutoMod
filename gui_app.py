import tkinter
import customtkinter as ctk
import threading
from typing import Optional
import queue
import logging
import sys

# Assuming these tools and core classes are in the same directory as the GUI file
from network_interface_util import get_network_interfaces
from star_resonance_monitor_core import StarResonanceMonitor
from logging_config import setup_logging # Import logging settings

# Create a custom logging handler to send log messages to a queue
class QueueHandler(logging.Handler):
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        self.log_queue.put(self.format(record))

# Create a custom stream object to redirect print content to a queue
class StreamToQueue:
    def __init__(self, text_queue):
        self.text_queue = text_queue

    def write(self, text):
        self.text_queue.put(text)

    def flush(self):
        # This function must exist, even if it does nothing
        pass

class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        # --- Window Settings ---
        self.title("星痕共鸣模组筛选器 V2.0")
        self.geometry("800x600")
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        # --- Global Variables ---
        self.monitor_thread: Optional[threading.Thread] = None
        self.monitor_instance: Optional[StarResonanceMonitor] = None
        self.interfaces = get_network_interfaces()
        self.interface_map = {f"{i}: {iface.get('description', iface['name'])}": iface['name'] 
                              for i, iface in enumerate(self.interfaces)}

        # --- UI Layout ---
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # -- Create Main Frame --
        self.main_frame = ctk.CTkFrame(self)
        self.main_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        self.main_frame.grid_columnconfigure(1, weight=1)

        # -- Network Interface Selection --
        self.label_interface = ctk.CTkLabel(self.main_frame, text="选择网络接口:")
        self.label_interface.grid(row=0, column=0, padx=10, pady=5, sticky="w")
        
        self.interface_menu = ctk.CTkOptionMenu(self.main_frame, values=list(self.interface_map.keys()))
        self.interface_menu.grid(row=0, column=1, padx=10, pady=5, sticky="ew")

        # -- Module Type Selection --
        self.label_category = ctk.CTkLabel(self.main_frame, text="选择模组类型:")
        self.label_category.grid(row=1, column=0, padx=10, pady=5, sticky="w")
        
        self.category_menu = ctk.CTkOptionMenu(self.main_frame, values=["攻击", "守护", "辅助"])
        self.category_menu.grid(row=1, column=1, padx=10, pady=5, sticky="ew")

        # -- Attribute Filter Input --
        self.label_attributes = ctk.CTkLabel(self.main_frame, text="筛选属性 (用空格隔开):")
        self.label_attributes.grid(row=2, column=0, padx=10, pady=5, sticky="w")
        
        self.attributes_entry = ctk.CTkEntry(self.main_frame, placeholder_text="例如: 力量加持 敏捷加持 特攻伤害 (留空则不过滤)")
        self.attributes_entry.grid(row=2, column=1, padx=10, pady=5, sticky="ew")

        # -- Control Buttons --
        self.control_frame = ctk.CTkFrame(self.main_frame)
        self.control_frame.grid(row=3, column=0, columnspan=2, pady=10)

        self.start_button = ctk.CTkButton(self.control_frame, text="开始监控", command=self.start_monitoring)
        self.start_button.pack(side="left", padx=10)

        self.stop_button = ctk.CTkButton(self.control_frame, text="停止监控", command=self.stop_monitoring, state="disabled")
        self.stop_button.pack(side="left", padx=10)

        # -- Log Output Box --
        self.log_textbox = ctk.CTkTextbox(self, state="disabled", wrap="word")
        self.log_textbox.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")

        # --- Set up Log Queue ---
        self.log_queue = queue.Queue()
        
        # --- Set up Logging System ---
        # 1. Get the root logger
        logger = logging.getLogger()
        logger.setLevel(logging.INFO) # Set the minimum log level you want to capture
        # 2. Add our custom handler to the root logger
        logger.addHandler(QueueHandler(self.log_queue))

        # --- Redirect Standard Output ---
        # 3. Point sys.stdout to our custom stream object
        sys.stdout = StreamToQueue(self.log_queue)

        # --- Start Queue Polling ---
        # 4. Start a scheduled task to check the queue every 100 milliseconds
        self.after(100, self.poll_log_queue)

    def poll_log_queue(self):
        """Check the queue every 100ms and update the UI with messages"""
        while True:
            try:
                # Get messages from the queue without blocking
                record = self.log_queue.get(block=False)
                
                # Add the message to the log textbox
                self.log_textbox.configure(state="normal")
                self.log_textbox.insert("end", record)
                self.log_textbox.see("end")
                self.log_textbox.configure(state="disabled")

            except queue.Empty:
                break # Queue is empty, exit the loop
        
        # Schedule the next check
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
        
        # Run the monitor in a separate thread to prevent the GUI from freezing
        self.monitor_thread = threading.Thread(target=self.monitor_instance.start_monitoring, daemon=True)
        self.monitor_thread.start()

        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.interface_menu.configure(state="disabled")
        self.category_menu.configure(state="disabled")
        self.attributes_entry.configure(state="disabled")
        
    def stop_monitoring(self):
        if self.monitor_instance:
            self.monitor_instance.stop_monitoring()
        
        # Waiting for the thread to finish is optional but good practice
        if self.monitor_thread and self.monitor_thread.is_alive():
             self.monitor_thread.join(timeout=1.0)

        self.monitor_instance = None
        self.monitor_thread = None

        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.interface_menu.configure(state="normal")
        self.category_menu.configure(state="normal")
        self.attributes_entry.configure(state="normal")
        
    def on_closing(self):
        """Handle window closing event"""
        self.stop_monitoring()
        self.destroy()

if __name__ == "__main__":
    setup_logging(debug_mode=True) # Set up the logging system to log to a file
    ctk.set_appearance_mode("System")  # Modes: "System" (default), "Dark", "Light"
    ctk.set_default_color_theme("blue")  # Themes: "blue" (default), "green", "dark-blue"
    
    app = App()
    app.mainloop()