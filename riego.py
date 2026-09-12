#!/usr/bin/env python3
"""
Sistema de riego automatizado para huerto.

Diseno: dos tinacos de 2000 L alimentados de la red municipal. Una
valvula maestra controla la salida hacia el riego, y cinco valvulas
de zona reparten el agua por secciones.

Riega las zonas en secuencia, una a la vez, respetando este orden:

    abrir zona -> esperar -> abrir maestra -> regar
    -> cerrar maestra -> esperar -> cerrar zona

El orden importa. Abrir la zona primero evita presurizar contra un
extremo cerrado, y cerrar la maestra antes deja que la linea se
despresurice a traves de la zona abierta. Eso reduce el golpe de
ariete, que con el tiempo rompe conexiones.

Uso:
    python3 riego.py                  # ciclo completo, todas las zonas
    python3 riego.py --zona 2         # solo la zona 2
    python3 riego.py --minutos 1      # sobrescribe el tiempo (pruebas)
    python3 riego.py --test           # ciclo rapido de 3s por zona
    python3 riego.py --cerrar-todo    # cierra todo y sale
"""

import argparse
import logging
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent
CONFIG_POR_DEFECTO = RAIZ / "config.yaml"


# --------------------------------------------------------------------------
# Capa de hardware
#
# Toda interaccion con los pines pasa por aqui. En modo simulacion se
# imprime lo que haria, sin tocar nada. Eso permite probar la logica
# completa en cualquier computadora, sin Raspberry ni valvulas.
# --------------------------------------------------------------------------

class ControladorGPIO:
    """Envuelve el acceso a los pines. Real o simulado."""

    def __init__(self, real: bool, activo_en_alto: bool, log: logging.Logger):
        self.real = real
        self.activo_en_alto = activo_en_alto
        self.log = log
        self.gpio = None
        self._estado: dict[int, bool] = {}

        if self.real:
            try:
                import RPi.GPIO as GPIO
            except ImportError:
                self.log.error(
                    "No se pudo importar RPi.GPIO. "
                    "Estas en una Raspberry Pi? Instala: sudo apt install python3-rpi.gpio. "
                    "Para probar sin hardware, pon gpio_real: false en config.yaml"
                )
                raise
            self.gpio = GPIO
            self.gpio.setmode(self.gpio.BCM)
            self.gpio.setwarnings(False)
        else:
            self.log.info("MODO SIMULACION - no se tocara ningun pin real")

    def configurar_salida(self, pin: int) -> None:
        """Configura un pin como salida y lo deja cerrado."""
        if self.real:
            # Se configura ya en estado inactivo para que el rele no
            # haga un pulso al arrancar el programa.
            inactivo = self.gpio.LOW if self.activo_en_alto else self.gpio.HIGH
            self.gpio.setup(pin, self.gpio.OUT, initial=inactivo)
        self._estado[pin] = False

    def configurar_entrada(self, pin: int) -> None:
        """Configura un pin como entrada con resistencia pull-down."""
        if self.real:
            self.gpio.setup(pin, self.gpio.IN, pull_up_down=self.gpio.PUD_DOWN)

    def abrir(self, pin: int, etiqueta: str) -> None:
        if self.real:
            nivel = self.gpio.HIGH if self.activo_en_alto else self.gpio.LOW
            self.gpio.output(pin, nivel)
        self._estado[pin] = True
        self.log.info("ABRE   pin %-3s  %s", pin, etiqueta)

    def cerrar(self, pin: int, etiqueta: str) -> None:
        if self.real:
            nivel = self.gpio.LOW if self.activo_en_alto else self.gpio.HIGH
            self.gpio.output(pin, nivel)
        self._estado[pin] = False
        self.log.info("CIERRA pin %-3s  %s", pin, etiqueta)

    def leer(self, pin: int) -> bool:
        if self.real:
            return bool(self.gpio.input(pin))
        # En simulacion asumimos que siempre hay agua.
        return True

    def abiertos(self) -> list[int]:
        return [p for p, on in self._estado.items() if on]

    def liberar(self) -> None:
        if self.real and self.gpio is not None:
            self.gpio.cleanup()


