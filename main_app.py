import os
import sys
import json
import time
from collections import deque

# Trabajar siempre desde la carpeta del proyecto (config.json, interfaz.ui, modulos/)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import cv2
from PyQt5 import uic
from PyQt5.QtWidgets import QApplication, QMainWindow, QShortcut
from PyQt5.QtCore import Qt, QThread, QTimer, QTime, pyqtSignal
from PyQt5.QtGui import QKeySequence, QImage

from modulos.mediapipe_reader import generador_mediapipe
from modulos.gaze_controller import GazeStateController, actualizar_centro
from modulos.hardware_serial import DomoticaController
from modulos.voice_synth import hablar_en_segundo_plano
from modulos.calibracion_ui import DialogoCalibracion


# ============================================================
# CONFIGURACIÓN
# ============================================================

with open("config.json", "r") as f:
    config = json.load(f)

RUTA_UI = os.path.join(BASE_DIR, "interfaz.ui")

# (texto en pantalla, nombre que se le dice a Alexa)
DISPOSITIVOS = [
    ("Enchufe 2", "enchufe dos"),
    ("Enchufe 3", "enchufe tres"),
    ("Secadora 1", "secadora uno"),
    ("Ventilador 2", "ventilador dos"),
    ("Alexa 2", "Alexa dos"),
    ("Cafetera 2", "cafetera dos"),
]

# movimiento -> (texto, método de DomoticaController)
MOVIMIENTOS = {
    "avanzar": ("Avanzando", "avanzar"),
    "regresar": ("Retrocediendo", "regresar"),
    "izquierda": ("Girando a la izquierda", "girar_izquierda"),
    "derecha": ("Girando a la derecha", "girar_derecha"),
}

# Si la cámara deja de mandar datos este tiempo con la silla en marcha, se detiene
TIEMPO_SIN_SENAL = 0.8


# ============================================================
# HILO DE VISIÓN (MediaPipe: cámara + rastreo, un solo proceso)
# ============================================================

class HiloProcesamiento(QThread):

    senal_mensaje = pyqtSignal(str)
    senal_listo = pyqtSignal()
    senal_estado = pyqtSignal(dict)
    senal_frame = pyqtSignal(QImage)

    def __init__(self):
        super().__init__()
        self.controller = None
        self._activo = True

    def run(self):
        try:
            self.senal_mensaje.emit("Inicializando cámara y MediaPipe…")
            self.controller = GazeStateController()
            self.senal_listo.emit()
            self.senal_mensaje.emit("Sistema activo · leyendo bioseñales")

            for frame, hx, hy, au45, conf, y_51, y_57 in generador_mediapipe():
                if not self._activo:
                    break
                estado = self.controller.process_frame(hx, hy, au45, conf, y_51, y_57)
                if estado:
                    self.senal_estado.emit(estado)
                self._emitir_frame(frame)
        except Exception as e:
            self.senal_mensaje.emit(f"Error en visión: {e}")

    def _emitir_frame(self, frame_bgr):
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        alto, ancho, _ = rgb.shape
        imagen = QImage(rgb.data, ancho, alto, 3 * ancho, QImage.Format_RGB888).copy()
        self.senal_frame.emit(imagen)

    def soltar_clic(self):
        if self.controller:
            self.controller.soltar()

    def detener(self):
        self._activo = False
        self.soltar_clic()


# ============================================================
# VENTANA PRINCIPAL
# ============================================================

