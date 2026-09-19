import sys
import json
from PyQt5.QtWidgets import QApplication, QMainWindow
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5 import uic

from modulos.mediapipe_reader import generador_mediapipe
from modulos.gaze_controller import GazeStateController
from modulos.hardware_serial import DomoticaController
from modulos.yolo_security import HiloSeguridadYOLO
from modulos.voice_synth import hablar_en_segundo_plano

with open('config.json', 'r') as f:
    config = json.load(f)

class HiloProcesamiento(QThread):
    senal_actualizacion = pyqtSignal(str) 
    emergencia_activa = False # Nueva bandera para apagar el control facial

    def run(self):
        self.senal_actualizacion.emit("Inicializando MediaPipe (Modo Ligero)...")
        controller = GazeStateController()
        self.senal_actualizacion.emit("¡Sistema Activo! Leyendo bioseñales...")
        
        for hx, hy, au45, conf, y_51, y_57 in generador_mediapipe():
            # Si YOLO activó la alarma, ignoramos lo que haga el rostro
            if self.emergencia_activa:
                continue
                
            estado_mirada = controller.process_frame(hx, hy, au45, conf, y_51, y_57)
            if estado_mirada:
                self.senal_actualizacion.emit(f"Estado: {estado_mirada}")

    def detener(self):
        pass

class ControlCentral(QMainWindow):
    def __init__(self):
        super().__init__()
        uic.loadUi("interfaz.ui", self)
        
        botones = []
        if hasattr(self, 'btn_avanzar'): botones.append(self.btn_avanzar)
        if hasattr(self, 'btn_luz'): botones.append(self.btn_luz)
        if hasattr(self, 'btn_girar_izq'): botones.append(self.btn_girar_izq)
        if hasattr(self, 'btn_girar_der'): botones.append(self.btn_girar_der)
        if hasattr(self, 'btn_detener'): botones.append(self.btn_detener)
        
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

        # Índice 0 para que YOLO tome la cámara externa de tu setup
        self.hilo_yolo = HiloSeguridadYOLO(camera_index=0)
        self.hilo_yolo.senal_emergencia.connect(self.gestionar_emergencia)
        self.hilo_yolo.start()

    def gestionar_emergencia(self, hay_peligro):
        # Transmitimos la bandera al hilo de MediaPipe para bloquearlo o liberarlo
        self.hilo.emergencia_activa = hay_peligro 
        
        if hay_peligro:
            self.domotica.detener() # Envia el freno al hardware
            if hasattr(self, 'label_estado'):
                self.label_estado.setText("¡PELIGRO: OBSTÁCULO! FRENADO AUTOMÁTICO")
            hablar_en_segundo_plano("Alerta, obstáculo al frente")
        else:
            if hasattr(self, 'label_estado'):
                self.label_estado.setText("Camino libre. Reanudando...")
            hablar_en_segundo_plano("Camino libre")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        w = self.width()
        h = self.height()
        
        if w == 0 or h == 0: return
            
        h_tercio = h // 3
        
        if hasattr(self, 'btn_avanzar'):
            self.btn_avanzar.setGeometry(0, 0, w, h_tercio)
        if hasattr(self, 'btn_luz'):
            self.btn_luz.setGeometry(0, h_tercio * 2, w, h - (h_tercio * 2))
        if hasattr(self, 'btn_girar_izq'):
            self.btn_girar_izq.setGeometry(0, h_tercio, w // 2, h_tercio)
        if hasattr(self, 'btn_girar_der'):
            self.btn_girar_der.setGeometry(w // 2, h_tercio, w - (w // 2), h_tercio)
            
        if hasattr(self, 'btn_detener'):
            size = int(min(w, h) * 0.45) 
            self.btn_detener.setGeometry((w - size) // 2, (h - size) // 2, size, size)
            self.btn_detener.setStyleSheet(f"""
                QPushButton {{
                    background-color: #E63946; color: white;
                    border-radius: {size // 2}px; border: 4px solid #900C3F;
                    font-size: 26px; font-weight: bold;
                }}
                QPushButton:hover {{ background-color: #FF4D4D; }}
            """)
            self.btn_detener.raise_()

        if hasattr(self, 'label_estado'):
            self.label_estado.raise_()

    def actualizar_label(self, texto):
        if hasattr(self, 'label_estado'):
            self.label_estado.setText(texto)

    def closeEvent(self, event):
        self.hilo.detener()
        if hasattr(self, 'hilo_yolo'):
            self.hilo_yolo.detener()
        event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    ventana = ControlCentral()
    ventana.showFullScreen()
    sys.exit(app.exec_())