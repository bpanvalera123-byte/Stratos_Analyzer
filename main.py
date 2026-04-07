import sys
import os
import time
import ctypes
import numpy as np
import pyqtgraph as pg
from PyQt5 import QtWidgets, QtCore, QtGui

# --- 1. ПОДГОТОВКА ОКРУЖЕНИЯ ---
def setup_windows_environment():
    if getattr(sys, 'frozen', False):
        root = sys._MEIPASS
    else:
        root = os.path.dirname(os.path.abspath(__file__))
    
    drv_path = os.path.normpath(os.path.join(root, "drivers"))
    if os.path.exists(drv_path):
        if hasattr(os, 'add_dll_directory'):
            try:
                os.add_dll_directory(drv_path)
            except: pass
        os.environ['PATH'] = drv_path + os.pathsep + os.environ['PATH']
    return drv_path

DRIVERS_DIR = setup_windows_environment()

try:
    import SoapySDR
    from SoapySDR import *
    SDR_SUPPORTED = True
except ImportError:
    SDR_SUPPORTED = False

# --- 2. ЯДРО ОБРАБОТКИ (ДВИЖОК) ---
class ProfessionalRadioEngine(QtCore.QThread):
    on_data_package = QtCore.pyqtSignal(dict)
    on_error = QtCore.pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.running = True
        self.device = None
        self.stream = None
        
        # Параметры по умолчанию
        self.freq = 2400.0
        self.sample_rate = 10e6
        self.lna_gain = 16
        self.vga_gain = 16
        self.amp_enable = False
        self.is_scanning = False
        self.threshold = -45

    def init_sdr(self):
        if not SDR_SUPPORTED: return False
        try:
            results = SoapySDR.Device.enumerate(dict(driver="hackrf"))
            if not results: return False
            self.device = SoapySDR.Device(results[0])
            self.device.setSampleRate(SOAPY_SDR_RX, 0, self.sample_rate)
            self.stream = self.device.setupStream(SOAPY_SDR_RX, "CF32")
            self.device.activateStream(self.stream)
            return True
        except Exception as e:
            self.on_error.emit(f"Ошибка SDR: {e}")
            return False

    def run(self):
        self.setPriority(QtCore.QThread.TimeCriticalPriority)
        self.init_sdr()
        
        fft_size = 8192
        buf = np.zeros(fft_size, dtype=np.complex64)
        
        while self.running:
            if self.device and self.stream:
                try:
                    self.device.setFrequency(SOAPY_SDR_RX, 0, self.freq * 1e6)
                    self.device.setGain(SOAPY_SDR_RX, 0, "LNA", self.lna_gain)
                    self.device.setGain(SOAPY_SDR_RX, 0, "VGA", self.vga_gain)
                    self.device.setAntenna(SOAPY_SDR_RX, 0, "AMP" if self.amp_enable else "NONE")
                    
                    sr = self.device.readStream(self.stream, [buf], fft_size, timeoutUs=100000)
                    if sr.ret > 0:
                        data = buf
                    else: continue
                except:
                    self.device = None
                    continue
            else:
                # Режим эмуляции (Demo)
                time.sleep(0.04)
                data = np.random.normal(0, 0.005, fft_size) + 1j*np.random.normal(0, 0.005, fft_size)
                # Имитация сигнала
                if abs(self.freq - 2400) < 5:
                    t = np.arange(fft_size)
                    data += 0.05 * np.exp(1j * 2 * np.pi * 0.01 * t)

            # DSP
            windowed = data * np.blackman(fft_size)
            psd = 20 * np.log10(np.abs(np.fft.fftshift(np.fft.fft(windowed))) + 1e-12)
            
            peak = np.max(psd)
            detected = peak > self.threshold

            if self.is_scanning and not detected:
                self.freq += 10.0
                if self.freq > 6000: self.freq = 1.0

            self.on_data_package.emit({
                "psd": psd[::4], 
                "detected": detected,
                "freq": self.freq,
                "is_demo": self.device is None
            })

    def stop(self):
        self.running = False
        self.wait()

