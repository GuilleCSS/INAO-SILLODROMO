import sys
import json

from PyQt5.QtWidgets import QApplication, QMainWindow, QPushButton
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5 import uic

from modulos.openface_reader import (
    lanzar_openface,
    find_generated_csv,
    stream_openface_csv
)

from modulos.gaze_controller import GazeStateController
from modulos.hardware_serial import DomoticaController
from modulos.voice_synth import hablar_en_segundo_plano


# ============================================================
# CONFIGURACIÓN
# ============================================================

with open("config.json", "r") as f:
    config = json.load(f)


# ============================================================
# HILO DE OPENFACE
# ============================================================

class HiloProcesamiento(QThread):

    senal_actualizacion = pyqtSignal(str)

    def run(self):

        self.proceso_of = lanzar_openface()

        self.senal_actualizacion.emit(
            "Inicializando cámara y modelos de OpenFace..."
        )

        csv_file = find_generated_csv(
            config["output_dir"]
        )

        controller = GazeStateController()

        self.senal_actualizacion.emit(
            "¡Sistema Activo! Leyendo bioseñales..."
        )

        for hx, hy, au45, conf, y_51, y_57 in stream_openface_csv(csv_file):

            estado_mirada = controller.process_frame(
                hx,
                hy,
                au45,
                conf,
                y_51,
                y_57
            )

            if estado_mirada:

                self.senal_actualizacion.emit(
                    f"Estado: {estado_mirada}"
                )


    def detener(self):

        if hasattr(self, "proceso_of"):
            self.proceso_of.terminate()


# ============================================================
# VENTANA PRINCIPAL
# ============================================================

