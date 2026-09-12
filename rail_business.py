# 导入系统模块
import copy
import json
import os
import pathlib
import sys
import time
from typing import List, Optional

# 第三方库
import matplotlib.pyplot as plt
import numpy as np
from PyQt5.QtCore import (
    QDateTime, QTimer, Qt
)
from PyQt5.QtWidgets import (
    QApplication, QMessageBox, QInputDialog, QLabel,  # 文本标签组件，用于显示静态文本
    QPushButton,  # 按钮组件，用于触发交互事件
    QLineEdit,  # 单行文本输入框组件
    QVBoxLayout,  # 垂直布局管理器，组件垂直排列
    QHBoxLayout, QDialog, QFileDialog, QSpinBox, QDialogButtonBox,  # 水平布局管理器，组件水平排列
)
# ===================== 核心修复：工具栏强制显示整数，禁用科学计数法 =====================
from matplotlib.ticker import ScalarFormatter
import traceback
from client import StraightRulerClient,rtu_crc16  # 导入TCP客户端
from rail_data_utils import *
# 自定义模块导入
from rail_ui import RailStraightnessUIPanel  # 导入纯UI类

# 全局设置：解决Matplotlib中文显示问题
plt.rcParams['font.sans-serif'] = ['SimHei']
plt.rcParams['axes.unicode_minus'] = False

# 配置文件路径
CONFIG_FILE = "multi_checkbox_nolist_config.json"


