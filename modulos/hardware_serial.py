import serial
import time

class DomoticaController:
    def __init__(self, puerto='COM3', baudrate=9600):
        try:
            self.arduino = serial.Serial(puerto, baudrate, timeout=1)
            time.sleep(2) 
        except serial.SerialException:
            self.arduino = None
            print("Advertencia: Entorno domótico no conectado.")

    def enviar_comando(self, comando):
        if self.arduino:
            self.arduino.write(comando.encode('utf-8'))
            print(f"Comando enviado: {comando}")
        else:
            print(f"[Simulación Serial] Comando: {comando}")

    def encender_luz(self):
        self.enviar_comando('L')

    def avanzar(self):
        self.enviar_comando('W')

    def detener(self):
        self.enviar_comando('S')

    def girar_izquierda(self):
        self.enviar_comando('A')

    def girar_derecha(self):
        self.enviar_comando('D')