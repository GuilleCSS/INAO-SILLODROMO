import time
import json
import os
from .mouse_action import (
    mover_cursor, mover_cursor_absoluto, presionar_clic, soltar_clic,
    posicion_cursor, tamano_pantalla,
)
from .voice_synth import hablar_en_segundo_plano

with open('config.json', 'r') as f:
    config = json.load(f)

RUTA_CALIBRACION = "calibracion.json"


# ============================================================
# CALIBRACIÓN (mapeo absoluto cabeza -> pantalla)
# ============================================================

class Calibrador:
    """
    Recolecta 5 posturas de cabeza (centro + 4 extremos cómodos) para poder
    mapear la orientación de la cabeza directo a un punto de pantalla, en
    vez de usarla como acelerador de cursor.
    """

    PUNTOS = ["centro", "izquierda", "derecha", "arriba", "abajo"]
    ETIQUETAS = {
        "centro": "Mira al frente, relajado",
        "izquierda": "Gira la cabeza cómodamente a la izquierda",
        "derecha": "Gira la cabeza cómodamente a la derecha",
        "arriba": "Inclina la cabeza hacia arriba",
        "abajo": "Inclina la cabeza hacia abajo",
    }

    def __init__(self):
        self.muestras = {}

    def registrar(self, nombre, hx, hy):
        self.muestras[nombre] = (float(hx), float(hy))

    def completo(self):
        return all(p in self.muestras for p in self.PUNTOS)

    def guardar(self):
        with open(RUTA_CALIBRACION, "w") as f:
            json.dump(self.muestras, f, indent=2)
        return self.muestras


def cargar_calibracion():
    """Dict de calibración guardado, o None si no existe / está incompleto."""
    if not os.path.exists(RUTA_CALIBRACION):
        return None
    try:
        with open(RUTA_CALIBRACION, "r") as f:
            datos = json.load(f)
        if all(p in datos for p in Calibrador.PUNTOS):
            return datos
    except (ValueError, OSError):
        pass
    return None


def actualizar_centro(hx, hy):
    """
    Recalibra solo el punto "centro" (recentrado rápido), sin repetir los 4
    extremos. Corrige el caso típico de que la postura neutral de la persona
    se corra un poco durante la sesión (se acomoda en la silla, se cansa,
    etc.) y el cursor termine pegado en un borde por ese desfase acumulado.
    """
    datos = cargar_calibracion()
    if datos is None:
        return False
    datos["centro"] = [float(hx), float(hy)]
    with open(RUTA_CALIBRACION, "w") as f:
        json.dump(datos, f, indent=2)
    return True


