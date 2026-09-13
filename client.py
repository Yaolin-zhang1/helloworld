# 导入核心模块
import json
import os
import socket  # 实现TCP网络通信（客户端与下位机的网络连接）
import struct  # 字节流打包/解包（处理二进制帧的编解码）
import threading  # 多线程（独立的接收监听线程、主线程处理业务指令）
from typing import Optional, Tuple, Dict, List
import bluetooth
from bluetooth import BluetoothSocket, RFCOMM, BluetoothError, Protocols
from PyQt5.QtCore import QObject, pyqtSignal, QTimer  # 移除了Callable（不再需要原生回调）


# -------------------------- MODBUS RTU CRC16 校验算法（与协议C代码完全一致） --------------------------
def rtu_crc16(buf: bytes) -> int:
    """
    计算字节流的CRC16校验值（严格遵循协议提供的MODBUS RTU C代码，一字不差）

    Parameters:
        buf (bytes): 待校验的字节数据

    Returns:
        int: 16位CRC校验结果（十进制整数，小端序打包）
    """
    crc_sum = 0xFFFF  # CRC初始值（MODBUS RTU标准）
    for byte in buf:
        crc_sum ^= byte  # 与当前字节进行异或运算
        for _ in range(8):  # 逐位处理每个字节的8位
            if crc_sum & 0x01:  # 最低位为1时
                crc_sum >>= 1  # 右移1位
                crc_sum ^= 0xA001  # 异或标准多项式（MODBUS RTU指定）
            else:
                crc_sum >>= 1  # 最低位为0时，仅右移1位
    return crc_sum


# -------------------------- 数据帧打包/解包核心函数（无修改，与协议通用格式一致） --------------------------
def pack_command_frame(cmd: int, content_bytes: bytes = b"") -> bytes:
    """
    打包上位机→下位机的指令帧，生成符合协议通用格式的二进制帧（小端序）
    帧结构：帧头(2B,0x90EB) + 指令码(2B) + 内容(NB) + CRC校验(2B) + 帧尾(2B,0x80EB)
    """
    head = struct.pack("<H", 0x90EB)
    cmd_bytes = struct.pack("<H", cmd)
    data_for_crc = head + cmd_bytes + content_bytes
    crc = rtu_crc16(data_for_crc)
    crc_bytes = struct.pack("<H", crc)
    end = struct.pack("<H", 0x80EB)
    full_frame = head + cmd_bytes + content_bytes + crc_bytes + end
    return full_frame


def unpack_response_frame(frame_bytes: bytes) -> Tuple[int, bytes]:
    """
    解包下位机→上位机的响应帧，校验帧头/帧尾/CRC，返回（指令码，内容字节）
    校验失败抛出ValueError，严格遵循协议通用格式
    """
    if len(frame_bytes) < 8:
        raise ValueError(f"帧长度异常：实际{len(frame_bytes)}字节，最小需8字节（头2+指令2+CRC2+尾2）")
    # 解包帧头/指令码/帧尾
    head = struct.unpack("<H", frame_bytes[0:2])[0]
    cmd = struct.unpack("<H", frame_bytes[2:4])[0]
    end = struct.unpack("<H", frame_bytes[-2:])[0]
    # 校验帧头/帧尾
    if head != 0x90EB:
        raise ValueError(f"帧头错误：预期0x90EB，实际0x{head:04X}")
    if end != 0x80EB:
        raise ValueError(f"帧尾错误：预期0x80EB，实际0x{end:04X}")
    # 校验CRC
    content_len = len(frame_bytes) - 8
    data_for_crc = frame_bytes[0:4 + content_len]
    crc_received = struct.unpack("<H", frame_bytes[4 + content_len:6 + content_len])[0]
    crc_calculated = rtu_crc16(data_for_crc)
    if crc_received != crc_calculated:
        raise ValueError(f"CRC校验失败：接收0x{crc_received:04X}，计算0x{crc_calculated:04X}")
    # 解包内容
    content_bytes = frame_bytes[4:4 + content_len] if content_len > 0 else b""
    return cmd, content_bytes

