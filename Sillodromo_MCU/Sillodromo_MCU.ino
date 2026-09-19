// --- PINES PARA EL PUENTE H (Ej. L298N o BTS7960) ---
// Motor Izquierdo
const int pinIN1 = 5; 
const int pinIN2 = 6;
// Motor Derecho
const int pinIN3 = 9;
const int pinIN4 = 10;

// --- PIN PARA DOMÓTICA ---
const int pinReleLuz = 12;

// --- VARIABLES DE ESTADO ---
bool estadoLuz = false;
unsigned long ultimoComando = 0; // Para el sistema de seguridad (Watchdog)
const int TIEMPO_MAXIMO_SIN_DATOS = 500; // Si pasan 500ms sin conexión, frena.

void setup() {
  Serial.begin(9600); // Misma velocidad que configuraste en hardware_serial.py
  
  pinMode(pinIN1, OUTPUT);
  pinMode(pinIN2, OUTPUT);
  pinMode(pinIN3, OUTPUT);
  pinMode(pinIN4, OUTPUT);
  pinMode(pinReleLuz, OUTPUT);

  apagarMotores();
  digitalWrite(pinReleLuz, LOW);
}

void loop() {
  // 1. LECTURA DE COMANDOS DESDE PYTHON
  if (Serial.available() > 0) {
    char comando = Serial.read();
    ultimoComando = millis(); // Resetea el temporizador de seguridad

    switch (comando) {
      case 'W': // Avanzar
        avanzar();
        break;
      case 'S': // Detener (Paro de emergencia o soltar clic)
        apagarMotores();
        break;
      case 'A': // Girar Izquierda (Motor derecho avanza, izquierdo retrocede o se detiene)
        girarIzquierda();
        break;
      case 'D': // Girar Derecha
        girarDerecha();
        break;
      case 'L': // Alternar Luz
        estadoLuz = !estadoLuz;
        digitalWrite(pinReleLuz, estadoLuz ? HIGH : LOW);
        break;
    }
  }

  // 2. SISTEMA DE SEGURIDAD (WATCHDOG)
  // Si la comunicación con la laptop se pierde, detiene la silla de inmediato.
  if (millis() - ultimoComando > TIEMPO_MAXIMO_SIN_DATOS) {
    apagarMotores();
  }
}

// --- FUNCIONES DE MOVIMIENTO ---

void avanzar() {
  digitalWrite(pinIN1, HIGH);
  digitalWrite(pinIN2, LOW);
  digitalWrite(pinIN3, HIGH);
  digitalWrite(pinIN4, LOW);
}

void apagarMotores() {
  digitalWrite(pinIN1, LOW);
  digitalWrite(pinIN2, LOW);
  digitalWrite(pinIN3, LOW);
  digitalWrite(pinIN4, LOW);
}

void girarIzquierda() {
  digitalWrite(pinIN1, LOW);  // Izquierdo se detiene o va en reversa
  digitalWrite(pinIN2, HIGH); 
  digitalWrite(pinIN3, HIGH); // Derecho empuja
  digitalWrite(pinIN4, LOW);
}

void girarDerecha() {
  digitalWrite(pinIN1, HIGH); // Izquierdo empuja
  digitalWrite(pinIN2, LOW);
  digitalWrite(pinIN3, LOW);  // Derecho se detiene o va en reversa
  digitalWrite(pinIN4, HIGH);
}