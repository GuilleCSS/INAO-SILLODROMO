import json
import time
import threading

import serial


# ============================================================
# CONFIGURACIÓN
# ============================================================

try:
    with open("config.json", "r") as f:
        config = json.load(f)

except Exception:
    config = {}


PUERTO_SERIAL = config.get(
    "serial_port",
    "COM4"
)

BAUD_RATE = int(
    config.get(
        "serial_baud_rate",
        9600
    )
)

POSICION_NEUTRA = int(
    config.get(
        "serial_neutral",
        128
    )
)

VALOR_MAXIMO = 255
VALOR_MINIMO = 0

PASO_MOVIMIENTO = int(
    config.get(
        "serial_step",
        15
    )
)

MULTIPLICADOR_MOVIMIENTO = int(
    config.get(
        "serial_movement_multiplier",
        8
    )
)


# ============================================================
# CONTROLADOR ARDUINO
# ============================================================

class ControladorArduino:

    def __init__(
        self,
        puerto=PUERTO_SERIAL,
        baudrate=BAUD_RATE
    ):

        self.ver_duty = POSICION_NEUTRA
        self.hor_duty = POSICION_NEUTRA

        self.teclas_presionadas = set()

        self.arduino = None

        self.conectado = False

        self.lock = threading.Lock()

        try:

            self.arduino = serial.Serial(
                puerto,
                baudrate,
                timeout=1,
                write_timeout=1
            )

            # Muchos Arduino se reinician al abrir el puerto.
            time.sleep(2.0)

            self.conectado = True

            print(
                f"[SILLA] Arduino conectado en {puerto} "
                f"a {baudrate} baudios"
            )

            # Empezar siempre detenido.
            self.detener()

        except serial.SerialException as e:

            print(
                f"[SILLA] ERROR: No se pudo abrir {puerto}: {e}"
            )

            self.arduino = None
            self.conectado = False


    # ========================================================
    # UTILIDAD
    # ========================================================

    def limitar(
        self,
        valor
    ):

        return max(
            VALOR_MINIMO,
            min(
                VALOR_MAXIMO,
                int(valor)
            )
        )


    # ========================================================
    # ENVIAR DOS BYTES
    # ========================================================

    def enviar_datos(self):

        if (
            not self.conectado
            or
            self.arduino is None
            or
            not self.arduino.is_open
        ):

            print(
                "[SILLA] Arduino no conectado."
            )

            return False


        vertical = self.limitar(
            self.ver_duty
        )

        horizontal = self.limitar(
            self.hor_duty
        )


        try:

            with self.lock:

                self.arduino.write(
                    bytes(
                        [
                            vertical,
                            horizontal
                        ]
                    )
                )

                self.arduino.flush()


            print(
                f"[SILLA] Vertical={vertical} "
                f"Horizontal={horizontal}"
            )

            return True


        except serial.SerialException as e:

            print(
                f"[SILLA] Error serial: {e}"
            )

            return False


    # ========================================================
    # ESTABLECER MOVIMIENTO
    # ========================================================

    def establecer_movimiento(
        self,
        vertical,
        horizontal
    ):

        self.ver_duty = vertical
        self.hor_duty = horizontal

        return self.enviar_datos()


    # ========================================================
    # DETENER
    # ========================================================

    def detener(self):

        return self.establecer_movimiento(
            POSICION_NEUTRA,
            POSICION_NEUTRA
        )


    # ========================================================
    # AVANZAR
    #
    # Igual que W en tu código original:
    #
    # 128 + 15 * 8 = 248
    # ========================================================

    def avanzar(self):

        valor = (
            POSICION_NEUTRA
            +
            PASO_MOVIMIENTO
            *
            MULTIPLICADOR_MOVIMIENTO
        )

        return self.establecer_movimiento(
            valor,
            POSICION_NEUTRA
        )


    # ========================================================
    # RETROCEDER
    #
    # Igual que S:
    #
    # 128 - 120 = 8
    # ========================================================

    def retroceder(self):

        valor = (
            POSICION_NEUTRA
            -
            PASO_MOVIMIENTO
            *
            MULTIPLICADOR_MOVIMIENTO
        )

        return self.establecer_movimiento(
            valor,
            POSICION_NEUTRA
        )


    # ========================================================
    # GIRAR IZQUIERDA
    #
    # Respetamos exactamente tu movement.py funcional:
    #
    # A -> horizontal disminuye
    # ========================================================

    def girar_izquierda(self):

        valor = (
            POSICION_NEUTRA
            -
            PASO_MOVIMIENTO
            *
            MULTIPLICADOR_MOVIMIENTO
        )

        return self.establecer_movimiento(
            POSICION_NEUTRA,
            valor
        )


    # ========================================================
    # GIRAR DERECHA
    #
    # D -> horizontal aumenta
    # ========================================================

    def girar_derecha(self):

        valor = (
            POSICION_NEUTRA
            +
            PASO_MOVIMIENTO
            *
            MULTIPLICADOR_MOVIMIENTO
        )

        return self.establecer_movimiento(
            POSICION_NEUTRA,
            valor
        )


    # ========================================================
    # WASD
    # ========================================================

    def actualizar_movimiento(self):

        mov_vertical = 0
        mov_horizontal = 0


        if "w" in self.teclas_presionadas:
            mov_vertical += 1

        if "s" in self.teclas_presionadas:
            mov_vertical -= 1

        if "a" in self.teclas_presionadas:
            mov_horizontal -= 1

        if "d" in self.teclas_presionadas:
            mov_horizontal += 1


        self.ver_duty = (
            POSICION_NEUTRA
            +
            mov_vertical
            *
            PASO_MOVIMIENTO
            *
            MULTIPLICADOR_MOVIMIENTO
        )

        self.hor_duty = (
            POSICION_NEUTRA
            +
            mov_horizontal
            *
            PASO_MOVIMIENTO
            *
            MULTIPLICADOR_MOVIMIENTO
        )


        self.enviar_datos()


    # ========================================================
    # PRESIONAR TECLA
    # ========================================================

    def presionar(
        self,
        tecla
    ):

        tecla = tecla.lower()

        if tecla not in "wasd":
            return


        if tecla not in self.teclas_presionadas:

            self.teclas_presionadas.add(
                tecla
            )

            self.actualizar_movimiento()


    # ========================================================
    # SOLTAR TECLA
    # ========================================================

    def soltar(
        self,
        tecla
    ):

        tecla = tecla.lower()

        if tecla not in "wasd":
            return


        if tecla in self.teclas_presionadas:

            self.teclas_presionadas.discard(
                tecla
            )

            self.actualizar_movimiento()


    # ========================================================
    # CERRAR
    # ========================================================

    def cerrar_conexion(self):

        try:

            # La prioridad es dejar la silla neutral.
            self.detener()

            time.sleep(
                0.1
            )


            if (
                self.arduino
                and
                self.arduino.is_open
            ):

                self.arduino.close()


            self.conectado = False

            print(
                "[SILLA] Conexión serial cerrada."
            )


        except Exception as e:

            print(
                f"[SILLA] Error al cerrar conexión: {e}"
            )


# ============================================================
# PRUEBA MANUAL OPCIONAL
#
# Solo se ejecuta al correr:
#
# python movement.py
#
# NO se ejecuta cuando main_app.py lo importa.
# ============================================================

if __name__ == "__main__":

    try:

        from pynput import keyboard

    except ImportError:

        print(
            "Para la prueba WASD instala pynput:"
        )

        print(
            "python -m pip install pynput"
        )

        raise SystemExit(1)


    controlador = ControladorArduino()


    def al_presionar(key):

        try:

            if key == keyboard.Key.esc:

                return False


            controlador.presionar(
                key.char
            )

        except AttributeError:

            pass


    def al_liberar(key):

        try:

            controlador.soltar(
                key.char
            )

        except AttributeError:

            pass


    print(
        "Control manual activo."
    )

    print(
        "W/A/S/D = mover"
    )

    print(
        "ESC = salir"
    )


    try:

        with keyboard.Listener(
            on_press=al_presionar,
            on_release=al_liberar
        ) as listener:

            listener.join()


    finally:

        controlador.cerrar_conexion()