# --- 3. ИНТЕРФЕЙС ОПЕРАТОРА ---
class StratosProV8(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.engine = ProfessionalRadioEngine()
        self.init_ui()
        
        self.engine.on_data_package.connect(self.process_update)
        self.engine.on_error.connect(lambda e: self.statusBar().showMessage(e))
        self.engine.start()

    def init_ui(self):
        self.setWindowTitle("STRATOS RF v8.0 | PROFESSIONAL OPERATOR INTERFACE")
        self.setMinimumSize(1200, 800)
        self.setStyleSheet("""
            QMainWindow { background-color: #050505; }
            QWidget { background-color: #050505; color: #00FF41; font-family: 'Consolas'; }
            QTabWidget::pane { border: 1px solid #00FF41; }
            QTabBar::tab { background: #111; border: 1px solid #333; padding: 10px 20px; }
            QTabBar::tab:selected { background: #00FF41; color: #000; }
            QPushButton { border: 1px solid #00FF41; padding: 8px; background: #111; min-width: 100px; }
            QPushButton:hover { background: #004411; }
            QSlider::handle:horizontal { background: #00FF41; width: 18px; }
        """)

        self.tabs = QtWidgets.QTabWidget()
        self.setCentralWidget(self.tabs)

        # Вкладка 1: Терминал
        self.tab_main = QtWidgets.QWidget()
        self.setup_main_tab()
        self.tabs.addTab(self.tab_main, "📡 ТЕРМИНАЛ")

        # Вкладка 2: Конфигурация
        self.tab_settings = QtWidgets.QWidget()
        self.setup_settings_tab()
        self.tabs.addTab(self.tab_settings, "⚙️ КОНФИГУРАЦИЯ")

        # Вкладка 3: Инфо
        self.tab_help = QtWidgets.QWidget()
        self.setup_help_tab()
        self.tabs.addTab(self.tab_help, "📘 ИНФО-ЦЕНТР")

    def setup_main_tab(self):
        layout = QtWidgets.QHBoxLayout(self.tab_main)
        side = QtWidgets.QVBoxLayout()
        
        side.addWidget(QtWidgets.QLabel("ЧАСТОТА (MHz):"))
        self.freq_box = QtWidgets.QDoubleSpinBox()
        self.freq_box.setRange(1.0, 6000.0)
        self.freq_box.setValue(2400.0)
        self.freq_box.valueChanged.connect(lambda v: setattr(self.engine, 'freq', v))
        side.addWidget(self.freq_box)

        self.scan_btn = QtWidgets.QPushButton("СКАНИРОВАНИЕ")
        self.scan_btn.setCheckable(True)
        self.scan_btn.toggled.connect(self.toggle_scan)
        side.addWidget(self.scan_btn)
        
        side.addStretch()
        self.stat_label = QtWidgets.QLabel("SDR: ОЖИДАНИЕ")
        side.addWidget(self.stat_label)
        layout.addLayout(side, 1)

        self.plot = pg.PlotWidget()
        self.plot.setBackground('#000')
        self.curve = self.plot.plot(pen=pg.mkPen('#00FF41', width=1))
        self.plot.setYRange(-100, 10)
        layout.addWidget(self.plot, 4)

    def setup_settings_tab(self):
        layout = QtWidgets.QFormLayout(self.tab_settings)
        layout.setContentsMargins(40, 40, 40, 40)
        
        # Усиление
        self.s_lna = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.s_lna.setRange(0, 40)
        self.s_lna.setValue(16)
        self.s_lna.valueChanged.connect(lambda v: setattr(self.engine, 'lna_gain', v))
        layout.addRow("LNA Gain (IF):", self.s_lna)

        self.s_vga = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.s_vga.setRange(0, 62)
        self.s_vga.setValue(16)
        self.s_vga.valueChanged.connect(lambda v: setattr(self.engine, 'vga_gain', v))
        layout.addRow("VGA Gain (BB):", self.s_vga)

        self.c_amp = QtWidgets.QCheckBox("RF Amplifier (+14dB)")
        self.c_amp.toggled.connect(lambda v: setattr(self.engine, 'amp_enable', v))
        layout.addRow("МШУ:", self.c_amp)

        self.s_th = QtWidgets.QSpinBox()
        self.s_th.setRange(-100, 0)
        self.s_th.setValue(-45)
        self.s_th.valueChanged.connect(lambda v: setattr(self.engine, 'threshold', v))
        layout.addRow("Порог (dB):", self.s_th)

    def setup_help_tab(self):
        layout = QtWidgets.QVBoxLayout(self.tab_help)
        text = QtWidgets.QTextEdit()
        text.setReadOnly(True)
        text.setHtml("""
            <h2 style='color:#00FF41'>STRATOS RF - РУКОВОДСТВО</h2>
            <p><b>1. СКАНИРОВАНИЕ:</b> Нажмите кнопку на главной панели. Частота будет расти, пока не встретит сигнал выше Порога.</p>
            <p><b>2. УСИЛЕНИЕ:</b> Если спектр слишком шумный, уменьшите LNA Gain. Если сигнал слабый — включите RF Amplifier.</p>
            <p><b>3. ПОРОГ:</b> Регулирует чувствительность автоматического захвата частоты.</p>
        """)
        layout.addWidget(text)

    def toggle_scan(self, state):
        self.engine.is_scanning = state
        self.scan_btn.setText("СТОП" if state else "СКАНИРОВАНИЕ")

    def process_update(self, pkg):
        self.curve.setData(pkg["psd"])
        color = '#FF0000' if pkg["detected"] else '#00FF41'
        self.curve.setPen(pg.mkPen(color, width=1))
        
        self.stat_label.setText("SDR: HACKRF" if not pkg["is_demo"] else "SDR: DEMO")
        self.stat_label.setStyleSheet("color: #00FF41" if not pkg["is_demo"] else "color: #FFAA00")
        
        if self.engine.is_scanning:
            self.freq_box.blockSignals(True)
            self.freq_box.setValue(pkg["freq"])
            self.freq_box.blockSignals(False)

    def closeEvent(self, event):
        self.engine.stop()
        event.accept()

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = StratosProV8()
    window.show()
    sys.exit(app.exec_())