# --------------------------------------------------------------------------
# Modelo
# --------------------------------------------------------------------------

@dataclass
class Zona:
    nombre: str
    pin: int
    minutos: float


class SistemaRiego:

    def __init__(self, config: dict, log: logging.Logger):
        self.config = config
        self.log = log

        hw = config["hardware"]
        self.gpio = ControladorGPIO(
            real=hw["gpio_real"],
            activo_en_alto=hw["rele_activo_en_alto"],
            log=log,
        )

        pines = config["pines"]
        self.pin_maestra = pines["valvula_maestra"]
        self.pin_flotador = pines["flotador"]

        seg = config["seguridad"]
        self.retardo_zona_maestra = seg["retardo_zona_maestra"]
        self.retardo_maestra_zona = seg["retardo_maestra_zona"]
        self.max_minutos = seg["max_minutos_por_zona"]
        self.requiere_flotador = seg["requiere_flotador"]

        self.zonas = [
            Zona(nombre=z["nombre"], pin=z["pin"], minutos=z["minutos"])
            for z in config["zonas"]
        ]

        self._interrumpido = False

    # -- ciclo de vida --------------------------------------------------

    def preparar(self) -> None:
        """Configura los pines y deja todo en estado conocido.

        Esto es deliberado: si se fue la luz a media operacion, al volver
        no sabemos como quedaron las valvulas fisicamente. Arrancar
        cerrando todo elimina esa incertidumbre.
        """
        self.gpio.configurar_salida(self.pin_maestra)
        for zona in self.zonas:
            self.gpio.configurar_salida(zona.pin)
        self.gpio.configurar_entrada(self.pin_flotador)

        self.log.info("Estado inicial: todo cerrado")
        self.cerrar_todo(silencioso=True)

    def cerrar_todo(self, silencioso: bool = False) -> None:
        """Cierra la maestra primero, luego las zonas. El orden importa."""
        if not silencioso:
            self.log.warning("Cerrando todo")
        self.gpio.cerrar(self.pin_maestra, "VALVULA MAESTRA")
        for zona in self.zonas:
            self.gpio.cerrar(zona.pin, f"zona {zona.nombre}")

    def liberar(self) -> None:
        self.gpio.liberar()

    # -- comprobaciones -------------------------------------------------

    def hay_agua(self) -> bool:
        """Consulta el flotador de los tinacos."""
        if not self.requiere_flotador:
            return True
        nivel = self.gpio.leer(self.pin_flotador)
        if not nivel:
            self.log.error("Flotador indica tinacos vacios")
        return nivel

    def _minutos_seguros(self, pedidos: float) -> float:
        if pedidos > self.max_minutos:
            self.log.warning(
                "Zona pide %s min pero el tope es %s. Se limita.",
                pedidos, self.max_minutos,
            )
            return self.max_minutos
        return pedidos

    # -- riego ----------------------------------------------------------

    def _esperar(self, segundos: float, etiqueta: str) -> bool:
        """Espera en tramos de 1s para poder abortar rapido con Ctrl+C.

        Devuelve False si se interrumpio.
        """
        fin = time.monotonic() + segundos
        while time.monotonic() < fin:
            if self._interrumpido:
                return False
            time.sleep(min(1.0, max(0.0, fin - time.monotonic())))
        return True

    def regar_zona(self, zona: Zona, minutos: float | None = None) -> bool:
        """Riega una zona respetando la secuencia de seguridad."""
        duracion = self._minutos_seguros(
            zona.minutos if minutos is None else minutos
        )
        segundos = duracion * 60

        if not self.hay_agua():
            self.log.error("Se aborta %s por falta de agua", zona.nombre)
            return False

        self.log.info("--- %s | %.1f min ---", zona.nombre, duracion)

        try:
            # 1. Abrir la zona ANTES que la maestra, para no presurizar
            #    contra un extremo cerrado.
            self.gpio.abrir(zona.pin, f"zona {zona.nombre}")
            if not self._esperar(self.retardo_zona_maestra, "apertura de zona"):
                return False

            # 2. Ahora si, el agua tiene por donde salir.
            self.gpio.abrir(self.pin_maestra, "VALVULA MAESTRA")

            # 3. Regar.
            completo = self._esperar(segundos, "riego")

            # 4. Cerrar la maestra ANTES que la zona. La linea se
            #    despresuriza a traves de la zona, aun abierta.
            self.gpio.cerrar(self.pin_maestra, "VALVULA MAESTRA")
            self._esperar(self.retardo_maestra_zona, "despresurizacion")

            return completo

        finally:
            # Pase lo que pase (error, Ctrl+C, excepcion), la zona se
            # cierra. Es la garantia de que no queda agua corriendo.
            self.gpio.cerrar(zona.pin, f"zona {zona.nombre}")

    def ciclo_completo(self, minutos: float | None = None) -> None:
        inicio = time.monotonic()
        self.log.info("=== Inicio del ciclo de riego ===")

        regadas = 0
        for zona in self.zonas:
            if self._interrumpido:
                break
            if self.regar_zona(zona, minutos):
                regadas += 1
            else:
                self.log.warning("Zona %s no se completo", zona.nombre)

        transcurrido = (time.monotonic() - inicio) / 60
        self.log.info(
            "=== Fin del ciclo: %d de %d zonas en %.1f min ===",
            regadas, len(self.zonas), transcurrido,
        )

    def marcar_interrupcion(self) -> None:
        self._interrumpido = True


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------

