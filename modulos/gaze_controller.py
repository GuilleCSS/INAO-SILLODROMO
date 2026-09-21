import time
import json
import statistics

from collections import deque

from .mouse_action import (
    mover_cursor,
    presionar_mouse,
    soltar_mouse,
    feedback_clic_inmediato
)

from .voice_synth import hablar_en_segundo_plano


# ============================================================
# CONFIGURACIÓN
# ============================================================

with open("config.json", "r") as f:
    config = json.load(f)


# ============================================================
# CONTROLADOR
# ============================================================

class GazeStateController:

    def __init__(self):

        # ====================================================
        # SISTEMA
        # ====================================================

        self.system_enabled = True

        self.blink_start_time = None

        self.blink_action_triggered = False


        # ====================================================
        # CALIBRACIÓN
        # ====================================================

        self.calibrado = False

        self.muestras_calibracion_x = []
        self.muestras_calibracion_y = []

        self.frames_calibracion = int(
            config.get(
                "cursor_calibration_frames",
                30
            )
        )

        self.centro_x = 0.0
        self.centro_y = 0.0


        # ====================================================
        # FILTRO MEDIANA
        # ====================================================

        ventana = int(
            config.get(
                "cursor_median_window",
                5
            )
        )

        if ventana < 1:
            ventana = 1

        if ventana % 2 == 0:
            ventana += 1

        self.historial_x = deque(
            maxlen=ventana
        )

        self.historial_y = deque(
            maxlen=ventana
        )


        # ====================================================
        # EMA
        # ====================================================

        self.hx_suavizado = 0.0
        self.hy_suavizado = 0.0


        # ====================================================
        # ESTADO DE LOS EJES
        # ====================================================

        self.estado_x = 0
        self.estado_y = 0


        # ====================================================
        # BOCA / CLIC
        # ====================================================

        self.boca_abierta = False

        self.ultimo_clic_tiempo = 0.0

        self.cursor_bloqueado_hasta = 0.0


        # ====================================================
        # MENSAJES TEMPORALES
        # ====================================================

        self.mensaje_temporal = None

        self.mensaje_hasta = 0.0


        # ====================================================
        # TIEMPO
        # ====================================================

        self.ultimo_frame_tiempo = (
            time.perf_counter()
        )


    # ========================================================
    # REINICIAR CALIBRACIÓN
    # ========================================================

    def reiniciar_calibracion(self):

        self.calibrado = False

        self.muestras_calibracion_x.clear()
        self.muestras_calibracion_y.clear()

        self.historial_x.clear()
        self.historial_y.clear()

        self.hx_suavizado = 0.0
        self.hy_suavizado = 0.0

        self.estado_x = 0
        self.estado_y = 0


    # ========================================================
    # MENSAJE TEMPORAL
    # ========================================================

    def mostrar_temporal(
        self,
        texto,
        duracion=0.5
    ):

        self.mensaje_temporal = texto

        self.mensaje_hasta = (
            time.time()
            +
            duracion
        )


    # ========================================================
    # FILTRO ADAPTATIVO
    # ========================================================

    def filtrar_eje(
        self,
        valor,
        historial,
        valor_anterior
    ):

        historial.append(
            valor
        )

        valor_mediana = statistics.median(
            historial
        )

        alpha_quieto = float(
            config.get(
                "cursor_alpha_quiet",
                0.10
            )
        )

        alpha_rapido = float(
            config.get(
                "cursor_alpha_fast",
                0.45
            )
        )

        escala = float(
            config.get(
                "cursor_motion_scale",
                0.12
            )
        )

        diferencia = abs(
            valor_mediana
            -
            valor_anterior
        )

        intensidad = min(
            diferencia
            /
            max(
                escala,
                1e-6
            ),
            1.0
        )

        alpha = (
            alpha_quieto
            +
            (
                alpha_rapido
                -
                alpha_quieto
            )
            *
            intensidad
        )

        return (
            alpha * valor_mediana
            +
            (1.0 - alpha)
            *
            valor_anterior
        )


    # ========================================================
    # HISTÉRESIS
    # ========================================================

    def actualizar_estado_eje(
        self,
        valor,
        estado,
        umbral_on,
        umbral_off
    ):

        # ----------------------------------------------------
        # CENTRADO
        # ----------------------------------------------------

        if estado == 0:

            if valor >= umbral_on:
                return 1

            if valor <= -umbral_on:
                return -1

            return 0


        # ----------------------------------------------------
        # POSITIVO
        # ----------------------------------------------------

        if estado == 1:

            if valor <= -umbral_on:
                return -1

            if valor <= umbral_off:
                return 0

            return 1


        # ----------------------------------------------------
        # NEGATIVO
        # ----------------------------------------------------

        if estado == -1:

            if valor >= umbral_on:
                return 1

            if valor >= -umbral_off:
                return 0

            return -1


        return 0


    # ========================================================
    # PROCESAR FRAME
    # ========================================================

    def process_frame(
        self,
        hx,
        hy,
        au45_c,
        conf,
        y_51,
        y_57
    ):

        current_time = time.time()

        perf_now = time.perf_counter()

        dt = (
            perf_now
            -
            self.ultimo_frame_tiempo
        )

        self.ultimo_frame_tiempo = perf_now


        # ====================================================
        # NORMALIZAR DELTA DE TIEMPO
        # ====================================================

        dt = max(
            1.0 / 120.0,
            min(
                dt,
                1.0 / 15.0
            )
        )


        # ====================================================
        # CONFIANZA
        # ====================================================

        if conf < float(
            config.get(
                "conf_min",
                0.70
            )
        ):

            self.blink_start_time = None

            self.estado_x = 0
            self.estado_y = 0

            return None


        # ====================================================
        # DETECTAR OJOS CERRADOS
        # ====================================================

        is_eyes_closed = (
            au45_c >= 1.0
        )


        # ====================================================
        # PAUSA POR OJOS CERRADOS
        # ====================================================

        if is_eyes_closed:

            if self.blink_start_time is None:

                self.blink_start_time = (
                    current_time
                )

            elapsed = (
                current_time
                -
                self.blink_start_time
            )

            if (
                elapsed
                >=
                float(
                    config.get(
                        "blink_hold_time",
                        3.5
                    )
                )
                and
                not self.blink_action_triggered
            ):

                self.system_enabled = (
                    not self.system_enabled
                )

                self.blink_action_triggered = True

                if self.system_enabled:

                    estado = "Activado"

                    self.reiniciar_calibracion()

                else:

                    estado = "Pausado"

                hablar_en_segundo_plano(
                    f"Sistema {estado}"
                )

                self.mostrar_temporal(
                    f"SISTEMA {estado.upper()}",
                    1.2
                )


            # Mientras los ojos están cerrados,
            # NO movemos el cursor.
            return (
                self.mensaje_temporal
                if current_time < self.mensaje_hasta
                else
                "OJOS CERRADOS"
            )


        else:

            self.blink_start_time = None
            self.blink_action_triggered = False


        # ====================================================
        # SISTEMA PAUSADO
        # ====================================================

        if not self.system_enabled:

            return "PAUSADO"


        # ====================================================
        # CALIBRACIÓN AUTOMÁTICA
        # ====================================================

        if not self.calibrado:

            self.muestras_calibracion_x.append(
                hx
            )

            self.muestras_calibracion_y.append(
                hy
            )

            cantidad = len(
                self.muestras_calibracion_x
            )

            if cantidad >= self.frames_calibracion:

                self.centro_x = statistics.median(
                    self.muestras_calibracion_x
                )

                self.centro_y = statistics.median(
                    self.muestras_calibracion_y
                )

                self.calibrado = True

                self.historial_x.clear()
                self.historial_y.clear()

                self.hx_suavizado = 0.0
                self.hy_suavizado = 0.0

                self.estado_x = 0
                self.estado_y = 0

                self.mostrar_temporal(
                    "CALIBRADO ✓",
                    0.8
                )

                return "CALIBRADO ✓"


            progreso = int(
                cantidad
                /
                self.frames_calibracion
                *
                100
            )

            return (
                f"CALIBRANDO {progreso}%"
            )


        # ====================================================
        # RESTAR CENTRO
        # ====================================================

        hx_centrado = (
            hx
            -
            self.centro_x
        )

        hy_centrado = (
            hy
            -
            self.centro_y
        )


        # ====================================================
        # GANANCIA INDEPENDIENTE X
        # ====================================================

        if hx_centrado < 0:

            hx_centrado *= float(
                config.get(
                    "cursor_left_gain",
                    1.0
                )
            )

        elif hx_centrado > 0:

            hx_centrado *= float(
                config.get(
                    "cursor_right_gain",
                    1.0
                )
            )


        # ====================================================
        # GANANCIA INDEPENDIENTE Y
        # ====================================================

        if hy_centrado < 0:

            hy_centrado *= float(
                config.get(
                    "cursor_up_gain",
                    1.0
                )
            )

        elif hy_centrado > 0:

            hy_centrado *= float(
                config.get(
                    "cursor_down_gain",
                    1.0
                )
            )


        # ====================================================
        # CORRECCIÓN MUY LENTA DEL CENTRO
        #
        # Reduce drift si el usuario cambia levemente
        # de postura con el tiempo.
        # ====================================================

        zona_adaptacion = float(
            config.get(
                "cursor_center_adapt_zone",
                0.06
            )
        )

        alpha_centro = float(
            config.get(
                "cursor_center_adapt_alpha",
                0.0025
            )
        )

        if (
            abs(hx_centrado) < zona_adaptacion
            and
            abs(hy_centrado) < zona_adaptacion
            and
            not self.boca_abierta
        ):

            self.centro_x = (
                (1.0 - alpha_centro)
                *
                self.centro_x
                +
                alpha_centro
                *
                hx
            )

            self.centro_y = (
                (1.0 - alpha_centro)
                *
                self.centro_y
                +
                alpha_centro
                *
                hy
            )


        # ====================================================
        # CLIC POR BOCA
        # ====================================================

        # ====================================================
        # CONTROL DEL MOUSE POR BOCA
        #
        # Boca abierta  -> mouseDown
        # Boca cerrada  -> mouseUp
        # ====================================================

        apertura_boca = (
            y_57
            -
            y_51
        )

        umbral_abrir = float(
            config.get(
                "mp_mouth_open_threshold",
                22.0
            )
        )

        umbral_cerrar = float(
            config.get(
                "mp_mouth_close_threshold",
                15.0
            )
        )


        # ====================================================
        # BOCA CERRADA -> ABIERTA
        # ====================================================

        if (
            not self.boca_abierta
            and
            apertura_boca >= umbral_abrir
        ):

            self.boca_abierta = True

            # Mantener presionado el botón izquierdo
            presionar_mouse()

            # Feedback inmediato
            feedback_clic_inmediato()

            self.mostrar_temporal(
                "PRESIONANDO",
                0.30
            )


        # ====================================================
        # BOCA ABIERTA -> CERRADA
        # ====================================================

        elif (
            self.boca_abierta
            and
            apertura_boca <= umbral_cerrar
        ):

            self.boca_abierta = False

            # Soltar botón izquierdo
            soltar_mouse()

            self.mostrar_temporal(
                "LIBERADO",
                0.30
            )

        # ----------------------------------------------------
        # BOCA SE ABRE
        # ----------------------------------------------------

        if (
            not self.boca_abierta
            and
            apertura_boca >= umbral_abrir
        ):

            self.boca_abierta = True

            if (
                current_time
                -
                self.ultimo_clic_tiempo
            ) >= cooldown:

                hacer_clic()

                feedback_clic_inmediato()

                self.ultimo_clic_tiempo = (
                    current_time
                )

                self.cursor_bloqueado_hasta = (
                    current_time
                    +
                    float(
                        config.get(
                            "click_freeze",
                            0.18
                        )
                    )
                )

                self.mostrar_temporal(
                    "CLIC ✓",
                    float(
                        config.get(
                            "click_feedback_seconds",
                            0.45
                        )
                    )
                )


        # ----------------------------------------------------
        # BOCA SE CIERRA
        # ----------------------------------------------------

        elif (
            self.boca_abierta
            and
            apertura_boca <= umbral_cerrar
        ):

            self.boca_abierta = False

        # ====================================================
        # MIENTRAS LA BOCA ESTÁ ABIERTA:
        # NO MOVER EL CURSOR
        # ====================================================

        if self.boca_abierta:

            return "PRESIONANDO"


        # ====================================================
        # FILTRADO
        # ====================================================

        self.hx_suavizado = (
            self.filtrar_eje(
                hx_centrado,
                self.historial_x,
                self.hx_suavizado
            )
        )

        self.hy_suavizado = (
            self.filtrar_eje(
                hy_centrado,
                self.historial_y,
                self.hy_suavizado
            )
        )


        # ====================================================
        # CONGELACIÓN DESPUÉS DEL CLIC
        # ====================================================

        if (
            current_time
            <
            self.cursor_bloqueado_hasta
        ):

            return "CLIC ✓"


        # ====================================================
        # MOVIMIENTO
        # ====================================================

        (
            dx,
            dy,
            x_dir,
            y_dir
        ) = self.calcular_movimiento(
            self.hx_suavizado,
            self.hy_suavizado,
            dt
        )

        mover_cursor(
            dx,
            dy
        )


        # ====================================================
        # MENSAJE TEMPORAL
        # ====================================================

        if current_time < self.mensaje_hasta:

            return self.mensaje_temporal


        # ====================================================
        # DIRECCIÓN
        # ====================================================

        direccion = (
            f"{x_dir} {y_dir}"
            .strip()
        )

        if direccion:

            return direccion

        return "CENTRO"


    # ========================================================
    # MOVIMIENTO DEL CURSOR
    # ========================================================

    def calcular_movimiento(
        self,
        hx,
        hy,
        dt
    ):

        # ====================================================
        # UMBRALES X
        # ====================================================

        x_on = float(
            config.get(
                "cursor_deadzone_x_on",
                0.16
            )
        )

        x_off = float(
            config.get(
                "cursor_deadzone_x_off",
                0.10
            )
        )


        # ====================================================
        # UMBRALES Y
        # ====================================================

        y_on = float(
            config.get(
                "cursor_deadzone_y_on",
                0.12
            )
        )

        y_off = float(
            config.get(
                "cursor_deadzone_y_off",
                0.07
            )
        )


        # ====================================================
        # HISTÉRESIS
        # ====================================================

        self.estado_x = (
            self.actualizar_estado_eje(
                hx,
                self.estado_x,
                x_on,
                x_off
            )
        )

        self.estado_y = (
            self.actualizar_estado_eje(
                hy,
                self.estado_y,
                y_on,
                y_off
            )
        )


        # ====================================================
        # VELOCIDADES
        # ====================================================

        velocidad_minima = float(
            config.get(
                "cursor_min_speed",
                45.0
            )
        )

        velocidad_maxima = float(
            config.get(
                "cursor_max_speed",
                950.0
            )
        )

        max_input = float(
            config.get(
                "cursor_max_input",
                0.90
            )
        )

        gamma = float(
            config.get(
                "cursor_curve_gamma",
                1.75
            )
        )


        dx = 0.0
        dy = 0.0

        x_dir = ""
        y_dir = ""


        # ====================================================
        # CURVA DE VELOCIDAD
        # ====================================================

        def obtener_velocidad(
            valor,
            deadzone
        ):

            magnitud = abs(
                valor
            )

            exceso = max(
                0.0,
                magnitud
                -
                deadzone
            )

            rango = max(
                max_input
                -
                deadzone,
                1e-6
            )

            normalizado = min(
                exceso
                /
                rango,
                1.0
            )

            curva = (
                normalizado
                **
                gamma
            )

            return (
                velocidad_minima
                +
                (
                    velocidad_maxima
                    -
                    velocidad_minima
                )
                *
                curva
            )


        # ====================================================
        # X
        # ====================================================

        if self.estado_x != 0:

            velocidad_x = obtener_velocidad(
                hx,
                x_off
            )

            dx = (
                self.estado_x
                *
                velocidad_x
                *
                dt
            )

            if self.estado_x < 0:

                x_dir = "IZQUIERDA"

            else:

                x_dir = "DERECHA"


        # ====================================================
        # Y
        # ====================================================

        if self.estado_y != 0:

            velocidad_y = obtener_velocidad(
                hy,
                y_off
            )

            dy = (
                self.estado_y
                *
                velocidad_y
                *
                dt
            )

            if self.estado_y < 0:

                y_dir = "ARRIBA"

            else:

                y_dir = "ABAJO"


        return (
            dx,
            dy,
            x_dir,
            y_dir
        )