class GazeStateController:
    """
    Traduce las bioseñales de OpenFace en acciones de mouse.

    - Cabeza  -> posiciona el cursor.
                 Con calibración guardada: apunta directo a un punto de
                 pantalla (control por posición, como un mouse real).
                 Sin calibración: modo anterior por velocidad (la cabeza
                 acelera el cursor como un joystick), para no romper nada
                 en equipos donde aún no se calibró.
    - Boca    -> abrirla PRESIONA el clic y lo MANTIENE; cerrarla lo SUELTA.
    - Ojos    -> cerrarlos `blink_hold_time` segundos pausa / reanuda el sistema.
    """

    def __init__(self):
        self.system_enabled = True
        self.blink_start_time = None
        self.blink_action_triggered = False

        self.hx_suavizado = 0.0
        self.hy_suavizado = 0.0

        # Estado del clic sostenido
        self.clic_mantenido = False
        self._frames_abierta = 0
        self._frames_cerrada = 0
        self.ultima_apertura = 0.0
        self._ultimo_rostro_ok = time.time()
        self._puntos = []

        # Imán hacia botones/tiles (asistencia de precisión)
        self._objetivos = []       # lista de (cx, cy, radio) en coords. de pantalla
        self._iman_activo = False

        # Calibración para control por posición absoluta
        self.calibracion = cargar_calibracion()
        self.ancho_pantalla, self.alto_pantalla = tamano_pantalla()

    # --------------------------------------------------------
    # OBJETIVOS PARA EL IMÁN DE PRECISIÓN / CALIBRACIÓN
    # --------------------------------------------------------

    def set_objetivos(self, objetivos):
        """Actualiza los botones "imantados" (cx, cy, radio) en coords. de pantalla."""
        self._objetivos = objetivos or []

    def recargar_calibracion(self):
        """Vuelve a leer calibracion.json (se llama al terminar el asistente)."""
        self.calibracion = cargar_calibracion()

    # --------------------------------------------------------
    # CLIC SOSTENIDO
    # --------------------------------------------------------

    def _presionar(self):
        if not self.clic_mantenido:
            presionar_clic()
            self.clic_mantenido = True
        self._frames_cerrada = 0

    def soltar(self):
        """Suelta el clic si estaba presionado (seguro llamarlo siempre)."""
        if self.clic_mantenido:
            soltar_clic()
            self.clic_mantenido = False
        self._frames_abierta = 0
        self._frames_cerrada = 0

    def _actualizar_boca(self, apertura):
        umbral_on = config.get("boca_threshold", 25.0)
        # Histéresis: se suelta con un umbral más bajo para evitar parpadeos del clic
        umbral_off = config.get("boca_threshold_release", umbral_on * 0.8)
        frames_req = int(config.get("boca_frames", 2))

        if not self.clic_mantenido:
            self._frames_abierta = self._frames_abierta + 1 if apertura > umbral_on else 0
            if self._frames_abierta >= frames_req:
                self._presionar()
        else:
            self._frames_cerrada = self._frames_cerrada + 1 if apertura < umbral_off else 0
            if self._frames_cerrada >= frames_req:
                self.soltar()

    # --------------------------------------------------------
    # ESTADO PARA LA INTERFAZ
    # --------------------------------------------------------

    def _estado(self, rostro, direccion=""):
        return {
            "sistema": self.system_enabled,
            "rostro": rostro,
            "clic": self.clic_mantenido,
            "apertura": self.ultima_apertura,
            "hx": self.hx_suavizado,
            "hy": self.hy_suavizado,
            "direccion": direccion or "CENTRO",
            "puntos": self._puntos,
            "iman": self._iman_activo,
            "calibrado": self.calibracion is not None,
        }

    # --------------------------------------------------------
    # PROCESAMIENTO POR FRAME
    # --------------------------------------------------------

    def process_frame(self, hx, hy, au45_c, conf, y_51, y_57, puntos=None):
        current_time = time.time()
        self._puntos = puntos or []

        # 0. ROSTRO NO DETECTADO -> por seguridad se suelta el clic
        if conf < config["conf_min"]:
            self.blink_start_time = None
            tolerancia = config.get("rostro_perdido_tiempo", 0.3)
            if self.clic_mantenido and (current_time - self._ultimo_rostro_ok) > tolerancia:
                self.soltar()
            return self._estado(rostro=False)

        self._ultimo_rostro_ok = current_time
        is_eyes_closed = (au45_c >= 1.0)

        # 1. MECANISMO DE PAUSA (ojos cerrados)
        if is_eyes_closed:
            if self.blink_start_time is None:
                self.blink_start_time = current_time

            elapsed = current_time - self.blink_start_time
            if elapsed >= config["blink_hold_time"] and not self.blink_action_triggered:
                self.system_enabled = not self.system_enabled
                self.blink_action_triggered = True
                if not self.system_enabled:
                    self.soltar()
                estado = "Activado" if self.system_enabled else "Pausado"
                hablar_en_segundo_plano(f"Sistema {estado}")
        else:
            self.blink_start_time = None
            self.blink_action_triggered = False

        if not self.system_enabled:
            return self._estado(rostro=True)

        # 2. CLIC SOSTENIDO POR BOCA
        self.ultima_apertura = y_57 - y_51
        self._actualizar_boca(self.ultima_apertura)

        # 3. SUAVIZADO EMA PARA LA CABEZA
        alpha = config.get("suavizado_alpha", 0.2)
        self.hx_suavizado = (alpha * hx) + ((1 - alpha) * self.hx_suavizado)
        self.hy_suavizado = (alpha * hy) + ((1 - alpha) * self.hy_suavizado)

        # 4. POSICIÓN DEL CURSOR (el cursor se mueve aunque el clic esté presionado)
        if self.calibracion:
            x, y = self._posicion_absoluta(self.hx_suavizado, self.hy_suavizado)
            x, y = self._aplicar_iman_absoluto(x, y)
            mover_cursor_absoluto(x, y)
            x_dir, y_dir = self._direccion_absoluta(self.hx_suavizado, self.hy_suavizado)
        else:
            dx, dy, x_dir, y_dir = self.calcular_movimiento(self.hx_suavizado, self.hy_suavizado)
            mover_cursor(dx, dy)

        return self._estado(rostro=True, direccion=f"{y_dir} {x_dir}".strip())

    # ==========================================================
    # MODO POR POSICIÓN ABSOLUTA (requiere calibración)
    # ==========================================================

    def _interpolar_eje(self, valor, v_centro, v_min, v_max):
        """
        Convierte un ángulo de cabeza a un valor normalizado en [-1, 1]
        usando el centro y los extremos cómodos DE ESA PERSONA (no un
        umbral genérico), así el mapeo se ajusta a su rango real de movimiento.

        Se agrega un margen (`calibracion_margen`) más allá de cada extremo
        calibrado: llegar exactamente al punto que se registró en la
        calibración no pega el cursor al 100% del borde de inmediato, solo
        si la cabeza va un poco más allá. Sin esto, cualquier variación
        normal (la postura de calibración casi nunca es idéntica a como se
        mueve la persona en el uso real) deja el cursor trabado en un borde.
        """
        margen = 1 + config.get("calibracion_margen", 0.15)
        if valor >= v_centro:
            rango = ((v_max - v_centro) * margen) or 1e-6
            t = (valor - v_centro) / rango
        else:
            rango = ((v_centro - v_min) * margen) or 1e-6
            t = (valor - v_centro) / rango
        return max(-1.0, min(1.0, t))

    def _posicion_absoluta(self, hx, hy):
        centro_x, centro_y = self.calibracion["centro"]
        izq_x, _ = self.calibracion["izquierda"]
        der_x, _ = self.calibracion["derecha"]
        _, arriba_y = self.calibracion["arriba"]
        _, abajo_y = self.calibracion["abajo"]

        # Curva de precisión: da más resolución de pantalla por grado de
        # cabeza cerca del centro (gamma > 1), sin perder alcance a los
        # bordes. gamma = 1 sería un mapeo lineal puro.
        gamma = config.get("curva_precision", 1.3)

        nx = self._interpolar_eje(hx, centro_x, izq_x, der_x)
        ny = self._interpolar_eje(hy, centro_y, arriba_y, abajo_y)

        nx = (abs(nx) ** gamma) * (1 if nx >= 0 else -1)
        ny = (abs(ny) ** gamma) * (1 if ny >= 0 else -1)

        x = (self.ancho_pantalla / 2) + nx * (self.ancho_pantalla / 2)
        y = (self.alto_pantalla / 2) + ny * (self.alto_pantalla / 2)
        return (
            max(0, min(self.ancho_pantalla - 1, x)),
            max(0, min(self.alto_pantalla - 1, y)),
        )

    def _direccion_absoluta(self, hx, hy):
        """Solo para la etiqueta informativa de la interfaz (CABEZA: ...)."""
        centro_x, centro_y = self.calibracion["centro"]
        umbral_x = abs(self.calibracion["derecha"][0] - centro_x) * 0.15
        umbral_y = abs(self.calibracion["abajo"][1] - centro_y) * 0.15
        x_dir = y_dir = ""
        if abs(hx - centro_x) > umbral_x:
            x_dir = "DERECHA" if hx > centro_x else "IZQUIERDA"
        if abs(hy - centro_y) > umbral_y:
            y_dir = "ABAJO" if hy > centro_y else "ARRIBA"
        return x_dir, y_dir

    def _aplicar_iman_absoluto(self, x, y):
        """
        Igual que _aplicar_iman pero para el modo de posición: en vez de
        frenar velocidad, acerca el punto de destino hacia el centro del
        botón más cercano cuando el punto calculado ya cayó dentro de su radio.
        """
        self._iman_activo = False
        if not self._objetivos:
            return x, y

        radio_iman = config.get("iman_radio", 90)
        factor_min = config.get("iman_factor", 0.35)

        for cx, cy, radio in self._objetivos:
            radio_efectivo = radio + radio_iman
            dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
            if dist < radio_efectivo:
                t = max(0.0, min(1.0, dist / radio_efectivo))
                atraccion = (1 - factor_min) * (1 - t)  # más fuerte cerca del centro
                self._iman_activo = True
                return x + (cx - x) * atraccion, y + (cy - y) * atraccion

        return x, y

    # ==========================================================
    # MODO POR VELOCIDAD (respaldo, se usa solo sin calibración)
    # ==========================================================

    def calcular_movimiento(self, hx, hy):
        velocidad_base = config.get("mouse_speed", 5)
        limite_multiplicador = 25.0  # Límite para poder cruzar una pantalla 2K

        dx = 0.0
        dy = 0.0
        x_dir = ""
        y_dir = ""

        xt, yt = config["x_threshold"], config["y_threshold"]

        # Eje X (giro de cuello). El multiplicador arranca en 0 justo al cruzar
        # el umbral y crece cuadráticamente, en vez de saltar de golpe a
        # velocidad_base: así el primer instante tras salir de la zona muerta
        # es controlable y no un "brinco" del cursor.
        if abs(hx) > xt:
            exceso = (abs(hx) - xt) / xt
            multiplicador = min(exceso ** 2, limite_multiplicador)
            dx = velocidad_base * multiplicador * (1 if hx > 0 else -1)
            x_dir = "DERECHA" if hx > 0 else "IZQUIERDA"

        # Eje Y (inclinación de cráneo), misma rampa suave.
        if abs(hy) > yt:
            exceso = (abs(hy) - yt) / yt
            multiplicador = min(exceso ** 2, limite_multiplicador)
            dy = velocidad_base * multiplicador * (1 if hy > 0 else -1)
            y_dir = "ABAJO" if hy > 0 else "ARRIBA"

        dx, dy = self._aplicar_iman(dx, dy)

        return dx, dy, x_dir, y_dir

    def _aplicar_iman(self, dx, dy):
        """
        Frena el cursor cuando se acerca a un botón registrado, para que
        acertar un tile no dependa de apuntar con precisión milimétrica con
        la cabeza. No cambia la dirección, solo amortigua la velocidad.
        """
        self._iman_activo = False
        if not self._objetivos or (dx == 0.0 and dy == 0.0):
            return dx, dy

        radio_iman = config.get("iman_radio", 90)
        factor_min = config.get("iman_factor", 0.35)

        try:
            x, y = posicion_cursor()
        except Exception:
            return dx, dy

        nx, ny = x + dx, y + dy
        for cx, cy, radio in self._objetivos:
            radio_efectivo = radio + radio_iman
            dist = ((nx - cx) ** 2 + (ny - cy) ** 2) ** 0.5
            if dist < radio_efectivo:
                t = max(0.0, min(1.0, dist / radio_efectivo))
                amortiguacion = factor_min + (1 - factor_min) * t
                self._iman_activo = True
                return dx * amortiguacion, dy * amortiguacion

        return dx, dy
