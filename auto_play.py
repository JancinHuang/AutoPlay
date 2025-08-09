import os
import sys
import time
import pyautogui
import ctypes
import cv2
import numpy as np
import mss
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QPoint
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QLabel, QFileDialog, QGridLayout, QShortcut)
from PyQt5.QtGui import QCursor, QPainter, QPen, QBrush, QColor, QImage, QKeySequence


# 高性能点击函数
def precise_click(x, y):
    ctypes.windll.user32.SetCursorPos(x, y)
    ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)  # 按下左键
    ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)  # 释放左键


# 区域选择窗口
class SnipWidget(QWidget):
    selection_done = pyqtSignal(tuple)  # (x1, y1, x2, y2)

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setWindowState(Qt.WindowFullScreen)
        self.setCursor(QCursor(Qt.CrossCursor))
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.start_pos = None
        self.end_pos = None
        self.is_selecting = False

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 100))
        if self.is_selecting and self.start_pos and self.end_pos:
            pen = QPen(QColor('red'), 2)
            painter.setPen(pen)
            brush = QBrush(QColor(255, 0, 0, 50))
            painter.setBrush(brush)
            x = min(self.start_pos.x(), self.end_pos.x())
            y = min(self.start_pos.y(), self.end_pos.y())
            w = abs(self.end_pos.x() - self.start_pos.x())
            h = abs(self.end_pos.y() - self.start_pos.y())
            painter.drawRect(x, y, w, h)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.start_pos = event.pos()
            self.end_pos = self.start_pos
            self.is_selecting = True
            self.update()

    def mouseMoveEvent(self, event):
        if self.is_selecting:
            self.end_pos = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.is_selecting:
            self.is_selecting = False
            self.end_pos = event.pos()
            self.update()
            x1, y1 = min(self.start_pos.x(), self.end_pos.x()), min(self.start_pos.y(), self.end_pos.y())
            x2, y2 = max(self.start_pos.x(), self.end_pos.x()), max(self.start_pos.y(), self.end_pos.y())
            screen_x1 = self.mapToGlobal(QPoint(x1, y1)).x()
            screen_y1 = self.mapToGlobal(QPoint(x1, y1)).y()
            screen_x2 = self.mapToGlobal(QPoint(x2, y2)).x()
            screen_y2 = self.mapToGlobal(QPoint(x2, y2)).y()
            self.selection_done.emit((screen_x1, screen_y1, screen_x2, screen_y2))
            self.close()


# 模板匹配检测线程
class TemplateMatcherThread(QThread):
    match_status_signal = pyqtSignal(bool)
    matched_5s_signal = pyqtSignal()  # 新增信号，当匹配持续5秒时触发

    def __init__(self, region, template_gray, threshold):
        super().__init__()
        self.region = region
        self.template_gray = template_gray
        self.threshold = threshold
        self.running = False
        self.match_start_time = None  # 新增：记录开始匹配的时间

    def run(self):
        self.running = True
        with mss.mss() as sct:
            while self.running:
                x1, y1, x2, y2 = self.region
                width, height = x2 - x1, y2 - y1
                img = np.array(sct.grab({"top": y1, "left": x1, "width": width, "height": height}))
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                res = cv2.matchTemplate(gray, self.template_gray, cv2.TM_CCOEFF_NORMED)
                max_val = cv2.minMaxLoc(res)[1]

                if max_val >= self.threshold:
                    if self.match_start_time is None:
                        self.match_start_time = time.time()  # 第一次检测到匹配时记录时间
                    elif time.time() - self.match_start_time >= 5:  # 持续5秒
                        self.matched_5s_signal.emit()  # 发送信号
                        self.match_start_time = None  # 重置计时器
                else:
                    self.match_start_time = None  # 匹配中断则重置计时器

                self.match_status_signal.emit(max_val >= self.threshold)
                time.sleep(0.1)

    def stop(self):
        self.running = False


