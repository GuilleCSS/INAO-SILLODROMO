# Sillodromo - Interfaz de Control Accesible y Sistema ADAS

Sillodromo es un sistema avanzado de control para sillas de ruedas automatizadas, diseñado para usuarios con movilidad reducida. Utiliza visión por computadora para traducir los movimientos de la cabeza y bioseñales faciales en comandos de navegación físicos, incorporando un sistema de seguridad anticolisión autónomo.

## 🏗️ Arquitectura de Software y Ramas (Branches)

Este proyecto fue desarrollado bajo un enfoque modular, permitiendo escalar los requerimientos de procesamiento de acuerdo con el hardware disponible. El repositorio cuenta con 3 ramas principales:

*   **`main` (Precisión Clínica - OpenFace):** Utiliza modelos topológicos compilados en C++ para extraer Action Units (AUs) con alta fiabilidad, ideal para entornos controlados y hardware de alto rendimiento.
*   **`feature/mediapipe-fallback` (Alta Portabilidad - MediaPipe):** Implementación ligera en Python/TensorFlow Lite. Calcula ángulos de Euler (Pitch/Yaw) y biometría ocular (EAR) para lograr cero latencia sin depender de binarios externos.
*   **`feature/yolo-detection` (Visión Multimodal y Seguridad):** La versión definitiva para entornos reales. Combina MediaPipe para el control de navegación continuo con YOLOv8n (Red Neuronal Convolucional) como Sistema Avanzado de Asistencia (ADAS), forzando paros de emergencia autónomos ante obstáculos físicos.

## ⚙️ Tecnologías Utilizadas
*   **Interfaz:** PyQt5 (Python)
*   **Visión Artificial:** OpenCV, MediaPipe, Ultralytics (YOLOv8), OpenFace
*   **Hardware (Microcontrolador):** C++ (Arduino/ESP32) vía Comunicación Serial
*   **Audio:** PyTTSx3 (Sintetizador de voz)

## 🛠️ Instalación y Configuración

1. **Clonar el repositorio y seleccionar la arquitectura deseada:**
   ```bash
   git clone [https://github.com/GuilleCSS/INAO-SILLODROMO.git](https://github.com/GuilleCSS/INAO-SILLODROMO.git)
   cd INAO-SILLODROMO
   git checkout feature/yolo-detection
   ```

2. **Instalar dependencias:**
   Se recomienda el uso de un entorno virtual para mantener la compatibilidad (específicamente Numpy 1.26.4).
   ```bash
   pip install -r requirements.txt
   ```

3. **Configuración de Hardware (`config.json`):**
   *   Ajustar `camera_index` (0 para webcam interna, 1 para externa).
   *   Configurar el `puerto_serial` asignado al microcontrolador (ej. "COM3").

4. **Ejecución:**
   ```bash
   python main_app.py
   ```

## 🧠 Lógica del Sistema de Seguridad (Rama YOLO)
El vehículo implementa **Reanudación Explícita**. Si la red convolucional detecta una obstrucción en el área frontal (mayor al 40% del encuadre), la máquina de estados interrumpe el control facial, detiene los motores y emite una alerta auditiva. El sistema requiere que el obstáculo sea retirado y que el usuario emita una nueva orden de avance consciente para reanudar la marcha.