def cargar_config(ruta: Path) -> dict:
    if not ruta.exists():
        print(f"No se encontro el archivo de configuracion: {ruta}", file=sys.stderr)
        sys.exit(1)
    with ruta.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def preparar_log(config: dict) -> logging.Logger:
    reg = config.get("registro", {})
    archivo = RAIZ / reg.get("archivo", "riego.log")
    nivel = getattr(logging, reg.get("nivel", "INFO").upper(), logging.INFO)

    log = logging.getLogger("riego")
    log.setLevel(nivel)
    log.handlers.clear()

    formato = logging.Formatter(
        "%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    consola = logging.StreamHandler(sys.stdout)
    consola.setFormatter(formato)
    log.addHandler(consola)

    try:
        fichero = logging.FileHandler(archivo, encoding="utf-8")
        fichero.setFormatter(formato)
        log.addHandler(fichero)
    except OSError as e:
        print(f"Aviso: no se pudo escribir el log en {archivo}: {e}", file=sys.stderr)

    return log


def main() -> int:
    ap = argparse.ArgumentParser(description="Riego automatizado del huerto")
    ap.add_argument("--config", type=Path, default=CONFIG_POR_DEFECTO,
                    help="Ruta al archivo de configuracion")
    ap.add_argument("--zona", type=int, metavar="N",
                    help="Riega solo la zona N (1 a 5)")
    ap.add_argument("--minutos", type=float, metavar="M",
                    help="Sobrescribe los minutos de riego")
    ap.add_argument("--test", action="store_true",
                    help="Ciclo rapido: 3 segundos por zona")
    ap.add_argument("--cerrar-todo", action="store_true",
                    help="Cierra maestra y zonas, y termina")
    args = ap.parse_args()

    config = cargar_config(args.config)
    log = preparar_log(config)

    sistema = SistemaRiego(config, log)

    def manejar_senal(signum, frame):
        log.warning("Interrupcion recibida. Cerrando de forma segura.")
        sistema.marcar_interrupcion()

    signal.signal(signal.SIGINT, manejar_senal)
    signal.signal(signal.SIGTERM, manejar_senal)

    try:
        sistema.preparar()

        if args.cerrar_todo:
            log.info("Todo cerrado por peticion explicita")
            return 0

        minutos = args.minutos
        if args.test:
            minutos = 3 / 60  # 3 segundos

        if args.zona is not None:
            if not 1 <= args.zona <= len(sistema.zonas):
                log.error("Zona invalida: %s (hay %d)", args.zona, len(sistema.zonas))
                return 1
            sistema.regar_zona(sistema.zonas[args.zona - 1], minutos)
        else:
            sistema.ciclo_completo(minutos)

        return 0

    except Exception:
        log.exception("Error inesperado. Se cierra todo por seguridad.")
        return 1

    finally:
        sistema.cerrar_todo()
        sistema.liberar()


if __name__ == "__main__":
    sys.exit(main())
