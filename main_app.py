import os
import sys
import json
import time

# Trabajar siempre desde la carpeta del proyecto (config.json, interfaz.ui, modulos/)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import cv2
from PyQt5 import uic
from PyQt5.QtWidgets import QApplication, QMainWindow, QShortcut
from PyQt5.QtCore import Qt, QThread, QTimer, QTime, QPoint, pyqtSignal
from PyQt5.QtGui import QKeySequence, QImage

from modulos.mediapipe_reader import generador_mediapipe
from modulos.gaze_controller import GazeStateController
from modulos.hardware_serial import DomoticaController
from modulos.voice_synth import hablar_en_segundo_plano
from modulos.calibracion_ui import DialogoCalibracion


# ============================================================
# CONFIGURACIÓN
# ============================================================

with open("config.json", "r") as f:
    config = json.load(f)

RUTA_UI = os.path.join(BASE_DIR, "interfaz.ui")

# (texto en pantalla, nombre que se le dice a Alexa, comando extra opcional
#  que se manda justo después de "Alexa, enciende {nombre}")
DISPOSITIVOS = [
    ("Enchufe 2", "enchufe dos", None),
    ("Enchufe 3", "enchufe tres", None),
    ("Foco 1", "foco uno", None),
    ("Ventilador 2", "ventilador dos", None),
    ("Alexa 2", "Alexa dos", None),
    ("Fire TV", "Fire TV", "abre Netflix en Fire TV"),
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
        self._ultimo_envio_frame = 0.0

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
        """
        La vista previa se manda con freno de mano a propósito. Mandar un
        QImage de 1280x720 (≈2.7 MB por copia) 30 veces por segundo satura
        la cola de eventos de Qt: si la interfaz no alcanza a consumirlos,
        se acumulan sin límite y todo se siente trabado. El control sí va a
        toda velocidad (senal_estado), pero el panel de cámara no necesita
        más de ~15 fps ni resolución completa para verse bien.
        """
        ahora = time.time()
        intervalo = 1.0 / max(1, int(config.get("vista_fps", 15)))
        if (ahora - self._ultimo_envio_frame) < intervalo:
            return
        self._ultimo_envio_frame = ahora

        ancho_vista = int(config.get("vista_ancho", 640))
        alto, ancho = frame_bgr.shape[:2]
        if ancho_vista and ancho > ancho_vista:
            escala = ancho_vista / float(ancho)
            frame_bgr = cv2.resize(frame_bgr, (ancho_vista, int(alto * escala)))

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
        self._emergencia_activa = False
        self._emergencia_luz_encendida = False
        self._dialogo_calib = None
        self.timer_emergencia = QTimer(self)
        self.timer_emergencia.timeout.connect(self._pulso_emergencia)

        self._configurar_movimiento()
        self._configurar_domotica()
        self._configurar_estado_inicial()
        self.btnRecentrar.clicked.connect(self.recentrar_cursor)

        # ---------- Visión ----------
        self.hilo = HiloProcesamiento()
        self.hilo.senal_mensaje.connect(self.mostrar_mensaje)
        self.hilo.senal_listo.connect(self._recalcular_nodos_navegacion)
        if config.get("calibrar_al_iniciar", True):
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
        QShortcut(QKeySequence("Ctrl+R"), self, activated=self.recentrar_cursor)
        QShortcut(QKeySequence("Ctrl+K"), self, activated=self.abrir_calibracion)
        QShortcut(QKeySequence("Ctrl+E"), self, activated=self.cancelar_emergencia)

    # --------------------------------------------------------
    # CONFIGURACIÓN DE LA INTERFAZ
    # --------------------------------------------------------

    def abrir_calibracion(self):
        """Mide el reposo y el alcance de gesto de hoy. Hace falta porque ese
        alcance cambia bastante entre sesiones (distancia a la cámara,
        ángulo, postura), y ningún umbral fijo sirve para todas."""
        self.detener_movimiento()
        dialogo = DialogoCalibracion(self)
        self._dialogo_calib = dialogo
        resultado = dialogo.exec_()
        self._dialogo_calib = None

        if dialogo.guardado and self.hilo.controller:
            self.hilo.controller.cargar_calibracion()
            self.mostrar_mensaje("Calibración lista")
            hablar_en_segundo_plano("Listo")
        elif resultado == 0:
            self.mostrar_mensaje("Calibración saltada: se usan los valores guardados")

    def recentrar_cursor(self):
        """Fuerza el centro de referencia de los gestos a la postura actual y
        regresa el foco a Avanzar. Útil si los gestos empiezan a sentirse
        desalineados (se disparan solos, o cuesta más de lo normal) tras
        acomodarse o cansarse durante la sesión. No hace falta calibrar nada
        de antemano — la navegación por gestos ya se auto-ajusta sola."""
        if self.hilo.controller:
            self.hilo.controller.recentrar()
            self.mostrar_mensaje("Centro de gestos recalibrado")
            hablar_en_segundo_plano("Centro actualizado")

    # --------------------------------------------------------
    # EMERGENCIA (ojos cerrados sostenidos mucho más tiempo que el de pausa)
    # --------------------------------------------------------

    def activar_emergencia(self):
        """Suena una alarma repetida y parpadea una luz, hasta que se cancele
        (abrir los ojos, o Ctrl+E para quien acompaña)."""
        if self._emergencia_activa:
            return
        self._emergencia_activa = True
        self._chip(self.chipSistema, "🚨 EMERGENCIA", "error")
        self.mostrar_mensaje("Emergencia activada: se necesita ayuda")
        self._pulso_emergencia()
        self.timer_emergencia.start(int(config.get("emergencia_intervalo_seg", 3.0) * 1000))

    def _pulso_emergencia(self):
        """Un "tic" de la alarma: repite el aviso hablado y alterna la luz."""
        hablar_en_segundo_plano(config.get("emergencia_mensaje", "Emergencia. Se necesita ayuda."))

        dispositivo = config.get("emergencia_dispositivo_voz", "foco uno")
        self._emergencia_luz_encendida = not self._emergencia_luz_encendida
        accion = "enciende" if self._emergencia_luz_encendida else "apaga"
        hablar_en_segundo_plano(f"Alexa, {accion} {dispositivo}")

    def cancelar_emergencia(self):
        """Detiene la alarma. Se llama sola al abrir los ojos, o con Ctrl+E
        si quien acompaña necesita pararla manualmente."""
        if not self._emergencia_activa:
            return
        self._emergencia_activa = False
        self.timer_emergencia.stop()
        if self._emergencia_luz_encendida:
            # No dejar la luz de emergencia encendida al cancelar.
            dispositivo = config.get("emergencia_dispositivo_voz", "foco uno")
            hablar_en_segundo_plano(f"Alexa, apaga {dispositivo}")
            self._emergencia_luz_encendida = False
        self._chip(self.chipSistema, "Sistema activo", "ok")
        self.mostrar_mensaje("Emergencia cancelada")
        hablar_en_segundo_plano("Emergencia cancelada")

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
        for i, (visual, voz, extra) in enumerate(DISPOSITIVOS, start=1):
            tarjeta = {
                "nombre": visual,
                "frame": getattr(self, f"tarjeta_{i}"),
                "estado": getattr(self, f"lbl_estado_{i}"),
            }
            getattr(self, f"lbl_disp_{i}").setText(visual)
            getattr(self, f"btn_on_{i}").clicked.connect(
                lambda _=False, t=tarjeta, v=voz, ex=extra: self.encender_dispositivo(t, v, ex))
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
            "Cabeza: gesto arriba/abajo/izq/der mueve el foco un botón (no hace falta calibrar)   ·   "
            "Boca abierta: clic sostenido   ·   "
            f"Ojos cerrados {config.get('blink_hold_time', 3.5):g} s: pausar   ·   "
            f"Ojos cerrados {config.get('emergencia_hold_time', 10.0):g} s: alarma de emergencia (Ctrl+E cancela)   ·   "
            "Botón Recentrar (o Ctrl+R): si los gestos se sienten desalineados"
        )

    # --------------------------------------------------------
    # NODOS DE NAVEGACIÓN (dónde teletransportar el cursor por cada foco)
    # --------------------------------------------------------

    def _recalcular_nodos_navegacion(self):
        """Informa a GazeStateController la posición real en pantalla de cada
        botón (o mitad de botón) del grafo de navegación, para que pueda
        teletransportar el cursor ahí cuando el foco avanza un paso."""
        hilo = getattr(self, "hilo", None)
        if not hilo or not hilo.controller:
            return

        def punto(btn, fx=0.5, fy=0.5):
            r = btn.rect()
            p = btn.mapToGlobal(QPoint(int(r.width() * fx), int(r.height() * fy)))
            return (p.x(), p.y())

        nodos = {
            "avanzar_izq": punto(self.btn_avanzar, 0.25),
            "avanzar_der": punto(self.btn_avanzar, 0.75),
            "izquierda": punto(self.btn_girar_izq),
            "derecha": punto(self.btn_girar_der),
            "regresar_izq": punto(self.btn_regresar, 0.25),
            "regresar_der": punto(self.btn_regresar, 0.75),
        }

        etiquetas = {}
        for i, tarjeta in enumerate(self.tarjetas, start=1):
            nodos[f"dom{i}_on"] = punto(getattr(self, f"btn_on_{i}"))
            nodos[f"dom{i}_off"] = punto(getattr(self, f"btn_off_{i}"))
            etiquetas[f"dom{i}_on"] = f"{tarjeta['nombre']} · Encender"
            etiquetas[f"dom{i}_off"] = f"{tarjeta['nombre']} · Apagar"

        hilo.controller.set_nodos(nodos, etiquetas)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Los botones cambian de posición al reacomodarse el layout.
        QTimer.singleShot(50, self._recalcular_nodos_navegacion)

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

    def encender_dispositivo(self, tarjeta, nombre_voz, comando_extra=None):
        hablar_en_segundo_plano(f"Alexa, enciende {nombre_voz}")
        if comando_extra:
            # Se encola después (voice_synth.py ya reproduce en orden, sin
            # pisarse), así "enciende Fire TV" sale primero y "abre Netflix"
            # después, no al mismo tiempo.
            hablar_en_segundo_plano(f"Alexa, {comando_extra}")
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

        if self._dialogo_calib is not None:
            self._dialogo_calib.actualizar_lectura(e["hx"], e["hy"], e["rostro"])

        if e.get("emergencia"):
            self.activar_emergencia()
        if e.get("emergencia_cancelar"):
            self.cancelar_emergencia()

        activo = e["rostro"] and e["sistema"]

        if self._emergencia_activa:
            pass  # el chip lo controla activar/cancelar_emergencia, no lo pises aquí
        elif not e["rostro"]:
            self._chip(self.chipSistema, "Rostro no detectado", "error")
        elif not e["sistema"]:
            self._chip(self.chipSistema, "Pausado", "warn")
        else:
            self._chip(self.chipSistema, "Sistema activo", "ok")

        self.vistaCamara.set_estado(e)
        self.indCabeza.actualizar(e["frac_x"], e["frac_y"], activo)
        self.indBoca.actualizar(e["apertura"], e["clic"], e.get("boca_umbral"))
        self.lblDireccion.setText(e["direccion"] if activo else "—")

    def _tick_reloj(self):
        self.lblReloj.setText(QTime.currentTime().toString("HH:mm"))

    # --------------------------------------------------------
    # CERRAR
    # --------------------------------------------------------

    def closeEvent(self, event):
        self.timer_emergencia.stop()
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
