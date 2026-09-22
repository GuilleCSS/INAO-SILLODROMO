import time
import json
from .mouse_action import mover_cursor_absoluto, presionar_clic, soltar_clic
from .voice_synth import hablar_en_segundo_plano

with open('config.json', 'r') as f:
    config = json.load(f)


# ============================================================
# GRAFO DE NAVEGACIÓN (cruceta + domótica como un solo mapa de saltos)
# ============================================================
#
# La cruceta queda así en pantalla:
#
#     [   ..... AVANZAR ..... ]      <- avanzar_izq | avanzar_der (un solo
#     [ IZQUIERDA | DERECHA   ]         botón, dos mitades conceptuales)
#     [   ..... REGRESAR .... ]      <- regresar_izq | regresar_der
#
# Avanzar y Regresar ocupan todo el ancho, así que se dividen en dos
# mitades conceptuales (mismo botón, dos puntos de destino distintos) para
# que desde cualquiera de las dos se pueda bajar/subir directo a Izquierda
# o a Derecha sin ambigüedad.
#
# Debajo sigue la domótica: 3 tarjetas por fila, cada una con Encender
# (izquierda) / Apagar (derecha) — 6 "columnas" por fila. Regresar conecta
# hacia abajo con la fila 1 (dom1..dom3); Avanzar es el techo, no baja a
# nada.

GRAFO_NAVEGACION = {
    "avanzar_izq": {"derecha": "avanzar_der", "abajo": "izquierda"},
    "avanzar_der": {"izquierda": "avanzar_izq", "abajo": "derecha"},

    "izquierda": {"arriba": "avanzar_izq", "abajo": "regresar_izq", "derecha": "derecha"},
    "derecha": {"arriba": "avanzar_der", "abajo": "regresar_der", "izquierda": "izquierda"},

    "regresar_izq": {"arriba": "izquierda", "derecha": "regresar_der", "abajo": "dom1_on"},
    "regresar_der": {"arriba": "derecha", "izquierda": "regresar_izq", "abajo": "dom3_off"},

    "dom1_on": {"arriba": "regresar_izq", "abajo": "dom4_on", "derecha": "dom1_off"},
    "dom1_off": {"arriba": "regresar_izq", "abajo": "dom4_off", "izquierda": "dom1_on", "derecha": "dom2_on"},
    "dom2_on": {"arriba": "regresar_izq", "abajo": "dom5_on", "izquierda": "dom1_off", "derecha": "dom2_off"},
    "dom2_off": {"arriba": "regresar_der", "abajo": "dom5_off", "izquierda": "dom2_on", "derecha": "dom3_on"},
    "dom3_on": {"arriba": "regresar_der", "abajo": "dom6_on", "izquierda": "dom2_off", "derecha": "dom3_off"},
    "dom3_off": {"arriba": "regresar_der", "abajo": "dom6_off", "izquierda": "dom3_on"},

    "dom4_on": {"arriba": "dom1_on", "derecha": "dom4_off"},
    "dom4_off": {"arriba": "dom1_off", "izquierda": "dom4_on", "derecha": "dom5_on"},
    "dom5_on": {"arriba": "dom2_on", "izquierda": "dom4_off", "derecha": "dom5_off"},
    "dom5_off": {"arriba": "dom2_off", "izquierda": "dom5_on", "derecha": "dom6_on"},
    "dom6_on": {"arriba": "dom3_on", "izquierda": "dom5_off", "derecha": "dom6_off"},
    "dom6_off": {"arriba": "dom3_off", "izquierda": "dom6_on"},
}

FOCO_INICIAL = "avanzar_izq"

ETIQUETAS_FOCO_BASE = {
    "avanzar_izq": "Avanzar",
    "avanzar_der": "Avanzar",
    "izquierda": "Girar izquierda",
    "derecha": "Girar derecha",
    "regresar_izq": "Regresar",
    "regresar_der": "Regresar",
}


