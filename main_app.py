import sys
import json

from PyQt5.QtWidgets import QApplication, QMainWindow, QPushButton
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5 import uic


# ============================================================
# MEDIAPIPE
# ============================================================

from modulos.mediapipe_reader import generador_mediapipe
from modulos.gaze_controller import GazeStateController


# ============================================================
# HARDWARE Y VOZ
# ============================================================

from modulos.hardware_serial import DomoticaController
from modulos.voice_synth import hablar_en_segundo_plano
from modulos.mouse_action import soltar_mouse


# ============================================================
# CONFIGURACIÓN
# ============================================================

with open("config.json", "r") as f:
    config = json.load(f)


# ============================================================
# HILO DE PROCESAMIENTO MEDIAPIPE
# ============================================================

class HiloProcesamiento(QThread):

    senal_actualizacion = pyqtSignal(str)

    def run(self):

        self.senal_actualizacion.emit(
            "Inicializando MediaPipe (Modo Ligero)..."
        )

        controller = GazeStateController()

        self.senal_actualizacion.emit(
            "¡Sistema Activo! Leyendo bioseñales..."
        )

        # ----------------------------------------------------
        # MEDIAPIPE SE MANTIENE COMO MOTOR DE PROCESAMIENTO
        # ----------------------------------------------------

        for hx, hy, au45, conf, y_51, y_57 in generador_mediapipe():

            # Permite solicitar el cierre del hilo.
            if self.isInterruptionRequested():
                break

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

        self.requestInterruption()


# ============================================================
# VENTANA PRINCIPAL
# ============================================================

