import sys
import time
import pyautogui
import ctypes
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QMutex
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QInputDialog, QMessageBox, QGridLayout)
from PyQt5.QtGui import QFont
from pynput import keyboard


# 高性能点击函数（Windows系统专用）
def precise_click(x, y):
    ctypes.windll.user32.SetCursorPos(x, y)
    ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)  # 按下左键
    ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)  # 释放左键


class GlobalHotkeyListener(QThread):
    hotkey_triggered = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.listener = None
        self.running = False
        self.mutex = QMutex()

    def run(self):
        self.running = True
        with keyboard.Listener(on_press=self.on_press) as listener:
            self.listener = listener
            listener.join()

    def on_press(self, key):
        try:
            if key == keyboard.Key.f8:
                self.hotkey_triggered.emit()
        except AttributeError:
            pass

    def stop(self):
        if self.listener:
            self.listener.stop()
        self.running = False


class PrecisionClickEngine(QThread):
    status_update = pyqtSignal(str)
    time_update = pyqtSignal(str)
    click_count_update = pyqtSignal(int)
    operation_completed = pyqtSignal()

    def __init__(self, click_pos, interval_pattern):
        super().__init__()
        self.running = False
        self.click_pos = click_pos
        self.interval_pattern = interval_pattern  # 使用传入的点击间隔模式
        self.current_index = 0
        self.next_click_time = 0
        self.start_timestamp = 0
        self.click_counter = 0

    def run(self):
        if not self.interval_pattern:
            self.status_update.emit("错误: 没有设置时间节点")
            self.operation_completed.emit()
            return

        self.running = True
        self.start_timestamp = time.time()
        self.next_click_time = self.start_timestamp + self.interval_pattern[0]
        self.current_index = 0
        self.click_counter = 0

        try:
            while self.running:
                current_time = time.time()

                # 更新时间显示（每秒更新一次）
                if int(current_time) > int(current_time - 1):
                    elapsed = int(current_time - self.start_timestamp)
                    self.time_update.emit(
                        f"{elapsed // 3600:02d}:{(elapsed % 3600) // 60:02d}:{elapsed % 60:02d}"
                    )

                # 执行点击的条件判断
                if current_time >= self.next_click_time:
                    self.execute_click()
                    self.schedule_next_click(current_time)

                # 智能休眠机制
                sleep_time = self.calculate_sleep_time(current_time)
                time.sleep(sleep_time)

        except Exception as e:
            self.status_update.emit(f"错误: {str(e)}")
        finally:
            self.operation_completed.emit()

    def execute_click(self):
        try:
            precise_click(*self.click_pos)
            self.click_counter += 1
            self.click_count_update.emit(self.click_counter)
            current_interval = self.interval_pattern[self.current_index % len(self.interval_pattern)]
            self.status_update.emit(
                f"成功点击 ({self.click_pos[0]}, {self.click_pos[1]})\n"
                f"下次点击间隔: {current_interval}秒"
            )
        except Exception as e:
            self.status_update.emit(f"点击失败: {str(e)}")

    def schedule_next_click(self, current_time):
        self.current_index += 1
        if self.current_index >= len(self.interval_pattern):
            self.current_index = 0  # 循环模式
        next_interval = self.interval_pattern[self.current_index]
        self.next_click_time = current_time + next_interval

    def calculate_sleep_time(self, current_time):
        remaining = self.next_click_time - current_time
        if remaining > 1:
            return 0.1  # 长间隔时低频检查
        elif remaining > 0.1:
            return 0.01  # 接近点击时间时提高检查频率
        else:
            return 0.001  # 最后阶段高频检查

    def stop(self):
        self.running = False


class AutoClickerWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.click_engine = None
        self.hotkey_listener = GlobalHotkeyListener()
        self.click_pos = None
        self.interval_pattern = []  # 存储时间节点
        self.init_ui()
        self.init_hotkeys()
        self.setWindowTitle("自定义自动点击器 (F8开始/停止)")
        self.setMinimumSize(600, 450)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.is_topmost = True

    def init_ui(self):
        main_layout = QVBoxLayout()

        # 状态显示区
        self.status_display = QLabel("准备就绪\n1. 设置鼠标位置\n2. 添加时间节点\n3. 按F8或点击按钮开始运行", self)
        self.status_display.setAlignment(Qt.AlignCenter)
        self.status_display.setStyleSheet("font-size: 14px;")
        main_layout.addWidget(self.status_display)

        # 数据展示区
        data_layout = QHBoxLayout()

        # 运行时间面板
        time_panel = QVBoxLayout()
        time_label = QLabel("运行时长:", self)
        self.time_display = QLabel("00:00:00", self)
        self.time_display.setStyleSheet("font: bold 16px; color: #2c3e50;")
        time_panel.addWidget(time_label)
        time_panel.addWidget(self.time_display)

        # 点击次数面板
        count_panel = QVBoxLayout()
        count_label = QLabel("点击次数:", self)
        self.count_display = QLabel("0", self)
        self.count_display.setStyleSheet("font: bold 16px; color: #27ae60;")
        count_panel.addWidget(count_label)
        count_panel.addWidget(self.count_display)

        # 鼠标位置面板
        pos_panel = QVBoxLayout()
        pos_label = QLabel("鼠标位置:", self)
        self.pos_display = QLabel("未设置", self)
        self.pos_display.setStyleSheet("font: bold 16px; color: #8e44ad;")
        pos_panel.addWidget(pos_label)
        pos_panel.addWidget(self.pos_display)

        data_layout.addLayout(time_panel)
        data_layout.addLayout(count_panel)
        data_layout.addLayout(pos_panel)
        main_layout.addLayout(data_layout)

        # 时间节点设置区
        interval_layout = QVBoxLayout()
        interval_label = QLabel("时间节点列表 (秒):", self)
        interval_layout.addWidget(interval_label)

        # 时间节点列表
        self.interval_list = QListWidget(self)
        self.interval_list.setStyleSheet("font: 14px;")
        interval_layout.addWidget(self.interval_list)

        # 时间节点操作按钮
        interval_btn_layout = QGridLayout()

        self.add_interval_btn = QPushButton("添加节点 (Ctrl+A)", self)
        self.add_interval_btn.setShortcut("Ctrl+A")
        self.add_interval_btn.clicked.connect(self.add_interval)

        self.edit_interval_btn = QPushButton("编辑节点 (Ctrl+E)", self)
        self.edit_interval_btn.setShortcut("Ctrl+E")
        self.edit_interval_btn.clicked.connect(self.edit_interval)

        self.remove_interval_btn = QPushButton("删除节点 (Del)", self)
        self.remove_interval_btn.setShortcut("Delete")
        self.remove_interval_btn.clicked.connect(self.remove_interval)

        self.clear_intervals_btn = QPushButton("清空列表 (Ctrl+D)", self)
        self.clear_intervals_btn.setShortcut("Ctrl+D")
        self.clear_intervals_btn.clicked.connect(self.clear_intervals)

        interval_btn_layout.addWidget(self.add_interval_btn, 0, 0)
        interval_btn_layout.addWidget(self.edit_interval_btn, 0, 1)
        interval_btn_layout.addWidget(self.remove_interval_btn, 1, 0)
        interval_btn_layout.addWidget(self.clear_intervals_btn, 1, 1)

        interval_layout.addLayout(interval_btn_layout)
        main_layout.addLayout(interval_layout)

        # 控制按钮区
        control_layout = QHBoxLayout()

        self.set_position_btn = QPushButton("设置鼠标位置 (F2)", self)
        self.set_position_btn.setShortcut("F2")
        self.set_position_btn.setStyleSheet("padding: 8px; background: #3498db; color: white;")
        self.set_position_btn.clicked.connect(self.set_click_position)

        self.toggle_top_btn = QPushButton("取消置顶 (F3)", self)
        self.toggle_top_btn.setShortcut("F3")
        self.toggle_top_btn.setStyleSheet("padding: 8px; background: #f39c12; color: white;")
        self.toggle_top_btn.clicked.connect(self.toggle_window_top)

        self.main_action_btn = QPushButton("开始运行 (F8)", self)
        self.main_action_btn.setShortcut("F8")
        self.main_action_btn.setStyleSheet("padding: 12px; font: bold 14px; background: #2ecc71; color: white;")
        self.main_action_btn.clicked.connect(self.toggle_operation)

        control_layout.addWidget(self.set_position_btn)
        control_layout.addWidget(self.toggle_top_btn)
        control_layout.addWidget(self.main_action_btn)
        main_layout.addLayout(control_layout)

        # 快捷键说明
        shortcut_info = QLabel(
            "快捷键说明: F2-设置位置 | F3-置顶切换 | F8-开始/停止 | Ctrl+A-添加节点 | Ctrl+E-编辑节点 | Del-删除节点 | Ctrl+D-清空列表",
            self)
        shortcut_info.setStyleSheet("font-size: 11px; color: #7f8c8d;")
        main_layout.addWidget(shortcut_info)

        self.setLayout(main_layout)

    def init_hotkeys(self):
        self.hotkey_listener.hotkey_triggered.connect(self.toggle_operation)
        self.hotkey_listener.start()

    def toggle_window_top(self):
        self.is_topmost = not self.is_topmost
        if self.is_topmost:
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
            self.toggle_top_btn.setText("取消置顶 (F3)")
        else:
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowStaysOnTopHint)
            self.toggle_top_btn.setText("窗口置顶 (F3)")
        self.show()

    def set_click_position(self):
        self.click_pos = pyautogui.position()
        self.pos_display.setText(f"X: {self.click_pos[0]}, Y: {self.click_pos[1]}")
        self.status_display.setText(f"鼠标位置已设置为 ({self.click_pos[0]}, {self.click_pos[1]})\n请添加时间节点")

    def add_interval(self):
        interval, ok = QInputDialog.getDouble(
            self, '添加时间节点', '输入时间间隔(秒):',
            min=0.1, max=3600, decimals=2
        )
        if ok:
            self.interval_pattern.append(interval)
            self.update_interval_list()
            self.status_display.setText(f"已添加时间节点: {interval}秒")

    def edit_interval(self):
        if not self.interval_list.currentItem():
            QMessageBox.warning(self, "警告", "请先选择一个时间节点")
            return

        row = self.interval_list.currentRow()
        old_value = self.interval_pattern[row]

        interval, ok = QInputDialog.getDouble(
            self, '编辑时间节点', '输入新的时间间隔(秒):',
            value=old_value, min=0.1, max=3600, decimals=2
        )
        if ok:
            self.interval_pattern[row] = interval
            self.update_interval_list()
            self.status_display.setText(f"已更新时间节点: {old_value}秒 → {interval}秒")

    def remove_interval(self):
        if not self.interval_list.currentItem():
            QMessageBox.warning(self, "警告", "请先选择一个时间节点")
            return

        row = self.interval_list.currentRow()
        removed = self.interval_pattern.pop(row)
        self.update_interval_list()
        self.status_display.setText(f"已删除时间节点: {removed}秒")

    def clear_intervals(self):
        if not self.interval_pattern:
            return

        reply = QMessageBox.question(
            self, '确认', '确定要清空所有时间节点吗?',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self.interval_pattern.clear()
            self.update_interval_list()
            self.status_display.setText("已清空所有时间节点")

    def update_interval_list(self):
        self.interval_list.clear()
        for i, interval in enumerate(self.interval_pattern, 1):
            item = QListWidgetItem(f"{i}. {interval}秒")
            self.interval_list.addItem(item)

    def toggle_operation(self):
        if self.click_engine and self.click_engine.isRunning():
            self.stop_operation()
        else:
            self.start_operation()

    def start_operation(self):
        if self.click_pos is None:
            self.status_display.setText("错误: 请先设置鼠标位置")
            return

        if not self.interval_pattern:
            self.status_display.setText("错误: 请先添加时间节点")
            return

        self.click_engine = PrecisionClickEngine(self.click_pos, self.interval_pattern)
        self.click_engine.status_update.connect(self.update_status)
        self.click_engine.time_update.connect(self.update_time)
        self.click_engine.click_count_update.connect(self.update_click_count)
        self.click_engine.operation_completed.connect(self.on_operation_end)
        self.click_engine.start()

        self.main_action_btn.setText("停止运行 (F8)")
        self.main_action_btn.setStyleSheet("padding: 12px; font: bold 14px; background: #e74c3c; color: white;")
        self.status_display.setText(f"运行中...\n首次点击将在{self.interval_pattern[0]}秒后执行")

    def stop_operation(self):
        if self.click_engine:
            self.click_engine.stop()
            self.click_engine.wait()

    def on_operation_end(self):
        self.main_action_btn.setText("开始运行 (F8)")
        self.main_action_btn.setStyleSheet("padding: 12px; font: bold 14px; background: #2ecc71; color: white;")
        self.status_display.setText("操作已停止")

    def update_status(self, message):
        self.status_display.setText(message)

    def update_time(self, time_str):
        self.time_display.setText(time_str)

    def update_click_count(self, count):
        self.count_display.setText(str(count))

    def closeEvent(self, event):
        self.stop_operation()
        self.hotkey_listener.stop()
        self.hotkey_listener.wait()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = AutoClickerWindow()
    window.show()
    sys.exit(app.exec_())