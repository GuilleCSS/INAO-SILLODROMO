from movement import ControladorArduino


# ============================================================
# CONTROL DE LA SILLA
# ============================================================

class DomoticaController:

    def __init__(self):

        self.silla = ControladorArduino()


    # ========================================================
    # MOVIMIENTO
    # ========================================================

    def avanzar(self):

        print(
            "[DOMOTICA] Avanzar"
        )

        return self.silla.avanzar()


    def retroceder(self):

        print(
            "[DOMOTICA] Retroceder"
        )

        return self.silla.retroceder()


    def girar_izquierda(self):

        print(
            "[DOMOTICA] Girar izquierda"
        )

        return self.silla.girar_izquierda()


    def girar_derecha(self):

        print(
            "[DOMOTICA] Girar derecha"
        )

        return self.silla.girar_derecha()


    def detener(self):

        print(
            "[DOMOTICA] Detener"
        )

        return self.silla.detener()


    # ========================================================
    # CERRAR
    # ========================================================

    def cerrar_conexion(self):

        if hasattr(
            self,
            "silla"
        ):

            self.silla.cerrar_conexion()