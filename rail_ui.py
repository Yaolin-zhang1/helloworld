import ctypes

# 放在所有import最开头
ctypes.windll.user32.SetProcessDPIAware()

# 导入系统模块，用于处理程序退出等系统级操作
import os
import sys

# === 全局设置：解决Matplotlib中文显示乱码/负号显示异常问题 ===
import matplotlib.pyplot as plt
from PyQt5.QtCore import (
    Qt,
    pyqtSignal,
    QObject, )
from PyQt5.QtGui import QIcon
# 导入PyQt5的核心窗口组件，用于构建GUI界面
from PyQt5.QtWidgets import (
    # 应用程序主类，管理应用程序的控制流和主要设置
    QMainWindow,  # 主窗口类，提供菜单栏、工具栏、状态栏等标准窗口元素
    QWidget,  # 基础窗口组件，作为其他组件的容器
    QLabel,  # 文本标签组件，用于显示静态文本
    QPushButton,  # 按钮组件，用于触发交互事件
    # 单选按钮组件
    QComboBox,  # 下拉选择框组件
    QLineEdit,  # 单行文本输入框组件
    QVBoxLayout,  # 垂直布局管理器，组件垂直排列
    QHBoxLayout,  # 水平布局管理器，组件水平排列
    QGridLayout,  # 网格布局管理器，组件按行列排列
    QTabWidget,  # 标签页组件，用于切换不同内容区域
    QTextEdit,  # 多行文本编辑/显示组件
    QGroupBox,  # 分组框组件，用于分组相关组件并显示标题
    QSizePolicy,  # 尺寸策略类，控制组件的拉伸/收缩行为
    # 对话框基类
    # 输入对话框
    # 文件选择对话框
    # 消息提示框
    QCheckBox, QProgressBar, QSpacerItem, QTableWidget, QHeaderView, QTableWidgetItem, QMenu, QAction, QAbstractItemView
)
# 导入matplotlib与PyQt5的集成组件，用于在Qt界面中显示绘图
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure  # matplotlib的绘图画布类

# 设置字体为黑体，确保中文正常显示
plt.rcParams['font.sans-serif'] = ['SimHei']
# 解决负号（-）显示为方块的问题
plt.rcParams['axes.unicode_minus'] = False

# # -------------------------- 信号类：用于线程安全更新UI --------------------------
# class SignalEmitter(QObject):
#     log_signal = pyqtSignal(str)

# 适配PyInstaller打包的资源路径函数
def get_icon_path(relative_path):
    # 打包后运行：读取临时目录里的图标
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    # 直接运行Python：读取当前目录的图标
    return os.path.join(os.path.abspath("."), relative_path)

