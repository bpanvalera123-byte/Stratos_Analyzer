import sys
import os
import time
import ctypes
import numpy as np
import pyqtgraph as pg
from PyQt5 import QtWidgets, QtCore, QtGui

# --- [КОД ДВИЖКА ProfessionalRadioEngine ОСТАЕТСЯ ПРЕЖНИМ ИЗ ПРЕДЫДУЩЕГО ОТВЕТА] ---
# (Предположим, он импортирован или находится выше)

class StratosProV8(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.engine = ProfessionalRadioEngine() # Используем проф-движок
        self.init_ui()
        self.engine.on_data_package.connect(self.process_update)
        self.engine.start()

    def init_ui(self):
        self.setWindowTitle("STRATOS RF v8.0 | PROFESSIONAL OPERATOR INTERFACE")
        self.setMinimumSize(1300, 900)
        self.setStyleSheet("""
            QMainWindow { background-color: #050505; }
            QWidget { background-color: #050505; color: #00FF41; font-family: 'Consolas', 'Courier New'; }
            QTabWidget::pane { border: 1px solid #00FF41; top: -1px; }
            QTabBar::tab { background: #111; border: 1px solid #333; padding: 10px 20px; margin-right: 2px; }
            QTabBar::tab:selected { background: #00FF41; color: #000; border: 1px solid #00FF41; }
            QPushButton { border: 1px solid #00FF41; padding: 8px; background: #111; }
            QPushButton:hover { background: #004411; }
            QTextEdit { background: #000; border: 1px solid #111; color: #00FF41; }
        """)

        # Главный виджет с вкладками
        self.tabs = QtWidgets.QTabWidget()
        self.setCentralWidget(self.tabs)

        # 1. ВКЛАДКА: ТЕРМИНАЛ (РАБОЧАЯ ОБЛАСТЬ)
        self.tab_main = QtWidgets.QWidget()
        self.setup_main_tab()
        self.tabs.addTab(self.tab_main, "📡 ТЕРМИНАЛ")

        # 2. ВКЛАДКА: НАСТРОЙКИ
        self.tab_settings = QtWidgets.QWidget()
        self.setup_settings_tab()
        self.tabs.addTab(self.tab_settings, "⚙️ КОНФИГУРАЦИЯ")

        # 3. ВКЛАДКА: РУКОВОДСТВО И ПОМОЩЬ
        self.tab_help = QtWidgets.QWidget()
        self.setup_help_tab()
        self.tabs.addTab(self.tab_help, "📘 ИНФО-ЦЕНТР")

        self.statusBar().showMessage("СИСТЕМА ГОТОВА К РАБОТЕ")

    def setup_main_tab(self):
        layout = QtWidgets.QHBoxLayout(self.tab_main)
        
        # Панель быстрого управления (слева)
        side = QtWidgets.QVBoxLayout()
        side.addWidget(QtWidgets.QLabel("--- БЫСТРЫЙ ДОСТУП ---"))
        
        self.freq_box = QtWidgets.QDoubleSpinBox()
        self.freq_box.setRange(1.0, 6000.0)
        self.freq_box.setValue(2400.0)
        self.freq_box.setSuffix(" MHz")
        self.freq_box.valueChanged.connect(lambda v: setattr(self.engine, 'freq', v))
        side.addWidget(self.freq_box)

        self.scan_btn = QtWidgets.QPushButton("ЗАПУСК СКАНИРОВАНИЯ")
        self.scan_btn.setCheckable(True)
        self.scan_btn.toggled.connect(self.toggle_scan)
        side.addWidget(self.scan_btn)
        
        side.addStretch()
        self.stat_label = QtWidgets.QLabel("SDR: ОЖИДАНИЕ...")
        side.addWidget(self.stat_label)
        layout.addLayout(side, 1)

        # График спектра
        self.plot = pg.PlotWidget()
        self.curve = self.plot.plot(pen=pg.mkPen('#00FF41', width=1))
        self.plot.setYRange(-100, 20)
        layout.addWidget(self.plot, 4)

    def setup_settings_tab(self):
        layout = QtWidgets.QFormLayout(self.tab_settings)
        layout.setContentsMargins(50, 50, 50, 50)
        layout.setSpacing(20)

        title = QtWidgets.QLabel("ГЛОБАЛЬНЫЕ ПАРАМЕТРЫ HACKRF")
        title.setStyleSheet("font-size: 18px; font-weight: bold; margin-bottom: 20px;")
        layout.addRow(title)

        # Настройки усиления
        self.set_lna = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.set_lna.setRange(0, 40)
        self.set_lna.setValue(16)
        self.set_lna.valueChanged.connect(lambda v: setattr(self.engine, 'lna_gain', v))
        layout.addRow("Усиление ПЧ (LNA Gain, 0-40 dB):", self.set_lna)

        self.set_vga = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.set_vga.setRange(0, 62)
        self.set_vga.setValue(16)
        self.set_vga.valueChanged.connect(lambda v: setattr(self.engine, 'vga_gain', v))
        layout.addRow("Усиление НЧ (VGA Gain, 0-62 dB):", self.set_vga)

        self.set_amp = QtWidgets.QCheckBox("Аппаратный МШУ (RF Amp +14dB)")
        self.set_amp.toggled.connect(lambda v: setattr(self.engine, 'amp_enable', v))
        layout.addRow("Входной каскад:", self.set_amp)

        # Настройки алгоритма
        self.set_thresh = QtWidgets.QSpinBox()
        self.set_thresh.setRange(-120, 0)
        self.set_thresh.setValue(-40)
        self.set_thresh.valueChanged.connect(lambda v: setattr(self.engine, 'threshold', v))
        layout.addRow("Порог обнаружения (dB):", self.set_thresh)

        btn_zadig = QtWidgets.QPushButton("ПЕРЕУСТАНОВИТЬ ДРАЙВЕР (ZADIG)")
        btn_zadig.clicked.connect(self.run_zadig)
        layout.addRow("Сервис:", btn_zadig)

    def setup_help_tab(self):
        layout = QtWidgets.QVBoxLayout(self.tab_help)
        
        help_text = QtWidgets.QTextEdit()
        help_text.setReadOnly(True)
        help_text.setHtml("""
            <h2 style='color: #00FF41;'>РУКОВОДСТВО ОПЕРАТОРА STRATOS RF</h2>
            <hr>
            <h3>1. Начало работы</h3>
            <p>Убедитесь, что <b>HackRF One</b> подключен к порту USB 3.0. Если в строке статуса указано 'DEMO MODE', 
            проверьте драйвер через вкладку 'Конфигурация'.</p>
            
            <h3>2. Управление усилением</h3>
            <ul>
                <li><b>LNA (IF):</b> Регулирует чувствительность. Для поиска слабых сигналов ставьте 24-32.</li>
                <li><b>VGA (BB):</b> Регулирует амплитуду после фильтрации.</li>
                <li><b>AMP:</b> Включайте только при использовании внешних антенн на открытой местности.</li>
            </ul>
            
            <h3>3. Режим сканирования</h3>
            <p>В режиме 'SCAN', система автоматически переключает частоту каждые 3 секунды, если уровень сигнала 
            ниже установленного порога (Threshold).</p>
            
            <hr>
            <h2 style='color: #00FF41;'>ПОМОЩЬ И ТЕХПОДДЕРЖКА</h2>
            <p><b>Ошибка 'USB Bulk Transfer':</b> Недостаточно питания порта. Смените разъем.</p>
            <p><b>Фантомные пики:</b> Перегрузка приемника. Снизьте LNA Gain до 16 или выключите AMP.</p>
        """)
        layout.addWidget(help_text)

    # --- [ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ] ---
    def run_zadig(self):
        # Логика запуска Zadig из папки drivers
        pass

    def toggle_scan(self, state):
        self.engine.is_scanning = state
        self.scan_btn.setText("СТОП СКАНИРОВАНИЕ" if state else "ЗАПУСК СКАНИРОВАНИЯ")

    def process_update(self, pkg):
        self.curve.setData(pkg["psd"])
        self.stat_label.setText("SDR: АКТИВЕН" if not pkg["is_demo"] else "SDR: ДЕМО (ЭМУЛЯЦИЯ)")
        if self.engine.is_scanning:
            self.freq_box.blockSignals(True)
            self.freq_box.setValue(pkg["freq"])
            self.freq_box.blockSignals(False)

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    gui = StratosProV8()
    gui.show()
    sys.exit(app.exec_())
