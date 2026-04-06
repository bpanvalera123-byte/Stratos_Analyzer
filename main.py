        #
import sys
import os
import time
import hashlib
import subprocess
import ctypes
import numpy as np
import cv2
import pyqtgraph as pg
from PyQt5 import QtWidgets, QtCore, QtGui
from scipy.signal import firwin, lfilter

# --- 1. АВТОНОМНАЯ ПОДГОТОВКА ОКРУЖЕНИЯ (LOCKED DLL LOADING) ---
def setup_io_environment():
    """Принудительно подтягивает локальные DLL из папки drivers."""
    if getattr(sys, 'frozen', False):
        root = sys._MEIPASS
    else:
        root = os.path.dirname(os.path.abspath(__file__))
    
    drv_path = os.path.normpath(os.path.join(root, "drivers"))
    
    if os.path.exists(drv_path):
        os.environ['PATH'] = drv_path + os.pathsep + os.environ['PATH']
        os.environ['SOAPY_SDR_ROOT'] = drv_path
        os.environ['SOAPY_SDR_PLUGIN_PATH'] = os.path.join(drv_path, "modules64")
        
        if hasattr(os, 'add_dll_directory'):
            try:
                os.add_dll_directory(drv_path)
            except Exception:
                pass

        # Принудительный прогруз рантайма VC++
        vc_libs = ["vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll", "concrt140.dll"]
        for dll in vc_libs:
            dll_full_path = os.path.join(drv_path, dll)
            if os.path.exists(dll_full_path):
                try:
                    ctypes.WinDLL(dll_full_path)
                except Exception:
                    pass
    return drv_path

# Инициализация путей
DRIVERS_DIR = setup_io_environment()

try:
    import SoapySDR
    from SoapySDR import *
    SDR_SUPPORTED = True
except Exception as e:
    print(f"🔴 Ошибка SDR модулей: {e}")
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
        except Exception:
            return "hwid_generic_v1"

    def wipe_system(self):
        if os.path.exists("data_record.db"):
            os.remove("data_record.db")
        self.settings.clear()
        QtWidgets.QMessageBox.critical(None, "SECURITY", "Access Denied. Local data wiped.")
        sys.exit()

    def authenticate(self, parent):
        current_hwid = self.get_hwid()
        saved_hwid = self.settings.value("hwid_token")
        fails = int(self.settings.value("fails", 0))

        if saved_hwid == current_hwid:
            return True
        if fails >= self.max_fails:
            self.wipe_system()

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