class GazeStateController:
    """
    Traduce las bioseñales de OpenFace en acciones de mouse.

    - Cabeza  -> NO mueve un cursor libre y NO necesita calibración: cada
                 gesto claro hacia arriba, abajo, izquierda o derecha (salir
                 de la zona central y volver a ella) mueve el foco UN paso en
                 el grafo de navegación (ver GRAFO_NAVEGACION) y
                 teletransporta el cursor real al centro de ese botón. El
                 "centro" de referencia se auto-ajusta solo, siguiendo la
                 postura de descanso real de la persona.
    - Boca    -> abrirla PRESIONA el clic y lo MANTIENE (sobre el botón
                 donde está el foco); cerrarla lo SUELTA. Totalmente
                 independiente de la navegación por gestos de arriba.
    - Ojos    -> cerrarlos `blink_hold_time` segundos pausa / reanuda el sistema.
    """

    def __init__(self):
        self.system_enabled = True
        self.blink_start_time = None
        self.blink_action_triggered = False

        # Emergencia: ojos cerrados mucho más tiempo que el de pausa.
        # `emergencia_disparada` evita repetir el evento cada frame mientras
        # se sigue con los ojos cerrados; los otros dos son banderas de un
        # solo frame para avisarle a main_app.py (se limpian en _estado()).
        self.emergencia_disparada = False
        self._emergencia_evento = False
        self._emergencia_cancelar = False

        self.hx_suavizado = 0.0
        self.hy_suavizado = 0.0

        # Estado del clic sostenido
        self.clic_mantenido = False
        self._frames_abierta = 0
        self._frames_cerrada = 0
        self.ultima_apertura = 0.0
        self._ultimo_rostro_ok = time.time()
        self._puntos = []

        # Línea base de "boca cerrada en reposo", auto-ajustada (no un
        # número fijo adivinado): la apertura real con la boca cerrada varía
        # según la distancia a la cámara, el tamaño de cara, etc., así que
        # los umbrales de clic se calculan como un margen POR ENCIMA de esta
        # base, no como valores absolutos.
        self._apertura_base = None

        # Navegación por saltos
        self._nodos = {}                       # nodo -> (x, y) en pantalla
        self._etiquetas_nodos = dict(ETIQUETAS_FOCO_BASE)
        self._foco = FOCO_INICIAL
        self._zona_anterior = "centro"

        # "Centro" de referencia para los gestos, auto-ajustado (no requiere
        # ningún paso de calibración): arranca igual que hx_suavizado/
        # hy_suavizado (en 0.0, no en "lo que sea que traiga el primer
        # frame" — si el primer frame ya trae parte de un gesto, el centro
        # lo absorbería y ese umbral quedaría mal calibrado desde el
        # arranque) y se va corrigiendo solo mientras la cabeza está en reposo.
        self._centro_x = 0.0
        self._centro_y = 0.0

        # Pausa tras cada paso: da tiempo a que la cabeza regrese al centro
        # antes de volver a evaluar gestos. `_tiempo_ultimo_paso` no-None
        # significa "en pausa/esperando volver al centro".
        self._tiempo_ultimo_paso = None

    # --------------------------------------------------------
    # NODOS DE NAVEGACIÓN (posiciones reales en pantalla)
    # --------------------------------------------------------

    def set_nodos(self, nodos, etiquetas=None):
        """`nodos`: {nombre_de_nodo: (x, y)} con la posición real en pantalla
        de cada botón/mitad de botón. `etiquetas`: nombres legibles extra
        (p. ej. los de domótica, que dependen de qué dispositivo esté
        conectado a cada tarjeta)."""
        self._nodos = nodos or {}
        self._etiquetas_nodos = dict(ETIQUETAS_FOCO_BASE)
        self._etiquetas_nodos.update(etiquetas or {})
        self._teleportar_cursor()

    def _teleportar_cursor(self):
        punto = self._nodos.get(self._foco)
        if punto:
            mover_cursor_absoluto(*punto)

    def recentrar(self):
        """Fuerza el "centro" de referencia a la postura actual ya mismo, y
        regresa el foco a Avanzar. Útil si los gestos empiezan a sentirse
        desalineados (la persona se acomodó, se cansó, etc.)."""
        self._centro_x, self._centro_y = self.hx_suavizado, self.hy_suavizado
        self._zona_anterior = "centro"
        self._foco = FOCO_INICIAL
        self._tiempo_ultimo_paso = None
        self._teleportar_cursor()

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
        if self._apertura_base is None:
            self._apertura_base = apertura

        # Umbrales como margen por encima de la boca cerrada real de esta
        # persona (auto-ajustada), no números absolutos que rara vez
        # coinciden exactos con la cámara/distancia real de cada quien.
        delta_on = config.get("boca_delta_on", 15.0)
        delta_off = config.get("boca_delta_off", 6.0)
        umbral_on = self._apertura_base + delta_on
        umbral_off = self._apertura_base + delta_off
        frames_req = int(config.get("boca_frames", 2))

        if not self.clic_mantenido:
            # Solo se adapta la base mientras la boca está claramente cerrada
            # (bien por debajo del umbral de soltar) — sigue el reposo real
            # sin "perseguir" una boca que ya se está empezando a abrir.
            if apertura < umbral_off:
                alpha_base = config.get("boca_base_alpha", 0.02)
                self._apertura_base += alpha_base * (apertura - self._apertura_base)
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

    def _estado(self, rostro):
        base = self._apertura_base if self._apertura_base is not None else self.ultima_apertura
        emergencia_evento = self._emergencia_evento
        emergencia_cancelar = self._emergencia_cancelar
        self._emergencia_evento = False
        self._emergencia_cancelar = False
        return {
            "sistema": self.system_enabled,
            "rostro": rostro,
            "clic": self.clic_mantenido,
            "apertura": self.ultima_apertura,
            "boca_umbral": base + config.get("boca_delta_on", 15.0),
            "hx": self.hx_suavizado,
            "hy": self.hy_suavizado,
            "direccion": self._etiquetas_nodos.get(self._foco, self._foco).upper(),
            "foco": self._foco,
            "emergencia": emergencia_evento,
            "emergencia_cancelar": emergencia_cancelar,
            "puntos": self._puntos,
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

        # Apertura de boca, calculada antes del mecanismo de pausa: al abrir
        # la boca, OpenFace a veces malinterpreta la forma de la cara y da
        # falsos positivos en el AU45 (ojos cerrados) — así que mientras la
        # boca esté abierta, NO cuenta como parpadeo para pausar el sistema.
        self.ultima_apertura = y_57 - y_51
        if self._apertura_base is not None:
            umbral_boca_abierta = self._apertura_base + config.get("boca_delta_off", 6.0)
            boca_abierta_ahora = self.ultima_apertura > umbral_boca_abierta
        else:
            boca_abierta_ahora = False  # todavía no se conoce la base (primer frame)
        is_eyes_closed = (au45_c >= 1.0) and not boca_abierta_ahora

        # 1. MECANISMO DE PAUSA (ojos cerrados) + EMERGENCIA (ojos cerrados
        # mucho más tiempo, un umbral bien separado del de pausa para que no
        # se confundan).
        if is_eyes_closed:
            if self.blink_start_time is None:
                self.blink_start_time = current_time

            elapsed = current_time - self.blink_start_time
            if elapsed >= config["blink_hold_time"] and not self.blink_action_triggered:
                self.system_enabled = not self.system_enabled
                self.blink_action_triggered = True
                if not self.system_enabled:
                    self.soltar()
                    hablar_en_segundo_plano("Sistema pausado")
                else:
                    # En este instante los ojos siguen cerrados (recién se
                    # cumplió el tiempo sostenido) y el sistema ya está
                    # activo de nuevo — sin este aviso, la persona no sabe
                    # que ya puede (y debe) abrir los ojos, y si los sigue
                    # cerrando por costumbre puede volver a pausar el sistema
                    # sin querer al cumplirse otro `blink_hold_time`.
                    hablar_en_segundo_plano("Sistema activado. Abre los ojos.")

            tiempo_emergencia = config.get("emergencia_hold_time", 10.0)
            if elapsed >= tiempo_emergencia and not self.emergencia_disparada:
                self.emergencia_disparada = True
                self._emergencia_evento = True
        else:
            self.blink_start_time = None
            self.blink_action_triggered = False
            if self.emergencia_disparada:
                self.emergencia_disparada = False
                self._emergencia_cancelar = True

        if not self.system_enabled:
            return self._estado(rostro=True)

        # 2. CLIC SOSTENIDO POR BOCA (sobre el botón donde está el foco) —
        # totalmente independiente de la navegación del paso 4.
        self._actualizar_boca(self.ultima_apertura)

        # 3. SUAVIZADO EMA LIGERO (solo para no reaccionar a un frame suelto con ruido)
        alpha = config.get("suavizado_alpha", 0.2)
        self.hx_suavizado = (alpha * hx) + ((1 - alpha) * self.hx_suavizado)
        self.hy_suavizado = (alpha * hy) + ((1 - alpha) * self.hy_suavizado)

        # 4. NAVEGACIÓN POR SALTOS (solo cabeza, sin gestos adicionales)
        self._actualizar_navegacion(self.hx_suavizado, self.hy_suavizado, current_time)

        return self._estado(rostro=True)

    # ==========================================================
    # NAVEGACIÓN POR SALTOS (gesto de cabeza -> un paso en el grafo)
    # ==========================================================

    def _umbrales(self):
        """Umbral de gesto POR DIRECCIÓN (no compartido entre arriba/abajo ni
        izquierda/derecha): la cámara no responde igual de sensible en los
        dos sentidos de un mismo eje (ángulo de montaje, postura habitual
        frente a la pantalla, etc.), así que cada rumbo se ajusta aparte."""
        xt = config.get("navegacion_umbral_x", config.get("x_threshold", 0.06))
        yt = config.get("navegacion_umbral_y", config.get("y_threshold", 0.05))
        return {
            "izquierda": config.get("navegacion_umbral_izquierda", xt),
            "derecha": config.get("navegacion_umbral_derecha", xt),
            "arriba": config.get("navegacion_umbral_arriba", yt),
            "abajo": config.get("navegacion_umbral_abajo", yt),
        }

    def _zona_actual(self, dx, dy, umbrales):
        """
        En qué dirección está apuntando la cabeza AHORA respecto al centro
        de referencia, como fracción del umbral de ESA dirección (0 = en el
        centro, 1 = ya cruzó el umbral). Usa histéresis: una vez que cuenta
        como "hacia la izquierda" (p. ej.), sigue contando como tal hasta que
        la cabeza vuelve bastante cerca del centro — así no dispara un
        segundo paso por quedarse justo en el borde del umbral.
        """
        fracciones = {
            "izquierda": max(0.0, -dx / umbrales["izquierda"]),
            "derecha": max(0.0, dx / umbrales["derecha"]),
            "arriba": max(0.0, -dy / umbrales["arriba"]),
            "abajo": max(0.0, dy / umbrales["abajo"]),
        }

        umbral_entrada = config.get("navegacion_histeresis", 0.55)
        if self._zona_anterior != "centro" and fracciones.get(self._zona_anterior, 0.0) >= umbral_entrada:
            return self._zona_anterior

        direccion, fraccion = max(fracciones.items(), key=lambda kv: kv[1])
        return direccion if fraccion >= 1.0 else "centro"

    def _actualizar_navegacion(self, hx, hy, current_time):
        umbrales = self._umbrales()
        margen_x = min(umbrales["izquierda"], umbrales["derecha"]) * 0.6
        margen_y = min(umbrales["arriba"], umbrales["abajo"]) * 0.6

        # Pausa tras cada paso: `navegacion_pausa_seg` es un MÍNIMO, no un
        # reloj fijo. Cumplido ese mínimo, solo se recentra cuando la cabeza
        # ya está de verdad cerca del centro ANTERIOR — si todavía no
        # regresó, se sigue esperando en vez de adoptar una posición todavía
        # desviada como si fuera neutral (eso hacía que terminar de volver
        # al centro se leyera como un gesto hacia el lado contrario).
        if self._tiempo_ultimo_paso is not None:
            transcurrido = current_time - self._tiempo_ultimo_paso
            dx_anterior = hx - self._centro_x
            dy_anterior = hy - self._centro_y
            if transcurrido < config.get("navegacion_pausa_seg", 0.5):
                return
            if abs(dx_anterior) >= margen_x or abs(dy_anterior) >= margen_y:
                return  # ya pasó el mínimo, pero la cabeza aún no volvió: seguir esperando
            self._centro_x, self._centro_y = hx, hy
            self._zona_anterior = "centro"
            self._tiempo_ultimo_paso = None

        dx = hx - self._centro_x
        dy = hy - self._centro_y

        # El centro se auto-ajusta lentamente, pero SOLO mientras la cabeza
        # ya está en reposo (no en medio de un gesto) — así sigue la postura
        # neutral real de la persona sin pedir calibración, y sin "perseguir"
        # un gesto en curso y evitar que cruce el umbral.
        if self._zona_anterior == "centro" and abs(dx) < margen_x and abs(dy) < margen_y:
            alpha_centro = config.get("navegacion_centro_alpha", 0.01)
            self._centro_x += alpha_centro * (hx - self._centro_x)
            self._centro_y += alpha_centro * (hy - self._centro_y)

        zona = self._zona_actual(dx, dy, umbrales)
        if zona != "centro" and self._zona_anterior == "centro":
            self._mover_foco(zona)
            self._tiempo_ultimo_paso = current_time
        self._zona_anterior = zona

    def _mover_foco(self, direccion):
        vecino = GRAFO_NAVEGACION.get(self._foco, {}).get(direccion)
        if vecino is None:
            return  # no hay nada en esa dirección desde aquí; se queda
        self._foco = vecino
        self._teleportar_cursor()
