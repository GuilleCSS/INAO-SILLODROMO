import sys
import json
from PyQt5.QtWidgets import QApplication, QMainWindow
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5 import uic

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
        
        for hx, hy, au45, conf, y_51, y_57 in stream_openface_csv(csv_file):
            estado_mirada = controller.process_frame(hx, hy, au45, conf, y_51, y_57)
            if estado_mirada:
                self.senal_actualizacion.emit(f"Estado: {estado_mirada}")

    def detener(self):
        if hasattr(self, 'proceso_of'):
            self.proceso_of.terminate()

class ControlCentral(QMainWindow):
    def __init__(self):
        super().__init__()
        uic.loadUi("interfaz.ui", self)
        
        # --- HACK DEFINITIVO: DESTRUIR LÍMITES DE QT DESIGNER ---
        # Recolectamos todos los botones que diseñaste
        botones = []
        if hasattr(self, 'btn_avanzar'): botones.append(self.btn_avanzar)
        if hasattr(self, 'btn_luz'): botones.append(self.btn_luz)
        if hasattr(self, 'btn_girar_izq'): botones.append(self.btn_girar_izq)
        if hasattr(self, 'btn_girar_der'): botones.append(self.btn_girar_der)
        if hasattr(self, 'btn_detener'): botones.append(self.btn_detener)
        
        # Forzamos a que su tamaño máximo sea infinito y los desvinculamos de layouts fantasma
        for btn in botones:
            btn.setMinimumSize(0, 0)
            btn.setMaximumSize(16777215, 16777215)
            btn.setParent(self.centralwidget)

        self.domotica = DomoticaController()

        if hasattr(self, 'btn_luz'):
            self.btn_luz.clicked.connect(self.domotica.encender_luz)
        if hasattr(self, 'btn_avanzar'):
            self.btn_avanzar.clicked.connect(self.domotica.avanzar)
        if hasattr(self, 'btn_detener'):
            self.btn_detener.clicked.connect(self.domotica.detener)
        if hasattr(self, 'btn_girar_izq'):
            self.btn_girar_izq.clicked.connect(self.domotica.girar_izquierda)
        if hasattr(self, 'btn_girar_der'):
            self.btn_girar_der.clicked.connect(self.domotica.girar_derecha)

        self.hilo = HiloProcesamiento()
        self.hilo.senal_actualizacion.connect(self.actualizar_label)
        self.hilo.start()

    # --- CONTROL TOTAL DE LA GEOMETRÍA ---
    def resizeEvent(self, event):
        super().resizeEvent(event)
        
        # Tomamos el ancho y alto real del monitor
        w = self.width()
        h = self.height()
        
        # Evitamos cálculos si la ventana está minimizada
        if w == 0 or h == 0:
            return
            
        h_tercio = h // 3
        
        # 1. Ajuste matemático exacto (sin huecos grises)
        if hasattr(self, 'btn_avanzar'):
            self.btn_avanzar.setGeometry(0, 0, w, h_tercio)
        if hasattr(self, 'btn_luz'):
            self.btn_luz.setGeometry(0, h_tercio * 2, w, h - (h_tercio * 2))
        if hasattr(self, 'btn_girar_izq'):
            self.btn_girar_izq.setGeometry(0, h_tercio, w // 2, h_tercio)
        if hasattr(self, 'btn_girar_der'):
            self.btn_girar_der.setGeometry(w // 2, h_tercio, w - (w // 2), h_tercio)
            
        # 2. Renderizado del círculo rojo
        if hasattr(self, 'btn_detener'):
            size = int(min(w, h) * 0.45) 
            self.btn_detener.setGeometry((w - size) // 2, (h - size) // 2, size, size)
            
            # Inyectamos el CSS puro
            self.btn_detener.setStyleSheet(f"""
                QPushButton {{
                    background-color: #E63946; 
                    color: white;
                    border-radius: {size // 2}px; 
                    border: 4px solid #900C3F;
                    font-size: 26px; 
                    font-weight: bold;
                }}
                QPushButton:hover {{ background-color: #FF4D4D; }}
            """)
            # Lo traemos al frente para que no se oculte
            self.btn_detener.raise_()

        # Aseguramos que el texto de estado sea visible
        if hasattr(self, 'label_estado'):
            self.label_estado.raise_()

    def actualizar_label(self, texto):
        if hasattr(self, 'label_estado'):
            self.label_estado.setText(texto)

    def closeEvent(self, event):
        self.hilo.detener()
        event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    ventana = ControlCentral()
    ventana.showFullScreen()
    sys.exit(app.exec_())