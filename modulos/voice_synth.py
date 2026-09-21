import sys
import os
import asyncio
import tempfile
import subprocess
import time

import edge_tts
import pygame


# ============================================================
# CONFIGURACIÓN DE VOZ
# ============================================================

VOZ = "es-MX-JorgeNeural"

VELOCIDAD = "-5%"
VOLUMEN = "+0%"
TONO = "-15Hz"

# Pequeña pausa SOLO para comandos de encendido
RETARDO_ENCENDIDO = 0.05


# ============================================================
# GENERAR AUDIO
# ============================================================

async def generar_audio(texto, archivo):

    comunicacion = edge_tts.Communicate(
        text=texto,
        voice=VOZ,
        rate=VELOCIDAD,
        volume=VOLUMEN,
        pitch=TONO
    )

    await comunicacion.save(archivo)


# ============================================================
# REPRODUCIR AUDIO
# ============================================================

def reproducir(archivo):

    pygame.mixer.music.load(archivo)
    pygame.mixer.music.play()

    while pygame.mixer.music.get_busy():
        time.sleep(0.02)

    pygame.mixer.music.unload()


# ============================================================
# CREAR ARCHIVO TEMPORAL
# ============================================================

def crear_temporal():

    archivo = tempfile.NamedTemporaryFile(
        delete=False,
        suffix=".mp3"
    )

    ruta = archivo.name
    archivo.close()

    return ruta


# ============================================================
# HABLAR
# ============================================================

async def hablar(texto):

    texto = texto.strip()

    pygame.mixer.init()

    try:

        # ====================================================
        # CASO ESPECIAL:
        # "Alexa, enciende..."
        # ====================================================

        if texto.lower().startswith("alexa, enciende"):

            # Quitamos "Alexa," y dejamos solamente
            # "enciende enchufe dos", etc.
            comando = texto.split(",", 1)[1].strip()

            ruta_alexa = crear_temporal()
            ruta_comando = crear_temporal()

            # IMPORTANTE:
            # Generamos LOS DOS audios ANTES de reproducirlos.
            #
            # Así no hay retraso de Internet/TTS entre
            # "Alexa" y "enciende..."
            await asyncio.gather(
                generar_audio(
                    "Alexa",
                    ruta_alexa
                ),
                generar_audio(
                    comando,
                    ruta_comando
                )
            )

            # Decir palabra de activación
            reproducir(ruta_alexa)

            # Pausa muy pequeña
            time.sleep(RETARDO_ENCENDIDO)

            # Dar inmediatamente la instrucción
            reproducir(ruta_comando)

            # Limpiar archivos
            try:
                os.remove(ruta_alexa)
            except:
                pass

            try:
                os.remove(ruta_comando)
            except:
                pass

        # ====================================================
        # RESTO DE COMANDOS
        #
        # Por ejemplo:
        # Alexa, apaga enchufe dos
        #
        # Se mantienen de corrido porque ya funcionan.
        # ====================================================

        else:

            ruta = crear_temporal()

            await generar_audio(
                texto,
                ruta
            )

            reproducir(ruta)

            try:
                os.remove(ruta)
            except:
                pass

    finally:

        pygame.mixer.quit()


# ============================================================
# HABLAR EN SEGUNDO PLANO
# ============================================================

def hablar_en_segundo_plano(texto):

    subprocess.Popen(
        [
            sys.executable,
            os.path.abspath(__file__),
            texto
        ],
        creationflags=(
            subprocess.CREATE_NO_WINDOW
            if os.name == "nt"
            else 0
        )
    )


# ============================================================
# EJECUCIÓN INDEPENDIENTE
# ============================================================

if __name__ == "__main__":

    if len(sys.argv) > 1:

        texto_recibido = sys.argv[1]

        asyncio.run(
            hablar(texto_recibido)
        )