# 纯界面类：仅负责界面绘制，无任何业务逻辑
class RailStraightnessUIPanel(QMainWindow):
    """
    钢轨平直度测量仪测量系统界面类（纯UI）
    功能：仅构建GUI界面布局，暴露所有控件作为实例属性，不处理任何业务逻辑
    """
    log_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()

        # # ========== 初始化信号发射器（仅定义，绑定由业务类处理） ==========
        # self.signal_emitter = SignalEmitter()
        # self.setWindowIcon(QIcon("icon.ico"))  # 替换成你的图标文件名
        self.setWindowIcon(QIcon(get_icon_path("icon.ico")))
        # ========== 窗口基础属性设置 ==========
        self.setWindowTitle("钢轨平直度测量仪测量系统")
        self.setGeometry(100, 100, 1400, 800)

        # ========== 创建中心部件和主布局 ==========
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # ========== 调用子方法创建各功能模块 ==========
        self._create_info_bar(main_layout)
        self._create_control_container(main_layout)
        self._create_plot_area(main_layout)
        self._create_log_area(main_layout)

    def _create_info_bar(self, parent_layout):
        """创建顶部设备基础信息栏"""
        info_group = QGroupBox("设备基础信息")
        grid_layout = QGridLayout(info_group)
        grid_layout.setSpacing(15)
        grid_layout.setContentsMargins(10, 5, 10, 5)

        info_items = [
            ("设备型号：", "神澜云尺"),
            ("固件版本：", "513"),
            ("硬件版本：", "2.5"),
            ("设备温度：", "19.2℃"),
            ("电池电压：", "4.24v"),
            ("能量强度：", "-"),
            ("校准时间：", "33FFD8053131563934572543")
        ]

        self.info_labels = {}  # 存储信息标签，方便业务类更新
        for idx, (label_text, value) in enumerate(info_items):
            label = QLabel(label_text + value)
            key = label_text.strip("：")
            self.info_labels[key] = label
            grid_layout.addWidget(label, 0, idx)

        parent_layout.addWidget(info_group)

    def _create_control_container(self, parent_layout):
        """创建控制区容器（功能控制+底层控制+复选框控制）"""
        control_container = QWidget()
        control_layout = QHBoxLayout(control_container)
        control_layout.setSpacing(10)
        control_layout.setContentsMargins(0, 0, 0, 0)
        control_layout.setAlignment(Qt.AlignLeft)

        # 创建各控制区
        self._create_function_area(control_layout)
        self._create_bottom_control_area(control_layout)
        self._create_checkbox_area(control_layout)

        parent_layout.addWidget(control_container)

    def _create_function_area(self, parent_layout):
        """创建核心功能控制区"""
        func_group = QGroupBox("功能控制")
        h_layout = QHBoxLayout(func_group)
        h_layout.setSpacing(15)
        h_layout.setContentsMargins(0, 0, 0, 0)
        h_layout.setAlignment(Qt.AlignLeft)

        # 按钮组
        btn_group = QWidget()
        btn_grid = QGridLayout(btn_group)
        btn_grid.setSpacing(3)
        btn_grid.setContentsMargins(0, 0, 0, 0)
        btn_grid.setAlignment(Qt.AlignLeft)

        # 第一行按钮
        self.func_btns = {}  # 存储功能按钮，方便业务类绑定事件
        btns_row1 = [
            ("初始化掩码", "init_mask"),
            ("掩码设置", "set_mask"),
            ("稳定测试", "stability_test"),
            ("原始采样", "original_sampling"),
            ("版本信息", "version_info")
        ]
        for col, (btn_text, key) in enumerate(btns_row1):
            btn = QPushButton(btn_text)
            btn.setFixedWidth(80)
            btn.setFixedHeight(30)
            btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            self.func_btns[btn_text] = btn
            btn_grid.addWidget(btn, 0, col, Qt.AlignLeft)

        # 第二行按钮
        btns_row2 = [
            ("2次校准", "double_calibration"),
            ("清除校准", "factory_reset"),
            ("清除二校", "factory_report"),
            ("获取标签", "get_label"),
            ("存储数据", "save_data")
        ]
        for col, (btn_text, key) in enumerate(btns_row2):
            btn = QPushButton(btn_text)
            btn.setFixedWidth(80)
            btn.setFixedHeight(30)
            btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            self.func_btns[btn_text] = btn
            btn_grid.addWidget(btn, 1, col, Qt.AlignLeft)

        # 输入项组
        input_group = QWidget()
        h_layout4 = QHBoxLayout(input_group)
        h_layout4.setSpacing(10)
        h_layout4.setContentsMargins(0, 0, 0, 0)
        h_layout4.setAlignment(Qt.AlignLeft)

        # 输入项创建工具函数
        def create_input_item(label_text, widget):
            item_widget = QWidget()
            v_layout = QVBoxLayout(item_widget)
            v_layout.setSpacing(2)
            v_layout.setContentsMargins(0, 0, 0, 0)
            v_layout.setAlignment(Qt.AlignLeft)
            label = QLabel(label_text)
            v_layout.addWidget(label)
            v_layout.addWidget(widget)
            return item_widget

        # 输入项存储字典
        self.input_widgets = {}

        # 复位点位输入
        reset_input = QLineEdit()
        reset_input.setPlaceholderText("输入值")
        reset_input.setFixedWidth(80)
        self.input_widgets["reset_point"] = reset_input
        reset_item = create_input_item("复位点位：", reset_input)

        # 采样单位下拉框
        unit_combo = QComboBox()
        unit_combo.addItems(["mm", "cm", "m"])
        unit_combo.setFixedWidth(80)
        self.input_widgets["sample_unit"] = unit_combo
        unit_item = create_input_item("采样单位：", unit_combo)

        # 测量总数输入
        count_input = QLineEdit()
        count_input.setPlaceholderText("输入值")
        count_input.setFixedWidth(80)
        self.input_widgets["measure_count"] = count_input
        count_item = create_input_item("测量总数：", count_input)

        # 测量间隔下拉框
        interval_combo = QComboBox()
        interval_combo.addItems(["10ms", "20ms", "50ms", "100ms"])
        interval_combo.setFixedWidth(80)
        self.input_widgets["measure_interval"] = interval_combo
        interval_item = create_input_item("测量间隔：", interval_combo)

        h_layout4.addWidget(reset_item)
        h_layout4.addWidget(unit_item)
        h_layout4.addWidget(count_item)
        h_layout4.addWidget(interval_item)
        input_group.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        # 添加组件到布局
        h_layout.addWidget(btn_group)
        h_layout.addWidget(input_group)

        # func_group.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        parent_layout.addWidget(func_group, alignment=Qt.AlignLeft)

    def _create_bottom_control_area(self, parent_layout):
        """创建底层控制区"""
        bottom_group = QGroupBox("底层控制")
        h_layout = QHBoxLayout(bottom_group)
        h_layout.setSpacing(0)
        h_layout.setContentsMargins(5, 0, 0, 0)
        h_layout.setAlignment(Qt.AlignLeft)

        # IP和端口输入组
        ip_port_group = QWidget()
        grid_layout_ip = QGridLayout(ip_port_group)
        grid_layout_ip.setSpacing(3)
        grid_layout_ip.setContentsMargins(0, 0, 0, 0)
        grid_layout_ip.setAlignment(Qt.AlignLeft)

        # IP输入
        ip_row = QWidget()
        ip_h_layout = QHBoxLayout(ip_row)
        ip_h_layout.setSpacing(2)
        ip_h_layout.setContentsMargins(0, 0, 0, 0)
        ip_h_layout.setAlignment(Qt.AlignLeft)
        ip_label = QLabel("蓝牙名称：")
        self.ip_edit = QLineEdit()
        self.ip_edit.setText("SL0000B")
        self.ip_edit.setAlignment(Qt.AlignCenter)
        self.ip_edit.setFixedWidth(120)
        ip_h_layout.addWidget(ip_label)
        ip_h_layout.addWidget(self.ip_edit)
        grid_layout_ip.addWidget(ip_row, 0, 0)

        # 端口输入
        port_row = QWidget()
        port_h_layout = QHBoxLayout(port_row)
        port_h_layout.setSpacing(2)
        port_h_layout.setContentsMargins(0, 0, 0, 0)
        port_h_layout.setAlignment(Qt.AlignLeft)
        port_label = QLabel("端口号：")
        self.port_edit = QLineEdit()
        self.port_edit.setText("")
        self.port_edit.setFixedWidth(120)
        port_h_layout.addWidget(port_label)
        port_h_layout.addWidget(self.port_edit)
        grid_layout_ip.addWidget(port_row, 1, 0)

        self.bottom_btns = {}

        # 连接按钮
        self.bottom_btns["连接下位机"] = QPushButton("连接下位机")
        self.bottom_btns["连接下位机"].setFixedWidth(90)
        self.bottom_btns["连接下位机"].setFixedHeight(60)
        self.bottom_btns["连接下位机"].setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.bottom_btns["连接下位机"].setStyleSheet("""
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
        grid_layout_ip.addWidget(self.bottom_btns["连接下位机"], 0, 1, 2, 1, Qt.AlignLeft | Qt.AlignVCenter)

        ip_port_group.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        # 底层功能按钮组
        btn_group = QWidget()
        btn_grid = QGridLayout(btn_group)
        btn_grid.setSpacing(3)
        btn_grid.setContentsMargins(0, 0, 0, 0)
        btn_grid.setAlignment(Qt.AlignLeft)

        # 底层按钮存储字典

        bottom_buttons = [
            ("读取参数", "read_params"),
            ("设置参数", "set_params"),
            ("正常测量", "normal_measure"),
            ("单点测量", "single_point_measure"),
            ("显示正常", "show_normal_top10"),
            ("版本升级", "show_single_top10"),
            ("读取校准", "read_calibration"),
            ("设置校准", "set_calibration"),
            ("连续测量", "continuous_measure"),
            ("退出", "exit_app")
        ]

        # 第一行按钮
        for col in range(5):
            btn_text, key = bottom_buttons[col]
            btn = QPushButton(btn_text)
            btn.setFixedWidth(80)
            btn.setFixedHeight(30)
            btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            self.bottom_btns[btn_text] = btn
            btn_grid.addWidget(btn, 0, col, Qt.AlignLeft)
            if btn_text == "正常测量":
                btn.setStyleSheet("""
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

        # 第二行按钮
        for col in range(5):
            btn_text, key = bottom_buttons[5 + col]
            btn = QPushButton(btn_text)
            btn.setFixedWidth(80)
            btn.setFixedHeight(30)
            btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            self.bottom_btns[btn_text] = btn
            btn_grid.addWidget(btn, 1, col, Qt.AlignLeft)

        # 添加组件到布局
        h_layout.addWidget(ip_port_group)
        h_layout.addWidget(btn_group)

        # bottom_group.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        parent_layout.addWidget(bottom_group, alignment=Qt.AlignLeft)

    def _create_checkbox_area(self, parent_layout):
        """创建复选框控制区"""
        checkbox_group = QGroupBox("复选框控制")
        checkbox_grid = QGridLayout(checkbox_group)
        checkbox_grid.setSpacing(0)
        checkbox_grid.setContentsMargins(0, 0, 0, 0)
        checkbox_grid.setAlignment(Qt.AlignLeft)

        # 复选框存储字典
        self.checkboxes = {}
        checkbox_texts = [
            "采用二次校准",
            "去板间",
            "取奇数",
            "使用掩码",
            "显示数值",
            "校准值翻转",
            "中值滤波",
            "取偶数",
            "显示上下界限",
            "自动校准补偿"
        ]

        # 2行5列添加复选框
        for row in range(2):
            for col in range(5):
                idx = row * 5 + col
                if idx >= len(checkbox_texts):
                    break
                cb_text = checkbox_texts[idx]
                cb = QCheckBox(cb_text)
                cb.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
                # cb.setFixedWidth(120)
                cb.setFixedHeight(25)
                # 特殊初始化：采用二次校准默认选中
                if cb_text == "采用二次校准":
                    cb.setChecked(True)
                self.checkboxes[cb_text] = cb
                checkbox_grid.addWidget(cb, row, col, Qt.AlignLeft)

        # checkbox_group.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        parent_layout.addWidget(checkbox_group, alignment=Qt.AlignLeft)

    def _create_plot_area(self, parent_layout):
        """创建测量波形显示区"""
        plot_group = QGroupBox("测量波形显示")
        v_layout = QVBoxLayout(plot_group)
        v_layout.setContentsMargins(8, 8, 8, 8)
        v_layout.setSpacing(0)

        # 创建matplotlib画布
        self.main_fig = Figure(figsize=(8, 4), dpi=100, constrained_layout=True)
        self.main_canvas = FigureCanvas(self.main_fig)
        self.main_toolbar = NavigationToolbar(self.main_canvas, self, coordinates=False)
        self.main_toolbar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.main_toolbar.setFixedHeight(30)
        self.main_canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # 工具栏+进度条水平布局
        toolbar_progress_layout = QHBoxLayout()
        toolbar_progress_layout.setSpacing(5)

        toolbar_progress_layout.addWidget(self.main_toolbar)

        # 进度条
        self.plot_progress_bar = QProgressBar()
        self.plot_progress_bar.setFixedHeight(30)
        self.plot_progress_bar.setFixedWidth(200)
        self.plot_progress_bar.setFormat("%p%")
        self.plot_progress_bar.setValue(0)
        self.plot_progress_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid #e0e0e0;
                border-radius: 6px;
                text-align: center;
                font-size: 10px;
            }
            QProgressBar::chunk {
                background-color: #2196F3;
                border-radius: 4px;
            }
        """)
        toolbar_progress_layout.addWidget(self.plot_progress_bar)

        # 间隔时间标签
        self.Lable_time = QLabel("间隔时间:0.00秒")
        toolbar_progress_layout.addWidget(self.Lable_time)

        # 添加到垂直布局
        v_layout.addLayout(toolbar_progress_layout)
        v_layout.addWidget(self.main_canvas)

        parent_layout.addWidget(plot_group)

    def _create_log_area(self, parent_layout):
        """创建数据与日志显示区"""
        log_group = QGroupBox("数据与日志")
        log_layout = QVBoxLayout(log_group)
        self.tab_widget = QTabWidget()
        self.tab_widget.setContentsMargins(0, 0, 0, 0)

        # 1. 日志标签页
        log_tab = QWidget()
        log_layout_tab = QVBoxLayout(log_tab)
        self.log_text = QTextEdit()
        self.log_text.setPlaceholderText("系统日志、测量数据等将显示在这里...")
        self.log_text.append("=== 系统初始化完成 ===")

        log_layout_tab.addWidget(self.log_text)
        self.tab_widget.addTab(log_tab, "日志")

        # 2. 源值比对标签页
        compare_tab = QWidget()
        compare_layout = QVBoxLayout(compare_tab)
        compare_layout.setSpacing(0)

        self.compare_fig = Figure(figsize=(8, 3), dpi=100, constrained_layout=True)
        self.compare_canvas = FigureCanvas(self.compare_fig)
        self.compare_toolbar = NavigationToolbar(self.compare_canvas, self, coordinates=False)

        # 顶部水平布局（工具栏+下拉框+复选框）
        top_h_layout = QHBoxLayout()
        top_h_layout.setSpacing(20)
        top_h_layout.setContentsMargins(0, 0, 0, 0)

        top_h_layout.addWidget(self.compare_toolbar)
        # ===================== 核心修改：添加水平拉伸弹簧 =====================
        # 弹簧自动填充中间空白，把右侧控件推到最右边
        top_h_layout.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        # ====================================================================

        # Y轴范围下拉框
        self.ylimcombo = QComboBox()
        self.ylimcombo.addItems(["0.2", "0.5", "1", "2", "4", "5"])
        self.ylimcombo.setFixedWidth(80)
        top_h_layout.addWidget(self.ylimcombo)

        # 显示反推mm值曲线复选框
        self.cb_show_mm_curve = QCheckBox("显示反推mm值曲线")
        self.cb_show_mm_curve.setChecked(False)
        top_h_layout.addWidget(self.cb_show_mm_curve)

        # 显示点到弦距离线复选框
        self.cb_show_distance = QCheckBox("显示点到弦距离线")
        self.cb_show_distance.setChecked(True)
        top_h_layout.addWidget(self.cb_show_distance)

        compare_layout.addLayout(top_h_layout)
        compare_layout.addWidget(self.compare_canvas)
        self.tab_widget.addTab(compare_tab, "源值比对")

        # 3. 出厂校准标签页
        # 3. 出厂校准标签页 —— 改造为Excel风格表格（新增校准距离列）
        cali_tab = QWidget()
        cali_layout = QVBoxLayout(cali_tab)
        cali_layout.setContentsMargins(0, 0, 0, 0)
        cali_layout.setSpacing(0)

        # ===================== 关键修改：列数+1（1+1+100=102列） =====================
        self.cali_table = QTableWidget()
        DATA_COL_COUNT = 100
        # 列数：1(时间) + 1(校准距离) + 100(测点) = 102列
        self.cali_table.setColumnCount(2 + DATA_COL_COUNT)
        self.cali_table.setRowCount(20)

        # 关键修改：表头插入「校准距离」
        headers = ["校准时间", "校准距离"] + [str(i + 1) for i in range(DATA_COL_COUNT)]
        self.cali_table.setHorizontalHeaderLabels(headers)

        # 表格基础配置（不变）
        self.cali_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.cali_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.cali_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.cali_table.setShowGrid(True)
        self.cali_table.setGridStyle(Qt.SolidLine)
        self.cali_table.setAlternatingRowColors(True)

        # 表头样式（不变）
        self.cali_table.horizontalHeader().setStyleSheet("""
            QHeaderView::section {
                background-color: #DCDCDC;
                color: #000000;
                border: 1px solid #C0C0C0;
                font-weight: bold;
                padding: 4px;
            }
        """)
        self.cali_table.verticalHeader().setStyleSheet("""
            QHeaderView::section {
                background-color: #DCDCDC;
                color: #000000;
                border: 1px solid #C0C0C0;
                font-weight: bold;
                padding: 4px;
            }
        """)

        # ===================== 关键修改：新增校准距离列的列宽配置 =====================
        self.cali_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.cali_table.horizontalHeader().setMinimumSectionSize(0)
        self.cali_table.horizontalHeader().setSectionResizeMode(QHeaderView.Fixed)
        # 1. 校准时间列：200px（不变）
        self.cali_table.horizontalHeader().resizeSection(0, 200)
        # 2. 新增：校准距离列：120px
        self.cali_table.horizontalHeader().resizeSection(1, 120)
        # 3. 测点列：从第2列开始（原第1列），统一100px
        for col in range(2, 2 + DATA_COL_COUNT):
            self.cali_table.horizontalHeader().resizeSection(col, 100)

        # 右键菜单（不变）
        self.cali_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.cali_table.customContextMenuRequested.connect(self.show_cali_context_menu)
        self.cali_table_menu = QMenu(self.cali_table)
        self.cali_download_action = QAction("下载", self.cali_table)
        self.cali_delete_action = QAction("删除", self.cali_table)
        self.cali_show_action = QAction("显示", self.cali_table)

        self.cali_table_menu.addAction(self.cali_show_action)
        self.cali_table_menu.addAction(self.cali_download_action)
        self.cali_table_menu.addAction(self.cali_delete_action)


        # 添加到布局（不变）
        cali_layout.addWidget(self.cali_table)
        self.tab_widget.addTab(cali_tab, "出厂校准")

        # 4. 测量记录标签页 —— 改造为Excel风格表格
        record_tab = QWidget()
        record_layout = QVBoxLayout(record_tab)
        record_layout.setContentsMargins(0, 0, 0, 0)
        record_layout.setSpacing(0)

        # ===================== 固定列表格：1列时间 + 100列测点(1-100) =====================
        self.record_table = QTableWidget()
        # 固定列数：1(时间) + 100(测点) = 101列
        DATA_COL_COUNT = 100
        self.record_table.setColumnCount(1 + DATA_COL_COUNT)
        # 初始行数0
        self.record_table.setRowCount(20)

        # 生成表头：测量时间、1、2、3...100
        headers = ["测量时间"] + [str(i + 1) for i in range(DATA_COL_COUNT)]
        self.record_table.setHorizontalHeaderLabels(headers)

        # 表格基础配置（只读、Excel风格、美观）
        self.record_table.setEditTriggers(QTableWidget.NoEditTriggers)  # 禁止编辑
        self.record_table.setSelectionBehavior(QTableWidget.SelectRows)  # 整行选中
        # 【新增】开启多行选择：支持Ctrl多选、Shift连选、拖动框选
        self.record_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.record_table.setShowGrid(True)  # 显示网格线
        self.record_table.setGridStyle(Qt.SolidLine)
        self.record_table.setAlternatingRowColors(True)  # 交替行颜色（更清晰）

        # ===================== 【关键修改】水平+垂直表头统一灰色样式 =====================
        # 水平表头（顶部） + 垂直表头（左侧行号列）全部设置为浅灰色
        self.record_table.horizontalHeader().setStyleSheet("""
            QHeaderView::section {
                background-color: #DCDCDC;  /* 统一浅灰色背景 */
                color: #000000;            /* 黑色文字 */
                border: 1px solid #C0C0C0;  /* 边框 */
                font-weight: bold;          /* 文字加粗 */
                padding: 4px;
            }
        """)
        # 给垂直表头（行号列）设置完全相同的样式
        self.record_table.verticalHeader().setStyleSheet("""
            QHeaderView::section {
                background-color: #DCDCDC;
                color: #000000;
                border: 1px solid #C0C0C0;
                font-weight: bold;
                padding: 4px;
            }
        """)
        # ===================== 修复：强制固定宽度，彻底解决压缩/失效问题 =====================
        # 1. 【核心】强制开启水平滚动条（必须加！否则列宽再大都被窗口压缩）
        self.record_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)

        # 2. 取消表头最小宽度限制（让自定义宽度100%生效）
        self.record_table.horizontalHeader().setMinimumSectionSize(0)

        # 3. 【全局重置】所有列强制改为固定模式（清空之前的拉伸/自适应残留）
        self.record_table.horizontalHeader().setSectionResizeMode(QHeaderView.Fixed)

        # 4. 时间列：固定1000px（现在会100%生效，不再被压缩）
        self.record_table.horizontalHeader().resizeSection(0, 200)

        # 5. 所有测点列：统一固定600px（彻底消除前窄后宽，全部一样宽）
        for col in range(1, 1 + DATA_COL_COUNT):
            self.record_table.horizontalHeader().resizeSection(col, 100)

        # ===================== 【新增】表格右键菜单功能 =====================
        # 1. 设置表格支持自定义右键菜单
        self.record_table.setContextMenuPolicy(Qt.CustomContextMenu)
        # 2. 绑定右键信号到菜单弹出函数
        self.record_table.customContextMenuRequested.connect(self.show_table_context_menu)
        # 3. 创建右键菜单和选项
        self.table_menu = QMenu(self.record_table)
        self.show_action = QAction("显示", self.record_table)
        self.download_action = QAction("下载", self.record_table)
        self.delete_action = QAction("删除", self.record_table)
        self.table_menu.addAction(self.show_action)
        self.table_menu.addAction(self.download_action)
        self.table_menu.addAction(self.delete_action)


        # 添加到布局
        record_layout.addWidget(self.record_table)
        self.tab_widget.addTab(record_tab, "测量记录")

        # 5. 线性度标签页
        linear_tab = QWidget()
        linear_layout = QVBoxLayout(linear_tab)
        self.linear_text = QTextEdit()
        self.linear_text.setPlaceholderText("线性度数据将显示在这里...")
        linear_layout.addWidget(self.linear_text)
        self.tab_widget.addTab(linear_tab, "线性度")

        # 6. 均值散点分析标签页
        mean_scatter_tab = QWidget()
        mean_scatter_layout = QVBoxLayout(mean_scatter_tab)
        mean_scatter_layout.setContentsMargins(0, 0, 0, 0)
        mean_scatter_layout.setSpacing(0)

        self.mean_scatter_fig = Figure(dpi=100, constrained_layout=True)
        self.mean_scatter_canvas = FigureCanvas(self.mean_scatter_fig)
        self.mean_scatter_toolbar = NavigationToolbar(self.mean_scatter_canvas, self, coordinates=False)
        self.mean_scatter_toolbar.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)  # 关键！禁止工具栏拉伸
        self.mean_scatter_canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # ===================== 核心修改：创建水平布局，放工具栏 + 标签 =====================
        toolbar_label_layout = QHBoxLayout()
        toolbar_label_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_label_layout.setSpacing(5)

        # 1. 左侧：工具栏
        toolbar_label_layout.addWidget(self.mean_scatter_toolbar)
        # toolbar_label_layout.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

        # 3. 右侧：自定义QLabel（你可以修改文本、样式）

        self.mean_scatter_label = QLabel("均值散点分析")  # 自定义标签文本
        self.mean_scatter_label.setStyleSheet("font-size:14px; color:#333; padding-right:5px;")  # 样式
        toolbar_label_layout.addWidget(self.mean_scatter_label)

        # 将【工具栏+标签】的水平布局 添加到垂直布局
        mean_scatter_layout.addLayout(toolbar_label_layout)
        # ==================================================================================

        mean_scatter_layout.addWidget(self.mean_scatter_canvas, stretch=1)
        self.tab_widget.addTab(mean_scatter_tab, "均值散点")

        # 7. 单点分析标签页
        scatter_tab = QWidget()
        scatter_layout = QVBoxLayout(scatter_tab)
        scatter_layout.setContentsMargins(0, 0, 0, 0)
        scatter_layout.setSpacing(0)

        self.scatter_fig = Figure(dpi=100, constrained_layout=True)
        self.scatter_canvas = FigureCanvas(self.scatter_fig)
        self.scatter_toolbar = NavigationToolbar(self.scatter_canvas, self ,coordinates=False)
        self.scatter_canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # 单点刷新按钮
        single_refresh_btn = QPushButton("单点刷新")
        single_refresh_btn.setFixedWidth(80)
        single_refresh_btn.setFixedHeight(30)
        self.scatter_toolbar.addWidget(single_refresh_btn)
        self.single_refresh_btn = single_refresh_btn  # 暴露为实例属性

        # 连续单点按钮
        self.single_continuous_btn = QPushButton("连续单点")
        self.single_continuous_btn.setFixedWidth(80)
        self.single_continuous_btn.setFixedHeight(30)
        self.scatter_toolbar.addWidget(self.single_continuous_btn)

        scatter_layout.addWidget(self.scatter_toolbar)
        scatter_layout.addWidget(self.scatter_canvas, stretch=1)
        self.tab_widget.addTab(scatter_tab, "单点分析")

        # 添加标签页到日志布局
        log_layout.addWidget(self.tab_widget)
        parent_layout.addWidget(log_group)

    def append_log(self, message):
        """日志追加方法（仅UI更新，无业务逻辑）"""
        self.log_text.append(message)
        # 自动滚动到日志最后一行
        self.log_text.moveCursor(self.log_text.textCursor().End)

    # 弹出右键菜单
    def show_table_context_menu(self, pos):
        # 全局坐标转换
        self.table_menu.exec_(self.record_table.mapToGlobal(pos))

    def show_cali_context_menu(self, pos):
        """出厂校准表格 - 右键菜单弹出函数"""
        # 获取右键点击的全局位置
        global_pos = self.cali_table.mapToGlobal(pos)
        # 弹出菜单
        self.cali_table_menu.exec_(global_pos)
    # ===================== 核心：添加测量数据方法（直接调用） =====================
    def add_measurement_record(self, measure_time, data_list):
        """
        自动向表格添加一行测量数据（适配初始20行空白，填满后自动新增行）
        :param measure_time: 测量时间字符串 例：2026-04-07 17:30:00
        :param data_list: 100个测量数据列表
        """

        DATA_COL_COUNT = 100

        # 1. 查找第一个空白行（时间列为空的行）
        target_row = -1
        for row in range(self.record_table.rowCount()):
            # 获取时间列单元格
            item = self.record_table.item(row, 0)
            if not item or item.text().strip() == "":
                target_row = row
                break

        # 2. 如果没有空白行，自动新增一行
        if target_row == -1:
            target_row = self.record_table.rowCount()
            self.record_table.insertRow(target_row)

        # 3. 填充测量时间（第一列）
        time_item = QTableWidgetItem(measure_time)
        time_item.setTextAlignment(Qt.AlignCenter)  # 居中
        self.record_table.setItem(target_row, 0, time_item)

        # 4. 填充1~100号测点数据
        for col_idx in range(DATA_COL_COUNT):
            # 安全取值
            value = data_list[col_idx] if col_idx < len(data_list) else ""
            # 数值格式化
            if isinstance(value, (int, float)):
                val_text = f"{value:.1f}"
            else:
                val_text = str(value)
            # 创建单元格
            item = QTableWidgetItem(val_text)
            item.setTextAlignment(Qt.AlignCenter)
            self.record_table.setItem(target_row, col_idx + 1, item)

        # 自动滚动到最新数据
        self.record_table.scrollToItem(self.record_table.item(target_row, 0))

    def add_calibration_record(self, calibrate_time, calibrate_distance, data_list):
        """
        自动向出厂校准表格添加一行校准数据（适配校准距离列）
        :param calibrate_time: 校准时间字符串 例：2026-04-08 10:00:00
        :param calibrate_distance: 校准距离数值（微米）
        :param data_list: 100个校准数据列表
        """
        # 固定100个测点列
        DATA_COL_COUNT = 100

        # 1. 查找第一个空白行（时间列为空的行）
        target_row = -1
        for row in range(self.cali_table.rowCount()):
            item = self.cali_table.item(row, 0)
            if not item or item.text().strip() == "":
                target_row = row
                break

        # 2. 没有空白行则自动新增一行
        if target_row == -1:
            target_row = self.cali_table.rowCount()
            self.cali_table.insertRow(target_row)

        # 3. 填充校准时间（第0列）
        time_item = QTableWidgetItem(calibrate_time)
        time_item.setTextAlignment(Qt.AlignCenter)
        self.cali_table.setItem(target_row, 0, time_item)

        # 4. 填充校准距离（第1列，新增列）
        if isinstance(calibrate_distance, (int, float)):
            distance_text = f"{calibrate_distance:.1f}"  # 保留1位小数
        else:
            distance_text = str(calibrate_distance) if calibrate_distance else ""  # 空值处理
        distance_item = QTableWidgetItem(distance_text)
        distance_item.setTextAlignment(Qt.AlignCenter)
        self.cali_table.setItem(target_row, 1, distance_item)

        # 5. 填充1~100号测点数据（从第2列开始）
        for col_idx in range(DATA_COL_COUNT):
            # 安全取值：防止数据列表长度不足
            if col_idx < len(data_list):
                value = data_list[col_idx]
                if isinstance(value, (int, float)):
                    val_text = f"{value:.1f}"
                else:
                    val_text = str(value) if value else ""
            else:
                val_text = ""  # 数据不足时填充空字符串

            # 创建单元格并居中
            item = QTableWidgetItem(val_text)
            item.setTextAlignment(Qt.AlignCenter)
            # 列索引：2 + col_idx（第2列对应第1个测点，以此类推）
            self.cali_table.setItem(target_row, 2 + col_idx, item)

        # 6. 自动滚动到最新添加的行
        self.cali_table.scrollToItem(self.cali_table.item(target_row, 0))