class ControlCentral(QMainWindow):

    def __init__(self):
        super().__init__()
        uic.loadUi(RUTA_UI, self)

        self.domotica = DomoticaController(
            puerto=config.get("serial_port", "COM5"),
            baudrate=config.get("serial_baudrate", 9600),
        )
        self.movimiento_actual = None
        self._ultimo_frame = None
        self._ultimo_hx = 0.0
        self._ultimo_hy = 0.0
        self._historial_hxhy = deque(maxlen=45)  # ~1.5 s, para el recentrado rápido
        self._dialogo_calibracion = None

        self._configurar_movimiento()
        self._configurar_domotica()
        self._configurar_calibracion()
        self._configurar_estado_inicial()

        # ---------- Visión ----------
        self.hilo = HiloProcesamiento()
        self.hilo.senal_mensaje.connect(self.mostrar_mensaje)
        self.hilo.senal_listo.connect(self._recalcular_objetivos_iman)
        self.hilo.senal_listo.connect(self.abrir_calibracion)
        self.hilo.senal_estado.connect(self.actualizar_estado)
        self.hilo.senal_frame.connect(self._frame_camara)
        self.hilo.start()

        # ---------- Temporizadores ----------
        self.timer_reloj = QTimer(self)
        self.timer_reloj.timeout.connect(self._tick_reloj)
        self.timer_reloj.start(1000)
        self._tick_reloj()

        self.timer_seguridad = QTimer(self)
        self.timer_seguridad.timeout.connect(self._vigilancia)
        self.timer_seguridad.start(200)

        # ---------- Atajos (para quien acompaña al usuario) ----------
        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=self.close)
        QShortcut(QKeySequence(Qt.Key_Space), self, activated=self.detener_movimiento)
        QShortcut(QKeySequence("Ctrl+K"), self, activated=self.abrir_calibracion)
        QShortcut(QKeySequence("Ctrl+R"), self, activated=self.recentrar_cursor)

    # --------------------------------------------------------
    # CONFIGURACIÓN DE LA INTERFAZ
    # --------------------------------------------------------

    def _configurar_calibracion(self):
        self.btnCalibrar.clicked.connect(self.abrir_calibracion)

    def abrir_calibracion(self):
        self.detener_movimiento()
        dialogo = DialogoCalibracion(self)
        self._dialogo_calibracion = dialogo
        dialogo.actualizar_lectura(self._ultimo_hx, self._ultimo_hy)
        dialogo.exec_()
        self._dialogo_calibracion = None

        if dialogo.guardado:
            if self.hilo.controller:
                self.hilo.controller.recargar_calibracion()
            self.mostrar_mensaje("Calibración guardada: el cursor ahora apunta directo a la pantalla")
            hablar_en_segundo_plano("Calibración completada")

    def recentrar_cursor(self):
        """Recalibra solo el 'centro' con la postura actual (promedio de ~1.5 s),
        sin repetir los 4 extremos. Corrige que el cursor se quede pegado en un
        borde cuando la postura neutral se corrió durante la sesión."""
        if len(self._historial_hxhy) < 10:
            self.mostrar_mensaje("Recentrar: espera un momento con la cara detectada e inténtalo de nuevo")
            return
        hx = sum(p[0] for p in self._historial_hxhy) / len(self._historial_hxhy)
        hy = sum(p[1] for p in self._historial_hxhy) / len(self._historial_hxhy)
        if actualizar_centro(hx, hy):
            if self.hilo.controller:
                self.hilo.controller.recargar_calibracion()
            self.mostrar_mensaje("Centro del cursor recalibrado")
            hablar_en_segundo_plano("Centro actualizado")
        else:
            self.mostrar_mensaje("Recentrar: primero completa la calibración con Ctrl+K")

    def _configurar_movimiento(self):
        self.botones_movimiento = {
            "izquierda": self.btn_girar_izq,
            "avanzar": self.btn_avanzar,
            "derecha": self.btn_girar_der,
            "regresar": self.btn_regresar,
        }
        for mov, btn in self.botones_movimiento.items():
            # La silla se mueve mientras el clic esté presionado y se detiene al soltarlo
            btn.pressed.connect(lambda m=mov: self.iniciar_movimiento(m))
            btn.released.connect(self.detener_movimiento)

    def _configurar_domotica(self):
        self.tarjetas = []
        for i, (visual, voz) in enumerate(DISPOSITIVOS, start=1):
            tarjeta = {
                "nombre": visual,
                "frame": getattr(self, f"tarjeta_{i}"),
                "estado": getattr(self, f"lbl_estado_{i}"),
            }
            getattr(self, f"lbl_disp_{i}").setText(visual)
            getattr(self, f"btn_on_{i}").clicked.connect(
                lambda _=False, t=tarjeta, v=voz: self.encender_dispositivo(t, v))
            getattr(self, f"btn_off_{i}").clicked.connect(
                lambda _=False, t=tarjeta, v=voz: self.apagar_dispositivo(t, v))
            self.tarjetas.append(tarjeta)

    def _configurar_estado_inicial(self):
        puerto = config.get("serial_port", "COM5")
        conectado = getattr(self.domotica, "arduino", None) is not None
        if conectado:
            self._chip(self.chipSilla, "Silla detenida", "idle")
            self.mostrar_mensaje(f"Silla conectada en {puerto}")
        else:
            self._chip(self.chipSilla, "Silla: simulación", "warn")
            self.mostrar_mensaje(f"Silla en simulación: no se pudo abrir {puerto}")
        self._chip(self.chipSistema, "Iniciando…", "warn")
        self.lblAyuda.setText(
            "Cabeza: mover cursor   ·   Boca abierta: clic sostenido   ·   "
            f"Ojos cerrados {config.get('blink_hold_time', 3.5):g} s: pausar   ·   "
            "Punto verde en CABEZA: imán activo cerca de un botón   ·   "
            "La calibración corre sola al iniciar   ·   "
            "Botón Calibrar (o Ctrl+K): repetirla si hace falta   ·   "
            "Ctrl+R: recentrar si el cursor se queda pegado en un borde"
        )

    # --------------------------------------------------------
    # IMÁN DE PRECISIÓN (asiste al cursor cerca de los botones)
    # --------------------------------------------------------

    def _recalcular_objetivos_iman(self):
        """Informa a GazeStateController dónde están los botones en pantalla
        para que el cursor se frene al acercarse (más fácil de acertar)."""
        hilo = getattr(self, "hilo", None)
        if not hilo or not hilo.controller:
            return
        botones = list(self.botones_movimiento.values())
        for i in range(1, len(DISPOSITIVOS) + 1):
            botones.append(getattr(self, f"btn_on_{i}"))
            botones.append(getattr(self, f"btn_off_{i}"))

        objetivos = []
        for btn in botones:
            rect = btn.rect()
            if rect.width() <= 0 or rect.height() <= 0:
                continue
            centro = btn.mapToGlobal(rect.center())
            radio = min(rect.width(), rect.height()) / 2
            objetivos.append((centro.x(), centro.y(), radio))
        hilo.controller.set_objetivos(objetivos)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Los botones cambian de posición al reacomodarse el layout.
        QTimer.singleShot(50, self._recalcular_objetivos_iman)

    # --------------------------------------------------------
    # ESTILOS DINÁMICOS (propiedades usadas por el QSS del .ui)
    # --------------------------------------------------------

    @staticmethod
    def _repulir(widget):
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()

    def _chip(self, chip, texto, estado):
        chip.setText(f"●  {texto}")
        if chip.property("estado") != estado:
            chip.setProperty("estado", estado)
            self._repulir(chip)

    def _marcar_tarjeta(self, tarjeta, encendido):
        tarjeta["frame"].setProperty("encendido", encendido)
        tarjeta["estado"].setProperty("estado", "on" if encendido else "off")
        tarjeta["estado"].setText("ENCENDIDO" if encendido else "APAGADO")
        self._repulir(tarjeta["frame"])
        self._repulir(tarjeta["estado"])

    # --------------------------------------------------------
    # CÁMARA (un solo origen: el mismo hilo que hace el rastreo con MediaPipe)
    # --------------------------------------------------------

    def _frame_camara(self, imagen):
        if not config.get("vista_camara", True):
            self._sin_video("Vista de cámara desactivada")
            return
        if self.vistaCamara.modo != "vivo":
            self.lblInfoCamara.setText("Cámara en vivo")
        self.vistaCamara.set_frame(imagen)

    def _sin_video(self, motivo):
        self.vistaCamara.set_sin_video()
        self.lblInfoCamara.setText(f"{motivo} · mostrando rastreo")

    # --------------------------------------------------------
    # MOVIMIENTO (mantener presionado)
    # --------------------------------------------------------

    def iniciar_movimiento(self, mov):
        texto, metodo = MOVIMIENTOS[mov]
        getattr(self.domotica, metodo)()
        self.movimiento_actual = mov
        hablar_en_segundo_plano(texto)
        self._chip(self.chipSilla, texto, "move")
        self.mostrar_mensaje(f"Silla: {texto}")

    def detener_movimiento(self, motivo=None):
        if self.movimiento_actual is None:
            return
        self.domotica.detener()
        self.movimiento_actual = None
        self._chip(self.chipSilla, "Silla detenida", "idle")
        self.mostrar_mensaje(motivo or "Silla detenida")

    def _vigilancia(self):
        """Si la visión deja de mandar datos con la silla en marcha, se detiene."""
        if self.movimiento_actual is None or self._ultimo_frame is None:
            return
        if time.time() - self._ultimo_frame > TIEMPO_SIN_SENAL:
            self.hilo.soltar_clic()
            for btn in self.botones_movimiento.values():
                btn.setDown(False)
            self.detener_movimiento("Seguridad: se perdió la señal de la cámara · silla detenida")

    # --------------------------------------------------------
    # DOMÓTICA
    # --------------------------------------------------------

    def encender_dispositivo(self, tarjeta, nombre_voz):
        hablar_en_segundo_plano(f"Alexa, enciende {nombre_voz}")
        self._marcar_tarjeta(tarjeta, True)
        self.mostrar_mensaje(f"Encendiendo: {tarjeta['nombre']}")

    def apagar_dispositivo(self, tarjeta, nombre_voz):
        hablar_en_segundo_plano(f"Alexa, apaga {nombre_voz}")
        self._marcar_tarjeta(tarjeta, False)
        self.mostrar_mensaje(f"Apagando: {tarjeta['nombre']}")

    # --------------------------------------------------------
    # ESTADO
    # --------------------------------------------------------

    def mostrar_mensaje(self, texto):
        self.label_estado.setText(texto)

    def actualizar_estado(self, e):
        self._ultimo_frame = time.time()
        self._ultimo_hx, self._ultimo_hy = e["hx"], e["hy"]
        self._historial_hxhy.append((e["hx"], e["hy"]))
        if self._dialogo_calibracion is not None:
            self._dialogo_calibracion.actualizar_lectura(e["hx"], e["hy"])
        activo = e["rostro"] and e["sistema"]

        if not e["rostro"]:
            self._chip(self.chipSistema, "Rostro no detectado", "error")
        elif not e["sistema"]:
            self._chip(self.chipSistema, "Pausado", "warn")
        else:
            self._chip(self.chipSistema, "Sistema activo", "ok")

        self.vistaCamara.set_estado(e)
        self.indCabeza.actualizar(e["hx"], e["hy"], activo, e.get("iman", False))
        self.indBoca.actualizar(e["apertura"], e["clic"])
        self.lblDireccion.setText(e["direccion"] if activo else "—")

    def _tick_reloj(self):
        self.lblReloj.setText(QTime.currentTime().toString("HH:mm"))

    # --------------------------------------------------------
    # CERRAR
    # --------------------------------------------------------

    def closeEvent(self, event):
        self.detener_movimiento()
        self.hilo.detener()
        self.hilo.wait(500)
        if self.hilo.isRunning():
            self.hilo.terminate()
        event.accept()


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    ventana = ControlCentral()
    ventana.showFullScreen()
    sys.exit(app.exec_())