class ControlCentral(QMainWindow):

    def __init__(self):

        super().__init__()

        uic.loadUi(
            "interfaz.ui",
            self
        )


        # ====================================================
        # BOTONES ORIGINALES DE MOVIMIENTO
        # ====================================================

        botones = []

        if hasattr(self, "btn_avanzar"):
            botones.append(self.btn_avanzar)

        if hasattr(self, "btn_girar_izq"):
            botones.append(self.btn_girar_izq)

        if hasattr(self, "btn_girar_der"):
            botones.append(self.btn_girar_der)

        if hasattr(self, "btn_detener"):
            botones.append(self.btn_detener)


        # Eliminar botón antiguo de luz
        if hasattr(self, "btn_luz"):

            self.btn_luz.hide()
            self.btn_luz.deleteLater()


        for btn in botones:

            btn.setMinimumSize(0, 0)

            btn.setMaximumSize(
                16777215,
                16777215
            )

            btn.setParent(
                self.centralwidget
            )


        # ====================================================
        # CONTROL DEL HARDWARE
        # ====================================================

        self.domotica = DomoticaController()


        # ====================================================
        # BOTONES DE MOVIMIENTO
        # ====================================================

        if hasattr(self, "btn_avanzar"):

            self.btn_avanzar.clicked.connect(
                self.ejecutar_avanzar
            )


        if hasattr(self, "btn_detener"):

            self.btn_detener.clicked.connect(
                self.ejecutar_detener
            )


        if hasattr(self, "btn_girar_izq"):

            self.btn_girar_izq.clicked.connect(
                self.ejecutar_girar_izq
            )


        if hasattr(self, "btn_girar_der"):

            self.btn_girar_der.clicked.connect(
                self.ejecutar_girar_der
            )


        # ====================================================
        # DISPOSITIVOS DE ALEXA
        # ====================================================

        self.dispositivos_alexa = [

            ("Enchufe 2", "enchufe dos"),

            ("Enchufe 3", "enchufe tres"),

            ("Secadora 1", "secadora uno"),

            ("Ventilador 2", "ventilador dos"),

            ("Alexa 2", "Alexa dos"),

            ("Cafetera 2", "cafetera dos")

        ]


        # ====================================================
        # GUARDAMOS LOS PARES DE BOTONES
        # ====================================================

        self.botones_alexa = []


        # ====================================================
        # CREACIÓN DE LOS 12 BOTONES
        # ====================================================

        for nombre_visual, nombre_voz in self.dispositivos_alexa:

            # ------------------------------------------------
            # BOTÓN ENCENDER
            # ------------------------------------------------

            btn_encender = QPushButton(
                f"ENCENDER\n{nombre_visual}",
                self.centralwidget
            )

            self.estilo_boton_encender(
                btn_encender
            )


            # ------------------------------------------------
            # BOTÓN APAGAR
            # ------------------------------------------------

            btn_apagar = QPushButton(
                f"APAGAR\n{nombre_visual}",
                self.centralwidget
            )

            self.estilo_boton_apagar(
                btn_apagar
            )


            # ------------------------------------------------
            # CONECTAR ENCENDER
            # ------------------------------------------------

            btn_encender.clicked.connect(

                lambda checked,
                n=nombre_visual,
                voz=nombre_voz:

                self.encender_dispositivo(
                    n,
                    voz
                )
            )


            # ------------------------------------------------
            # CONECTAR APAGAR
            # ------------------------------------------------

            btn_apagar.clicked.connect(

                lambda checked,
                n=nombre_visual,
                voz=nombre_voz:

                self.apagar_dispositivo(
                    n,
                    voz
                )
            )


            # Guardamos ambos botones
            self.botones_alexa.append(
                (
                    btn_encender,
                    btn_apagar
                )
            )


        # ====================================================
        # OPENFACE
        # ====================================================

        self.hilo = HiloProcesamiento()

        self.hilo.senal_actualizacion.connect(
            self.actualizar_label
        )

        self.hilo.start()


    # ========================================================
    # ESTILO ENCENDER
    # ========================================================

    def estilo_boton_encender(self, boton):

        boton.setStyleSheet("""
            QPushButton {

                background-color: #1F4E79;

                color: white;

                border: 2px solid #163A5C;

                font-size: 24px;

                font-weight: bold;
            }

            QPushButton:hover {

                background-color: #2E75B6;
            }

            QPushButton:pressed {

                background-color: #163A5C;
            }
        """)


    # ========================================================
    # ESTILO APAGAR
    # ========================================================

    def estilo_boton_apagar(self, boton):

        boton.setStyleSheet("""
            QPushButton {

                background-color: #E4E3A9;

                color: #0B1F3A;

                border: 2px solid #0B1F3A;

                font-size: 24px;

                font-weight: bold;
            }

            QPushButton:hover {

                background-color: #F5F1E6;
            }

            QPushButton:pressed {

                background-color: #D1CF87;
            }
        """)


    # ========================================================
    # MOVIMIENTO DE SILLA
    # ========================================================

    def ejecutar_avanzar(self):

        self.domotica.avanzar()

        hablar_en_segundo_plano(
            "Avanzando"
        )

        self.actualizar_label(
            "Silla: Avanzando"
        )


    def ejecutar_detener(self):

        self.domotica.detener()

        hablar_en_segundo_plano(
            "Silla detenida"
        )

        self.actualizar_label(
            "Silla: Detenida"
        )


    def ejecutar_girar_izq(self):

        self.domotica.girar_izquierda()

        hablar_en_segundo_plano(
            "Girando a la izquierda"
        )

        self.actualizar_label(
            "Silla: Girando a la izquierda"
        )


    def ejecutar_girar_der(self):

        self.domotica.girar_derecha()

        hablar_en_segundo_plano(
            "Girando a la derecha"
        )

        self.actualizar_label(
            "Silla: Girando a la derecha"
        )


    # ========================================================
    # ENCENDER DISPOSITIVO
    # ========================================================

    def encender_dispositivo(
        self,
        nombre_visual,
        nombre_voz
    ):

        comando = (
            f"Alexa, enciende {nombre_voz}"
        )

        hablar_en_segundo_plano(
            comando
        )

        if hasattr(
            self,
            "label_estado"
        ):

            self.label_estado.setText(
                f"Encendiendo: {nombre_visual}"
            )


    # ========================================================
    # APAGAR DISPOSITIVO
    # ========================================================

    def apagar_dispositivo(
        self,
        nombre_visual,
        nombre_voz
    ):

        comando = (
            f"Alexa, apaga {nombre_voz}"
        )

        hablar_en_segundo_plano(
            comando
        )

        if hasattr(
            self,
            "label_estado"
        ):

            self.label_estado.setText(
                f"Apagando: {nombre_visual}"
            )


    # ========================================================
    # REDIMENSIONAMIENTO
    # ========================================================

    def resizeEvent(self, event):

        super().resizeEvent(event)

        w = self.width()
        h = self.height()

        if w == 0 or h == 0:
            return


        # ====================================================
        # DIVIDIR PANTALLA
        # ====================================================

        h_tercio = h // 3


        # ====================================================
        # AVANZAR
        # ====================================================

        if hasattr(
            self,
            "btn_avanzar"
        ):

            self.btn_avanzar.setGeometry(
                0,
                0,
                w,
                h_tercio
            )


        # ====================================================
        # GIRAR IZQUIERDA
        # ====================================================

        if hasattr(
            self,
            "btn_girar_izq"
        ):

            self.btn_girar_izq.setGeometry(
                0,
                h_tercio,
                w // 2,
                h_tercio
            )


        # ====================================================
        # GIRAR DERECHA
        # ====================================================

        if hasattr(
            self,
            "btn_girar_der"
        ):

            self.btn_girar_der.setGeometry(
                w // 2,
                h_tercio,
                w - (w // 2),
                h_tercio
            )


        # ====================================================
        # DETENER
        # ====================================================

        if hasattr(
            self,
            "btn_detener"
        ):

            size = int(
                min(w, h) * 0.45
            )

            self.btn_detener.setGeometry(
                (w - size) // 2,
                (h - size) // 2,
                size,
                size
            )


            self.btn_detener.setStyleSheet(
                f"""
                QPushButton {{

                    background-color: #E63946;

                    color: white;

                    border-radius:
                    {size // 2}px;

                    border:
                    4px solid #900C3F;

                    font-size:
                    26px;

                    font-weight:
                    bold;
                }}

                QPushButton:hover {{

                    background-color:
                    #FF4D4D;
                }}
                """
            )

            self.btn_detener.raise_()


        # ====================================================
        # PANEL DE DOMÓTICA
        # ====================================================

        y_base = h_tercio * 2

        alto_panel = h - y_base


        # 3 dispositivos por fila
        columnas = 3

        filas = 2


        # Tamaño disponible para cada dispositivo
        ancho_dispositivo = w // columnas

        alto_dispositivo = alto_panel // filas


        # ====================================================
        # POSICIONAR LOS 6 DISPOSITIVOS
        # ====================================================

        for i, (
            btn_encender,
            btn_apagar
        ) in enumerate(
            self.botones_alexa
        ):

            # -----------------------------------------------
            # Calcular fila y columna
            # -----------------------------------------------

            fila = i // columnas

            columna = i % columnas


            # -----------------------------------------------
            # Posición del dispositivo
            # -----------------------------------------------

            x = columna * ancho_dispositivo

            y = (
                y_base
                +
                fila * alto_dispositivo
            )


            # -----------------------------------------------
            # Ajustar última columna
            # -----------------------------------------------

            if columna == columnas - 1:

                ancho_actual = (
                    w - x
                )

            else:

                ancho_actual = (
                    ancho_dispositivo
                )


            # -----------------------------------------------
            # Cada dispositivo se divide en dos
            # -----------------------------------------------

            mitad = (
                ancho_actual // 2
            )


            # ===============================================
            # BOTÓN ENCENDER
            # ===============================================

            btn_encender.setGeometry(
                x,
                y,
                mitad,
                alto_dispositivo
            )


            # ===============================================
            # BOTÓN APAGAR
            # ===============================================

            btn_apagar.setGeometry(
                x + mitad,
                y,
                ancho_actual - mitad,
                alto_dispositivo
            )


            btn_encender.raise_()

            btn_apagar.raise_()


        # ====================================================
        # LABEL ESTADO
        # ====================================================

        if hasattr(
            self,
            "label_estado"
        ):

            self.label_estado.raise_()


    # ========================================================
    # LABEL
    # ========================================================

    def actualizar_label(
        self,
        texto
    ):

        if hasattr(
            self,
            "label_estado"
        ):

            self.label_estado.setText(
                texto
            )


    # ========================================================
    # CERRAR
    # ========================================================

    def closeEvent(
        self,
        event
    ):

        self.hilo.detener()

        event.accept()


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    app = QApplication(
        sys.argv
    )

    ventana = ControlCentral()

    ventana.showFullScreen()

    sys.exit(
        app.exec_()
    )