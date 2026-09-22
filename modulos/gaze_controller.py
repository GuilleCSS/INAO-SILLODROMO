import time
import json
from collections import deque
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
        #
        # Se estima como un percentil BAJO de una ventana larga de lecturas
        # recientes, y se actualiza SIEMPRE (esté o no presionado el clic).
        # Antes se fijaba con un solo frame y solo se refrescaba mientras el
        # clic estaba suelto: si ese primer frame venía con ruido, o si el
        # clic se enganchaba por error, la base nunca se corregía y la boca
        # quedaba detectada como abierta de forma permanente. Con la ventana
        # larga, un rato de boca genuinamente abierta (p. ej. avanzar) no
        # alcanza a mover el percentil, pero una detección trabada sí se
        # corrige sola en cuanto la ventana se llena de valores de reposo.
        ventana_seg = config.get("boca_base_ventana_seg", 30.0)
        self._aperturas = deque(maxlen=max(30, int(ventana_seg * 30)))
        self._apertura_base = None
        self._frames_desde_base = 0

        # Navegación por saltos
        self._nodos = {}                       # nodo -> (x, y) en pantalla
        self._etiquetas_nodos = dict(ETIQUETAS_FOCO_BASE)
        self._foco = FOCO_INICIAL
        # Un rastreador de zona POR EJE (no uno solo compartido): así, si el
        # gesto cruza el umbral de X y de Y en el mismo instante (un
        # movimiento en diagonal), se detectan los dos por separado y se
        # aplican ambos pasos seguidos — más rápido que tener que hacer el
        # gesto horizontal y el vertical uno a la vez.
        self._zona_anterior_x = "centro"       # "izquierda" | "derecha" | "centro"
        self._zona_anterior_y = "centro"       # "arriba" | "abajo" | "centro"

        # "Centro" de referencia para los gestos, auto-ajustado (no requiere
        # ningún paso de calibración).
        #
        # NO se puede arrancar en 0.0: eso asume que la señal en reposo vale
        # cero, lo cual es cierto para unos backends y falso para otros (con
        # MediaPipe el reposo vertical ronda +2.5, porque la nariz siempre
        # está por debajo de los ojos). Con el centro en 0 la cabeza queda
        # permanentemente "hacia abajo" y jamás se puede detectar "arriba".
        #
        # Tampoco se toma del primer frame suelto (si viene con ruido o con
        # un gesto a medias, el centro queda mal desde el arranque). Se usa
        # la MEDIANA de las primeras lecturas, que es inmune a ambas cosas.
        self._centro_x = None
        self._centro_y = None
        self._muestras_centro = []

        # Historial corto de posiciones, para detectar que el centro quedó
        # mal y recuperarse solo (ver _recuperar_centro).
        self._hist_pos = deque()

        # Desviación actual respecto al centro, en fracción del umbral
        # (±1 = justo en el umbral). Es lo que dibuja el indicador de cabeza.
        self._frac_x = 0.0
        self._frac_y = 0.0

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
        self._muestras_centro = []
        self._hist_pos.clear()
        self._zona_anterior_x = "centro"
        self._zona_anterior_y = "centro"
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

    def _refrescar_apertura_base(self, apertura):
        """Recalcula la base de "boca cerrada" como un percentil bajo de las
        lecturas recientes. La boca pasa cerrada la mayor parte del tiempo,
        así que ese percentil bajo ES el reposo real — y se recalcula
        siempre, lo que permite que una detección trabada se destrabe sola."""
        self._aperturas.append(apertura)

        # Recalcular cada ciertos frames (no en cada uno): ordenar la ventana
        # completa 30 veces por segundo no aporta nada y solo gasta CPU.
        self._frames_desde_base += 1
        if self._apertura_base is not None and self._frames_desde_base < 10:
            return
        self._frames_desde_base = 0

        muestras = sorted(self._aperturas)
        percentil = config.get("boca_base_percentil", 10) / 100.0
        idx = min(len(muestras) - 1, int(len(muestras) * percentil))
        self._apertura_base = muestras[idx]

    def _actualizar_boca(self, apertura):
        self._refrescar_apertura_base(apertura)

        # Umbrales como margen por encima de la boca cerrada real de esta
        # persona (auto-ajustada), no números absolutos que rara vez
        # coinciden exactos con la cámara/distancia real de cada quien.
        delta_on = config.get("boca_delta_on", 15.0)
        delta_off = config.get("boca_delta_off", 6.0)
        umbral_on = self._apertura_base + delta_on
        umbral_off = self._apertura_base + delta_off
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
            "frac_x": self._frac_x,
            "frac_y": self._frac_y,
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

    def _zona_eje(self, delta, umbral_neg, umbral_pos, nombre_neg, nombre_pos, zona_anterior):
        """
        Versión de un solo eje (X o Y) de la detección de gesto: en qué
        sentido está apuntando la cabeza AHORA respecto al centro, como
        fracción del umbral de ESE sentido (0 = en el centro, 1 = ya cruzó
        el umbral). Histéresis: una vez que cuenta como "hacia nombre_neg"
        (p. ej. izquierda), sigue contando como tal hasta que la cabeza
        vuelve bastante cerca del centro — así no dispara un segundo paso
        por quedarse justo en el borde del umbral.
        """
        frac_neg = max(0.0, -delta / umbral_neg)
        frac_pos = max(0.0, delta / umbral_pos)
        umbral_entrada = config.get("navegacion_histeresis", 0.55)

        if zona_anterior == nombre_neg and frac_neg >= umbral_entrada:
            return nombre_neg
        if zona_anterior == nombre_pos and frac_pos >= umbral_entrada:
            return nombre_pos

        if frac_neg >= 1.0:
            return nombre_neg
        if frac_pos >= 1.0:
            return nombre_pos
        return "centro"

    def _margenes(self, dx, dy, umbrales):
        """Margen de "ya regresó al centro", medido contra el umbral del lado
        hacia el que la cabeza está desviada AHORA (no contra el menor de los
        dos): con umbrales asimétricos —p. ej. izquierda más sensible que
        derecha— usar el menor para ambos lados volvería innecesariamente
        estricto el regreso desde el lado de umbral grande."""
        umbral_x = umbrales["izquierda"] if dx < 0 else umbrales["derecha"]
        umbral_y = umbrales["arriba"] if dy < 0 else umbrales["abajo"]
        return umbral_x * 0.6, umbral_y * 0.6

    def _centro_listo(self, hx, hy):
        """Fija el centro con la mediana de las primeras lecturas. Devuelve
        False mientras aún esté juntando muestras."""
        if self._centro_x is not None:
            return True
        self._muestras_centro.append((hx, hy))
        if len(self._muestras_centro) < int(config.get("navegacion_centro_muestras", 15)):
            return False
        xs = sorted(m[0] for m in self._muestras_centro)
        ys = sorted(m[1] for m in self._muestras_centro)
        medio = len(xs) // 2
        self._centro_x, self._centro_y = xs[medio], ys[medio]
        self._muestras_centro = []
        return True

    def _recuperar_centro(self, hx, hy, dx, dy, margen_x, margen_y, current_time):
        """
        Red de seguridad contra quedarse atorado.

        Si el centro de referencia queda mal (backend con otra escala, la
        persona se reacomodó, un arranque con la cara a medio girar), la
        cabeza queda permanentemente fuera del margen: no se dispara ningún
        gesto nuevo y tampoco se re-arma nunca. Para distinguir eso de un
        gesto en curso se exige que la cabeza lleve un rato QUIETA pero
        desviada: un gesto de verdad se mueve, un centro mal puesto no.
        """
        ventana = float(config.get("navegacion_recuperacion_seg", 4.0))
        self._hist_pos.append((current_time, hx, hy))
        while self._hist_pos and (current_time - self._hist_pos[0][0]) > ventana:
            self._hist_pos.popleft()

        if abs(dx) < margen_x and abs(dy) < margen_y:
            return False  # está donde debe: nada que recuperar
        if len(self._hist_pos) < 5 or (current_time - self._hist_pos[0][0]) < ventana:
            return False  # aún no hay suficiente historial

        xs = [p[1] for p in self._hist_pos]
        ys = [p[2] for p in self._hist_pos]
        quieta = (max(xs) - min(xs)) < margen_x and (max(ys) - min(ys)) < margen_y
        if not quieta:
            return False  # se está moviendo: es un gesto, no un atasco

        self._centro_x, self._centro_y = hx, hy
        self._zona_anterior_x = "centro"
        self._zona_anterior_y = "centro"
        self._tiempo_ultimo_paso = None
        self._hist_pos.clear()
        return True

    def _actualizar_navegacion(self, hx, hy, current_time):
        if not self._centro_listo(hx, hy):
            return

        umbrales = self._umbrales()

        # Red de seguridad ANTES de cualquier otra cosa: si el centro quedó
        # mal, todas las ramas de abajo se quedarían esperando para siempre.
        dx_act = hx - self._centro_x
        dy_act = hy - self._centro_y
        mx, my = self._margenes(dx_act, dy_act, umbrales)
        if self._recuperar_centro(hx, hy, dx_act, dy_act, mx, my, current_time):
            return

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
            margen_x, margen_y = self._margenes(dx_anterior, dy_anterior, umbrales)
            if abs(dx_anterior) >= margen_x or abs(dy_anterior) >= margen_y:
                return  # ya pasó el mínimo, pero la cabeza aún no volvió: seguir esperando
            self._centro_x, self._centro_y = hx, hy
            self._zona_anterior_x = "centro"
            self._zona_anterior_y = "centro"
            self._tiempo_ultimo_paso = None

        dx = hx - self._centro_x
        dy = hy - self._centro_y

        # El centro se auto-ajusta lentamente, pero SOLO mientras la cabeza
        # ya está en reposo en LOS DOS ejes (no en medio de un gesto) — así
        # sigue la postura neutral real de la persona sin pedir calibración,
        # y sin "perseguir" un gesto en curso y evitar que cruce el umbral.
        en_reposo = self._zona_anterior_x == "centro" and self._zona_anterior_y == "centro"
        margen_x, margen_y = self._margenes(dx, dy, umbrales)
        if en_reposo and abs(dx) < margen_x and abs(dy) < margen_y:
            alpha_centro = config.get("navegacion_centro_alpha", 0.01)
            self._centro_x += alpha_centro * (hx - self._centro_x)
            self._centro_y += alpha_centro * (hy - self._centro_y)

        # Fracción del umbral en cada eje, para que el indicador de cabeza
        # dibuje exactamente lo que ve la navegación.
        self._frac_x = dx / (umbrales["derecha"] if dx >= 0 else umbrales["izquierda"])
        self._frac_y = dy / (umbrales["abajo"] if dy >= 0 else umbrales["arriba"])

        zona_x = self._zona_eje(dx, umbrales["izquierda"], umbrales["derecha"], "izquierda", "derecha", self._zona_anterior_x)
        zona_y = self._zona_eje(dy, umbrales["arriba"], umbrales["abajo"], "arriba", "abajo", self._zona_anterior_y)

        disparo_x = zona_x != "centro" and self._zona_anterior_x == "centro"
        disparo_y = zona_y != "centro" and self._zona_anterior_y == "centro"

        if disparo_x or disparo_y:
            # Si los dos ejes cruzan el umbral en el mismo instante (gesto en
            # diagonal, p. ej. arriba-derecha a la vez), se aplican los dos
            # pasos seguidos en vez de solo uno — así un movimiento diagonal
            # avanza el doble de rápido que hacer cada gesto por separado.
            if disparo_x:
                self._mover_foco(zona_x)
            if disparo_y:
                self._mover_foco(zona_y)
            self._tiempo_ultimo_paso = current_time

        self._zona_anterior_x = zona_x
        self._zona_anterior_y = zona_y

    def _mover_foco(self, direccion):
        vecino = GRAFO_NAVEGACION.get(self._foco, {}).get(direccion)
        if vecino is None:
            return  # no hay nada en esa dirección desde aquí; se queda
        self._foco = vecino
        self._teleportar_cursor()