# 点击引擎
class PrecisionClickEngine(QThread):
    status_update = pyqtSignal(str)
    time_update = pyqtSignal(str)
    click_count_update = pyqtSignal(int)
    next_click_update = pyqtSignal(str)

    def __init__(self, click_pos, interval_pattern):
        super().__init__()
        self.running = False
        self.click_pos = click_pos
        self.interval_pattern = interval_pattern
        self.current_index = 0
        self.next_click_time = 0
        self.start_timestamp = 0
        self.click_counter = 0

    def run(self):
        if not self.interval_pattern:
            self.status_update.emit("错误: 没有设置时间节点")
            return

        self.running = True
        self.start_timestamp = time.time()
        self.next_click_time = self.start_timestamp + self.interval_pattern[0]
        self.current_index = 0
        self.click_counter = 0

        try:
            while self.running:
                current_time = time.time()
                elapsed = int(current_time - self.start_timestamp)
                self.time_update.emit(f"{elapsed // 3600:02d}:{(elapsed % 3600) // 60:02d}:{elapsed % 60:02d}")

                # 更新下一次点击时间
                next_click_in = max(0, self.next_click_time - current_time)
                self.next_click_update.emit(f"{next_click_in:.1f}秒")

                if current_time >= self.next_click_time:
                    precise_click(*self.click_pos)
                    self.click_counter += 1
                    self.click_count_update.emit(self.click_counter)
                    self.current_index = (self.current_index + 1) % len(self.interval_pattern)
                    self.next_click_time += self.interval_pattern[self.current_index]

                time.sleep(0.1)
        except Exception as e:
            self.status_update.emit(f"错误: {str(e)}")

    def stop(self):
        self.running = False


