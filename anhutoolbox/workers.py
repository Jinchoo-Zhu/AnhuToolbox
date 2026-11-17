
# -*- coding: utf-8 -*-
"""AnhuToolbox 通信后端 -- 超低延迟版本"""

import os, socket, select, time, ctypes, threading
from PySide6.QtCore import QThread, Signal
import serial

# Windows 默认定时器分辨率约 15.6ms, 会让 time.sleep(0.003) 实际睡 ~15.6ms,
# 期间所有帧都到达缓冲 -> 必然合包。这里把系统定时器精度提高到 1ms。
try:
    ctypes.windll.winmm.timeBeginPeriod(1)
except Exception:
    pass

# TCP 帧间隙: 读取缓冲读空后, 等待这么久没有新字节即认为一帧结束。
# 串口会根据实际波特率和帧格式动态计算至少两个字符时间，避免在低波特率
# (例如 9600) 下把帧内相邻字节误判为两帧。
FRAME_GAP_S = 0.001
# 一帧最大字节数: 超过即强制切分输出, 防止设备持续发数据(高频心跳)时无限合并
FRAME_MAX_BYTES = 512
# 一帧最长累积时间: 超过即强制输出, 兜底保证延迟
FRAME_MAX_HOLD_S = 0.05


class SerialReadWorker(QThread):
    """串口读取 -- 事件驱动 + 帧间隙分帧, 低延迟且能拆开驱动合并的多帧"""
    data_received = Signal(bytes)
    error_occurred = Signal(str)
    disconnected = Signal(str)

    def __init__(self):
        super().__init__()
        self._serial: serial.Serial | None = None
        self._running = False
        self._stopping = False
        self._stop_event = threading.Event()

    def set_serial(self, ser: serial.Serial | None):
        # 保留外部设置的 timeout (作为无数据时的最大等待, 保证线程可退出)
        # 数据到达时 pyserial 是事件驱动, 阻塞 read() 会立即返回, 不受 timeout 影响
        # 下一次明确设置串口时才解除停止标志。这样 start 后立刻 stop 的
        # 取消请求不会被 run() 入口重新清除。
        self._stop_event.clear()
        self._serial = ser

    @staticmethod
    def _framing_times(ser):
        """按当前串口帧格式计算帧间隙和最长保持时间。"""
        try:
            baud = max(1, int(ser.baudrate))
        except (TypeError, ValueError, AttributeError):
            baud = 115200
        try:
            data_bits = int(ser.bytesize)
        except (TypeError, ValueError, AttributeError):
            data_bits = 8
        try:
            stop_bits = float(ser.stopbits)
        except (TypeError, ValueError, AttributeError):
            stop_bits = 1.0
        parity = getattr(ser, "parity", "N")
        parity_bits = 0 if parity in ("N", b"N", serial.PARITY_NONE) else 1
        bits_per_char = 1 + data_bits + parity_bits + stop_bits
        char_time = bits_per_char / baud
        gap = max(FRAME_GAP_S, char_time * 2.0)
        # 时间兜底也必须覆盖一整帧；否则 300/1200/9600 等低波特率下，
        # 固定 50ms 会在一帧尚未传完时被强制切断。
        hold = max(FRAME_MAX_HOLD_S, char_time * FRAME_MAX_BYTES)
        return gap, hold

    def _wait_serial_gap(self, ser, gap_s=None) -> bool:
        """高精度等待帧间隙: 忙等 FRAME_GAP_S 内无新字节则返回 True(帧结束)。

        Windows 的 time.sleep 精度仅 ~15.6ms, 无法满足 1ms 级等待,
        必须用忙等 (monotonic + in_waiting 轮询) 才能精确捕捉帧间空隙。
        """
        deadline = time.monotonic() + (
            FRAME_GAP_S if gap_s is None else gap_s)
        while (self._running
               and not self._stop_event.is_set()
               and time.monotonic() < deadline):
            if ser.in_waiting > 0:
                return False
        return not self._stop_event.is_set() and self._running

    def _read_frame(self, ser) -> bytes:
        """从串口读取一帧数据 (按帧间隙分帧)。

        - read(1) 阻塞等待首字节: 数据到达立即返回, 低延迟
        - 帧内字节通过 in_waiting 批量取走, 减少系统调用
        - 缓冲读空后忙等 FRAME_GAP_S, 无新字节则确认帧结束
        - 超过 FRAME_MAX_BYTES / FRAME_MAX_HOLD_S 强制输出, 防止高频心跳流无限合并
        - 独立发送的帧之间天然存在间隙, 据此拆开驱动合并的多帧
        """
        first = ser.read(1)
        if not first:
            return b""
        gap_s, hold_s = self._framing_times(ser)
        chunks = [first]
        total = 1
        t0 = time.monotonic()
        while self._running and not self._stop_event.is_set():
            # 读尽当前缓冲 (帧内字节)
            while True:
                n = ser.in_waiting
                if n <= 0:
                    break
                data = ser.read(n)
                chunks.append(data)
                total += len(data)
            # 强制切分保护: 持续数据流时按字节数/时间切开
            if total >= FRAME_MAX_BYTES or time.monotonic() - t0 >= hold_s:
                break
            # 忙等帧间隙确认 (精确, 不受 sleep 精度影响)
            if self._wait_serial_gap(ser, gap_s):
                break
        return b"".join(chunks)

    def run(self):
        self._running = True
        while self._running and not self._stop_event.is_set():
            ser = self._serial
            if ser and ser.is_open:
                try:
                    data = self._read_frame(ser)
                    if data:
                        self.data_received.emit(data)
                except serial.SerialException as e:
                    self._running = False
                    self.error_occurred.emit(str(e))
                    if not self._stopping:
                        self.disconnected.emit(str(e))
                    break
            elif ser is not None:
                self._running = False
                if not self._stopping:
                    message = "串口已关闭"
                    self.error_occurred.emit(message)
                    self.disconnected.emit(message)
                break
            else:
                self.msleep(5)

    def stop(self):
        self._stopping = True
        self._running = False
        self._stop_event.set()
        self.wait(1500)
        self._stopping = False