class ControlCentral(QMainWindow):

    def __init__(self):

        super().__init__()

        # ====================================================
        # CARGAR INTERFAZ
        # ====================================================

        uic.loadUi(
            "interfaz.ui",
            self
        )


        # ====================================================
        # BOTONES DE MOVIMIENTO EXISTENTES
        # ====================================================

        botones_movimiento = []

        if hasattr(self, "btn_avanzar"):

            botones_movimiento.append(
                self.btn_avanzar
            )

        if hasattr(self, "btn_girar_izq"):

            botones_movimiento.append(
                self.btn_girar_izq
            )

        if hasattr(self, "btn_girar_der"):

            botones_movimiento.append(
                self.btn_girar_der
            )

        if hasattr(self, "btn_detener"):

            botones_movimiento.append(
                self.btn_detener
            )


        # ====================================================
        # QUITAR ANTIGUO BOTÓN DE LUZ
        # ====================================================

        if hasattr(self, "btn_luz"):

            self.btn_luz.hide()
            self.btn_luz.deleteLater()


        # ====================================================
        # ELIMINAR RESTRICCIONES DE QT DESIGNER
        # ====================================================

        for btn in botones_movimiento:

            btn.setMinimumSize(
                0,
                0
            )

            btn.setMaximumSize(
                16777215,
                16777215
            )

            btn.setParent(
                self.centralwidget
            )


        # ====================================================
        # CONTROL SERIAL / SILLA
        # ====================================================

        self.domotica = DomoticaController()


        # ====================================================
        # BOTONES DE MOVIMIENTO
        #
        # IMPORTANTE:
        #
        # pressed  = empieza el movimiento
        # released = detener inmediatamente
        #
        # Esto permite que:
        #
        # boca abierta  -> mouseDown
        #                -> botón pressed
        #                -> silla se mueve
        #
        # boca cerrada  -> mouseUp
        #                -> botón released
        #                -> silla se detiene
        # ====================================================


        # ----------------------------------------------------
        # AVANZAR
        # ----------------------------------------------------

        if hasattr(self, "btn_avanzar"):

            self.btn_avanzar.pressed.connect(
                self.ejecutar_avanzar
            )

            self.btn_avanzar.released.connect(
                self.ejecutar_detener
            )


        # ----------------------------------------------------
        # GIRAR IZQUIERDA
        # ----------------------------------------------------

        if hasattr(self, "btn_girar_izq"):

            self.btn_girar_izq.pressed.connect(
                self.ejecutar_girar_izq
            )

            self.btn_girar_izq.released.connect(
                self.ejecutar_detener
            )


        # ----------------------------------------------------
        # GIRAR DERECHA
        # ----------------------------------------------------

        if hasattr(self, "btn_girar_der"):

            self.btn_girar_der.pressed.connect(
                self.ejecutar_girar_der
            )

            self.btn_girar_der.released.connect(
                self.ejecutar_detener
            )


        # ----------------------------------------------------
        # DETENER
        #
        # Este botón sigue funcionando mediante clic normal.
        # ----------------------------------------------------

        if hasattr(self, "btn_detener"):

            self.btn_detener.clicked.connect(
                self.ejecutar_detener
            )


        # ====================================================
        # DISPOSITIVOS CONTROLADOS POR ALEXA
        #
        # ("Nombre visual", "Nombre pronunciado")
        # ====================================================

        self.dispositivos_alexa = [

            (
                "Enchufe 2",
                "enchufe dos"
            ),

            (
                "Enchufe 3",
                "enchufe tres"
            ),

            (
                "Secadora 1",
                "secadora uno"
            ),

            (
                "Ventilador 2",
                "ventilador dos"
            ),

            (
                "Alexa 2",
                "Alexa dos"
            ),

            (
                "Cafetera 2",
                "cafetera dos"
            )
        ]


        # ====================================================
        # PARES DE BOTONES ALEXA
        #
        # [
        #     (encender, apagar),
        #     (encender, apagar),
        #     ...
        # ]
        # ====================================================

        self.botones_alexa = []


        # ====================================================
        # CREAR LOS 12 BOTONES DE ALEXA
        # ====================================================

        for nombre_visual, nombre_voz in self.dispositivos_alexa:

            # ------------------------------------------------
            # ENCENDER
            # ------------------------------------------------

            btn_encender = QPushButton(
                f"ENCENDER\n{nombre_visual}",
                self.centralwidget
            )

            self.aplicar_estilo_encender(
                btn_encender
            )


            # ------------------------------------------------
            # APAGAR
            # ------------------------------------------------

            btn_apagar = QPushButton(
                f"APAGAR\n{nombre_visual}",
                self.centralwidget
            )

            self.aplicar_estilo_apagar(
                btn_apagar
            )


            # ------------------------------------------------
            # ALEXA SIGUE USANDO CLIC NORMAL
            #
            # Aquí NO queremos mantener una acción.
            # Queremos simplemente emitir una orden.
            # ------------------------------------------------

            btn_encender.clicked.connect(
                lambda checked=False,
                visual=nombre_visual,
                voz=nombre_voz:
                self.encender_dispositivo(
                    visual,
                    voz
                )
            )

            btn_apagar.clicked.connect(
                lambda checked=False,
                visual=nombre_visual,
                voz=nombre_voz:
                self.apagar_dispositivo(
                    visual,
                    voz
                )
            )


            self.botones_alexa.append(
                (
                    btn_encender,
                    btn_apagar
                )
            )


        # ====================================================
        # INICIAR MEDIAPIPE
        # ====================================================

        self.hilo = HiloProcesamiento()

        self.hilo.senal_actualizacion.connect(
            self.actualizar_label
        )

        self.hilo.start()


    # ========================================================
    # ESTILO BOTÓN ENCENDER
    # ========================================================

    def aplicar_estilo_encender(
        self,
        boton
    ):

        boton.setStyleSheet("""
            QPushButton {
                background-color: #1F4E79;
                color: white;

                border: 2px solid #163A5C;

                font-size: 26px;
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
    # ESTILO BOTÓN APAGAR
    # ========================================================

    def aplicar_estilo_apagar(
        self,
        boton
    ):

        boton.setStyleSheet("""
            QPushButton {
                background-color: #E4E3A9;
                color: #0B1F3A;

                border: 2px solid #0B1F3A;

                font-size: 26px;
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
    # MOVIMIENTO DE LA SILLA
    # ========================================================

    def ejecutar_avanzar(self):

        print(
            "[SILLA] Orden: AVANZAR"
        )

        self.domotica.avanzar()

        hablar_en_segundo_plano(
            "Avanzando"
        )

        self.actualizar_label(
            "Silla: Avanzando"
        )


    # ========================================================
    # DETENER SILLA
    # ========================================================

    def ejecutar_detener(self):

        print(
            "[SILLA] Orden: DETENER"
        )

        self.domotica.detener()

        hablar_en_segundo_plano(
            "Silla detenida"
        )

        self.actualizar_label(
            "Silla: Detenida"
        )


    # ========================================================
    # GIRAR IZQUIERDA
    # ========================================================

    def ejecutar_girar_izq(self):

        print(
            "[SILLA] Orden: IZQUIERDA"
        )

        self.domotica.girar_izquierda()

        hablar_en_segundo_plano(
            "Girando a la izquierda"
        )

        self.actualizar_label(
            "Silla: Girando a la izquierda"
        )


    # ========================================================
    # GIRAR DERECHA
    # ========================================================

    def ejecutar_girar_der(self):

        print(
            "[SILLA] Orden: DERECHA"
        )

        self.domotica.girar_derecha()

        hablar_en_segundo_plano(
            "Girando a la derecha"
        )

        self.actualizar_label(
            "Silla: Girando a la derecha"
        )


    # ========================================================
    # ENCENDER DISPOSITIVO CON ALEXA
    # ========================================================

    def encender_dispositivo(
        self,
        nombre_visual,
        nombre_voz
    ):

        comando = (
            f"Alexa, enciende {nombre_voz}"
        )

        print(
            f"[ALEXA] {comando}"
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
    # APAGAR DISPOSITIVO CON ALEXA
    # ========================================================

    def apagar_dispositivo(
        self,
        nombre_visual,
        nombre_voz
    ):

        comando = (
            f"Alexa, apaga {nombre_voz}"
        )

        print(
            f"[ALEXA] {comando}"
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
    # CONTROL DE TAMAÑO Y POSICIONES
    # ========================================================

    def resizeEvent(
        self,
        event
    ):

        super().resizeEvent(
            event
        )

        w = self.width()
        h = self.height()

        if w <= 0 or h <= 0:
            return


        # ====================================================
        # DIVIDIR PANTALLA EN TRES SECCIONES
        # ====================================================

        h_tercio = (
            h // 3
        )


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
        # IZQUIERDA
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
        # DERECHA
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
        # BOTÓN DETENER
        # ====================================================

        if hasattr(
            self,
            "btn_detener"
        ):

            size = int(
                min(w, h)
                *
                0.45
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

                    border-radius: {size // 2}px;

                    border: 4px solid #900C3F;

                    font-size: 26px;
                    font-weight: bold;
                }}

                QPushButton:hover {{
                    background-color: #FF4D4D;
                }}

                QPushButton:pressed {{
                    background-color: #C1121F;
                }}
                """
            )

            self.btn_detener.raise_()


        # ====================================================
        # PANEL INFERIOR DE ALEXA
        # ====================================================

        y_base = (
            h_tercio
            *
            2
        )

        alto_panel = (
            h
            -
            y_base
        )


        # ----------------------------------------------------
        # 3 DISPOSITIVOS POR FILA
        # 2 FILAS
        # ----------------------------------------------------

        columnas = 3
        filas = 2

        ancho_dispositivo = (
            w
            //
            columnas
        )

        alto_dispositivo = (
            alto_panel
            //
            filas
        )


        # ====================================================
        # POSICIONAR LOS 6 DISPOSITIVOS
        # ====================================================

        for i, (
            btn_encender,
            btn_apagar
        ) in enumerate(
            self.botones_alexa
        ):

            fila = (
                i
                //
                columnas
            )

            columna = (
                i
                %
                columnas
            )


            # ------------------------------------------------
            # POSICIÓN DEL BLOQUE
            # ------------------------------------------------

            x = (
                columna
                *
                ancho_dispositivo
            )

            y = (
                y_base
                +
                fila
                *
                alto_dispositivo
            )


            # ------------------------------------------------
            # AJUSTAR ÚLTIMA COLUMNA
            # ------------------------------------------------

            if columna == columnas - 1:

                ancho_actual = (
                    w
                    -
                    x
                )

            else:

                ancho_actual = (
                    ancho_dispositivo
                )


            # ------------------------------------------------
            # DIVIDIR EN ENCENDER / APAGAR
            # ------------------------------------------------

            mitad = (
                ancho_actual
                //
                2
            )


            # ------------------------------------------------
            # ENCENDER
            # ------------------------------------------------

            btn_encender.setGeometry(
                x,
                y,
                mitad,
                alto_dispositivo
            )


            # ------------------------------------------------
            # APAGAR
            # ------------------------------------------------

            btn_apagar.setGeometry(
                x + mitad,
                y,
                ancho_actual - mitad,
                alto_dispositivo
            )


            btn_encender.raise_()
            btn_apagar.raise_()


        # ====================================================
        # TEXTO DE ESTADO
        # ====================================================

        if hasattr(
            self,
            "label_estado"
        ):

            self.label_estado.raise_()


    # ========================================================
    # ACTUALIZAR TEXTO DE ESTADO
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
    # CERRAR APLICACIÓN DE FORMA SEGURA
    # ========================================================

    def closeEvent(
        self,
        event
    ):

        print(
            "[SISTEMA] Cerrando aplicación..."
        )


        # ====================================================
        # 1. SOLTAR BOTÓN DEL MOUSE
        #
        # Evita dejar Windows con mouseDown activo.
        # ====================================================

        try:

            soltar_mouse()

        except Exception as e:

            print(
                f"[SISTEMA] Error liberando mouse: {e}"
            )


        # ====================================================
        # 2. DETENER FÍSICAMENTE LA SILLA
        # ====================================================

        if hasattr(
            self,
            "domotica"
        ):

            try:

                self.domotica.detener()

                print(
                    "[SILLA] Posición neutral enviada."
                )

            except Exception as e:

                print(
                    f"[SILLA] Error al detener: {e}"
                )


        # ====================================================
        # 3. CERRAR PUERTO SERIAL
        # ====================================================

        if hasattr(
            self,
            "domotica"
        ):

            try:

                self.domotica.cerrar_conexion()

            except Exception as e:

                print(
                    f"[SILLA] Error cerrando conexión: {e}"
                )


        # ====================================================
        # 4. DETENER MEDIAPIPE
        # ====================================================

        if hasattr(
            self,
            "hilo"
        ):

            self.hilo.detener()

            self.hilo.wait(
                1000
            )


        print(
            "[SISTEMA] Aplicación cerrada correctamente."
        )

        event.accept()


# ============================================================
# EJECUCIÓN PRINCIPAL
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