# 主窗口
class AutoClickerWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.click_engine = None
        self.click_pos = None
        self.interval_pattern = [9, 10]  # 固定时间节点
        self.match_region = None
        self.template_gray = None
        self.match_threshold = 0.9
        self.matcher_thread = None
        self.is_topmost = True
        self.original_interval_pattern = [9, 10]  # 新增：保存原始时间节点

        self.default_template_path = "test.png"  # 添加默认图片路径
        self.template_gray = None

        # 添加快捷键
        self.shortcut_set_pos = QShortcut(QKeySequence("F8"), self)
        self.shortcut_set_pos.activated.connect(self.set_click_position)

        self.shortcut_start_stop = QShortcut(QKeySequence("F9"), self)
        self.shortcut_start_stop.activated.connect(self.toggle_operation)

        self.init_ui()
        # 尝试加载默认图片
        self.try_load_default_template()

    def init_ui(self):
        main_layout = QVBoxLayout()

        # 状态显示区
        self.status_display = QLabel("准备就绪")
        self.status_display.setAlignment(Qt.AlignCenter)
        self.status_display.setStyleSheet("font-size: 14px;")
        main_layout.addWidget(self.status_display)

        # 数据展示区
        data_layout = QGridLayout()

        # 第一行
        time_label = QLabel("运行时长:")
        self.time_display = QLabel("00:00:00")
        self.time_display.setStyleSheet("font: bold 16px; color: #2c3e50;")
        data_layout.addWidget(time_label, 0, 0)
        data_layout.addWidget(self.time_display, 0, 1)

        count_label = QLabel("点击次数:")
        self.count_display = QLabel("0")
        self.count_display.setStyleSheet("font: bold 16px; color: #27ae60;")
        data_layout.addWidget(count_label, 0, 2)
        data_layout.addWidget(self.count_display, 0, 3)

        # 第二行
        next_label = QLabel("下一次点击:")
        self.next_click_display = QLabel("0.0秒")
        self.next_click_display.setStyleSheet("font: bold 16px; color: #e67e22;")
        data_layout.addWidget(next_label, 1, 0)
        data_layout.addWidget(self.next_click_display, 1, 1)

        pos_label = QLabel("鼠标位置:")
        self.pos_display = QLabel("未设置")
        self.pos_display.setStyleSheet("font: bold 16px; color: #8e44ad;")
        data_layout.addWidget(pos_label, 1, 2)
        data_layout.addWidget(self.pos_display, 1, 3)

        # 第三行
        self.match_status_label = QLabel("检测状态: 未检测到")
        self.match_status_label.setStyleSheet("font: bold 16px;")
        data_layout.addWidget(self.match_status_label, 2, 0, 1, 4)

        main_layout.addLayout(data_layout)

        # 按钮样式 - 大按钮
        big_btn_style = """
                QPushButton {
                    padding: 20px 30px;
                    font-size: 16px;
                    font-weight: bold;
                    min-width: 200px;
                    min-height: 60px;
                    margin: 5px;
                    color: white;
                }
            """
        # 按钮区
        btn_layout = QHBoxLayout()
        btn_grid = QGridLayout()

        self.set_position_btn = QPushButton("设置鼠标位置 (F8)")
        self.set_position_btn.setStyleSheet(big_btn_style +
                                          """
                                              QPushButton {
                                                  background: #2ecc71;
                                              }
                                          """)
        self.set_position_btn.clicked.connect(self.set_click_position)
        btn_grid.addWidget(self.set_position_btn, 0, 0)

        self.toggle_top_btn = QPushButton("取消置顶")
        self.toggle_top_btn.setStyleSheet(big_btn_style +
                                          """
                                              QPushButton {
                                                  background: #3498db;
                                              }
                                          """)
        self.toggle_top_btn.clicked.connect(self.toggle_window_top)
        btn_grid.addWidget(self.toggle_top_btn, 0, 1)

        self.load_template_btn = QPushButton("加载匹配图片")
        self.load_template_btn.setStyleSheet(big_btn_style +
                                          """
                                              QPushButton {
                                                  background: #FE9900;
                                              }
                                          """)
        self.load_template_btn.clicked.connect(self.load_template)
        btn_grid.addWidget(self.load_template_btn, 1, 0)

        self.select_region_btn = QPushButton("框选识别区域")
        self.select_region_btn.setStyleSheet(big_btn_style +
                                          """
                                              QPushButton {
                                                  background: #5DE2E7;
                                              }
                                          """)
        self.select_region_btn.clicked.connect(self.select_region)
        btn_grid.addWidget(self.select_region_btn, 1, 1)

        main_layout.addLayout(btn_grid)

        # 开始/停止按钮
        self.main_action_btn = QPushButton("开始运行 (F9)")
        self.main_action_btn.setStyleSheet("padding: 18px; font: bold 20px; background: #2ecc71; color: white;")
        self.main_action_btn.clicked.connect(self.toggle_operation)
        main_layout.addWidget(self.main_action_btn)

        self.setLayout(main_layout)
        self.setWindowTitle("自动识别点击器")
        self.setMinimumSize(500, 300)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

    def try_load_default_template(self):
        """尝试加载默认模板图片"""
        try:
            if os.path.exists(self.default_template_path):
                template = cv2.imread(self.default_template_path, cv2.IMREAD_COLOR)
                if template is not None:
                    self.template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
                    self.status_display.setText(f"已自动加载默认模板: {self.default_template_path}")
                else:
                    self.status_display.setText("默认模板加载失败（图片可能损坏）")
            else:
                self.status_display.setText("未找到默认模板图片 test.png")
        except Exception as e:
            self.status_display.setText(f"加载默认模板出错: {str(e)}")

    def set_click_position(self):
        self.click_pos = pyautogui.position()
        self.pos_display.setText(f"{self.click_pos[0]}, {self.click_pos[1]}")
        self.status_display.setText(f"鼠标位置已设置为 ({self.click_pos[0]}, {self.click_pos[1]}) (F8快捷键)")

    def select_region(self):
        self.snipper = SnipWidget()
        self.snipper.selection_done.connect(self.on_region_selected)
        self.snipper.show()

    def on_region_selected(self, region):
        self.match_region = region
        self.status_display.setText(f"已选择检测区域: {region}")

    def load_template(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择模板图片", "", "Images (*.png *.jpg *.bmp)"
        )
        if path:
            try:
                template = cv2.imread(path, cv2.IMREAD_COLOR)
                if template is None:
                    self.status_display.setText("模板图片加载失败")
                    return
                self.template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
                self.status_display.setText(f"模板已加载: {path}")
            except Exception as e:
                self.status_display.setText(f"加载模板出错: {str(e)}")

    def toggle_operation(self):
        if self.click_engine and self.click_engine.isRunning():
            self.stop_operation()
            self.status_display.setText("操作已停止 (F9快捷键)")
        else:
            self.start_operation()
            self.status_display.setText("运行中... (F9停止)")

    def update_match_status(self, matched):
        if matched:
            self.match_status_label.setText("检测状态: 检测到")
            self.match_status_label.setStyleSheet("font: bold 16px; color: green;")
        else:
            self.match_status_label.setText("检测状态: 未检测到")
            self.match_status_label.setStyleSheet("font: bold 16px; color: red;")

    def start_operation(self):
        if self.click_pos is None:
            self.status_display.setText("错误: 请先设置鼠标位置")
            return

        # 启动模板匹配线程
        if self.match_region and self.template_gray is not None:
            self.matcher_thread = TemplateMatcherThread(self.match_region, self.template_gray, self.match_threshold)
            self.matcher_thread.match_status_signal.connect(self.update_match_status)
            self.matcher_thread.matched_5s_signal.connect(self.on_matched_5s)  # 连接新信号
            self.matcher_thread.start()

        # 启动点击引擎
        self.click_engine = PrecisionClickEngine(self.click_pos, self.interval_pattern)
        self.click_engine.status_update.connect(self.update_status)
        self.click_engine.time_update.connect(self.update_time)
        self.click_engine.click_count_update.connect(self.update_click_count)
        self.click_engine.next_click_update.connect(self.update_next_click)
        self.click_engine.start()

        self.main_action_btn.setText("停止运行")
        self.main_action_btn.setStyleSheet("padding: 12px; font: bold 14px; background: #e74c3c; color: white;")
        self.status_display.setText(f"运行中... 时间节点: {self.interval_pattern}")

    # 新增方法：处理匹配持续5秒的情况
    def on_matched_5s(self):
        if self.click_engine and self.click_engine.isRunning():
            # 立即点击一次
            precise_click(*self.click_pos)
            self.click_engine.click_counter += 1
            self.update_click_count(self.click_engine.click_counter)

            # 重置为原始时间节点 [9,10]
            self.click_engine.interval_pattern = self.original_interval_pattern.copy()
            self.click_engine.current_index = 0
            self.click_engine.next_click_time = time.time() + self.original_interval_pattern[0]

            self.status_display.setText(
                f"检测到匹配持续5秒，已立即点击\n重置时间节点为: {self.original_interval_pattern}")

    def stop_operation(self):
        if self.click_engine:
            self.click_engine.stop()
            self.click_engine.wait()
            self.click_engine = None
        if self.matcher_thread:
            self.matcher_thread.stop()
            self.matcher_thread.wait()
            self.matcher_thread = None

        self.main_action_btn.setText("开始运行")
        self.main_action_btn.setStyleSheet("padding: 12px; font: bold 14px; background: #2ecc71; color: white;")
        self.status_display.setText("操作已停止")

    def update_status(self, message):
        self.status_display.setText(message)

    def update_time(self, time_str):
        self.time_display.setText(time_str)

    def update_click_count(self, count):
        self.count_display.setText(str(count))

    def update_next_click(self, time_str):
        self.next_click_display.setText(time_str)

    def toggle_window_top(self):
        self.is_topmost = not self.is_topmost
        if self.is_topmost:
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
            self.toggle_top_btn.setText("取消置顶")
        else:
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowStaysOnTopHint)
            self.toggle_top_btn.setText("窗口置顶")
        self.show()

    def closeEvent(self, event):
        self.stop_operation()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = AutoClickerWindow()
    window.show()
    sys.exit(app.exec_())
