import sys
import json
from PyQt5.QtWidgets import QApplication, QMainWindow, QPushButton
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5 import uic

from modulos.openface_reader import lanzar_openface, find_generated_csv, stream_openface_csv
from modulos.gaze_controller import GazeStateController
from modulos.hardware_serial import DomoticaController
from modulos.voice_synth import hablar_en_segundo_plano

with open('config.json', 'r') as f:
    config = json.load(f)

class HiloProcesamiento(QThread):
    senal_actualizacion = pyqtSignal(str) 

    def run(self):
        self.proceso_of = lanzar_openface()
        self.senal_actualizacion.emit("Inicializando cámara y modelos de OpenFace...")
        
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
        
        botones = []
        if hasattr(self, 'btn_avanzar'): botones.append(self.btn_avanzar)
        if hasattr(self, 'btn_girar_izq'): botones.append(self.btn_girar_izq)
        if hasattr(self, 'btn_girar_der'): botones.append(self.btn_girar_der)
        if hasattr(self, 'btn_detener'): botones.append(self.btn_detener)
        
        if hasattr(self, 'btn_luz'): 
            self.btn_luz.hide()
            self.btn_luz.deleteLater()
        
        for btn in botones:
            btn.setMinimumSize(0, 0)
            btn.setMaximumSize(16777215, 16777215)
            btn.setParent(self.centralwidget)

        self.domotica = DomoticaController()

        # Conectamos los botones a las nuevas funciones con voz
        if hasattr(self, 'btn_avanzar'):
            self.btn_avanzar.clicked.connect(self.ejecutar_avanzar)
        if hasattr(self, 'btn_detener'):
            self.btn_detener.clicked.connect(self.ejecutar_detener)
        if hasattr(self, 'btn_girar_izq'):
            self.btn_girar_izq.clicked.connect(self.ejecutar_girar_izq)
        if hasattr(self, 'btn_girar_der'):
            self.btn_girar_der.clicked.connect(self.ejecutar_girar_der)

        # --- DICCIONARIO DE ESTADOS Y BOTONES PARA ALEXA ---
        self.estados_alexa = {
            "Ventilador 1": False, "Cafetera 1": False, "Secadora 1": False, 
            "Ventilador 2": False, "Alexa 2": False, "Cafetera 2": False
        }
        
        self.botones_alexa = []
        
        for nombre in self.estados_alexa.keys():
            btn = QPushButton(f"Encender\n{nombre}", self.centralwidget)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #2E86C1; color: white;
                    border: 2px solid #1B4F72; font-size: 20px; font-weight: bold;
                }
                QPushButton:hover { background-color: #3498DB; }
            """)
            btn.clicked.connect(lambda checked, n=nombre, b=btn: self.alternar_comando_alexa(n, b))
            self.botones_alexa.append(btn)

        self.hilo = HiloProcesamiento()
        self.hilo.senal_actualizacion.connect(self.actualizar_label)
        self.hilo.start()

    # --- NUEVAS FUNCIONES DE NAVEGACIÓN CON VOZ ---
    def ejecutar_avanzar(self):
        self.domotica.avanzar()
        hablar_en_segundo_plano("Avanzando")
        self.actualizar_label("Silla: Avanzando")

    def ejecutar_detener(self):
        self.domotica.detener()
        hablar_en_segundo_plano("Silla detenida")
        self.actualizar_label("Silla: Detenida")

    def ejecutar_girar_izq(self):
        self.domotica.girar_izquierda()
        hablar_en_segundo_plano("Girando a la izquierda")
        self.actualizar_label("Silla: Girando a la izquierda")

    def ejecutar_girar_der(self):
        self.domotica.girar_derecha()
        hablar_en_segundo_plano("Girando a la derecha")
        self.actualizar_label("Silla: Girando a la derecha")

    # --- FUNCIONES DE DOMÓTICA ---
    def alternar_comando_alexa(self, dispositivo, boton):
        estado_actual = self.estados_alexa[dispositivo]
        
        if estado_actual: 
            comando = f"Alexa, apaga {dispositivo}"
            nuevo_texto = f"Encender\n{dispositivo}"
            color_fondo = "#2E86C1"
            color_hover = "#3498DB"
            self.estados_alexa[dispositivo] = False
        else:
            comando = f"Alexa, enciende {dispositivo}"
            nuevo_texto = f"Apagar\n{dispositivo}"
            color_fondo = "#C0392B"
            color_hover = "#E74C3C"
            self.estados_alexa[dispositivo] = True

        boton.setText(nuevo_texto)
        boton.setStyleSheet(f"""
            QPushButton {{
                background-color: {color_fondo}; color: white;
                border: 2px solid #641E16; font-size: 20px; font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {color_hover}; }}
        """)

        hablar_en_segundo_plano(comando)
        if hasattr(self, 'label_estado'):
            self.label_estado.setText(f"Domótica: {comando}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        w = self.width()
        h = self.height()
        
        if w == 0 or h == 0: return
            
        h_tercio = h // 3
        
        if hasattr(self, 'btn_avanzar'):
            self.btn_avanzar.setGeometry(0, 0, w, h_tercio)
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

        y_base = h_tercio * 2
        alto_panel = h - y_base
        btn_w = w // 3
        btn_h = alto_panel // 2
        
        self.botones_alexa[0].setGeometry(0, y_base, btn_w, btn_h)
        self.botones_alexa[1].setGeometry(btn_w, y_base, btn_w, btn_h)
        self.botones_alexa[2].setGeometry(btn_w * 2, y_base, w - (btn_w * 2), btn_h)
        self.botones_alexa[3].setGeometry(0, y_base + btn_h, btn_w, alto_panel - btn_h)
        self.botones_alexa[4].setGeometry(btn_w, y_base + btn_h, btn_w, alto_panel - btn_h)
        self.botones_alexa[5].setGeometry(btn_w * 2, y_base + btn_h, w - (btn_w * 2), alto_panel - btn_h)

        for btn in self.botones_alexa:
            btn.raise_()
        
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