class RailStraightnessBusiness:
    """
    钢轨平直度测量仪业务逻辑类
    功能：处理所有业务逻辑（TCP通信、数据处理、绘图、交互事件），与UI层解耦
    """

    def __init__(self):
        # ========== 初始化UI面板 ==========
        self.ui = RailStraightnessUIPanel()

        # ========== 业务状态变量 ==========
        self.client: Optional[StraightRulerClient] = None  # TCP客户端
        self.is_continuous_measuring = False  # 连续测量状态
        self.is_continus_dandian = False  # 连续单点测量状态
        self.scatter_plot_connected = False  # 散点图信号连接状态
        self.dandian_plot_connected = False  # 单点图信号连接状态
        self.last_time = None  # 测量时间记录
        self.mark_list = None  # 掩码列表
        self.two_jioazhun = None  # 二次校准数据

        self.point = 0  # 单点测量点位
        self.finished_time = None  # 测量完成时间
        self.current_cali_num = 0  # 当前校准编号

        self.num_spin = 1

        # ========== 绑定UI信号与业务逻辑 ==========
        self._bind_ui_events()

        # ========== 加载配置 ==========
        self.load_all_checkbox_states()

        # ========== 初始化绘图 ==========
        self._init_main_plot_data()
        self._init_compare_plot_data()

        # ============ 画图的数据 ===============
        self.final_um = []  # 微米值数据缓存
        self.final_mm = []  # 毫米值数据缓存
        self.distance_to_chord = []  # 拉弦后的数据缓存
        

    def _bind_ui_events(self):
        """绑定UI控件的事件到业务逻辑方法"""
        # 1. 功能控制区按钮
        self.ui.func_btns["初始化掩码"].clicked.connect(self.on_firmware_update)
        self.ui.func_btns["掩码设置"].clicked.connect(self.on_name_setting)
        self.ui.func_btns["稳定测试"].clicked.connect(self.on_stability_test)
        self.ui.func_btns["原始采样"].clicked.connect(self.on_original_sampling)
        self.ui.func_btns["版本信息"].clicked.connect(self.on_version_info)
        self.ui.func_btns["2次校准"].clicked.connect(self.on_double_calibration)
        self.ui.func_btns["清除校准"].clicked.connect(self.on_factory_reset)
        self.ui.func_btns["清除二校"].clicked.connect(self.on_remove_erjiao)
        self.ui.func_btns["获取标签"].clicked.connect(self.on_get_label)
        self.ui.func_btns["存储数据"].clicked.connect(self.on_save_data)

        # 2. 底层控制区按钮
        self.ui.bottom_btns["连接下位机"].clicked.connect(self.on_connect)
        self.ui.bottom_btns["读取参数"].clicked.connect(self.on_read_parameters)
        self.ui.bottom_btns["设置参数"].clicked.connect(self.on_set_parameters)
        self.ui.bottom_btns["正常测量"].clicked.connect(self.on_start_normal_measure)
        self.ui.bottom_btns["单点测量"].clicked.connect(self.on_start_single_point_measure)
        self.ui.bottom_btns["显示正常"].clicked.connect(self.on_show_normal_top10)
        self.ui.bottom_btns["版本升级"].clicked.connect(self.on_update_version)
        self.ui.bottom_btns["读取校准"].clicked.connect(self.on_read_calibration)
        self.ui.bottom_btns["设置校准"].clicked.connect(self.on_set_calibration2)
        self.ui.bottom_btns["连续测量"].clicked.connect(self.on_continuous_measure_toggle)
        self.ui.bottom_btns["退出"].clicked.connect(self.on_exit_app)

        # 3. 复选框控制区
        self.ui.checkboxes["采用二次校准"].stateChanged.connect(self.on_checkbox1_changed)
        self.ui.checkboxes["校准值翻转"].stateChanged.connect(self.on_checkbox2_changed)
        self.ui.checkboxes["去板间"].stateChanged.connect(self.update_compare_plot)
        self.ui.checkboxes["中值滤波"].stateChanged.connect(self.update_compare_plot)
        self.ui.checkboxes["取奇数"].stateChanged.connect(self.update_compare_plot)
        self.ui.checkboxes["取偶数"].stateChanged.connect(self.update_compare_plot)
        self.ui.checkboxes["使用掩码"].stateChanged.connect(self.update_compare_plot)
        self.ui.checkboxes["显示上下界限"].stateChanged.connect(self.updabianjie)
        self.ui.checkboxes["显示数值"].stateChanged.connect(self.update_main_plot)
        self.ui.checkboxes["显示数值"].stateChanged.connect(self.update_compare_plot)

        # 4. 源值比对页控件
        self.ui.ylimcombo.currentTextChanged.connect(self.update_compare_plot)
        self.ui.cb_show_mm_curve.stateChanged.connect(self.update_compare_plot)
        self.ui.cb_show_distance.stateChanged.connect(self.update_compare_plot)

        # 5. 单点分析页按钮
        self.ui.single_refresh_btn.clicked.connect(self.on_start_single_point_measure)
        self.ui.single_continuous_btn.clicked.connect(self.on_continuous_single)

        # 6. 信号发射器绑定
        self.ui.log_signal.connect(self.ui.append_log)

        # 7. 绑定菜单点击事件
        self.ui.show_action.triggered.connect(self.on_table_show)
        self.ui.download_action.triggered.connect(self.on_table_download)
        self.ui.delete_action.triggered.connect(self.on_delete_selected)
        # 出厂校准右键菜单绑定（添加这一行）
        self.ui.cali_download_action.triggered.connect(self.on_cali_download)
        self.ui.cali_delete_action.triggered.connect(self.on_cali_delete_selected)
        self.ui.cali_show_action.triggered.connect(self.on_cali_table_show)
    # ===================== 基础UI交互事件 =====================
    def on_firmware_update(self):
        """初始化掩码按钮事件"""
        self.ui.append_log("【操作】点击了初始化掩码按钮")
        if self.client:
            self.mark_list = [0] * self.client.sensor_count

    def on_name_setting(self):
        """掩码设置按钮事件：输入索引并置1"""
        self.ui.append_log("【操作】点击了掩码设置按钮")
        if not self.client:
            QMessageBox.critical(self.ui, "错误", "请先连接下位机！")
            return

        # 弹出输入对话框
        title = "掩码索引设置"
        prompt = f"请输入需要置为1的索引(1-{self.client.sensor_count})"
        input_str, ok = QInputDialog.getText(self.ui, title, prompt)

        if not ok or not input_str.strip():
            self.ui.append_log("【提示】用户取消了掩码索引输入/未输入任何内容")
            return

        # 解析输入
        input_list = input_str.replace(',', ' ').split()
        input_list = [item.strip() for item in input_list if item.strip()]
        if not input_list:
            self.ui.append_log("【警告】未识别到任何有效输入！")
            return

        # 处理索引
        valid_indexes = []
        invalid_inputs = []
        max_valid_idx = min(200, len(self.mark_list) - 1) if self.mark_list else 200

        for item in input_list:
            try:
                idx = int(item)
                if 0 <= idx <= max_valid_idx:
                    self.mark_list[idx - 1] = 1
                    valid_indexes.append(idx)
                else:
                    invalid_inputs.append(f"{idx}（有效范围：0~{max_valid_idx}）")
            except ValueError:
                invalid_inputs.append(f"{item}（非有效整数）")

        # 日志输出
        if valid_indexes:
            self.ui.append_log(f"【成功】已将索引 {sorted(valid_indexes)} 对应的掩码置为1")
        if invalid_inputs:
            self.ui.append_log(f"【警告】无效输入：{'; '.join(invalid_inputs)}")

    def on_stability_test(self):
        """稳定测试按钮事件"""
        self.ui.append_log("【操作】点击了稳定测试按钮，开始执行设备稳定测试...")
        self.client.start_upgrade_010F()

    def on_original_sampling(self):
        """原始采样按钮事件"""
        self.ui.append_log("【操作】点击了原始采样按钮，开始采集原始数据...")

    def on_version_info(self):
        """版本信息按钮事件"""
        self.ui.append_log("【操作】点击了版本信息按钮，显示设备版本信息：固件v513，硬件v2.5")

    def on_double_calibration(self):
        """二次校准按钮事件"""
        self.ui.append_log("【操作】点击了2次校准按钮，开始执行二次校准流程...")
        if not self.client:
            return

        try:
            self.client.normal_measure_finished.disconnect(self.cal_two_jioazhun)
            self.ui.checkboxes["采用二次校准"].stateChanged.disconnect(self.on_checkbox1_changed)
        except:
            pass
        self.ui.checkboxes["采用二次校准"].setChecked(True)

        self.client.normal_measure_finished.connect(self.cal_two_jioazhun)
        self.client.start_normal_measure(side=0)
        self.last_time = QDateTime.currentDateTime()
        self.ui.plot_progress_bar.setValue(50)

    def on_factory_reset(self):
        """清除校准按钮事件"""
        self.ui.append_log("【操作】点击了清除校准按钮，准备恢复设备出厂设置...")
        if self.client:
            self.client.clear_calibration_table()

    def on_remove_erjiao(self):
        """出厂报告按钮事件"""

        try:
            self.ui.append_log("【操作】点击了清除二校按钮...")
            # ========== 新增：弹窗获取整数 ==========
            # # 1. 创建输入对话框，仅允许输入整数
            # input_dialog = QInputDialog(self.ui)
            # input_dialog.setWindowTitle("输入编号")
            # input_dialog.setLabelText("请输入需要清除的编号：")
            # input_dialog.setInputMode(QInputDialog.IntInput)  # 强制整数输入模式
            # input_dialog.setIntMinimum(0)  # 可选：设置最小值（根据需求调整）
            # input_dialog.setIntMaximum(20)  # 可选：设置最大值（根据需求调整）
            # input_dialog.setIntValue(0)  # 默认值
            #
            # # 2. 显示弹窗并判断用户是否确认
            # if not input_dialog.exec_():
            #     self.ui.append_log("【操作】用户取消输入整数，清除二校操作终止")
            #     return  # 用户点击取消，终止函数
            #
            # # 3. 获取用户输入的整数
            # input_int = input_dialog.intValue()

            timestamp = QDateTime.currentDateTime()
            time1 = timestamp.toString("yyyyMMdd")
            time2 = int(time1)
            # if input_int == 0:
            #     self.client.calibration_data[input_int]["distance"] = 999
            self.client.set_calibration_value(0, 0, time2, 999,
                                              [0] * self.client.sensor_count)
            self.client.calibration_data[0]["table"] = [0] * self.client.sensor_count
            self.update_main_plot()
            self.update_compare_plot()
        except:
            pass

    def on_get_label(self):
        """获取标签按钮事件"""
        self.ui.append_log("【操作】点击了获取标签按钮，读取设备标识标签信息...")

    def on_save_data(self):
        """存储数据按钮事件"""
        if not self.client:
            return
        self.ui.append_log("【操作】点击了存储数据按钮，开始保存当前测量数据...")
        self.save_list_to_table_with_qt(self.client.normal_measure_data)
        self.save_list_to_table_with_qt(self.final_um)

    # ===================== TCP连接与参数管理 =====================
    def on_connect(self):
        """连接下位机按钮事件"""
        lanya_name = self.ui.ip_edit.text().strip()
        port_str = self.ui.port_edit.text().strip()

        if not lanya_name:
            QMessageBox.critical(self.ui, "错误", "请先输入下位机IP地址！")
            return

        text = self.ui.bottom_btns["连接下位机"].text()
        if text =='已连接':
            self.ui.bottom_btns["连接下位机"].setText("连接下位机")
            self.ui.bottom_btns["连接下位机"].setStyleSheet("")
        # try:
        #     port = int(port_str)
        #     if not (1 <= port <= 65535):
        #         raise ValueError
        # except ValueError:
        #     QMessageBox.critical(self.ui, "错误", "端口号必须是1-65535之间的整数！")
        #     return

        # 日志转发函数
        def forward_client_log(message):
            self.ui.log_signal.emit(f"[客户端] {message}")

        # 连接逻辑
        try:
            if self.client:
                self.ui.append_log("【连接】发现旧客户端，准备清理...")
                # 设备连接/校准完成信号 安全断开
                try:
                    self.client.calibration_finished.disconnect()
                    self.client.normal_measure_finished.disconnect()
                    self.client.log_signal.disconnect()
                    self.client.disconnect()
                except TypeError:
                    pass

            self.ui.append_log(f"【连接】创建客户端实例：{lanya_name}")
            self.client = StraightRulerClient(lanya_name)
            self.client.log_signal.connect(forward_client_log)# 在创建客户端的同时即绑定信号输出
            self.client.connected_signal.connect(self.yilianjie)
            self.client.connect()


            # 绑定客户端信号
            if self.client:
                self.client.normal_measure_finished.connect(self.updata_jindutiao)
                self.client.normal_measure_finished.connect(self.update_main_plot)
                self.client.normal_measure_finished.connect(self.update_compare_plot)
                self.client.normal_measure_finished.connect(self.add_data)
                self.client.calibration_finished.connect(self.update_main_plot)
                # self.client.calibration_finished.connect(self.add_data_cal)
                self.client.state_disconnected.connect(self.state_dis)
                self.mark_list = [0] * self.client.sensor_count

        except Exception as e:
            import traceback
            err_detail = traceback.format_exc()
            self.ui.append_log(f"【连接失败】原因：{str(e)}")
            self.ui.append_log(f"【连接失败详情】\n{err_detail}")
    def yilianjie(self):
        self.ui.append_log(
            f"【连接】connect()执行完成，客户端connected状态：{getattr(self.client, 'connected', False)}")

        if self.client.connected:
            # 更新按钮样式和文本
            self.ui.bottom_btns["连接下位机"].setStyleSheet("""
                           QPushButton {
                               background-color: #4CAF50;
                               color: white;
                               font-size: 12px;
                               border: none;
                               border-radius: 4px;
                           }
                           QPushButton:hover {
                               background-color: #45a049;
                           }
                       """)
            self.ui.bottom_btns["连接下位机"].setText("已连接")
            self.on_read_parameters()
            QTimer.singleShot(2000, self.on_read_calibration)


    def updata_jindutiao(self):
        """更新进度条和时间间隔"""
        self.ui.plot_progress_bar.setValue(100)
        self.finished_time = QDateTime.currentDateTime()

        if self.last_time is None:
            self.last_time = self.finished_time

        # 计算时间间隔
        msecs_diff = self.last_time.msecsTo(self.finished_time)
        time_diff_seconds = msecs_diff / 1000.0
        self.ui.Lable_time.setText(f"时间间隔:{time_diff_seconds:.2f}秒")
        self.last_time = self.finished_time

    def state_dis(self):
        """断开连接状态更新"""
        self.ui.bottom_btns["连接下位机"].setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                font-size: 12px;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        self.ui.bottom_btns["连接下位机"].setText("连接下位机")

    def on_read_parameters(self):
        """读取参数按钮事件"""
        if not self.client or not self.client.connected:
            QMessageBox.critical(self.ui, "错误", "请先连接下位机！")
            return

        self.client.read_parameters()
        QTimer.singleShot(1000, self.update_parameter_labels)

    def update_parameter_labels(self):
        """更新设备参数标签"""
        if not self.client:
            return
        self.ui.info_labels["设备型号"].setText(f'设备型号：{self.client.device_params.get("sn", "未知")}')
        self.ui.info_labels["设备温度"].setText(f'设备温度：{self.client.device_params.get("batttemp", "未知")}℃')
        self.ui.info_labels["电池电压"].setText(f'电池电压：{self.client.device_params.get("battvoltage", "1000")}mV')
        self.ui.info_labels["固件版本"].setText(f'固件版本：{self.client.sensor_count}')
        self.ui.info_labels["校准时间"].setText(f'校准时间：{self.client.device_params.get("calib_time","未知")}')
        self.ui.append_log("【读取参数】参数已更新")

    def on_set_parameters(self):
        """设置参数按钮事件【标准Qt模态弹窗，匹配set_calibration2风格】"""
        # 1. 连接校验（和你原有逻辑一致）
        if not self.client or not self.client.connected:
            QMessageBox.critical(self.ui, "错误", "请先连接下位机！")
            return

        # ===================== 标准Qt Dialog弹窗（核心修改） =====================
        dialog = QDialog(self.ui)  # 改用QDialog，原生标准弹窗
        dialog.setWindowTitle("设置设备参数")
        dialog.setFixedSize(750, 900)
        dialog.setWindowModality(Qt.WindowModal)  # 模态弹窗（必须操作完才能点主界面）
        # 灰色背景
        dialog.setAutoFillBackground(True)
        dialog.setStyleSheet("background-color: #e0e0e0;")
        # ======================================================================

        # 自动关机时间
        power_off_label = QLabel("自动关机时间：", dialog)
        power_off_edit = QLineEdit(dialog)
        power_off_edit.setText(str(self.client.device_params.get("PowerOffTime", "<UNK>")))
        power_off_edit.setPlaceholderText("请输入非负整数")

        # 校准数据条数
        calib_num_label = QLabel("校准数据条数(0-31)：", dialog)
        calib_num_edit = QLineEdit(dialog)
        calib_num_edit.setText(str(self.client.device_params.get("calib_num", "<UNK>")))
        calib_num_edit.setPlaceholderText("请输入0-31的整数")

        # QDateTime 获取当前日期 → 格式化为 20260313 纯数字整数
        calib_time_label = QLabel("校准时间(自动获取)：", dialog)
        current_dt = QDateTime.currentDateTime()
        # 格式化为 yyyyMMdd 字符串（20260313），并转换为整数
        date_str = current_dt.toString("yyyyMMdd")
        auto_calib_time = int(date_str)
        # 界面显示
        calib_time_display = QLabel(f"{auto_calib_time} (日期格式：年月日)", dialog)
        calib_time_display.setStyleSheet("color: #666666; font-style: italic;")

        # 设备SN
        sn_label = QLabel("设备SN(最长12字符)：", dialog)
        sn_edit = QLineEdit(dialog)
        sn_edit.setText(self.client.device_params.get("sn", "未知"))
        sn_edit.setPlaceholderText("请输入最多12位字符")

        # 10个保留字段
        res_labels = []
        res_edits = []
        for i in range(10):
            res_label = QLabel(f"保留字段{i}(最长16字符)：", dialog)
            res_edit = QLineEdit(dialog)
            res_edit.setPlaceholderText(f"保留字段{i}，可不填")
            res_labels.append(res_label)
            res_edits.append(res_edit)

        # 确定/取消按钮
        ok_btn = QPushButton("确定", dialog)
        cancel_btn = QPushButton("取消", dialog)

        # 布局
        main_layout = QVBoxLayout(dialog)
        main_layout.addWidget(power_off_label)
        main_layout.addWidget(power_off_edit)
        main_layout.addWidget(calib_num_label)
        main_layout.addWidget(calib_num_edit)
        main_layout.addWidget(calib_time_label)
        main_layout.addWidget(calib_time_display)
        main_layout.addWidget(sn_label)
        main_layout.addWidget(sn_edit)
        for label, edit in zip(res_labels, res_edits):
            main_layout.addWidget(label)
            main_layout.addWidget(edit)

        btn_layout = QHBoxLayout()
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        main_layout.addLayout(btn_layout)
        dialog.setLayout(main_layout)

        # 确定按钮逻辑
        def on_ok():
            try:
                power_off_time = int(power_off_edit.text().strip())
                calib_num = int(calib_num_edit.text().strip())
                calib_time = auto_calib_time
                sn = sn_edit.text().strip()
                res_list = [edit.text().strip() for edit in res_edits]

                # 前端校验
                if power_off_time < 0:
                    QMessageBox.critical(dialog, "错误", "自动关机时间必须为非负整数！")
                    return
                if not 0 <= calib_num <= 31:
                    QMessageBox.critical(dialog, "错误", "校准数据条数必须在0-31之间！")
                    return
                if len(sn) > 12:
                    QMessageBox.critical(dialog, "错误", "SN长度不能超过12字符！")
                    return

                # 发送指令
                result = self.client.set_parameters(
                    power_off_time=power_off_time,
                    calib_num=calib_num,
                    calib_time=calib_time,
                    sn=sn,
                    res_list=res_list
                )

                if result:
                    self.ui.append_log(
                        f"【设置参数成功】自动关机={power_off_time}s，校准条数={calib_num}，时间={calib_time}，SN={sn}")
                    dialog.accept()  # 标准关闭弹窗
                else:
                    QMessageBox.critical(dialog, "错误", "参数设置失败！")

            except ValueError:
                QMessageBox.critical(dialog, "错误", "请输入有效整数！")

        # 绑定按钮
        ok_btn.clicked.connect(on_ok)
        cancel_btn.clicked.connect(dialog.reject)  # 标准取消逻辑

        # ===================== 标准弹窗显示（和你示例一致） =====================
        dialog.exec_()  # 模态执行，替代show()，完全匹配你的代码风格

    # ===================== 测量相关逻辑 =====================
    def on_start_normal_measure(self):
        """正常测量按钮事件"""
        if not self.client or not self.client.connected:
            QMessageBox.critical(self.ui, "错误", "请先连接下位机！")
            return

        self.client.start_normal_measure(side=0)
        self.ui.plot_progress_bar.setValue(50)
        self.last_time = QDateTime.currentDateTime()
        self.ui.append_log(f"【启动正常测量】已触发数据采集")
        self.update_single_plot()

    def on_start_single_point_measure(self):
        """单点测量按钮事件"""
        try:
            self.client.single_finished.disconnect()
        except:
            pass
        self.client.single_finished.connect(self.update_single_plot)

        if not self.client or not self.client.connected:
            QMessageBox.critical(self.ui, "错误", "请先连接下位机！")
            return

        point, ok = QInputDialog.getInt(self.ui, "单点测量", f"测量点（1-{self.client.sensor_count}）：", min=1, max=self.client.sensor_count)
        if ok:
            self.point = point
            self.client.start_single_point_measure(side=0, point=point)
            self.ui.append_log(f"【启动单点测量】已完成测点{point}的数据采集")

    def on_show_normal_top10(self):
        """显示正常测量前10值"""
        if not self.client:
            QMessageBox.critical(self.ui, "错误", "请先连接下位机！")
            return
        if len(self.client.normal_measure_data) == 0:
            return

        with self.client.data_lock:
            adc_list = self.client.normal_measure_data[-1].copy()

        top10 = adc_list[:10]
        self.ui.append_log(f"【正常测量前10值】{top10}")

        # 绘制临时图表
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
        from PyQt5.QtWidgets import QMainWindow

        plot_window = QMainWindow(self.ui)
        plot_window.setWindowTitle("正常测量数据分布")
        plot_window.setGeometry(200, 200, 900, 600)

        fig = Figure(figsize=(9, 5), dpi=100)
        ax = fig.add_subplot(111)
        x = list(range(1, 201))
        ax.plot(x, adc_list, color="#1f77b4", linewidth=1.5, marker=".", markersize=3, label="正常测量ADC值")
        ax.set_title("正常测量数据分布（200个测点）", fontsize=14)
        ax.set_xlabel("测点编号（1-200）", fontsize=12)
        ax.set_ylabel("ADC测量值", fontsize=12)
        ax.grid(True, alpha=0.3)
        ax.legend(loc="upper right")
        ax.set_xlim(1, 201)

        canvas = FigureCanvas(fig)
        plot_window.setCentralWidget(canvas)
        plot_window.show()

    def on_update_version(self):
        """升级版本：选择BIN文件 → 读取数据 → 计算CRC → 发送升级指令"""
        # 1. 弹出文件选择框，只筛选 .bin 格式文件
        file_path, file_type = QFileDialog.getOpenFileName(
            self.ui,  # 父窗口（你的主窗口）
            "选择升级固件文件",  # 对话框标题
            "",  # 默认打开路径（空=桌面）
            "固件文件 (*.bin)"  # 文件过滤：只显示.bin
        )

        # 2. 如果用户取消选择文件，直接退出
        if not file_path:

            return

        # 3. 读取选中的二进制文件
        try:
            with open(file_path, "rb") as f:
                binary_data = f.read()  # 读取文件二进制数据

            # 4. 校验文件是否为空
            if len(binary_data) == 0:

                return

            # 5. 计算CRC、赋值升级数据
            crc = rtu_crc16(binary_data)
            self.client.upgrade_file_data = binary_data



            # 7. 调用升级指令（传入文件长度+CRC）
            self.client.start_upgrade_0105(len(binary_data), crc)

        except Exception as e:
            # 捕获文件读取异常
            self.ui.append_log(f"【错误】文件读取失败：{str(e)}")




    # ===================== 连续测量逻辑 =====================
    def on_continuous_measure_toggle(self):
        """连续测量切换按钮事件"""
        if not self.client or not self.client.connected:
            QMessageBox.critical(self.ui, "错误", "请先连接下位机！")
            return

        if not self.is_continuous_measuring:
            self._start_continuous_measure()
        else:
            self._stop_continuous_measure()

    def _start_continuous_measure(self):
        """启动连续测量"""
        try:
            if not self.scatter_plot_connected:
                self.client.normal_measure_finished.connect(self.plot_mean_scatter)
                self.client.normal_measure_finished.connect(self.on_start_normal_measure)
                self.scatter_plot_connected = True
            self.client.normal_measure_data.clear()
            self.ui.bottom_btns["连续测量"].setText("停止")
            self.is_continuous_measuring = True
            self.on_start_normal_measure()
            self.ui.append_log("【连续测量】已启动")
        except Exception as e:
            self.ui.append_log(f"【连续测量启动失败】{str(e)}")
            self.is_continuous_measuring = False
            self.scatter_plot_connected = False

    def _stop_continuous_measure(self):
        """停止连续测量"""
        try:
            if self.scatter_plot_connected:
                self.client.normal_measure_finished.disconnect(self.plot_mean_scatter)
                self.client.normal_measure_finished.disconnect(self.on_start_normal_measure)
                self.scatter_plot_connected = False

            self.ui.bottom_btns["连续测量"].setText("连续测量")
            self.is_continuous_measuring = False
            self.ui.append_log("【连续测量】已停止")
        except Exception as e:
            self.ui.append_log(f"【连续测量停止失败】{str(e)}")

    def on_continuous_single(self):
        """连续单点测量切换"""
        if not self.client or not self.client.connected:
            QMessageBox.critical(self.ui, "错误", "请先连接下位机！")
            return

        if not self.is_continus_dandian:
            point, ok = QInputDialog.getInt(self.ui, "单点测量", "测量点（1-200）：", min=1, max=200)
            if ok:
                self.point = point
                self._start_continuous_dandian_measure()
        else:
            self._stop_continuous_dandian_measure()

    def _start_continuous_dandian_measure(self):
        """启动连续单点测量"""
        try:
            if not self.dandian_plot_connected:
                self.client.single_finished.connect(self.update_single_plot)
                self.client.single_finished.connect(self._start_continuous_dandian_measure)
                self.dandian_plot_connected = True

            self.ui.single_continuous_btn.setText("停止")
            self.is_continus_dandian = True
            self.client.start_single_point_measure(side=0, point=self.point)
            self.ui.append_log("【连续单点】已启动")
        except Exception as e:
            self.ui.append_log(f"【连续单点启动失败】{str(e)}")
            self.is_continus_dandian = False
            self.dandian_plot_connected = False

    def _stop_continuous_dandian_measure(self):
        """停止连续单点测量"""
        try:
            if self.dandian_plot_connected:
                self.client.single_finished.disconnect(self.update_single_plot)
                self.client.single_finished.disconnect(self._start_continuous_dandian_measure)
                self.dandian_plot_connected = False

            self.ui.single_continuous_btn.setText("连续单点")
            self.is_continus_dandian = False
            self.ui.append_log("【连续单点】已停止")
        except Exception as e:
            self.ui.append_log(f"【连续单点停止失败】{str(e)}")

    # ===================== 校准相关逻辑 =====================
    def on_read_calibration(self):
        """读取校准值（1-8号），读完后自动计算二次校准值 two_jioazhun"""
        if not self.client or not self.client.connected:
            QMessageBox.critical(self.ui, "错误", "请先连接下位机！")
            return

        self.current_cali_num = 0


        def read_next_calibration():
            try:
                if self.current_cali_num > 0:
                    self.add_data_cal()
                # 循环读取所有校准编号
                if self.current_cali_num <= self.client.device_params["calib_num"]:
                    try:
                        # 读取当前编号校准值
                        self.client.read_calibration_value(self.current_cali_num)
                        self.ui.append_log(f"【读取校准值】正在读取编号 {self.current_cali_num} 的校准数据")
                        self.current_cali_num += 1
                    except Exception as e:
                        self.ui.append_log(f"【读取校准值】编号 {self.current_cali_num} 读取失败：{str(e)}")
                        self.current_cali_num += 1
                else:
                    # ===================== 核心：所有数据读取完毕，开始计算二次校准值 =====================
                    self.ui.append_log("【读取校准值】所有校准数据读取完成，开始计算二次校准值...")
                    # 断开信号，避免重复触发
                    try:
                        self.client.calibration_finished.disconnect(read_next_calibration)
                    except:
                        pass

                    target_table = None  # 存储distance=999的table
                    base_table = None  # 存储基准num对应的table

                    # 1. 遍历已读取的校准数据，查找 distance=999 的校准表
                    with self.client.data_lock:
                        for num, data in self.client.calibration_data.items():
                            if data.get("distance") == 999:
                                target_table = data.get("table", [])
                                self.ui.append_log(f"【找到校准表】distance=999 对应编号：{num}")
                                break

                        # 2. 校验 target_table 是否合法（存在 + 第一个值≠0）
                        if not target_table or len(target_table) == 0 or target_table[0] == 0:
                            self.ui.append_log("【错误】未找到有效 distance=999 校准表（或首值为0），无法计算二次校准！")
                            return

                        # 3. 获取基准校准表（self.client.jiaozhun_num 对应的table）
                        base_num = self.client.jiaozhun_num
                        if base_num == -1:
                            return
                        base_data = self.client.calibration_data.get(base_num)
                        if not base_data:
                            self.ui.append_log(f"【错误】未找到基准编号 {base_num} 的校准表！")
                            return
                        base_table = base_data.get("table", [])
                        self.ui.append_log(f"【找到基准表】基准编号：{base_num}")

                    # 4. 校验两个表长度一致
                    if len(target_table) != len(base_table):
                        self.ui.append_log("【错误】校准表长度不匹配，无法计算！")
                        return

                    # 5. 核心计算：999表 - 基准表 → 二次校准值
                    if self.ui.checkboxes["校准值翻转"].isChecked():
                        # 翻转模式：16383 - (后值 - 前值)
                        self.two_jioazhun = [16383 - (a - b) for a, b in zip(base_table, target_table)]
                    else:
                        # 正常模式：后值 - 前值
                        self.two_jioazhun = [a - b for a, b in zip(base_table, target_table)]

                    self.ui.append_log("✅ 二次校准值计算完成！")
                    return

            except Exception as e:
                self.ui.append_log(f"【读取校准值】异常：{str(e)}")
                # 异常时断开信号
                try:
                    self.client.calibration_finished.disconnect(read_next_calibration)
                except:
                    pass

        # 绑定信号，启动读取
        try:
            self.client.calibration_finished.disconnect(read_next_calibration)
        except:
            pass
        self.client.calibration_finished.connect(read_next_calibration)
        read_next_calibration()


    def on_set_calibration(self):
        """设置校准值按钮回调"""
        if self.client is None or not self.client.connected:
            QMessageBox.critical(self.ui, "错误", "请先连接下位机！")
            return

        # 第一步：输入校准编号
        num, ok = QInputDialog.getInt(self.ui, "设置校准值", "校准编号（0-8）：", min=0, max=8)
        if not ok:
            return

        # 第二步：选择TXT文件
        file_path, _ = QFileDialog.getOpenFileName(
            self.ui,
            "请选择校准值TXT文件",
            "./",
            "文本文件 (*.txt);;所有文件 (*.*)"
        )


        if not file_path:
            return

        # 第三步：读取文件并设置校准值
        try:
            table = []
            with open(file_path, "r", encoding="utf-8") as f:
                # 第一步：把所有行的十六进制字符拼接成一个连续的字符串（去除空格/换行）
                all_hex_chars = ""
                for line in f:
                    clean_line = line.strip()
                    if clean_line:
                        # 去掉行内的空格，拼接成连续的十六进制字符串
                        all_hex_chars += clean_line.replace(" ", "")

                # 第二步：每4个字符拆分，拼接为一个完整的十六进制值
                # 校验：字符总数必须是4的倍数，否则补0或提示
                if len(all_hex_chars) % 4 != 0:
                    print(f"警告：十六进制字符总数 {len(all_hex_chars)} 不是4的倍数，已补0至最近的4的倍数")
                    # 补0到4的倍数（可选：也可直接报错返回）
                    pad_len = 4 - (len(all_hex_chars) % 4)
                    all_hex_chars += "0" * pad_len

                # 每4个字符处理一次
                for i in range(0, len(all_hex_chars), 4):
                    # 截取4个字符的十六进制串
                    hex_4char = all_hex_chars[i:i + 4]
                    hex_4char = self.swap_2bytes_hex(hex_4char)
                    try:
                        # 转换为十进制值（如需浮点型则改为 float(int(hex_4char, 16))）
                        dec_value = int(hex_4char, 16)
                        table.append(dec_value)
                    except ValueError:
                        print(f"警告：无效的4位十六进制串 {hex_4char}，已跳过")
                        continue

            # 直接在主线程执行
            current_local_dt = QDateTime.currentDateTime()
            # 2. 转为Unix时间戳（秒级，对应1970-01-01 00:00:00 UTC，返回Python int类型）
            unix_timestamp_sec = current_local_dt.toSecsSinceEpoch()
            self.client.set_calibration_value(num,unix_timestamp_sec, table)
            # self.signal_emitter.log_signal.emit(f"【设置校准值】成功设置编号{num}的校准值（共{len(table)}个数据）")

        except FileNotFoundError:
            QMessageBox.critical(self.ui, "错误", f"选中的文件不存在：{file_path}")
        except ValueError:
            QMessageBox.critical(self.ui, "错误", f"文件 {file_path} 中存在非数字的无效校准值！")
        except Exception as e:
            QMessageBox.critical(self.ui, "错误", f"读取校准文件失败：{str(e)}")


    def on_set_calibration1(self):
        """设置校准值按钮回调"""
        if self.client is None or not self.client.connected:
            QMessageBox.critical(self.ui, "错误", "请先连接下位机！")
            return

        # 第一步：输入校准编号
        num, ok = QInputDialog.getInt(self.ui, "设置校准值", "校准编号（0-8）：", min=0, max=8)
        if not ok:
            return

        # 第二步：选择XLS/XLSX文件
        file_path, _ = QFileDialog.getOpenFileName(
            self.ui,
            "请选择校准值Excel文件",
            "./",
            "Excel文件 (*.xls *.xlsx);;所有文件 (*.*)"
        )

        if not file_path:
            return

        try:
            # 校准值：跳过前2列（skip_cols_start=2），读取全量行
            calib_data = read_data_file(file_path, 2, self.client.sensor_count)

            # ========== 核心逻辑：新建字典存储校准数据 ==========
            calib_data_dict = {}

            # 场景A：处理二维列表格式（自定义读取结果）
            if isinstance(calib_data, list):
                # 提前校验：二维列表是否为空
                if not calib_data:
                    QMessageBox.warning(self.ui, "警告", "读取到的Excel数据为空，无法设置校准值！")
                    return
                for row_index, row_data in enumerate(calib_data):
                    calib_data_dict[row_index] = row_data

            # 场景B：处理pandas DataFrame格式（优雅且严谨的判断方式）
            elif isinstance(calib_data, pd.DataFrame):
                # 提前校验：DataFrame是否为空
                if calib_data.empty:
                    QMessageBox.warning(self.ui, "警告", "读取到的Excel数据为空，无法设置校准值！")
                    return
                for row_index, row_data in calib_data.iterrows():
                    calib_data_dict[row_index] = row_data.tolist()

            # 额外校验1：数据字典是否为空（兼容两种格式校验后的兜底）
            if not calib_data_dict:
                QMessageBox.warning(self.ui, "警告", "未提取到有效校准数据，无法设置！")
                return

            # 额外校验2：校准编号num是否在字典的键范围内（避免KeyError）
            max_row_index = max(calib_data_dict.keys())
            if num not in calib_data_dict:
                QMessageBox.critical(self.ui, "错误", f"校准编号超出数据范围！当前文件仅支持编号0-{max_row_index}")
                return

            # 提取对应编号的校准数据
            table = calib_data_dict[num]

            # 额外校验3：提取的该行数据是否为空
            if not table:
                QMessageBox.warning(self.ui, "警告", f"编号{num}对应的校准数据为空，无法下发！")
                return

            # 下发校准值
            time = QDateTime.currentDateTime()
            time = time.toString("yyyyMMdd")
            time = int(time)
            self.ui.append_log(f"【设置校准值】设置编号{num}的校准值（共{len(table)}个数据）")
            self.client.set_calibration_value(num, time , num *1000 , table)


        except FileNotFoundError:
            QMessageBox.critical(self.ui, "错误", f"选中的文件不存在：{file_path}")
        except KeyError as e:
            # 精准捕获键不存在异常（兜底，防止漏判）
            QMessageBox.critical(self.ui, "错误", f"校准编号无效，未找到对应数据：{str(e)}")
        except Exception as e:
            # 捕获其他未知异常
            QMessageBox.critical(self.ui, "错误", f"读取/处理校准文件失败：{str(e)}")



    def on_set_calibration2(self):
        """设置校准值（基于当前测量数据）【合并弹窗版】"""
        if not self.client or not self.client.connected:
            QMessageBox.critical(self.ui, "错误", "请先连接下位机！")
            return


        # ===================== 自定义合并弹窗 =====================
        dialog = QDialog(self.ui)
        dialog.setWindowTitle("设置校准参数")
        layout = QVBoxLayout(dialog)


        # 1. 校准编号输入
        layout.addWidget(QLabel("校准编号（1-9）："))
        num_spin = QSpinBox()
        num_spin.setRange(1, 16)
        num_spin.setValue(self.num_spin)
        layout.addWidget(num_spin)

        # 2. 校准距离输入
        layout.addWidget(QLabel("校准距离："))
        dist_spin = QSpinBox()
        dist_spin.setRange(0, 99999)  # 可根据需求修改范围
        layout.addWidget(dist_spin)

        # 3. 是否基准输入（默认值0）
        layout.addWidget(QLabel("是否基准（0=否，1=是）："))
        jizhun_spin = QSpinBox()
        jizhun_spin.setRange(0, 1)
        jizhun_spin.setValue(0)  # ✅ 默认值设置为0
        layout.addWidget(jizhun_spin)

        # 确认/取消按钮
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        # 执行弹窗，判断是否确认
        if dialog.exec_() != QDialog.Accepted:
            return


        # 获取输入的三个参数
        num = num_spin.value()
        distance = dist_spin.value()
        isjizhun = jizhun_spin.value()
        self.num_spin = num_spin.value() + 1
        # ==========================================================

        # 执行测量并设置校准值
        self.on_start_normal_measure()
        # time.sleep(2)
        # self._set_calibration_data(num, distance, isjizhun)
        QTimer.singleShot(2000, lambda: self._set_calibration_data(num, distance, isjizhun))

    def _set_calibration_data(self, num,distance,isjizhun):
        """延迟设置校准值"""
        if not self.client or len(self.client.normal_measure_data) == 0:
            return

        table = self.client.normal_measure_data[-1]

        current_dt = QDateTime.currentDateTime()
        date_str = current_dt.toString("yyyyMMdd")
        auto_calib_time = int(date_str)
        self.ui.append_log(f"【设置校准值】成功设置编号{num}的校准值（共{len(table)}个数据）")
        self.client.set_calibration_value(num, isjizhun,auto_calib_time, distance, table)
        self.ui.append_log(f"【设置校准值】成功设置编号{num}的校准值（共{len(table)}个数据）")

    # ===================== 绘图相关逻辑 =====================
    def _init_main_plot_data(self):
        """初始化主绘图区"""
        self.ui.main_fig.clear()
        ax = self.ui.main_fig.add_subplot(111)

        # 模拟数据
        x = np.linspace(0, 100, 100)
        baseline = np.zeros_like(x)
        measure_data = np.random.normal(0, 0.01, size=len(x))

        ax.plot(x, baseline, 'b-', label='测量基线', linewidth=1.5)
        ax.plot(x, measure_data, 'r-', label='测量值', linewidth=1)
        ax.set_xlabel('采样点')
        ax.set_ylabel('偏差值 (mm)')
        ax.set_title('钢轨平直度测量波形')
        ax.grid(True, alpha=0.3)
        ax.legend()
        # 主绘图区

        # ===================== 新增：校准数据点数值标注 =====================
        for x, y in zip(x, measure_data):
            # 字体6号，点正下方显示，颜色和线条一致
            ax.text(x, y, f'{y:.2f}', fontsize=6,
                    ha='center', va='top',
                    color='black')
        # ==================================================================
        if self.ui.checkboxes["显示数值"].isChecked():
            # ===================== 新增：校准数据点数值标注 =====================
            for x, y in zip(x, measure_data):
                # 字体6号，点正下方显示，颜色和线条一致
                ax.text(x, y, f'{int(y)}', fontsize=6,
                        ha='center', va='top',
                        color='black')
            # ==================================================================
        self.ui.main_canvas.draw()

    def _init_compare_plot_data(self):
        """初始化源值比对绘图区"""
        self.ui.compare_fig.clear()
        self.ui.compare_ax = self.ui.compare_fig.add_subplot(111)

        # 模拟数据
        x = np.linspace(0, 100, 500)
        ref_data = np.sin(x * 0.1) * 0.05
        actual_data = ref_data + np.random.normal(0, 0.005, size=len(x))
        diff_data = actual_data - ref_data

        self.ui.compare_ax.plot(x, ref_data, 'g-', label='参考值', linewidth=1.2)
        self.ui.compare_ax.plot(x, actual_data, 'orange', label='实测值', linewidth=1.2)
        self.ui.compare_ax.plot(x, diff_data, 'r--', label='差值', linewidth=1)
        self.ui.compare_ax.set_xlabel('采样点')
        self.ui.compare_ax.set_ylabel('偏差值 (mm)')
        self.ui.compare_ax.set_title('源值比对波形')
        self.ui.compare_ax.grid(True, alpha=0.3)
        self.ui.compare_ax.legend()

        self.ui.compare_canvas.draw()

    def update_main_plot(self):
        """更新主绘图区"""
        if not self.client:
            self.ui.append_log("【绘图更新】客户端未连接，跳过绘图更新")
            return

        try:
            # 读取数据
            with self.client.data_lock:
                calibration_data = copy.copy(self.client.calibration_data)
                last_normal_data = self.client.normal_measure_data[-1] if self.client.normal_measure_data else None

            self.ui.plot_progress_bar.setValue(0)
            self.ui.main_fig.clear()
            ax = self.ui.main_fig.add_subplot(111)
            x_points = list(range(1, self.client.sensor_count+1))


            # 创建格式化器，关闭偏移量、关闭科学计数法
            formatter = ScalarFormatter(useOffset=False)
            formatter.set_scientific(False)  # 禁用科学计数法
            formatter.set_useMathText(False)
            # 应用到X/Y轴，工具栏数字跟随轴格式化
            ax.xaxis.set_major_formatter(formatter)
            ax.yaxis.set_major_formatter(formatter)

            # 绘制校准数据
            cali_colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f',
                           '#bcbd22']
            color_idx = 0
            if calibration_data:
                for cali_num, cali_dict in sorted(calibration_data.items()):
                    if cali_num == 0:
                        continue
                    cali_values = cali_dict.get('table', [])
                    if len(cali_values) >= self.client.sensor_count:
                        cali_values = cali_values[:self.client.sensor_count]
                    else:
                        cali_values += [0] * (self.client.sensor_count - len(cali_values))

                    if self.ui.checkboxes["校准值翻转"].isChecked():
                        cali_values = [16383 - x for x in cali_values]

                    ax.plot(
                        x_points, cali_values, linestyle='--', linewidth=1.2,
                        color=cali_colors[color_idx % len(cali_colors)],
                        label=f"{cali_num}号"
                    )
                    if self.ui.checkboxes["显示数值"].isChecked():
                        # ===================== 新增：校准数据点数值标注 =====================
                        for x, y in zip(x_points, cali_values):
                            # 字体6号，点正下方显示，颜色和线条一致
                            ax.text(x, y, f'{int(y)}', fontsize=6,
                                    ha='center', va='top',
                                    color='black')
                        # ==================================================================
                    color_idx += 1

            # 绘制测量数据
            if last_normal_data is not None:
                normal_values = last_normal_data[:self.client.sensor_count] if len(last_normal_data) >= self.client.sensor_count else last_normal_data + [0] * (
                            self.client.sensor_count - len(last_normal_data))
                if self.ui.checkboxes["采用二次校准"].isChecked() and self.two_jioazhun is not None and self.client.calibration_data[0].get("table")[0] != 0:
                    normal_values = [a + b for a, b in zip(normal_values, self.two_jioazhun)]

                ax.plot(
                    x_points, normal_values, linestyle='-', linewidth=2,
                    color='black', label='last', marker='.', markersize=5
                )
                if self.ui.checkboxes["显示数值"].isChecked():
                    # ===================== 新增：测量数据点数值标注 =====================
                    for x, y in zip(x_points, normal_values):
                        # 字体7号，点正上方显示，黑色加粗
                        ax.text(x, y, f'{int(y)}', fontsize=7,
                                ha='center', va='bottom',
                                color='black', weight='bold')
                    # ==================================================================

            # 样式设置
            ax.set_title("钢轨平直度测量 - 校准数据 vs 最后一组测量数据", fontsize=14)
            ax.set_xlabel(f"测点编号（1-{self.client.sensor_count}）", fontsize=12)
            ax.set_ylabel("ADC测量值", fontsize=12)
            ax.set_xlim(1, self.client.sensor_count)
            ax.set_ylim(0, 17000)
            ax.grid(True, alpha=0.3)
            ax.set_xticks(range(0, self.client.sensor_count+1, 20))
            ax.set_xticklabels(range(0, self.client.sensor_count+1, 20), fontsize=10)

            # 图例样式
            legend = ax.legend(
                loc='upper right', fontsize=10, labelcolor='#666666',
                facecolor='white', framealpha=0.7, edgecolor='#e0e0e0',
                fancybox=True, shadow=False
            )
            for text in legend.get_texts():
                text.set_alpha(0.8)

            self.ui.main_canvas.draw()
            self.ui.append_log("【绘图更新】主图表已更新完成")

        except Exception as e:

            err_msg = f"【绘图更新错误】{str(e)}\n{traceback.format_exc()}"
            self.ui.append_log(err_msg)

    def update_compare_plot(self):
        """更新源值比对绘图区"""
        if not self.client:
            self.ui.append_log("【对比绘图更新】客户端未连接，跳过绘图更新")
            return

        # 更新电池电压
        self.ui.info_labels["电池电压"].setText(f"电池电压：{self.client.dianya}mV")

        try:
            # 读取数据
            with self.client.data_lock:
                calibration_data = copy.copy(self.client.calibration_data)
                last_normal_adc = self.client.normal_measure_data[-1] if self.client.normal_measure_data else None

            if not calibration_data or not last_normal_adc:
                return

            # 数据标准化
            data_point_num = self.client.sensor_count
            std_adc_data = last_normal_adc[-data_point_num:] if len(last_normal_adc) >= data_point_num else [0] * (
                        data_point_num - len(last_normal_adc)) + last_normal_adc

            # 二次校准
            if (self.ui.checkboxes["采用二次校准"].isChecked() and self.two_jioazhun is not None and
                    self.client.calibration_data[0].get("table")[0] != 0) :
                std_adc_data = [a + b for a, b in zip(std_adc_data, self.two_jioazhun)]

            # 有效校准列表
            valid_mm_list = sorted([k for k in calibration_data.keys() if k != 0])

            # 逐点插值计算mm值
            self.final_um = []
            for point_idx in range(data_point_num):
                adc_val = std_adc_data[point_idx]

                mm_val = get_single_point_mm_compare1(
                    adc_val, point_idx,
                    calibration_data, valid_mm_list,
                    self.ui.checkboxes["校准值翻转"].isChecked()
                )
                self.final_um.append(mm_val)

            
            # 掩码插值
            if self.ui.checkboxes["使用掩码"].isChecked() and self.mark_list:
                self.final_um = linear_interpolate_masked(self.final_um, self.mark_list)

            # 奇偶筛选
            if self.ui.checkboxes["取奇数"].isChecked() and not self.ui.checkboxes["取偶数"].isChecked():
                self.final_um = self.final_um[::2]
                data_point_num = data_point_num // 2
            elif self.ui.checkboxes["取偶数"].isChecked() and not self.ui.checkboxes["取奇数"].isChecked():
                self.final_um = self.final_um[1::2]
                data_point_num = data_point_num // 2

            # 去板间
            if self.ui.checkboxes["去板间"].isChecked():
                self.final_um = qubanjian(self.final_um)

            # 中值滤波
            if self.ui.checkboxes["中值滤波"].isChecked():
                self.final_um = median_filter(self.final_um)

            # 计算点到弦的距离
            x_axis = list(range(1, data_point_num + 1))
            x_axis1 = [x * 0.5 * 1000 for x in range(1, data_point_num + 1)]
            self.distance_to_chord,power = calculate_distance_to_chord(x_axis1, self.final_um)
            self.ui.info_labels["能量强度"].setText(f"能量强度:{power}%")
            # 绘制图形
            self.ui.compare_ax.clear()

            self.final_mm = [x /1000 for x in self.final_um]
            # 显示mm曲线
            if self.ui.cb_show_mm_curve.isChecked():
                self.ui.compare_ax.plot(
                    x_axis, self.final_mm, color='#2196F3', linewidth=1.8,
                    marker='.', markersize=4, alpha=0.9, label='测量值反推mm曲线'
                )
                if self.ui.checkboxes["显示数值"].isChecked():
                    # ===================== 新增：测量数据点数值标注 =====================
                    for x, y in zip(x_axis, self.final_mm):
                        # 字体7号，点正上方显示，黑色加粗
                        self.ui.compare_ax.text(x, y, f'{y:.3f}', fontsize=7,
                                ha='center', va='bottom',
                                color='black', weight='bold')
                    # ==================================================================



            # 显示上下界限
            if self.ui.checkboxes["显示上下界限"].isChecked() and self.final_um:
                try:
                    measure_data = [row for row in self.final_um if isinstance(row, list) and len(row) > 0]
                    if measure_data:
                        min_col_num = min(len(row) for row in measure_data)
                        max_list = []
                        min_list = []
                        for col_idx in range(min_col_num):
                            col_values = [row[col_idx] for row in measure_data if col_idx < len(row)]
                            max_list.append(max(col_values)) if col_values else max_list.append(0)
                            min_list.append(min(col_values)) if col_values else min_list.append(0)

                        # 标准化长度
                        if len(max_list) >= data_point_num:
                            std_max_list = max_list[:data_point_num]
                            std_min_list = min_list[:data_point_num]
                        else:
                            std_max_list = max_list + [max_list[-1]] * (data_point_num - len(max_list))
                            std_min_list = min_list + [min_list[-1]] * (data_point_num - len(min_list))

                        # 绘制最大/最小值曲线
                        self.ui.compare_ax.plot(
                            x_axis, std_max_list, color='#757575', linewidth=1.2,
                            linestyle='--', alpha=0.8, label='每列最大值'
                        )
                        self.ui.compare_ax.plot(
                            x_axis, std_min_list, color='#757575', linewidth=1.2,
                            linestyle='--', alpha=0.8, label='每列最小值'
                        )
                except Exception as e:
                    self.ui.append_log(f"【绘制上下界限错误】{str(e)}")

            # 显示点到弦的距离
            if self.ui.cb_show_distance.isChecked():
                self.ui.compare_ax.plot(
                    x_axis, self.distance_to_chord, color='#F44336', linewidth=1.2,
                    marker='.', markersize=3, alpha=0.8, label='到弦的距离（上正下负）'
                )
                if self.ui.checkboxes["显示数值"].isChecked():
                    # ===================== 新增：测量数据点数值标注 =====================
                    for x, y in zip(x_axis, self.distance_to_chord):
                        # 字体7号，点正上方显示，黑色加粗
                        self.ui.compare_ax.text(x, y, f'{y:.3f}', fontsize=7,
                                                ha='center', va='bottom',
                                                color='black', weight='bold')
                    # ==================================================================

            # 样式设置
            ylim_text = float(self.ui.ylimcombo.currentText())
            self.ui.compare_ax.set_xlim(1, data_point_num)
            self.ui.compare_ax.set_ylim(-ylim_text, ylim_text)
            self.ui.compare_ax.set_title('测量值反推毫米曲线 (200点 | 线性插值)', fontsize=12)
            self.ui.compare_ax.set_xlabel('测量点位序号 (1-200)', fontsize=10)
            self.ui.compare_ax.set_ylabel('反推精准值 (mm)', fontsize=10)
            self.ui.compare_ax.grid(True, linestyle='--', alpha=0.7)
            self.ui.compare_ax.set_xticks(range(0, data_point_num + 1, 20))
            self.ui.compare_ax.set_xticklabels(range(0, data_point_num + 1, 20), fontsize=10)

            # 图例
            legend = self.ui.compare_ax.legend(
                loc='upper right', fontsize=9, labelcolor='#666666',
                facecolor='white', framealpha=0.7, edgecolor='#e0e0e0',
                fancybox=True, shadow=False
            )
            for text in legend.get_texts():
                text.set_alpha(0.8)

            self.ui.compare_canvas.draw()
            self.ui.append_log("【对比绘图更新】mm值曲线+弦距离已更新完成")

        except Exception as e:
            err_msg = f"【对比绘图更新错误】{str(e)}\n{traceback.format_exc()}"
            self.ui.append_log(err_msg)

    def update_single_plot(self):
        """更新单点分析绘图区"""
        if not self.client or self.client.single_point_measure_data is None:
            return

        with self.client.data_lock:
            adc_list = self.client.single_point_measure_data.copy()

        # 初始化坐标轴
        if not hasattr(self.ui, 'scatter_ax'):
            self.ui.scatter_ax = self.ui.scatter_fig.add_subplot(111)

        self.ui.scatter_ax.clear()
        x = list(range(1, len(adc_list) + 1))
        self.ui.scatter_ax.plot(
            x, adc_list, color="#ff7f0e", linewidth=1.5,
            marker=".", markersize=3, label="单点测量ADC值"
        )

        # 样式设置
        self.ui.scatter_ax.set_title(f"单点{self.point}测量数据分布（{len(adc_list)}个测点）", fontsize=14)
        self.ui.scatter_ax.set_xlabel("测点编号", fontsize=12)
        self.ui.scatter_ax.set_ylabel("ADC测量值", fontsize=12)
        self.ui.scatter_ax.grid(True, alpha=0.3)
        self.ui.scatter_ax.legend(loc="upper right")
        self.ui.scatter_ax.set_xlim(1, len(adc_list) + 1)
        self.ui.scatter_ax.ticklabel_format(style='plain', axis='y', useOffset=False)

        self.ui.scatter_canvas.draw()
        self.ui.scatter_canvas.update()

    def plot_mean_scatter(self):
        """绘制均值散点分析图"""
        if not self.client or not self.client.normal_measure_data:
            self._init_mean_scatter_plot()
            return

        with self.client.data_lock:
            all_data = copy.deepcopy(self.client.normal_measure_data)

        num = self.client.sensor_count
        # 数据标准化
        std_data = []
        for group in all_data:
            if len(group) >= num:
                std_group = group[:num]
            else:
                std_group = group + [0] * (num - len(group))
            std_data.append(std_group)

        # 计算均值和差值
        data_array = np.array(std_data)
        mean_vals = np.mean(data_array, axis=0)
        last_vals = std_data[-1]
        diffs = last_vals - mean_vals

        # ===================== 新增：差值统计计算 =====================
        # 1. 计算【代数差值均值】和【绝对差值均值】（更具参考意义）
        diff_mean = np.mean(diffs)
        diff_abs_mean = np.mean(np.abs(diffs))

        # 2. 提取【绝对值最大的前10个差值】+ 对应测点序号(1-200)
        abs_diffs = np.abs(diffs)
        # 获取排序后索引（降序，取前10）
        top10_idx = np.argsort(abs_diffs)[-10:][::-1]
        top10_points = top10_idx + 1  # 转换为测点编号（1开始）
        top10_diff_values = diffs[top10_idx]  # 原始差值（带正负）
        # ==============================================================

        # 绘制图形
        self.ui.mean_scatter_fig.clear()
        ax = self.ui.mean_scatter_fig.add_subplot(111)

        # 均值折线
        ax.plot(
            range(1, num+1), mean_vals, color='#3498DB', linewidth=2,
            alpha=0.8, label=f'所有数据均值（共{len(std_data)}组）'
        )

        # 最后一次数据散点
        colors = ['#FF5733' if abs(d) > 10 else '#2ECC71' for d in diffs]
        ax.scatter(
            range(1, num+1), last_vals, c=colors, s=30, alpha=0.9,
            edgecolors='black', linewidth=0.5,
            label='最后一次测量（差值>10→红，否则→绿）'
        )

        # 标注异常点
        for i, (x, y, d) in enumerate(zip(range(1, num+1), last_vals, diffs)):
            if abs(d) > 10:
                ax.annotate(f'{d:.1f}', (x, y), xytext=(5, 5),
                            textcoords='offset points', fontsize=8, color='red')

        # 样式设置
        ax.set_title('正常测量数据均值对比分析', fontsize=12, pad=15)
        ax.set_xlabel(f'测点编号（1-{num}）', fontsize=10)
        ax.set_ylabel('ADC测量值', fontsize=10)
        ax.set_xlim(0.5, num)
        ax.set_xticks(range(0, num+1, 20))
        ax.set_xticklabels(range(0, num+1, 20), fontsize=10)
        ax.margins(x=0)
        self.ui.mean_scatter_fig.subplots_adjust(left=0.06, right=0.98, top=0.9, bottom=0.12)
        ax.grid(True, alpha=0.3, linestyle='--')

        # 图例
        ax.legend(
            loc='upper right', fontsize=10, labelcolor='#666666',
            facecolor='white', framealpha=0.7, edgecolor='#e0e0e0',
            fancybox=True, shadow=False
        )

        self.ui.mean_scatter_canvas.draw()
        # ===================== 日志输出（逐行显示，已修改） =====================
        abnormal_count = sum(1 for d in diffs if abs(d) > 10)

        # 基础统计信息
        self.ui.append_log(f"均值散点图更新：异常测点{abnormal_count}个（差值>10）")
        self.ui.append_log(f"差值均值：{diff_mean:.2f} | 绝对差值均值：{diff_abs_mean:.2f}")
        self.ui.append_log("【TOP10 最大差值测点】：")
        text = f" 差值均值 {diff_abs_mean:.2f} ////"
        # 逐行输出每个测点+差值
        for point, val in zip(top10_points, top10_diff_values):
            self.ui.append_log(f"测点{point}号：差值{val:.1f}")
            text += f" 测点 {point}号：差值{val:.1f} ///"
        self.ui.mean_scatter_label.setText(text)
        self.ui.append_log("")
        self.ui.append_log("")
        # ======================================================================


    def _init_mean_scatter_plot(self):
        """初始化均值散点分析图"""
        self.ui.mean_scatter_fig.clear()
        ax = self.ui.mean_scatter_fig.add_subplot(111)
        ax.text(
            0.5, 0.5, "暂无正常测量数据\n请先执行正常测量",
            ha='center', va='center', transform=ax.transAxes,
            fontsize=12, color='#999999'
        )
        ax.set_xlim(0.5, 200.5)
        ax.set_xticks(range(0, 201, 20))
        ax.set_xticklabels(range(0, 201, 20), fontsize=10)
        ax.margins(x=0)
        self.ui.mean_scatter_fig.subplots_adjust(left=0.06, right=0.98, top=0.9, bottom=0.12)
        ax.set_title('正常测量数据均值对比分析', fontsize=12)
        ax.set_xlabel('测点编号（1-200）', fontsize=10)
        ax.set_ylabel('ADC测量值', fontsize=10)
        ax.grid(True, alpha=0.3, linestyle='--')
        self.ui.mean_scatter_canvas.draw()

    # ===================== 数据处理工具函数 =====================

    def add_data(self):
        time = QDateTime.currentDateTime()
        self.ui.add_measurement_record(time.toString("yyyy-MM-dd hh:mm:ss"),self.client.normal_measure_data[-1])

    def add_data_cal(self):
        if self.current_cali_num - 1 < len(self.client.calibration_data) :

            time = self.client.calibration_data[self.current_cali_num - 1]["time"]
            time_str = str(time).zfill(8)
            # 步骤2：按年月日拆分并格式化
            formatted_time = f"{time_str[:4]}-{time_str[4:6]}-{time_str[6:8]} 00:00:00"
            self.ui.add_calibration_record(formatted_time,self.client.calibration_data[self.current_cali_num -1]["distance"],
                                           self.client.calibration_data[self.current_cali_num -1]["table"])
        # time = self.client.calibration_data[self.current_cali_num - 1]["time"]
        # time_str = str(time).zfill(8)
        # # 步骤2：按年月日拆分并格式化
        # formatted_time = f"{time_str[:4]}-{time_str[4:6]}-{time_str[6:8]} 00:00:00"
        # self.ui.add_calibration_record(formatted_time,self.client.calibration_data[self.current_cali_num -1]["distance"],
        #                                self.client.calibration_data[self.current_cali_num -1]["table"])

    # 右键菜单 - 显示功能（支持单行/多行）
    def on_table_show(self):
        # 【修复】QTableWidget 获取所有选中行的正确写法
        selected_indexes = self.ui.record_table.selectedIndexes()
        # 提取唯一行号（去重+排序）
        selected_rows = sorted({index.row() for index in selected_indexes})

        if not selected_rows:
            QMessageBox.warning(self.ui, "提示", "请先选择一行或多行数据")
            return

        # 遍历所有选中行，收集信息（修复：兼容整数/小数格式的文本）
        alldata = []
        for row in selected_rows:
            row_data = []
            for col in range(1, self.ui.record_table.columnCount()):
                item = self.ui.record_table.item(row, col)
                if item:
                    # 【核心修复】先转浮点数再转整数，兼容 1234 / 1234.0 等格式
                    try:
                        # 先strip去除空格，转float后再转int（自动舍去小数）
                        num_str = item.text().strip()
                        float_value = float(num_str)
                        num_value = int(float_value)
                    except (ValueError, TypeError):
                        # 非数字格式（如空、字母）默认填0
                        num_value = 0
                    row_data.append(num_value)
                else:
                    # 单元格为空时补0
                    row_data.append(0)
            alldata.append(row_data)
        self.update_main_plot_table(alldata)

    def on_cali_table_show(self):
        """显示出厂校准表格选中行数据并更新图表（兼容整数/小数格式）"""
        # 【修复】获取出厂校准表格所有选中行的正确写法
        selected_indexes = self.ui.cali_table.selectedIndexes()
        # 提取唯一行号（去重+排序）
        selected_rows = sorted({index.row() for index in selected_indexes})

        if not selected_rows:
            QMessageBox.warning(self.ui, "提示", "请先选择一行或多行出厂校准数据")
            return

        try:
            self.ui.checkboxes["采用二次校准"].stateChanged.disconnect(self.on_checkbox1_changed)
        except :
            pass
        self.ui.checkboxes["采用二次校准"].setChecked(False)
        # 遍历所有选中行，收集信息（修复：兼容整数/小数格式的文本）
        alldata = []
        for row in selected_rows:
            row_data = []
            # 从第2列开始取数据（校准表格：0=时间，1=校准距离，2+=测点数据）
            for col in range(2, self.ui.cali_table.columnCount()):
                item = self.ui.cali_table.item(row, col)
                if item:
                    # 【核心修复】先转浮点数再转整数，兼容 1234 / 1234.0 等格式
                    try:
                        # 先strip去除空格，转float后再转int（自动舍去小数）
                        num_str = item.text().strip()
                        float_value = float(num_str)
                        num_value = int(float_value)
                    except (ValueError, TypeError):
                        # 非数字格式（如空、字母）默认填0
                        num_value = 0
                    row_data.append(num_value)
                else:
                    # 单元格为空时补0
                    row_data.append(0)
            alldata.append(row_data)
        # 传递校准数据更新图表（函数名可根据实际调整）
        self.update_main_plot_table(alldata)
        self.ui.checkboxes["采用二次校准"].stateChanged.connect(self.on_checkbox1_changed)
    # 右键菜单 - 下载功能（支持单行/多行，纯Qt实现，无需第三方库）
    def on_table_download(self):
        # 【修复】QTableWidget 获取所有选中行（替换原错误写法）
        selected_indexes = self.ui.record_table.selectedIndexes()
        selected_rows = sorted({index.row() for index in selected_indexes})

        if not selected_rows:
            QMessageBox.warning(self.ui, "提示", "请先选择一行或多行数据")
            return

        # 1. 准备导出数据：表头 + 选中行的所有列
        headers = [self.ui.record_table.horizontalHeaderItem(col).text() for col in
                   range(self.ui.record_table.columnCount())]
        # 2. 弹出保存文件对话框
        file_path, _ = QFileDialog.getSaveFileName(
            self.ui,
            "导出测量数据",
            "测量记录.csv",
            "CSV文件 (*.csv);;Excel文件 (*.xlsx);;所有文件 (*.*)"
        )
        if not file_path:
            return  # 用户取消保存

        # 3. 纯Qt实现CSV导出（无需安装pandas/openpyxl，开箱即用）
        try:
            with open(file_path, 'w', encoding='utf-8-sig', newline='') as f:
                # 写入表头
                f.write(','.join(headers) + '\n')
                # 【修复】直接遍历行号，无需再提取row()
                for row in selected_rows:
                    row_data = []
                    for col in range(self.ui.record_table.columnCount()):
                        item = self.ui.record_table.item(row, col)
                        # 处理逗号，避免CSV格式错乱
                        text = item.text().replace(',', '，') if item else ""
                        row_data.append(text)
                    f.write(','.join(row_data) + '\n')
            QMessageBox.information(self.ui, "导出成功", f"已成功导出{len(selected_rows)}行数据！\n保存路径：{file_path}")
        except Exception as e:
            QMessageBox.critical(self.ui, "导出失败", f"出错了：{str(e)}")

    def on_cali_download(self):
        # 获取出厂校准表格所有选中行
        selected_indexes = self.ui.cali_table.selectedIndexes()
        selected_rows = sorted({index.row() for index in selected_indexes})

        if not selected_rows:
            QMessageBox.warning(self.ui, "提示", "请先选择一行或多行出厂校准数据")
            return

        # 准备导出数据：表头 + 选中行的所有列
        headers = [self.ui.cali_table.horizontalHeaderItem(col).text() for col in
                   range(self.ui.cali_table.columnCount())]
        # 弹出保存文件对话框
        file_path, _ = QFileDialog.getSaveFileName(
            self.ui,
            "导出出厂校准数据",
            "出厂校准.csv",
            "CSV文件 (*.csv);;Excel文件 (*.xlsx);;所有文件 (*.*)"
        )
        if not file_path:
            return  # 用户取消保存

        # 纯Qt实现CSV导出
        try:
            with open(file_path, 'w', encoding='utf-8-sig', newline='') as f:
                # 写入表头
                f.write(','.join(headers) + '\n')
                # 遍历选中行并写入数据
                for row in selected_rows:
                    row_data = []
                    for col in range(self.ui.cali_table.columnCount()):
                        item = self.ui.cali_table.item(row, col)
                        # 处理逗号，避免CSV格式错乱
                        text = item.text().replace(',', '，') if item else ""
                        row_data.append(text)
                    f.write(','.join(row_data) + '\n')
            QMessageBox.information(self.ui, "导出成功",
                                    f"已成功导出{len(selected_rows)}行出厂校准数据！\n保存路径：{file_path}")
        except Exception as e:
            QMessageBox.critical(self.ui, "导出失败", f"出错了：{str(e)}")
    def on_delete_selected(self):
        """删除表格中选中的行（支持多行，带确认提示，倒序删除避免行号错乱）"""
        # 获取所有选中的单元格索引
        selected_indexes = self.ui.record_table.selectedIndexes()
        # 提取唯一行号并排序
        selected_rows = sorted({index.row() for index in selected_indexes})

        # 未选中任何行
        if not selected_rows:
            QMessageBox.warning(self.ui, "提示", "请先选择需要删除的行！")
            return

        # 弹出确认删除对话框
        reply = QMessageBox.question(self.ui, "确认删除",
                                     f"确定要删除选中的 {len(selected_rows)} 行数据吗？\n删除后无法恢复！",
                                     QMessageBox.Yes | QMessageBox.No,
                                     QMessageBox.No)
        if reply != QMessageBox.Yes:
            self.ui.append_log("【删除操作】用户取消删除")
            return

        try:
            # 核心：倒序删除！从最后一行删到第一行，避免行号错乱
            for row in reversed(selected_rows):
                self.ui.record_table.removeRow(row)

            # 日志输出
            self.ui.append_log(f"【删除成功】已删除选中的 {len(selected_rows)} 行数据")


        except Exception as e:
            err_msg = f"【删除错误】{str(e)}"
            self.ui.append_log(err_msg)
            QMessageBox.critical(self.ui, "错误", "删除失败，请重试！")

    def on_cali_delete_selected(self):
        """删除出厂校准表格中选中的行（支持多行，带确认提示，倒序删除避免行号错乱）"""
        # 获取所有选中的单元格索引（指向出厂校准表格）
        selected_indexes = self.ui.cali_table.selectedIndexes()
        # 提取唯一行号并排序
        selected_rows = sorted({index.row() for index in selected_indexes})

        # 未选中任何行
        if not selected_rows:
            QMessageBox.warning(self.ui, "提示", "请先选择需要删除的出厂校准行！")
            return

        # 弹出确认删除对话框（文案适配校准数据）
        reply = QMessageBox.question(self.ui, "确认删除",
                                     f"确定要删除选中的 {len(selected_rows)} 行出厂校准数据吗？\n删除后无法恢复！",
                                     QMessageBox.Yes | QMessageBox.No,
                                     QMessageBox.No)
        if reply != QMessageBox.Yes:
            self.ui.append_log("【出厂校准-删除操作】用户取消删除")
            return

        try:
            # 核心：倒序删除！从最后一行删到第一行，避免行号错乱
            for row in reversed(selected_rows):
                self.ui.cali_table.removeRow(row)

            # 日志输出（标注出厂校准）
            self.ui.append_log(f"【出厂校准-删除成功】已删除选中的 {len(selected_rows)} 行校准数据")

        except Exception as e:
            err_msg = f"【出厂校准-删除错误】{str(e)}"
            self.ui.append_log(err_msg)
            QMessageBox.critical(self.ui, "错误", "出厂校准数据删除失败，请重试！")
    # ===================== 配置与退出 =====================
    def cal_two_jioazhun(self):
        """计算二次校准值"""
        try:
            self.client.normal_measure_finished.disconnect(self.cal_two_jioazhun)
        except:
            pass

        if self.ui.checkboxes["校准值翻转"].isChecked():
            self.two_jioazhun = [16383 - b - a for a, b in
                                 zip(self.client.normal_measure_data[-1],
                                     self.client.calibration_data.get(self.client.jiaozhun_num, {}).get('table', []))]
        else:
            self.two_jioazhun = [b - a for a, b in
                                 zip(self.client.normal_measure_data[-1],
                                     self.client.calibration_data.get(self.client.jiaozhun_num, {}).get('table', []))]

        timestamp = QDateTime.currentDateTime()
        self.client.calibration_data[0]["table"] = self.client.normal_measure_data[-1]
        time1 = timestamp.toString("yyyyMMdd")
        time2 = int(time1)
        self.client.set_calibration_value(0, 0,time2, 999, self.client.normal_measure_data[-1])
        self.update_main_plot()
        self.update_compare_plot()
        self.ui.plot_progress_bar.setValue(0)
        self.ui.checkboxes["采用二次校准"].stateChanged.connect(self.on_checkbox1_changed)

    def save_list_to_table_with_qt(self, data_list: List[list], default_dir: str = None,
                                   header: Optional[List[str]] = None, encoding: str = 'utf-8-sig') -> bool:
        """保存数据到表格文件"""
        if not isinstance(data_list, list) or len(data_list) == 0:
            QMessageBox.critical(self.ui, "错误", "输入数据不是有效二维列表，或列表为空")
            return False

        # 获取桌面路径
        if default_dir is None:
            try:
                desktop_path = str(pathlib.Path.home() / "Desktop")
                if not os.path.exists(desktop_path):
                    desktop_path = str(pathlib.Path.home() / "desktop")
                default_dir = desktop_path
            except Exception as e:
                desktop_path = os.environ.get("DESKTOP", os.environ.get("HOME", "."))
                default_dir = desktop_path
                QMessageBox.warning(self.ui, "提示",
                                    f"自动获取桌面路径失败，使用备用目录 -> {default_dir}\n错误信息：{str(e)}")

        # 创建目录
        if not os.path.exists(default_dir):
            try:
                os.makedirs(default_dir)
            except Exception as e:
                QMessageBox.critical(self.ui, "错误", f"目录创建失败 -> {str(e)}")
                return False

        # 输入文件名
        file_name, ok = QInputDialog.getText(self.ui, "输入文件名", "请输入表格文件名（无需输入后缀）：",
                                             text="未命名表格")
        if not ok or not file_name.strip():
            QMessageBox.information(self.ui, "提示", "已取消文件保存")
            return False
        file_name = file_name.strip()

        # 选择格式
        format_options = ["csv", "xlsx"]
        format_choice, ok = QInputDialog.getItem(self.ui, "选择文件格式", "请选择要保存的表格格式：", format_options, 0,
                                                 False)
        if not ok:
            QMessageBox.information(self.ui, "提示", "已取消文件保存")
            return False
        format_choice = format_choice.lower()

        # 拼接路径
        file_path = os.path.join(default_dir, f"{file_name}.{format_choice}")

        # 转换为DataFrame
        try:
            df = pd.DataFrame(data_list, columns=header)
        except Exception as e:
            QMessageBox.critical(self.ui, "错误", f"数据转换为表格格式失败 -> {str(e)}")
            return False

        # 保存文件
        try:
            if format_choice == "csv":
                df.to_csv(file_path, index=False, header=header is not None, encoding=encoding)
                QMessageBox.information(self.ui, "成功", f"CSV 文件已保存至\n{file_path}")
            elif format_choice == "xlsx":
                df.to_excel(file_path, index=False, header=header is not None, engine='openpyxl')
                QMessageBox.information(self.ui, "成功", f"Excel 文件已保存至\n{file_path}")
            else:
                QMessageBox.warning(self.ui, "警告", "不支持的文件格式，保存失败")
                return False
            return True
        except ModuleNotFoundError as e:
            if "openpyxl" in str(e):
                QMessageBox.critical(self.ui, "错误",
                                     "保存 Excel 文件需要安装 openpyxl 库\n执行命令：pip install openpyxl")
            else:
                QMessageBox.critical(self.ui, "错误", f"缺少必要依赖库 -> {str(e)}")
            return False
        except Exception as e:
            QMessageBox.critical(self.ui, "错误", f"文件保存失败 -> {str(e)}")
            return False

    def on_checkbox1_changed(self, state):
        """二次校准复选框事件"""
        self.update_main_plot()
        self.update_compare_plot()

    def on_checkbox2_changed(self, state):
        """校准值翻转复选框事件"""
        self.update_main_plot()
        self.update_compare_plot()

    def updabianjie(self):
        """更新上下界限"""
        self.final_um.clear()
        self.update_compare_plot()

    def save_all_checkbox_states(self):
        """保存复选框配置"""
        config_data = {
            # 直接使用中文作为键名，一一对应复选框文本
            "采用二次校准": self.ui.checkboxes["采用二次校准"].isChecked(),
            "校准值翻转": self.ui.checkboxes["校准值翻转"].isChecked(),
            "去板间": self.ui.checkboxes["去板间"].isChecked(),
            "中值滤波": self.ui.checkboxes["中值滤波"].isChecked(),
            "ylim_selected_index": self.ui.ylimcombo.currentIndex()
        }

        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config_data, f, ensure_ascii=False, indent=4)

    def load_all_checkbox_states(self):
        """加载复选框配置"""
        if not os.path.exists(CONFIG_FILE):
            return

        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config_data = json.load(f)

            # 读取时直接使用中文键名匹配
            self.ui.checkboxes["采用二次校准"].setChecked(config_data.get("采用二次校准", False))
            self.ui.checkboxes["校准值翻转"].setChecked(config_data.get("校准值翻转", False))
            self.ui.checkboxes["去板间"].setChecked(config_data.get("去板间", False))
            self.ui.checkboxes["中值滤波"].setChecked(config_data.get("中值滤波", False))

            selected_index = config_data.get("ylim_selected_index", 0)
            if isinstance(selected_index, int) and 0 <= selected_index < self.ui.ylimcombo.count():
                self.ui.ylimcombo.setCurrentIndex(selected_index)
        except:
            pass

    def on_exit_app(self):
        """退出应用"""
        reply = QMessageBox.question(
            self.ui, "确认退出", "是否确定退出钢轨平直度测量系统？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self._cleanup_resources()
            QApplication.quit()
            sys.exit(0)

    def _cleanup_resources(self):
        """清理资源"""
        # 断开TCP连接
        if self.client:
            self.client.disconnect()
            self.client = None
            self.ui.append_log("已断开与下位机的连接并清理客户端实例")

        # 清理绘图资源
        if hasattr(self.ui, 'main_fig') and self.ui.main_fig:
            self.ui.main_fig.clear()
            self.ui.main_canvas.close()
        if hasattr(self.ui, 'compare_fig') and self.ui.compare_fig:
            self.ui.compare_fig.clear()
            self.ui.compare_canvas.close()

        # 保存配置
        self.save_all_checkbox_states()

        self.ui.append_log("所有资源已清理完成，程序即将退出")
        QApplication.processEvents()

    def update_main_plot_table(self, data):
        """更新主绘图区：支持绘制多条测量数据"""
        if not self.client:
            self.ui.append_log("【绘图更新】客户端未连接，跳过绘图更新")
            return

        try:
            # 读取数据
            with self.client.data_lock:
                calibration_data = copy.copy(self.client.calibration_data)

            # 传入的data为多条测量数据（alldata）
            self.ui.plot_progress_bar.setValue(0)
            self.ui.main_fig.clear()
            ax = self.ui.main_fig.add_subplot(111)
            x_points = list(range(1, self.client.sensor_count + 1))

            # 创建格式化器，关闭偏移量、关闭科学计数法
            formatter = ScalarFormatter(useOffset=False)
            formatter.set_scientific(False)  # 禁用科学计数法
            formatter.set_useMathText(False)
            # 应用到X/Y轴，工具栏数字跟随轴格式化
            ax.xaxis.set_major_formatter(formatter)
            ax.yaxis.set_major_formatter(formatter)

            # 绘制校准数据（原有逻辑无修改）
            cali_colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f',
                           '#bcbd22']
            color_idx = 0
            if calibration_data:
                for cali_num, cali_dict in sorted(calibration_data.items()):
                    if cali_num == 0:
                        continue
                    cali_values = cali_dict.get('table', [])
                    if len(cali_values) >= self.client.sensor_count:
                        cali_values = cali_values[:self.client.sensor_count]
                    else:
                        cali_values += [0] * (self.client.sensor_count - len(cali_values))

                    if self.ui.checkboxes["校准值翻转"].isChecked():
                        cali_values = [16383 - x for x in cali_values]

                    ax.plot(
                        x_points, cali_values, linestyle='--', linewidth=1.2,
                        color=cali_colors[color_idx % len(cali_colors)],
                        label=f"{cali_num}号"
                    )
                    if self.ui.checkboxes["显示数值"].isChecked():
                        # 校准数据点数值标注
                        for x, y in zip(x_points, cali_values):
                            ax.text(x, y, f'{int(y)}', fontsize=6,
                                    ha='center', va='top',
                                    color='black')
                    color_idx += 1

            # ===================== 核心修改：绘制多条测量数据 =====================
            # 测量数据专用配色池（可自定义颜色）
            measure_colors = ['#000000', '#FF5733', '#33FF57', '#3357FF', '#FF33F5', '#F5FF33', '#33FFF5', '#FF8C33']
            measure_color_idx = 0

            # 遍历所有选中的测量数据，逐条绘制
            if data:
                for idx, normal_data in enumerate(data):
                    # 数据截断/补0（兼容传感器数量）
                    normal_values = normal_data[:self.client.sensor_count] if len(
                        normal_data) >= self.client.sensor_count else normal_data + [0] * (
                                self.client.sensor_count - len(normal_data))

                    # 二次校准逻辑（原有逻辑保留）
                    if self.ui.checkboxes["采用二次校准"].isChecked() and self.two_jioazhun is not None and \
                            self.client.calibration_data[0].get("table")[0] != 0:
                        normal_values = [a + b for a, b in zip(normal_values, self.two_jioazhun)]

                    # 绘制：实线 + 更细线条(1.5) + 不同颜色 + 标记点
                    ax.plot(
                        x_points, normal_values, linestyle='-', linewidth=1.5,  # 线条变细
                        color=measure_colors[measure_color_idx % len(measure_colors)],
                        label=f'测量{idx + 1}组', marker='.', markersize=5
                    )

                    # 测量数据数值标注（原有样式保留）
                    if self.ui.checkboxes["显示数值"].isChecked():
                        for x, y in zip(x_points, normal_values):
                            ax.text(x, y, f'{int(y)}', fontsize=7,
                                    ha='center', va='bottom',
                                    color='black', weight='bold')

                    measure_color_idx += 1
            # ==================================================================

            # 样式设置（原有逻辑无修改）
            ax.set_title("钢轨平直度测量 - 校准数据 vs 多组测量数据", fontsize=14)
            ax.set_xlabel(f"测点编号（1-{self.client.sensor_count}）", fontsize=12)
            ax.set_ylabel("ADC测量值", fontsize=12)
            ax.set_xlim(1, self.client.sensor_count)
            ax.set_ylim(0, 17000)
            ax.grid(True, alpha=0.3)
            ax.set_xticks(range(0, self.client.sensor_count + 1, 20))
            ax.set_xticklabels(range(0, self.client.sensor_count + 1, 20), fontsize=10)

            # 图例样式（原有逻辑无修改）
            legend = ax.legend(
                loc='upper right', fontsize=10, labelcolor='#666666',
                facecolor='white', framealpha=0.7, edgecolor='#e0e0e0',
                fancybox=True, shadow=False
            )
            for text in legend.get_texts():
                text.set_alpha(0.8)

            self.ui.main_canvas.draw()
            self.ui.append_log("【绘图更新】主图表已更新完成（多组测量数据）")

        except Exception as e:
            err_msg = f"【绘图更新错误】{str(e)}\n{traceback.format_exc()}"
            self.ui.append_log(err_msg)



