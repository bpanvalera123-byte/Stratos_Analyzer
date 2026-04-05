# Stratos_Analyzerimport sys
import os
import time
import hashlib
import subprocess
import urllib.request
import winreg
import numpy as np
import cv2
import pyqtgraph as pg
from PyQt5 import QtWidgets, QtCore, QtGui
from scipy.signal import firwin, lfilter

# --- 1. АВТО-ПОДГОТОВКА СИСТЕМЫ (VISUAL C++) ---
def check_and_install_vc_redist():
    """Проверяет наличие Visual C++ 2015-2022 и ставит его, если нужно."""
    vcredist_url = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
    reg_path = r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64"
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reg_path)
        winreg.CloseKey(key)
    except FileNotFoundError:
        try:
            print("🚀 Загрузка системных компонентов Microsoft...")
            urllib.request.urlretrieve(vcredist_url, "vc_redist_install.exe")
            print("📦 Запуск тихой установки...")
            subprocess.run(["vc_redist_install.exe", "/passive", "/norestart"], check=True)
            os.remove("vc_redist_install.exe")
        except Exception as e:
            print(f"⚠️ Ошибка авто-установки: {e}")

def setup_io_environment():
    check_and_install_vc_redist()
    root = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
    drv_path = os.path.join(root, "drivers")
    if os.path.exists(drv_path):
        os.environ['SOAPY_SDR_ROOT'] = drv_path
        os.environ['PATH'] = drv_path + os.pathsep + os.environ['PATH']
        if hasattr(os, 'add_dll_directory'):
            try: os.add_dll_directory(drv_path)
            except: pass

setup_io_environment()

try:
    import SoapySDR
    from SoapySDR import *
    SDR_SUPPORTED = True
except:
    SDR_SUPPORTED = False

# --- 2. СИСТЕМА БЕЗОПАСНОСТИ (HWID + PASS) ---
class SecurityCore:
    def __init__(self):
        self.settings = QtCore.QSettings("SystemVendor", "NetworkAnalyzer")
        self.master_hash = "64f9f74786419736f3320c978e8d89e5352613d9692488880654160453303866" # 52546808
        self.max_fails = 10

    def get_hwid(self):
        try:
            cmd = "wmic csproduct get uuid"
            uuid = subprocess.check_output(cmd, shell=True).decode().split('\n')[1].strip()
            return hashlib.sha256(uuid.encode()).hexdigest()
        except: return "hwid_generic_v1"

    def wipe_system(self):
        """Самоликвидация данных."""
        if os.path.exists("data_record.db"): os.remove("data_record.db")
        self.settings.clear()
        QtWidgets.QMessageBox.critical(None, "SECURITY", "Access Denied. Local data wiped.")
        sys.exit()

    def authenticate(self, parent):
        current_hwid = self.get_hwid()
        saved_hwid = self.settings.value("hwid_token")
        fails = int(self.settings.value("fails", 0))

        if saved_hwid == current_hwid: return True
        if fails >= self.max_fails: self.wipe_system()

        while fails < self.max_fails:
            key, ok = QtWidgets.QInputDialog.getText(parent, "🛡️ System Activation", 
                                                    f"Enter Key ({fails+1}/{self.max_fails}):", 
                                                    QtWidgets.QLineEdit.Password)
            if not ok: sys.exit()
            if hashlib.sha256(key.encode()).hexdigest() == self.master_hash:
                self.settings.setValue("hwid_token", current_hwid)
                self.settings.setValue("fails", 0)
                return True
            else:
                fails += 1
                self.settings.setValue("fails", fails)
                if fails >= self.max_fails: self.wipe_system()
        sys.exit()