class TCPServerWorker(QThread):
    """TCP 服务器 -- select 1ms 超时, 不忙等"""
    client_connected = Signal(str, int)
    client_disconnected = Signal(str, int)
    data_received = Signal(bytes)
    error_occurred = Signal(str)
    log_message = Signal(str)
    started = Signal(int)
    start_failed = Signal(str)

    def __init__(self):
        super().__init__()
        self._port = 0
        self._running = False
        self._server: socket.socket | None = None
        self._clients: list[socket.socket] = []
        self._client_addrs: dict[int, tuple[str, int]] = {}
        self._buf_size = 4096
        # 客户端超时 (秒): 超过这么久未收到任何数据则判定为死连接 (拔网线等场景)
        # 0 = 禁用超时检测
        self._client_timeout_s = 30.0
        # {id(client): 最后收到数据的时间戳}
        self._last_rx: dict = {}
        # 是否正在主动关闭服务器. 该期间内清理客户端不发 client_* / log_message,
        # 否则会覆盖主线程已经设置好的"未连接"状态文字和状态栏消息.
        self._stopping = False

    def configure(self, port: int):
        self._port = port

    def set_client_timeout(self, seconds: float):
        """设置客户端无活动超时 (秒). 0 = 禁用."""
        self._client_timeout_s = float(seconds)

    @property
    def client_count(self) -> int:
        return len(self._clients)

    @property
    def client_addresses(self):
        return list(self._client_addrs.values())

    def send(self, data: bytes):
        dead = []
        sent = 0
        for c in self._clients:
            try:
                c.sendall(data)
                sent += 1
            except Exception:
                dead.append(c)
        for c in dead:
            self._remove_client(c)
        return sent

    def run(self):
        self._running = True
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            # Windows 的 SO_REUSEADDR 允许两个进程同时绑定同一端口，
            # 会让“端口已占用”检测失效。监听端使用独占地址，确保失败可感知。
            self._server.setsockopt(
                socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.settimeout(0.5)
        try:
            self._server.bind(("0.0.0.0", self._port))
            self._server.listen(5)
            self.log_message.emit("TCP server listening on port {}".format(self._port))
            self.started.emit(self._port)
        except Exception as e:
            message = "Server start failed: {}".format(e)
            self._running = False
            self.error_occurred.emit(message)
            self.start_failed.emit(message)
            self._cleanup()
            return

        while self._running:
            try:
                client, addr = self._server.accept()
                client.setblocking(False)
                # 禁用 Nagle: 避免小包(帧)被内核合并, 保留帧间间隙
                try:
                    client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                except Exception:
                    pass
                self._clients.append(client)
                self._client_addrs[id(client)] = (addr[0], addr[1])
                self._last_rx[id(client)] = time.monotonic()
                self.client_connected.emit(addr[0], addr[1])
                self.log_message.emit("Client connected: {}:{}".format(addr[0], addr[1]))
            except socket.timeout:
                pass
            except Exception:
                if not self._running:
                    break

            # 读取所有客户端数据 -- select 1ms 超时, 避免 CPU 空转
            if self._clients:
                socks = list(self._clients)
                try:
                    r, _, _ = select.select(socks, [], [], 0.001)
                    for c in r:
                        try:
                            first = c.recv(self._buf_size)
                            if first:
                                frame, alive = self._read_client_frame(c, first)
                                if frame:
                                    self.data_received.emit(frame)
                                if not alive:
                                    self._remove_client(c)
                                else:
                                    self._last_rx[id(c)] = time.monotonic()
                            else:
                                self._remove_client(c)
                        except Exception:
                            self._remove_client(c)
                except Exception:
                    pass

                # 超时扫描: 拔网线等场景客户端不会再发数据, 主动判定断开
                if self._client_timeout_s > 0:
                    now = time.monotonic()
                    for c in list(self._clients):
                        last = self._last_rx.get(id(c), now)
                        if now - last >= self._client_timeout_s:
                            addr = self._safe_peername(c)
                            addr_s = "{}:{}".format(*addr) if addr else "?"
                            self.log_message.emit(
                                "Client timeout (no data for {}s): {}".format(
                                    self._client_timeout_s, addr_s))
                            self._remove_client(c)

        self._cleanup()

    def _safe_peername(self, client):
        try:
            return client.getpeername()
        except Exception:
            return None

    def _read_client_frame(self, client, first: bytes):
        """从客户端 socket 读取一帧数据 (按帧间隙分帧)。

        - 读尽当前可读缓冲 (帧内数据)
        - 缓冲读空后等待 FRAME_GAP_S, 无新数据则确认帧结束
        - 超过 FRAME_MAX_BYTES / FRAME_MAX_HOLD_S 强制输出, 防止持续数据流无限合并
        - 返回 (frame_bytes, still_alive)
        """
        chunks = [first]
        total = len(first)
        t0 = time.monotonic()
        while True:
            # 读尽当前缓冲
            while True:
                try:
                    data = client.recv(self._buf_size)
                    if not data:
                        return b"".join(chunks), False
                    chunks.append(data)
                    total += len(data)
                except BlockingIOError:
                    break
            # 强制切分保护
            if total >= FRAME_MAX_BYTES or time.monotonic() - t0 >= FRAME_MAX_HOLD_S:
                break
            # 等待帧间隙确认
            r, _, _ = select.select([client], [], [], FRAME_GAP_S)
            if not r:
                break
        return b"".join(chunks), True

    def _remove_client(self, client: socket.socket):
        if client in self._clients:
            self._clients.remove(client)
            self._last_rx.pop(id(client), None)
            addr = self._client_addrs.pop(id(client), None)
            # 主动关闭服务器时清理客户端不应发信号 (会覆盖 UI 的"未连接"状态).
            if not self._stopping:
                addr = addr or self._safe_peername(client) or ("", 0)
                self.client_disconnected.emit(addr[0], addr[1])
                self.log_message.emit(
                    "Client disconnected: {}:{}".format(addr[0], addr[1]))
            try:
                client.close()
            except Exception:
                pass

    def _cleanup(self):
        for c in list(self._clients):
            self._remove_client(c)
        if self._server:
            try:
                self._server.close()
            except Exception:
                pass
            self._server = None

    def stop(self):
        # 标记为主动关闭服务器. 后续 _cleanup() 中清理客户端时不会发 client_* / log_message
        # 信号, 避免覆盖主线程已设置好的"未连接"状态.
        self._stopping = True
        self._running = False
        self.wait(1000)
        self._cleanup()
        # 重置标志, 让该 worker 再次启动时表现正常.
        self._stopping = False


class TCPClientWorker(QThread):
    """TCP 客户端 -- select 1ms 超时; 首次连接失败自动重试, 服务器后启动也能连上"""
    connected = Signal(str, int)
    disconnected = Signal()
    connect_failed = Signal(str)
    data_received = Signal(bytes)
    error_occurred = Signal(str)
    log_message = Signal(str)

    def __init__(self):
        super().__init__()
        self._host = ""
        self._port = 0
        # TCP 客户端本地端口. 0 表示由系统自动分配 (默认), 此时连接后 getsockname()
        # 读到的是系统分配的临时端口, 与远端端口无关. 指定非 0 时主动 bind 到该端口.
        self._local_port = 0
        self._running = False
        self._sock: socket.socket | None = None
        self._buf_size = 4096
        # 连接成功后才置 True. 连接未建立完成时 send() 不触碰 socket,
        # 避免并发 sendall 干扰正在进行的 connect (导致"一点发送就断").
        self._connected = False
        # 单次 connect 超时(秒) 与 失败重试间隔(秒): 数值小, 保证 stop() 能及时生效
        self._connect_timeout_s = 1.0
        self._retry_interval_s = 1.0
        # "尚未连接"提示限频时间戳: 重复发送/循环 tick 高频触发时不刷屏
        self._last_notify_s = 0.0

    def configure(self, host: str, port: int, local_port: int = 0):
        self._host = host
        self._port = port
        self._local_port = local_port

    @property
    def is_connected(self) -> bool:
        """是否已真正建立连接 (供 UI 判断"连接中/未连上"时禁止发送)"""
        return self._connected

    def send(self, data: bytes):
        if not (self._connected and self._sock):
            # 连接尚未建立完成: 不发送, 不影响重连流程. 限频提示避免重复发送时刷屏.
            now = time.monotonic()
            if now - self._last_notify_s >= 1.0:
                self._last_notify_s = now
                self.log_message.emit("尚未连接, 发送已忽略")
            return False
        try:
            self._sock.sendall(data)
            return True
        except Exception as e:
            # 发送失败意味着连接不可继续使用；关闭 socket 并通知 UI，
            # 避免界面继续显示“已连接”以及重复发送时反复报同一个错。
            self._connected = False
            self.error_occurred.emit("Send failed: {}".format(e))
            try:
                self._sock.close()
            except Exception:
                pass
            self.disconnected.emit()
            return False

    def _sleep_interruptible(self, seconds: float):
        """分段睡眠: 可被 stop() 立即打断"""
        end = time.monotonic() + seconds
        while self._running and time.monotonic() < end:
            time.sleep(0.05)

    def run(self):
        self._running = True
        self._connected = False
        # ---- 首次连接: 失败自动重试, 直到成功或用户断开 ----
        sock: socket.socket | None = None
        while self._running:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self._connect_timeout_s)
            # 若指定了本地端口, 主动 bind (常用于客户端需固定源端口的场景)
            if self._local_port > 0:
                try:
                    sock.bind(("0.0.0.0", self._local_port))
                except OSError as e:
                    message = "Bind local port {} failed: {}".format(
                        self._local_port, e)
                    self._running = False
                    self.error_occurred.emit(message)
                    try:
                        sock.close()
                    except Exception:
                        pass
                    self._cleanup()
                    # 连接尚未成功时不会走正常的远端断开分支；这里显式通知 UI
                    # 回滚“连接中”状态，否则按钮和状态栏会永久卡住。
                    self.connect_failed.emit(message)
                    return
            try:
                self.log_message.emit("Connecting to {}:{}...".format(self._host, self._port))
                sock.connect((self._host, self._port))
                break
            except Exception as e:
                try:
                    sock.close()
                except Exception:
                    pass
                self.log_message.emit("连接失败: {}, 正在重试...".format(e))
                self._sleep_interruptible(self._retry_interval_s)

        if not self._running:
            self._cleanup()
            return

        # ---- 连接成功 ----
        self._sock = sock
        self._sock.setblocking(False)
        # 禁用 Nagle: 避免小包(帧)被内核合并, 保留帧间间隙
        try:
            self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except Exception:
            pass
        self._connected = True
        self.connected.emit(self._host, self._port)
        self.log_message.emit("Connected to {}:{}".format(self._host, self._port))

        # ---- 收发循环 ----
        while self._running:
            try:
                r, _, _ = select.select([self._sock], [], [], 0.001)
                if r:
                    first = self._sock.recv(self._buf_size)
                    if first:
                        frame, alive = self._read_frame(first)
                        if frame:
                            self.data_received.emit(frame)
                        if not alive:
                            self.log_message.emit("Remote disconnected")
                            self.disconnected.emit()
                            break
                    else:
                        self.log_message.emit("Remote disconnected")
                        self.disconnected.emit()
                        break
            except Exception as e:
                # 异常断开(如连接被重置): 必须通知 UI, 否则界面会一直停留在"已连接"
                self.log_message.emit("连接异常断开: {}".format(e))
                self.error_occurred.emit("Connection error: {}".format(e))
                self.disconnected.emit()
                break

        self._cleanup()

    def _read_frame(self, first: bytes):
        """从 socket 读取一帧数据 (按帧间隙分帧)。

        - 读尽当前可读缓冲 (帧内数据)
        - 缓冲读空后等待 FRAME_GAP_S, 无新数据则确认帧结束
        - 超过 FRAME_MAX_BYTES / FRAME_MAX_HOLD_S 强制输出, 防止持续数据流无限合并
        - 返回 (frame_bytes, still_alive)
        """
        chunks = [first]
        total = len(first)
        t0 = time.monotonic()
        while True:
            while True:
                try:
                    data = self._sock.recv(self._buf_size)
                    if not data:
                        return b"".join(chunks), False
                    chunks.append(data)
                    total += len(data)
                except BlockingIOError:
                    break
            if total >= FRAME_MAX_BYTES or time.monotonic() - t0 >= FRAME_MAX_HOLD_S:
                break
            r, _, _ = select.select([self._sock], [], [], FRAME_GAP_S)
            if not r:
                break
        return b"".join(chunks), True

    def _cleanup(self):
        self._connected = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def stop(self):
        self._running = False
        # connect 的 socket 超时是 1 秒，额外留出收尾时间，避免在
        # connect 尚未返回时主线程就开始关闭 socket。
        self.wait(1500)
        self._cleanup()

