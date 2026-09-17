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

    def encender_luz(self):
        if self.arduino:
            self.arduino.write(b'L')