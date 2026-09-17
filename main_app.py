import sys
import json
from PyQt5.QtWidgets import QApplication, QMainWindow, QLabel, QVBoxLayout, QWidget, QPushButton
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QFont

from modulos.openface_reader import lanzar_openface, find_generated_csv, stream_openface_csv
from modulos.gaze_controller import GazeStateController
from modulos.hardware_serial import DomoticaController

with open('config.json', 'r') as f:
    config = json.load(f)

class HiloProcesamiento(QThread):
    senal_actualizacion = pyqtSignal(str) 

    def run(self):
        self.proceso_of = lanzar_openface()
        self.senal_actualizacion.emit("Inicializando cámara y modelos...")
        
        csv_file = find_generated_csv(config["output_dir"])
        controller = GazeStateController()
        
        self.senal_actualizacion.emit("¡Sistema Activo! Leyendo bioseñales...")
        
        for gx, gy, au45, conf, y_51, y_57 in stream_openface_csv(csv_file):
            estado_mirada = controller.process_frame(gx, gy, au45, conf, y_51, y_57)
            if estado_mirada:
                self.senal_actualizacion.emit(f"Estado: {estado_mirada}")

    def detener(self):
        if hasattr(self, 'proceso_of'):
            self.proceso_of.terminate()

class ControlCentral(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Sillodromo 2026 - Panel de Control")
        self.setGeometry(100, 100, 400, 300)
        
        self.label_estado = QLabel("Esperando inicialización...", self)
        self.label_estado.setFont(QFont("Arial", 14))
        
        self.btn_luz = QPushButton("Encender Luz (Simulación Domótica)", self)
        
        layout = QVBoxLayout()
        layout.addWidget(self.label_estado)
        layout.addWidget(self.btn_luz)
        
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.domotica = DomoticaController()
        self.btn_luz.clicked.connect(self.domotica.encender_luz)

        self.hilo = HiloProcesamiento()
        self.hilo.senal_actualizacion.connect(self.actualizar_label)
        self.hilo.start()

    def actualizar_label(self, texto):
        self.label_estado.setText(texto)

    def closeEvent(self, event):
        self.hilo.detener()
        event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    ventana = ControlCentral()
    ventana.show()
    sys.exit(app.exec_())