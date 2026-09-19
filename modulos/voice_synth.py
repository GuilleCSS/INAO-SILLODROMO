import subprocess

def hablar_en_segundo_plano(texto):
    """
    Ejecuta un proceso de Python independiente para hablar.
    Esto evita bloqueos de hilos (threads) en Windows.
    """
    codigo = f"import pyttsx3; motor = pyttsx3.init(); motor.setProperty('rate', 170); motor.say('{texto}'); motor.runAndWait()"
    
    # Lanza el comando en segundo plano sin interrumpir la cámara
    subprocess.Popen(["python", "-c", codigo])