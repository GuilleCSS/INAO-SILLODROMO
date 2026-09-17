import pyttsx3
import threading

def hablar_en_segundo_plano(texto):
    def run_tts():
        motor = pyttsx3.init()
        motor.setProperty('rate', 150)
        motor.say(texto)
        motor.runAndWait()
    
    hilo = threading.Thread(target=run_tts)
    hilo.start()