# --- 3. РАДИО-ДВИЖОК ---
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
        self.freq = 2400.0
        self.gain = 16
        self.threshold = -25
        self.is_scanning = False
        self.lock_duration = 5.0
        self.last_lock_time = 0
        self.scan_step = 20.0

    def run(self):
        if SDR_SUPPORTED:
            try:
                self.device = SoapySDR.Device(dict(driver="hackrf"))
                self.device.setSampleRate(SOAPY_SDR_RX, 0, 10e6)
                self.rx_stream = self.device.setupStream(SOAPY_SDR_RX, "CF32")
                self.device.activateStream(self.rx_stream)
                self.is_demo = False
            except:
                self.is_demo = True

        buf = np.zeros(16384, dtype=np.complex64)
        while self.running:
            if not self.is_demo and self.device:
                try:
                    self.device.setFrequency(SOAPY_SDR_RX, 0, self.freq * 1e6)
                    self.device.setGain(SOAPY_SDR_RX, 0, "LNA", self.gain)
                    sr = self.device.readStream(self.rx_stream, [buf], len(buf), timeoutUs=50000)
                    if sr.ret > 0:
                        data = buf
                    else: continue
                except:
                    self.is_demo = True
                    continue
            else:
                time.sleep(0.04)
                data = np.random.normal(0, 0.01, 16384) + 1j*np.random.normal(0, 0.01, 16384)

            psd = 20 * np.log10(np.abs(np.fft.fftshift(np.fft.fft(data))) + 1e-9)
            peak = np.max(psd)
            detected = peak > self.threshold
            
            if self.is_scanning and not detected:
                if (time.time() - self.last_lock_time) > self.lock_duration:
                    self.freq += self.scan_step
                    if self.freq > 6000: self.freq = 1.0
                    self.on_freq_changed.emit(self.freq)
            elif detected:
                self.last_lock_time = time.time()

            self.on_spec.emit(psd[::16], detected)
            self.on_stat.emit(36.6, self.is_demo)
            
            img = np.zeros((480, 640, 3), dtype=np.uint8)
            color = (0, 255, 0) if detected else (0, 120, 0)
            cv2.putText(img, f"{'LOCKED' if detected else 'SCANNING'} | {self.freq:.2f} MHz", 
                        (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
            self.on_frame.emit(img)

    def stop(self):
        self.running = False
        self.wait()

# --- 4. ИНТЕРФЕЙС ---
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
        self.setMinimumSize(1200, 800)

        main_w = QtWidgets.QWidget()
        self.setCentralWidget(main_w)
        lay = QtWidgets.QHBoxLayout(main_w)

        # Панель инструментов
        side = QtWidgets.QVBoxLayout()
        side.addWidget(QtWidgets.QLabel("--- SYSTEM ---"))
        
        # Кнопка Zadig
        self.zadig_btn = QtWidgets.QPushButton("🛠 INSTALL USB DRIVER")
        self.zadig_btn.setStyleSheet("background: #111; border: 1px solid #00ff41; padding: 5px;")
        self.zadig_btn.clicked.connect(self.run_zadig)
        side.addWidget(self.zadig_btn)
        
        side.addSpacing(20)
        
        self.f_val = QtWidgets.QDoubleSpinBox()
        self.f_val.setRange(1.0, 10000.0)
        self.f_val.setValue(2400.0)
        self.f_val.valueChanged.connect(lambda v: setattr(self.engine, 'freq', v))
        side.addWidget(QtWidgets.QLabel("FREQ (MHz):"))
        side.addWidget(self.f_val)

        self.scan_btn = QtWidgets.QPushButton("START SCANNING")
        self.scan_btn.setCheckable(True)
        self.scan_btn.toggled.connect(self.toggle_scan)
        side.addWidget(self.scan_btn)

        side.addStretch()
        self.stat_lab = QtWidgets.QLabel("STATUS: READY")
        side.addWidget(self.stat_lab)
        lay.addLayout(side, 1)

        # Графика
        v_lay = QtWidgets.QVBoxLayout()
        self.view = QtWidgets.QLabel()
        v_lay.addWidget(self.view)
        
        self.plot = pg.PlotWidget()
        self.curve = self.plot.plot(pen=pg.mkPen('#00ff41'))
        self.plot.setYRange(-100, 20)
        v_lay.addWidget(self.plot)
        lay.addLayout(v_lay, 4)

    def run_zadig(self):
        """Запуск Zadig из папки drivers."""
        zadig_path = os.path.join(DRIVERS_DIR, "Zadig.exe")
        if os.path.exists(zadig_path):
            try:
                # Запуск с правами администратора
                ctypes.windll.shell32.ShellExecuteW(None, "runas", zadig_path, None, None, 1)
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "Error", f"Could not start Zadig: {e}")
        else:
            QtWidgets.QMessageBox.critical(self, "Error", f"Zadig.exe not found in drivers folder!")

    def toggle_scan(self, state):
        self.engine.is_scanning = state
        self.scan_btn.setText("STOP SCAN" if state else "START SCAN")

    def update_video(self, img):
        h, w, c = img.shape
        qimg = QtGui.QImage(img.data, w, h, w*c, QtGui.QImage.Format_RGB888)
        self.view.setPixmap(QtGui.QPixmap.fromImage(qimg))

    def update_spectrum(self, data, detected):
        self.curve.setData(data)
        self.curve.setPen(pg.mkPen('#ff3131' if detected else '#00ff41'))

    def update_status(self, temp, is_demo):
        mode = "[DEMO]" if is_demo else "[HARDWARE]"
        self.stat_lab.setText(f"MODE: {mode}\nTEMP: {temp:.1f}°C")

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = StratosPro()
    window.show()
    sys.exit(app.exec_())