# -------------------------- 上位机TCP客户端核心类（全量协议修正+新增指令） --------------------------
class StraightRulerClient(QObject):
    """
    平直尺上位机TCP客户端核心类（严格遵循《平直尺通信协议V1.0》）
    已实现协议中所有10条指令（0x0101~0x010A+0x010B），线程安全，Qt信号解耦UI
    """

    # ========== Qt信号定义（与原代码一致，适配UI交互） ==========
    log_signal = pyqtSignal(str)  # 日志信号（带字符串参数）
    normal_measure_finished = pyqtSignal()  # 正常测量完成信号
    calibration_finished = pyqtSignal(int)  # 校准完成信号（带校准编号）
    state_disconnected = pyqtSignal()  # 断开连接信号
    single_finished = pyqtSignal()  # 单点测量完成信号
    clear_calibration_finished = pyqtSignal(bool)  # 清除校准表完成信号（True=成功，False=失败）
    # 🔥 修改点2：新增蓝牙连接相关信号
    connected_signal = pyqtSignal()  # 蓝牙连接成功信号
    connected_failed = pyqtSignal()  # 蓝牙连接失败信号

    # 🔥 修改点3：新增蓝牙MAC缓存文件
    _CACHE_FILE = "bt_mac_cache.json"

    def __init__(self, target_bt_name: str):
        super().__init__()
        # 连接信息（协议指定：TCP+8889端口，下位机为服务端）
        self.target_bt_name = target_bt_name  # 下位机蓝牙名称
        self.sock: Optional[BluetoothSocket] = None  # 蓝牙Socket（替换原TCP socket）
        self.connected = False
        self.cached_mac = self._load_cached_mac()  # 缓存蓝牙MAC，跳过重复扫描


        # 线程相关（解耦接收监听与业务逻辑，避免UI阻塞）
        self.recv_thread: Optional[threading.Thread] = None
        self.recv_running = False
        self.data_lock = threading.Lock()  # 多线程数据访问锁（线程安全核心）

        self.timer = QTimer()
        self.timer.timeout.connect(self.start_upgrade_010F)

        # 数据存储（严格对齐协议字段，线程安全访问）
        self.device_params = {}  # 0x0101设备参数（含新增的PowerOffTime/num/time）
        self.calibration_data: Dict[int, dict] = {}  # 校准数据 {编号: {time:校准时间, distance:校准距离, table:校准值列表}}
        self.normal_measure_data = []  # 0x0109正常测量数据（含温度/电压/side/ADC）
        self.wendu = None
        self.dianya = None
        self.single_point_measure_data = None  # 0x010A单点测量数据（含温度/电压/side/point/ADC）
        self.last_response = {}  # 最近指令响应结果 {指令码: 结果}

        self.upgrade_file_data = b""  # 升级文件二进制数据

        # 协议基础参数（从0x0101响应中动态更新）
        self.sensor_count = 200  # 单面传感器数量（默认200，协议支持100/200/400）
        self.double_side = 0  # 是否双面（0=单面，1=双面，默认单面）

        self.jiaozhun_num = -1
    def _log(self, message: str):
        """线程安全日志输出：触发Qt信号，失败则print兜底"""
        try:
            self.log_signal.emit(message)
        except Exception:
            print(message)
        # ===================== 🔥 修改点6：新增蓝牙MAC缓存方法（本地保存，秒连） =====================

    def _load_cached_mac(self):
        """加载本地缓存的MAC（健壮版）"""
        try:
            if os.path.exists(self._CACHE_FILE):
                with open(self._CACHE_FILE, 'r', encoding='utf-8') as f:
                    file_content = f.read().strip()
                    if not file_content:  # 空文件
                        return None
                    cache = json.loads(file_content)
                    mac = cache.get(self.target_bt_name)
                    if mac:
                        self._log(f"✅ 从缓存读取MAC：{self.target_bt_name} → {mac}")
                    return mac
        except (json.JSONDecodeError, PermissionError, IOError) as e:
            self._log(f"❌ 读取缓存异常：{str(e)}")
        return None

    def _save_cached_mac(self, mac):
        """保存MAC到本地（健壮版：兼容空文件/异常/格式化）"""
        cache = {}
        # 1. 读取现有缓存（兼容空文件/格式错误/文件不存在）
        try:
            if os.path.exists(self._CACHE_FILE):
                with open(self._CACHE_FILE, 'r', encoding='utf-8') as f:
                    # 先判断文件是否为空
                    file_content = f.read().strip()
                    if file_content:  # 非空才解析
                        cache = json.loads(file_content)
                    else:  # 空文件 → 重置为空字典
                        cache = {}
        except (json.JSONDecodeError, PermissionError, IOError) as e:
            self._log(f"读取缓存文件异常：{str(e)}，重置缓存")
            cache = {}

        # 2. 更新缓存（覆盖/新增当前设备的MAC）
        cache[self.target_bt_name] = mac

        # 3. 写入缓存（加异常捕获+格式化）
        try:
            with open(self._CACHE_FILE, 'w', encoding='utf-8') as f:
                # indent=2：格式化JSON，方便查看；ensure_ascii=False：兼容中文名称
                json.dump(cache, f, ensure_ascii=False, indent=2)
            self._log(f"✅ MAC地址已缓存：{self.target_bt_name} → {mac}")
        except (PermissionError, IOError) as e:
            self._log(f"❌ 保存缓存文件失败：{str(e)}")

    # -------------------------- 连接/断开核心方法（无修改，稳定可用） --------------------------
    # -------------------------- 🔥 修改点7：蓝牙连接/断开核心方法（替换原TCP连接） --------------------------
    def connect(self) -> bool:
        """对外接口：子线程蓝牙连接，不阻塞UI"""
        if self.connected:
            self._log("【提示】已连接到蓝牙设备，无需重复连接\n")
            return True
        # 子线程执行蓝牙连接（避免阻塞）
        threading.Thread(target=self._bt_connect_worker, daemon=True).start()
        return True

    def _bt_connect_worker(self):
        """蓝牙连接工作线程：扫描设备→找通道→建立RFCOMM连接"""
        try:
            # 1. 获取蓝牙MAC（缓存优先）
            mac = self.cached_mac
            mac = None
            if not mac:
                self._log("【扫描】正在查找蓝牙设备...\n")
                devices = bluetooth.discover_devices(duration=2, lookup_names=True)
                for addr, name in devices:
                    if name == self.target_bt_name:
                        mac = addr
                        self._save_cached_mac(mac)
                        break
                if not mac:
                    self._log(f"【失败】未找到蓝牙设备：{self.target_bt_name}\n")
                    self.connected_failed.emit()
                    return

            # 2. 固定RFCOMM通道1（下位机标准配置）
            channel = 1
            # 3. 创建蓝牙Socket并连接
            self.sock = BluetoothSocket(Protocols.RFCOMM)
            self.sock.settimeout(5.0)
            self.sock.connect((mac, channel))

            # 4. 连接成功
            self.connected = True
            self.connected_signal.emit()
            self.start_recv_listener()
            self._log(f"【成功】连接蓝牙设备：{self.target_bt_name} | MAC:{mac}\n")

        except BluetoothError as e:
            self._log(f"【失败】蓝牙连接失败：{e}\n")
            self.connected_failed.emit()
        finally:
            if not self.connected:
                self._cleanup_bt_socket()

    def disconnect(self):
        """断开蓝牙连接（替换原TCP断开）"""
        self.stop_recv_listener()
        if self.sock and self.connected:
            try:
                self.sock.close()
                self._log("【信息】已断开蓝牙连接\n")
            except Exception as e:
                self._log(f"【错误】断开连接时出错：{e}\n")
            finally:
                self.connected = False
                self.sock = None
                with self.data_lock:
                    self.device_params.clear()
                    self.calibration_data.clear()
                    self.normal_measure_data.clear()
                    self.single_point_measure_data = None
                    self.last_response.clear()
                self.state_disconnected.emit()

    def _cleanup_bt_socket(self):
        """清理蓝牙Socket资源"""
        try:
            if self.sock:
                self.sock.close()
        except:
            pass
        self.connected = False


    def start_recv_listener(self):
        if self.recv_running:
            return
        self.recv_running = True
        self.recv_thread = threading.Thread(target=self.recv_listener, daemon=True)
        self.recv_thread.start()
        self._log("【信息】接收监听线程已启动\n")

    def stop_recv_listener(self):
        if not self.recv_running:
            return
        self.recv_running = False
        if self.recv_thread and self.recv_thread.is_alive():
            self.recv_thread.join(timeout=2.0)
        self._log("【信息】接收监听线程已停止\n")

    def recv_listener(self):
        """蓝牙接收核心：按帧尾0x80EB分割，解决粘包/半包"""
        recv_buffer = b""
        while self.recv_running and self.connected:
            try:
                # 蓝牙Socket读取数据
                chunk = self.sock.recv(4096)
                if not chunk:
                    self._log("【信息】蓝牙设备关闭了连接\n")
                    self.connected = False
                    self.state_disconnected.emit()
                    break
                recv_buffer += chunk

                # 按帧尾分割完整帧
                while b"\xeb\x80" in recv_buffer:
                    frame_end_idx = recv_buffer.index(b"\xeb\x80") + 2
                    frame_data = recv_buffer[:frame_end_idx]
                    recv_buffer = recv_buffer[frame_end_idx:]
                    self._process_received_frame(frame_data)

            # 🔥 超时 → 直接 continue，继续循环接收
            except BluetoothError as e:
                # 非超时异常 → 断开连接
                self._log(f"【错误】蓝牙接收异常：{e}")
                self.connected = False
                break
            except Exception as e:
                if "timed out" in str(e).lower():
                    continue
                self._log(f"【错误】接收线程异常：{e}")
                break




    def _process_received_frame(self, frame_data: bytes):
        """帧处理分发：指令码→处理函数映射，严格对齐协议V1.0所有指令"""
        try:
            self._log(f"【接收】帧长度：{len(frame_data)} 字节，16进制：{frame_data.hex()}\n")

            cmd, content = unpack_response_frame(frame_data)
            # 指令码-处理函数映射（包含协议所有10条指令，新增0x010B）
            handler_map = {
                0x0101: self._handle_0101_response,  # 读取参数响应
                0x0102: self._handle_0102_response,  # 设置参数响应
                0x0103: self._handle_0103_response,  # 启动正常测量响应
                0x0104: self._handle_0104_response,  # 启动单点测量响应
                0x0105: self._handle_0105_response,
                0x0106: self._handle_0106_response,
                0x0109: self._handle_0109_data,      # 正常测量上报
                0x010A: self._handle_010A_data,      # 单点测量上报
                0x0107: self._handle_0107_response,  # 读取校准值响应
                0x0108: self._handle_0108_response,  # 设置校准值响应
                0x010B: self._handle_010B_response   # 清除校准表响应【新增】
            }
            if cmd in handler_map:
                handler_map[cmd](content)
            else:
                self._log(f"【警告】未处理的指令码：0x{cmd:04X}\n")
        except Exception as e:
            self._log(f"【错误】解析接收帧失败：{e}\n")

    # -------------------------- 协议指令响应处理函数（全量修正+新增） --------------------------
    def _handle_0101_response(self, content: bytes):
        """
        【核心修正】处理0x0101读取参数响应（修复char数组被解析为uint16_t的错误，严格匹配协议字段类型/顺序/长度）
        协议结构体字段（逐行严格对应）：
        1.int16_t batttemp      2.uint16_t battvoltage    3.uint16_t SensorPoint     4.uint16_t DoubleSide
        5.char FirmwareData[16] 6.char FirmwareTime[16]   7.uint16_t PowerOffTime    8.uint16_t num
        9.Uint32_t time         10.Char sn[12]            11.char res0-res9[16*10]
        总字节长度：2 + 2*3 + 16*2 + 2*2 + 4 + 12 + 16*10 = 220 字节（协议严格计算，不可修改）
        """
        try:
            # 【核心修正】修正总长度：从216→220（匹配char[16]*2的实际字节数）
            expected_len = 2 + (2 * 3) + (16 * 2) + (2 * 2) + 4 + 12 + (16 * 10)
            if len(content) != expected_len:
                self._log(f"【错误】0x0101参数长度错误：预期{expected_len}字节，实际{len(content)}字节\n")
                return

            # 【核心修正】修正解包格式字符串（严格按协议类型/顺序）：
            # h=batttemp | 3H=后3个uint16_t | 16s=FirmwareData | 16s=FirmwareTime | 2H=PowerOffTime+num | L=time | 12s=sn | 16s*10=res0-res9
            unpack_format = "<h3H16s16s2HL12s" + "16s" * 10
            res = struct.unpack(unpack_format, content)

            time = str(res[8])
            time = time[:4]+ "--" + time[4:6] +"--" + time[6:8]
            # 【核心修正】修正字段索引（严格对应解包结果，无偏移）
            device_params = {
                "batttemp_raw": res[0],  # 0: int16_t 温度原始值（*100）
                "batttemp": res[0] / 100.0,  # 实际温度（℃）
                "battvoltage": res[1],  # 1: uint16_t 电压（毫伏）
                "SensorPoint": res[2],  # 2: uint16_t 单面传感器数量（100/200/400）
                "DoubleSide": res[3],  # 3: uint16_t 是否双面（0=单面，1=双面）
                # 4/5: char[16] 固件日期/时间（正确解码，去除空字符）
                "FirmwareData": res[4].decode("gbk", errors="ignore").strip('\x00'),
                "FirmwareTime": res[5].decode("gbk", errors="ignore").strip('\x00'),
                "PowerOffTime": res[6],  # 6: uint16_t 自动关机时间（秒，0=不关机）
                "calib_num": res[7],  # 7: uint16_t 校准数据条数（0-31）
                "calib_time": time,  # 8: uint32_t 校准时间
                "sn": res[9].decode("gbk", errors="ignore").strip('\x00'),  # 9: char[12] 尺子SN
                # 10-19: char[16]*10 保留字段res0-res9
                "res0-res9": [res[i].decode("gbk", errors="ignore").strip('\x00') for i in range(10, 20)]
            }
            # # 秒级时间戳 → QDateTime 对象（自动转换为本地时区时间）
            # calib_time_qt = QDateTime.fromSecsSinceEpoch(res[8])
            # # 格式化为字符串（和你之前的格式完全一致：年-月-日 时:分:秒）
            # calib_time_str = calib_time_qt.toString("yyyy-MM-dd hh:mm:ss")
            # 线程安全更新全局参数（传感器数量/双面标志从正确解析的字段取值）
            with self.data_lock:
                self.device_params = device_params
                self.sensor_count = device_params["SensorPoint"]  # 动态更新传感器数量（核心，影响后续所有测量/校准指令）
                self.double_side = device_params["DoubleSide"]  # 动态更新双面标志
                self.last_response[0x0101] = device_params

            # 日志输出核心有效信息（固件日期/时间正常显示，不再是乱码）
            self._log(f"【成功】读取设备参数完成（传感器数量：{device_params['SensorPoint']}）\n")
            self._log(
                f"  温度：{device_params['batttemp']:.2f}℃ | 电压：{device_params['battvoltage']}mV | 双面标志：{device_params['DoubleSide']}\n")
            self._log(
                f"  自动关机：{device_params['PowerOffTime']}s | 校准条数：{device_params['calib_num']} | SN：{device_params['sn']}\n")
            self._log(f"  固件编译：{device_params['FirmwareData']} {device_params['FirmwareTime']} \n")
            self._log(f" cali_time: {device_params['calib_time']} \n ")
        except Exception as e:
            self._log(f"【错误】解析0x0101响应失败：{e}\n")

    def _handle_0102_response(self, content: bytes):
        """处理0x0102设置参数响应（协议无修改，原代码逻辑正确）"""
        try:
            expected_len = 4  # result(2B) + res(2B)
            if len(content) != expected_len:
                self._log(f"【错误】0x0102响应长度错误：预期{expected_len}字节，实际{len(content)}字节\n")
                return
            result, res = struct.unpack("<2H", content)
            success = result == 1
            with self.data_lock:
                self.last_response[0x0102] = {"success": success, "result": result, "res": res}
            self._log(f"【成功】设置设备参数{'成功' if success else '失败'}，返回码：{result}\n")
        except Exception as e:
            self._log(f"【错误】解析0x0102响应失败：{e}\n")

    def _handle_0103_response(self, content: bytes):
        """处理0x0103启动正常测量响应（协议无修改，原代码逻辑正确）"""
        try:
            expected_len = 4  # side(2B) + result(2B)
            if len(content) != expected_len:
                self._log(f"【错误】0x0103响应长度错误：预期{expected_len}字节，实际{len(content)}字节\n")
                return
            side, result = struct.unpack("<2H", content)
            success = result == 1
            with self.data_lock:
                self.last_response[0x0103] = {"side": side, "success": success, "result": result}
            self._log(f"【成功】启动正常测量（{side=}：0=行车面/1=导向面）{'成功' if success else '失败'}\n")
        except Exception as e:
            self._log(f"【错误】解析0x0103响应失败：{e}\n")

    def _handle_0104_response(self, content: bytes):
        """处理0x0104启动单点测量响应（协议无修改，原代码逻辑正确）"""
        try:
            expected_len = 4  # side(2B) + result(2B)
            if len(content) != expected_len:
                self._log(f"【错误】0x0104响应长度错误：预期{expected_len}字节，实际{len(content)}字节\n")
                return
            side, result = struct.unpack("<2H", content)
            success = result == 1
            with self.data_lock:
                self.last_response[0x0104] = {"side": side, "success": success, "result": result}
            self._log(f"【成功】启动单点测量（{side=}：0=行车面/1=导向面）{'成功' if success else '失败'}\n")
        except Exception as e:
            self._log(f"【错误】解析0x0104响应失败：{e}\n")

    # 升级响应处理
    def _handle_0105_response(self, content: bytes):
        result, _ = struct.unpack('<HH', content)
        success = result
        self.is_upgrading = success
        self._log(f"【开始升级】{'成功' if success else '失败'}\n")
        if result == 1:
            self.timer.stop()
            self.send_upgrade_data_0106(0,self.upgrade_file_data[0:512])
            self.offset = 512

    def _handle_0106_response(self, content: bytes):
        offset, result, _ = struct.unpack('<IHH', content)
        success = result
        self._log(f"【升级数据】起始位置{self.offset}：{'成功' if success else '失败'}\n")

        if self.offset < len(self.upgrade_file_data) and result == 1:

            end = self.offset + 512 if self.offset + 512 < len(self.upgrade_file_data) else len(self.upgrade_file_data)
            self.send_upgrade_data_0106(self.offset, self.upgrade_file_data[self.offset:end])
            self.offset = end


    def _handle_0109_data(self, content: bytes):
        """
        【顺序修正+协议匹配】处理0x0109正常测量上报，严格遵循协议字段顺序：
        协议结构体：uint16_t side → int16_t batttemp → uint16_t battvoltage → uint16_t ADC[N]
        预期长度：2(side) + 2(batttemp) + 2(battvoltage) + 2*N(ADC) （N=传感器数量）
        """
        try:
            # 长度计算正确，无需修改
            expected_len = 2 + 2 + 2 +2 + self.sensor_count * 2
            if len(content) != expected_len:
                self._log(f"【错误】0x0109数据长度错误：预期{expected_len}字节，实际{len(content)}字节\n")
                return

            # 【顺序修正】解包格式<HhH不变，但严格按协议顺序赋值：side → batttemp_raw → battvoltage
            # H=uint16_t(side) | h=int16_t(batttemp) | H=uint16_t(battvoltage)
            batttemp_raw, battvoltage , side ,res= struct.unpack("<HhHH", content[:8])
            # 解析ADC数组（后续所有字节）
            adc_data = struct.unpack(f"<{self.sensor_count}H", content[8:])

            # 整理数据（字段赋值完全匹配协议）
            measure_data = {
                "side": side,  # 协议第1字段：测量面（0=行车面/1=导向面）
                "batttemp_raw": batttemp_raw,  # 协议第2字段：温度原始值（int16_t，*100）
                "batttemp": batttemp_raw / 100.0,  # 实际温度（℃）
                "battvoltage": battvoltage,  # 协议第3字段：电压（毫伏）
                "ADC": list(adc_data)  # 协议第4字段：ADC采集值列表
            }

            # 线程安全存储并触发UI信号
            with self.data_lock:
                self.normal_measure_data.append(measure_data.get('ADC'))
                self.wendu = measure_data.get('batttemp')
                self.dianya = measure_data.get('battvoltage')
            self.normal_measure_finished.emit()

            # 日志输出（字段对应正确，无错位）
            self._log(f"【成功】接收正常测量数据（{side=}：0=行车面/1=导向面）\n")
            self._log(
                f"  温度：{measure_data['batttemp']:.2f}℃ | 电压：{measure_data['battvoltage']}mV | ADC数量：{len(adc_data)}\n")
            self._log(f"  前10个ADC值：{list(adc_data[:10])}\n")
        except Exception as e:
            self._log(f"【错误】解析0x0109数据失败：{e}\n")

    def _handle_010A_data(self, content: bytes):
        """
        【协议修正】处理0x010A单点测量上报（完全重构，匹配协议新结构体）
        协议结构体：int16_t batttemp + uint16_t battvoltage + uint16_t side + uint16_t point + uint16_t ADC[N]
        预期长度：2 + 2 + 2 + 2 + 2*N （N=传感器数量）
        """
        try:
            expected_len = 2 + 2 + 2 + 2 + self.sensor_count * 2
            if len(content) != expected_len:
                self._log(f"【错误】0x010A数据长度错误：预期{expected_len}字节，实际{len(content)}字节\n")
                return
            # 解包：严格按协议字段顺序（温度→电压→side→point→ADC）
            batttemp_raw, battvoltage, side, point = struct.unpack("<h3H", content[:8])
            adc_data = struct.unpack(f"<{self.sensor_count}H", content[8:])
            # 整理数据
            single_data = {
                "batttemp_raw": batttemp_raw,
                "batttemp": batttemp_raw / 100.0,
                "battvoltage": battvoltage,
                "side": side,
                "point": point,
                "ADC": list(adc_data)
            }
            # 线程安全存储并触发UI信号
            with self.data_lock:
                self.single_point_measure_data = single_data.get("ADC")
            self.single_finished.emit()
            self._log(f"【成功】接收单点测量数据（{side=}，{point=}），温度：{single_data['batttemp']:.2f}℃，前10个ADC：{list(adc_data[:10])}\n")
        except Exception as e:
            self._log(f"【错误】解析0x010A数据失败：{e}\n")

    def _handle_0107_response(self, content: bytes):
        """
        【协议修正】处理0x0107读取校准值响应（新增distance校准距离字段）
        协议结构体：uint16_t num + uint32_t time + uint16_t distance + uint16_t table[N]
        预期长度：2 + 4 + 2 + 2*N （N=传感器数量）
        """
        try:
            expected_len = 2 + 2 + 4 + 2 + self.sensor_count * 2
            if len(content) != expected_len:
                self._log(f"【错误】0x0107校准值长度错误：预期{expected_len}字节，实际{len(content)}字节\n")
                return
            # 解包：num(2B) + time(4B) + distance(2B) + table(N*2B)
            num, Isjizhun, time, distance = struct.unpack("<HHLH", content[:10])
            table = struct.unpack(f"<{self.sensor_count}H", content[10:])
            # 整理校准数据（新增distance字段）
            calib_data = {
                "num": num,
                "Isjizhun": Isjizhun,
                "time": time,
                "distance": distance,  # 校准距离 单位：微米
                "table": list(table)
            }
            if Isjizhun:
                self.jiaozhun_num = num
            # 线程安全存储并触发UI信号
            # if num !=1  and distance == 0:
            #     self._log("获取了无效数据！")
            #     return
            if num != 0 and table[0]== 0:
                self._log("获取了无效数据！")
                return

            with self.data_lock:
                self.calibration_data[num] = calib_data
                self.last_response[0x0107] = calib_data
            self.calibration_finished.emit(num)
            jizhun_text = "TRUE" if Isjizhun == 1 else "FALSE"
            self._log(f"【成功】读取校准值（编号{num}）,是否基准:{jizhun_text} 校准距离：{distance}，校准时间：{time} ,前10个值：{list(table[:10])}\n")
        except Exception as e:
            self._log(f"【错误】解析0x0107响应失败：{e}\n")

    def _handle_0108_response(self, content: bytes):
        """
        【协议修正】处理0x0108设置校准值响应（修正字段顺序：num→result，原代码颠倒）
        协议结构体：uint16_t num + uint16_t result （2+2=4字节）
        """
        try:
            expected_len = 4
            if len(content) != expected_len:
                self._log(f"【错误】0x0108响应长度错误：预期{expected_len}字节，实际{len(content)}字节\n")
                return
            # 解包：严格按协议顺序 num + result（原代码是result + num，核心错误）
            num,result = struct.unpack("<2H", content)
            success = result == 1
            # 线程安全存储
            with self.data_lock:
                self.last_response[0x0108] = {"num": num, "success": success, "result": result}
            self._log(f"【成功】设置校准值（编号{num}）{'成功' if success else '失败'}，返回码：{result}\n")
        except Exception as e:
            self._log(f"【错误】解析0x0108响应失败：{e}\n")

    def _handle_010B_response(self, content: bytes):
        """
        【新增】处理0x010B清除校准表响应（协议指定：result(2B) + res(2B) = 4字节）
        """
        try:
            expected_len = 4
            if len(content) != expected_len:
                self._log(f"【错误】0x010B响应长度错误：预期{expected_len}字节，实际{len(content)}字节\n")
                return
            result, res = struct.unpack("<2H", content)
            success = result == 1
            # 线程安全存储并触发UI信号
            with self.data_lock:
                self.last_response[0x010B] = {"success": success, "result": result, "res": res}
            self.clear_calibration_finished.emit(success)
            self._log(f"【成功】清除校准表{'成功' if success else '失败'}，返回码：{result}\n")
        except Exception as e:
            self._log(f"【错误】解析0x010B响应失败：{e}\n")

    # -------------------------- 协议指令发送函数（全量修正+新增） --------------------------
    def send_frame(self, frame: bytes) -> bool:
        """基础发送函数：蓝牙Socket发送（替换原TCP sendall）"""
        if not self.connected or not self.sock:
            self._log("【错误】未连接到蓝牙设备，无法发送数据\n")
            return False
        try:
            self.sock.send(frame)
            self._log(f"【发送】帧长度：{len(frame)} 字节，16进制：{frame.hex()}\n")
            return True
        except BluetoothError as e:
            self._log(f"【错误】发送帧失败（蓝牙连接异常）：{e}\n")
            self.connected = False
            return False
        except Exception as e:
            self._log(f"【错误】发送帧失败：{e}\n")
            return False

    def read_parameters(self) -> bool:
        """发送0x0101指令：读取设备参数（协议无修改，原代码逻辑正确）"""
        frame = pack_command_frame(0x0101)
        return self.send_frame(frame)

    def set_parameters(self, power_off_time: int, calib_num: int, calib_time: int, sn: str, res_list: List[str]) -> bool:
        """
        【协议修正】发送0x0102指令：设置设备参数（重构入参，匹配协议新结构体）
        协议content：PowerOffTime + num + time + SN[12] + res0-res9[16]
        Parameters:
            power_off_time: 自动关机时间（秒，0=不关机）
            calib_num: 校准数据条数（0-31）
            calib_time: 校准时间（uint32_t）
            sn: 尺子SN（最长12字符）
            res_list: 10个保留字段（每个最长16字符）
        """
        # 入参合法性校验（严格匹配协议范围）
        if not isinstance(power_off_time, int) or power_off_time < 0:
            self._log(f"【错误】自动关机时间非法：{power_off_time}，需为非负整数\n")
            return False
        if not 0 <= calib_num <= 31:
            self._log(f"【错误】校准条数非法：{calib_num}，需为0-31\n")
            return False
        if len(sn) > 12:
            self._log(f"【错误】SN过长：{len(sn)}字符，最长12字符\n")
            return False
        if len(res_list) != 10:
            self._log(f"【错误】保留字段数量错误：{len(res_list)}个，需为10个\n")
            return False
        # 格式化字符串：补\x00到协议指定长度，GBK编码
        sn_bytes = sn.ljust(12, '\x00').encode("gbk")
        res_bytes = [res.ljust(16, '\x00').encode("gbk") for res in res_list]
        # 打包content：严格按协议顺序（PowerOffTime→num→time→SN→res）
        content = struct.pack("<2HL", power_off_time, calib_num, calib_time)
        content += sn_bytes
        for res in res_bytes:
            content += res
        # 打包并发送帧
        frame = pack_command_frame(0x0102, content)
        return self.send_frame(frame)

    def start_normal_measure(self, side: int) -> bool:
        """发送0x0103指令：启动正常测量（协议无修改，原代码逻辑正确）"""
        if side not in [0, 1]:
            self._log(f"【错误】测量面非法：{side}，仅支持0（行车面）/1（导向面）\n")
            return False
        content = struct.pack("<2H", side, 0)  # side + 保留res=0
        frame = pack_command_frame(0x0103, content)
        return self.send_frame(frame)

    def start_single_point_measure(self, side: int, point: int) -> bool:
        """发送0x0104指令：启动单点测量（协议无修改，原代码逻辑正确）"""
        if side not in [0, 1]:
            self._log(f"【错误】测量面非法：{side}，仅支持0（行车面）/1（导向面）\n")
            return False
        if not 1 <= point <= self.sensor_count:
            self._log(f"【错误】测量点非法：{point}，需为1-{self.sensor_count}\n")
            return False
        content = struct.pack("<2H", side, point)  # side + point
        frame = pack_command_frame(0x0104, content)
        return self.send_frame(frame)

    def read_calibration_value(self, num: int) -> bool:
        """发送0x0107指令：读取指定编号校准值（协议无修改，原代码逻辑正确）"""
        if not 0 <= num <= 31:
            self._log(f"【错误】校准编号非法：{num}，需为0-31\n")
            return False
        content = struct.pack("<H", num)
        frame = pack_command_frame(0x0107, content)
        return self.send_frame(frame)

    def set_calibration_value(self, num: int, ISjizhun: int, time: int, distance: int, table: List[int]) -> bool:
        """
        【协议修正】发送0x0108指令：设置指定编号校准值（新增distance校准距离字段）
        Parameters:
            num: 校准编号（0-31）
            time: 校准时间（uint32_t）
            distance: 校准距离（uint16_t）【新增】
            table: 校准值列表（长度=传感器数量）
        """
        if not 0 <= num <= 31:
            self._log(f"【错误】校准编号非法：{num}，需为0-31\n")
            return False
        if len(table) != self.sensor_count:
            self._log(f"【错误】校准值数量错误：{len(table)}个，需为{self.sensor_count}个\n")
            return False
        # 打包content：num + time + distance + table（严格按协议顺序）
        content = struct.pack("<HHLH", num,ISjizhun, time, distance)
        content += struct.pack(f"<{self.sensor_count}H", *table)
        frame = pack_command_frame(0x0108, content)
        return self.send_frame(frame)

    def clear_calibration_table(self) -> bool:
        """
        【新增】发送0x010B指令：清除校准表（协议指定：无content）
        """
        frame = pack_command_frame(0x010B)
        return self.send_frame(frame)

    def start_upgrade_0105(self, file_size: int, file_crc: int) -> bool:
        """
        【函数1】0x0105 开始升级
        帧格式：head(0x90EB) + crc + cmd(0x0105) + content + end(0x80EB)
        常量全部内联，无外部依赖
        """


        # 1. 打包content
        content = struct.pack('<IHH', file_size, file_crc, 0)
        frame = pack_command_frame(0x0105, content)
        self.timer.start(2000)

        return self.send_frame(frame)



    def start_upgrade_010F(self) -> bool:
        """

        """
        frame = pack_command_frame(0x010F)
        return self.send_frame(frame)

    def send_upgrade_data_0106(self, offset: int, data: bytes) -> bool:
        """
        0x0106 升级数据（协议规定：无CRC！）
        帧格式：0x90EB + cmd(0x0106) + content + 0x80EB
        结构体：UInt32 偏移 + UInt32 实际长度 + byte[512] 数据（不足补0）
        """

        # 固定512字节数据（匹配C语言 data[512] 结构体）
        real_len = len(data)
        fixed_data = data.ljust(512, b'\x00')
        # 打包固定结构体 <II512s
        content = struct.pack('<II512s', offset, real_len, fixed_data)
        frame = pack_command_frame(0x0106, content)
        return self.send_frame(frame)