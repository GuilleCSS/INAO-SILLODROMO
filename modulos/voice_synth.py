"""
Síntesis de voz (edge-tts + pygame), con caché y una cola en el mismo proceso.

Antes, cada frase lanzaba un proceso de Python nuevo desde cero (arrancar
el intérprete + reimportar todo) Y sintetizaba por internet cada vez,
aunque fuera una frase que ya se había dicho antes ("Avanzando", "Sistema
Activado", los nombres de los puntos de calibración, etc. son un
vocabulario fijo que se repite todo el tiempo). Eso hacía que la voz se
sintiera con varios segundos de retraso.

Ahora: un solo hilo en segundo plano vive todo el programa y procesa una
cola en orden (nunca se pisan dos frases), y el audio de cada frase se
guarda en caché la primera vez que se dice — las siguientes veces se
reproduce directo desde disco, sin esperar la red.
"""

import os
import sys
import time
import queue
import asyncio
import hashlib
import threading

import edge_tts
import pygame

VOZ = "es-MX-JorgeNeural"
VELOCIDAD = "+10%"
VOLUMEN = "+0%"
TONO = "-15Hz"

# Pausa entre la palabra de activación ("Alexa") y el comando, para darle
# al Echo el instante que necesita para despertar antes de que empiece la
# orden. Se aplica a TODOS los comandos de Alexa: antes solo la recibían
# los de encender, así que los de apagar se decían de corrido y el Echo se
# perdía el principio de la frase.
RETARDO_ALEXA = 0.05

CACHE_DIR = "cache_voz"


# ============================================================
# CACHÉ DE AUDIO
# ============================================================

def _archivo_cache(texto):
    os.makedirs(CACHE_DIR, exist_ok=True)
    clave = hashlib.md5(texto.encode("utf-8")).hexdigest()
    return os.path.join(CACHE_DIR, f"{clave}.mp3")


async def _generar_audio(texto, archivo):
    comunicacion = edge_tts.Communicate(
        text=texto, voice=VOZ, rate=VELOCIDAD, volume=VOLUMEN, pitch=TONO
    )
    await comunicacion.save(archivo)


async def _asegurar_audio_async(texto):
    ruta = _archivo_cache(texto)
    if not os.path.exists(ruta):
        await _generar_audio(texto, ruta)
    return ruta


def _asegurar_audio(texto):
    return asyncio.run(_asegurar_audio_async(texto))


async def _preparar_alexa(comando):
    """Genera en paralelo "Alexa" + el comando, solo lo que falte en caché."""
    return await asyncio.gather(
        _asegurar_audio_async("Alexa"),
        _asegurar_audio_async(comando),
    )


# ============================================================
# REPRODUCIR
# ============================================================

def _reproducir(archivo):
    pygame.mixer.music.load(archivo)
    pygame.mixer.music.play()
    while pygame.mixer.music.get_busy():
        time.sleep(0.02)


# ============================================================
# COLA EN SEGUNDO PLANO (un solo hilo, dentro del mismo proceso)
# ============================================================

_cola = queue.Queue()
_hilo_iniciado = False
_lock_hilo = threading.Lock()


def _procesar_cola():
    pygame.mixer.init()
    while True:
        texto = _cola.get()
        try:
            texto = texto.strip()
            if texto.lower().startswith("alexa,"):
                comando = texto.split(",", 1)[1].strip()
                ruta_alexa, ruta_comando = asyncio.run(_preparar_alexa(comando))
                _reproducir(ruta_alexa)
                time.sleep(RETARDO_ALEXA)
                _reproducir(ruta_comando)
            else:
                _reproducir(_asegurar_audio(texto))
        except Exception as e:
            print(f"[voz] Error reproduciendo '{texto}': {e}")
        finally:
            _cola.task_done()


def hablar_en_segundo_plano(texto):
    global _hilo_iniciado
    if not _hilo_iniciado:
        with _lock_hilo:
            if not _hilo_iniciado:
                threading.Thread(target=_procesar_cola, daemon=True).start()
                _hilo_iniciado = True
    _cola.put(texto)


# ============================================================
# PRUEBA MANUAL: python modulos/voice_synth.py "texto a decir"
# ============================================================

if __name__ == "__main__":
    if len(sys.argv) > 1:
        pygame.mixer.init()
        _reproducir(_asegurar_audio(sys.argv[1]))