# --- 3. РАДИО-ДВИЖОК (SCANNER + DSP) ---
class RadioEngine(QtCore.QThread):
    on_frame = QtCore.pyqtSignal(np.ndarray)
    on_spec = QtCore.pyqtSignal(np.ndarray, bool)
    on_stat = QtCore.pyqtSignal(float, bool)
    on_freq_changed = QtCore.pyqtSignal(float)

    def __init__(self):
        super().__init__()
        self.running = True
        self.is_demo = True
        self.device = None
        
        # Настройки частот
        self.freq = 2400.0
        self.scan_start = 1.0
        self.scan_end = 10000.0
        self.scan_step = 20.0
        
        # Настройки приема
        self.gain = 16
        self.threshold = -25
        self.lock_duration = 5.0
        self.last_lock_time = 0
        self.is_scanning = False
        
        # DSP и Запись
        self.use_lpf = True
        self.use_agc = True
        self.is_recording = False
        self.raw_out = None

    def run(self):
        if SDR_SUPPORTED:
            try:
                self.device = SoapySDR.Device(dict(driver="hackrf"))
                self.device.setSampleRate(SOAPY_SDR_RX, 0, 10e6)
                self.rx_stream = self.device.setupStream(SOAPY_SDR_RX, "CF32")
                self.device.activateStream(self.rx_stream)
                self.is_demo = False
            except: self.is_demo = True

        buf = np.zeros(16384, dtype=np.complex64)
        lpf_taps = firwin(32, 0.25)

        while self.running:
            if not self.is_demo and self.device:
                self.device.setFrequency(SOAPY_SDR_RX, 0, self.freq * 1e6)
                self.device.setGain(SOAPY_SDR_RX, 0, "LNA", self.gain)
                sr = self.device.readStream(self.rx_stream, [buf], len(buf), timeoutUs=50000)
                if sr.ret > 0:
                    data = buf
                    try: temp = float(self.device.readSensor("active_board_temp"))
                    except: temp = 0.0
                else: continue
            else:
                time.sleep(0.04)
                data = np.random.normal(0, 0.01, 16384) + 1j*np.random.normal(0, 0.01, 16384)
                temp = 36.6

            # DSP Обработка
            if self.use_lpf: data = lfilter(lpf_taps, 1.0, data)
            if self.use_agc:
                avg = np.mean(np.abs(data))
                if avg > 0: data /= (avg * 2)

            # Запись IQ
            if self.is_recording and self.raw_out:
                data.astype(np.complex64).tofile(self.raw_out)

            # Спектральный анализ
            psd = 20 * np.log10(np.abs(np.fft.fftshift(np.fft.fft(data))) + 1e-9)
            peak = np.max(psd)
            detected = peak > self.threshold
            
            # Логика сканера
            if self.is_scanning:
                if detected:
                    self.last_lock_time = time.time()
                elif (time.time() - self.last_lock_time) > self.lock_duration:
                    self.freq += self.scan_step
                    if self.freq > self.scan_end: self.freq = self.scan_start
                    self.on_freq_changed.emit(self.freq)

            self.on_spec.emit(psd[::16], detected)
            self.on_stat.emit(temp, self.is_demo)
            
            # Генерация видеозаглушки
            img = np.zeros((480, 640, 3), dtype=np.uint8)
            status_color = (0, 255, 0) if detected else (0, 120, 0)
            cv2.putText(img, f"{'LOCKED' if detected else 'SCANNING'} | {self.freq:.2f} MHz", 
                        (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, status_color, 2)
            self.on_frame.emit(img)

    def stop(self):
        self.running = False
        if self.device: self.device.closeStream(self.rx_stream)
        if self.raw_out: self.raw_out.close()
        self.wait()

# --- 4. ОСНОВНОЙ ИНТЕРФЕЙС ---
class StratosPro(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.security = SecurityCore()
        if not self.security.authenticate(self): sys.exit()
        
        self.engine = RadioEngine()
        self.init_ui()
        
        self.engine.on_frame.connect(self.update_video)
        self.engine.on_spec.connect(self.update_spectrum)
        self.engine.on_stat.connect(self.update_status)
        self.engine.on_freq_changed.connect(self.f_val.setValue)
        self.engine.start()

    def init_ui(self):
        self.setWindowTitle("STRATOS RF ANALYZER v7.0 [PRO-LINK]")
        self.setStyleSheet("background: #050505; color: #00ff41; font-family: Consolas;")
        self.setMinimumSize(1300, 900)

        main_w = QtWidgets.QWidget()
        self.setCentralWidget(main_w)
        lay = QtWidgets.QHBoxLayout(main_w)

        # Боковая панель
        side = QtWidgets.QVBoxLayout()
        
        # Группа: Настройки приема
        g_rx = self.create_group("📡 ПРИЕМНИК")
        self.f_val = self.create_spin(1, 10000, 2400)
        self.f_val.valueChanged.connect(lambda v: setattr(self.engine, 'freq', v))
        g_rx.layout().addWidget(QtWidgets.QLabel("ЧАСТОТА (MHz):"))
        g_rx.layout().addWidget(self.f_main := self.f_val)
        side.addWidget(g_rx)

        # Группа: Границы сканирования
        g_scan = self.create_group("🔍 СКАНЕР (1-10000 MHz)")
        self.f_s = self.create_spin(1, 10000, 1)
        self.f_s.valueChanged.connect(lambda v: setattr(self.engine, 'scan_start', v))
        self.f_e = self.create_spin(1, 10000, 10000)
        self.f_e.valueChanged.connect(lambda v: setattr(self.engine, 'scan_end', v))
        
        g_scan.layout().addWidget(QtWidgets.QLabel("СТАРТ:"))
        g_scan.layout().addWidget(self.f_s)
        g_scan.layout().addWidget(QtWidgets.QLabel("СТОП:"))
        g_scan.layout().addWidget(self.f_e)
        
        self.btn_scan = QtWidgets.QPushButton("ЗАПУСТИТЬ ПОИСК")
        self.btn_scan.setCheckable(True)
        self.btn_scan.clicked.connect(self.toggle_scan)
        g_scan.layout().addWidget(self.btn_scan)
        side.addWidget(g_scan)

        # Группа: DSP и IQ
        g_dsp = self.create_group("⚙️ DSP И ЗАПИСЬ")
        cb_lpf = QtWidgets.QCheckBox("LPF Фильтр"); cb_lpf.setChecked(True)
        cb_lpf.toggled.connect(lambda v: setattr(self.engine, 'use_lpf', v))
        cb_agc = QtWidgets.QCheckBox("АРУ (AGC)"); cb_agc.setChecked(True)
        cb_agc.toggled.connect(lambda v: setattr(self.engine, 'use_agc', v))
        
        self.btn_rec = QtWidgets.QPushButton("ЗАПИСЬ RAW IQ")
        self.btn_rec.setCheckable(True)
        self.btn_rec.clicked.connect(self.toggle_record)
        
        g_dsp.layout().addWidget(cb_lpf)
        g_dsp.layout().addWidget(cb_agc)
        g_dsp.layout().addWidget(self.btn_rec)
        side.addWidget(g_dsp)

        side.addStretch()
        self.status_bar = QtWidgets.QLabel("SYSTEM READY")
        side.addWidget(self.status_bar)
        lay.addLayout(side, 1)

        # Главный экран
        work_view = QtWidgets.QVBoxLayout()
        self.scr = QtWidgets.QLabel(); self.scr.setStyleSheet("border: 2px solid #222; background: #000;")
        self.scr.setAlignment(QtCore.Qt.AlignCenter)
        
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('#050505')
        self.curve = self.plot_widget.plot(pen='#00ff41')
        
        work_view.addWidget(self.scr, 5)
        work_view.addWidget(self.plot_widget, 2)
        lay.addLayout(work_view, 4)

    def create_group(self, title):
        g = QtWidgets.QGroupBox(title)
        g.setStyleSheet("QGroupBox { border: 1px solid #333; margin-top: 10px; font-weight: bold; }")
        g.setLayout(QtWidgets.QVBoxLayout()); return g

    def create_spin(self, mi, ma, v):
        s = QtWidgets.QDoubleSpinBox(); s.setRange(mi, ma); s.setValue(v); s.setDecimals(2)
        s.setSuffix(" MHz"); return s

    def toggle_scan(self, state):
        self.engine.is_scanning = state
        self.btn_scan.setText("🛑 ОСТАНОВИТЬ" if state else "ЗАПУСТИТЬ ПОИСК")

    def toggle_record(self, state):
        if state:
            fname = f"iq_capture_{int(time.time())}.raw"
            self.engine.raw_out = open(fname, "wb")
            self.engine.is_recording = True
            self.btn_rec.setText("🔴 ИДЕТ ЗАПИСЬ...")
        else:
            self.engine.is_recording = False
            if self.engine.raw_out: self.engine.raw_out.close()
            self.btn_rec.setText("ЗАПИСЬ RAW IQ")

    def update_video(self, f):
        h, w, c = f.shape
        q_img = QtGui.QImage(f.data, w, h, w*c, QtGui.QImage.Format_RGB888)
        self.scr.setPixmap(QtGui.QPixmap.fromImage(q_img).scaled(self.scr.size(), QtCore.Qt.KeepAspectRatio))

    def update_spectrum(self, data, active):
        self.curve.setData(data)
        self.curve.setPen('#ff0000' if active else '#00ff41')

    def update_status(self, t, demo):
        mode = "DEMO (NO HW)" if demo else "HACKRF LIVE"
        self.status_bar.setText(f"MODE: {mode}\nTEMP: {t:.1f}°C")
        self.status_bar.setStyleSheet(f"color: {'#ffa500' if demo else '#00ff41'}; font-weight: bold;")

    def closeEvent(self, event):
        self.engine.stop(); event.accept()

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = StratosPro()
    window.show()
    sys.exit(app.exec_())
