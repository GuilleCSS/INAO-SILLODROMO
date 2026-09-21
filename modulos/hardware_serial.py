import json
import time
import serial

with open('config.json', 'r') as f:
    config = json.load(f)


class DomoticaController:
    """
    Habla con la tarjeta propia de la silla Airwheel (conectada directo en
    el puerto serial, sin Arduino intermedio). Esa tarjeta espera 2 bytes
    por actualización: (duty_vertical, duty_horizontal), 0-255, con 128 =
    neutral/detenido — protocolo confirmado por movement.py.

    (Sillodromo_MCU.ino, en la raíz del repo, es para un Arduino propio
    manejando un puente H con motores aparte; no aplica a este puerto
    mientras la Airwheel esté conectada directo.)
    """

    NEUTRO = int(config.get("airwheel_neutro", 128))
    DELTA = int(config.get("airwheel_delta", 120))

    def __init__(self, puerto='COM5', baudrate=9600):
        try:
            self.arduino = serial.Serial(puerto, baudrate, timeout=1)
            time.sleep(2)
        except serial.SerialException:
            self.arduino = None
            print("Advertencia: Entorno domótico no conectado.")

    def _enviar_duty(self, vertical, horizontal):
        vertical = max(0, min(255, int(vertical)))
        horizontal = max(0, min(255, int(horizontal)))
        if self.arduino:
            self.arduino.write(bytes([vertical, horizontal]))
            print(f"Comando enviado: V={vertical} H={horizontal}")
        else:
            print(f"[Simulación Serial] V={vertical} H={horizontal}")

    def avanzar(self):
        self._enviar_duty(self.NEUTRO + self.DELTA, self.NEUTRO)

    def regresar(self):
        self._enviar_duty(self.NEUTRO - self.DELTA, self.NEUTRO)

    def girar_izquierda(self):
        self._enviar_duty(self.NEUTRO, self.NEUTRO + self.DELTA)

    def girar_derecha(self):
        self._enviar_duty(self.NEUTRO, self.NEUTRO - self.DELTA)

    def detener(self):
        self._enviar_duty(self.NEUTRO, self.NEUTRO)
