# Guía de pruebas de hardware

De la Raspberry Pi a una válvula abriendo por software. En tres etapas, cada una verificable antes de pasar a la siguiente.

**La regla de oro:** no conectes la válvula hasta que los relés respondan correctamente sin ella. Si conectas todo de golpe y algo falla, no sabrás si es el código, el cableado o el módulo.

---

## Antes de empezar

Ten a la mano:

- Raspberry Pi 4 con Raspberry Pi OS y el repo clonado
- Módulo de relés de 8 canales, 5V, con optoacoplador
- Cables dupont hembra-hembra
- Fuente de 12V 5A y adaptador de barril a tornillo
- Electroválvula 2W-250-25 de 12V DC
- Un diodo 1N4007
- Multímetro, si lo tienes

**Trabaja siempre con la Pi apagada al conectar o desconectar cables.** Conectar en caliente es la forma más común de quemar un GPIO, y no hay reparación: se cambia la placa.

```bash
sudo shutdown -h now
```

Espera a que el LED verde deje de parpadear del todo antes de desconectar la corriente.

---

## Etapa 1 — Conectar la Pi al módulo de relés

Solo el lado de señal. Nada de 12V todavía.

### El cableado

Los pines de la Pi se nombran de dos formas y es fácil confundirse. La columna **BCM** es la que usa el código; la columna **físico** es la posición real en el conector de 40 pines, contando desde la esquina.

| Señal | BCM | Pin físico | Va a |
|---|---|---|---|
| Alimentación | 5V | **2** | VCC del módulo |
| Tierra | GND | **6** | GND del módulo |
| Válvula maestra | 17 | **11** | IN6 |
| Zona 1 | 22 | **15** | IN1 |
| Zona 2 | 23 | **16** | IN2 |
| Zona 3 | 24 | **18** | IN3 |
| Zona 4 | 25 | **22** | IN4 |
| Zona 5 | 5 | **29** | IN5 |

Los canales IN7 e IN8 quedan libres para el sensor de lluvia más adelante.

Para ubicar los pines físicos: el pin 1 es el que tiene la esquina cuadrada en la serigrafía, del lado del borde de la placa. Los impares van en una fila y los pares en la otra. Si dudas, en la Pi:

```bash
pinout
```

Te dibuja el conector completo en la terminal.

### Los dos jumpers del módulo

Antes de alimentar nada, revisa estos dos. Determinan si el sistema funciona bien o te da problemas raros.

**Jumper de disparo (alto/bajo).** Ponlo en **nivel ALTO**.

Con disparo alto, un GPIO en 0 deja el relé abierto y la válvula cerrada. Como los GPIO arrancan en 0 al encender la Pi, eso significa que durante el arranque —antes de que tu script corra— todas las válvulas están cerradas. Con disparo bajo pasaría lo contrario: se abrirían todas al prender la Pi, y lo descubrirías con el tinaco vaciándose.

Tu `config.yaml` ya está puesto para esto:

```yaml
rele_activo_en_alto: true
```

**Jumper VCC — JD-VCC.** Déjalo puesto **por ahora**, para estas pruebas. Alimenta las bobinas de los relés desde los 5V de la Pi, que es suficiente porque nunca tendrás más de dos relés activos a la vez.

Cuando montes el sistema definitivo en el campo, quítalo y alimenta JD-VCC desde una fuente de 5V aparte. Eso hace que el optoacoplador aísle de verdad la Pi del lado de potencia. Para el banco de pruebas no hace falta.

### Verificación

Enciende la Pi y conéctate:

```bash
ssh paul@riego.local
```

Prueba un canal a mano:

```bash
pinctrl set 22 op dh    # debe sonar un CLIC
pinctrl get 22

pinctrl set 22 op dl    # debe sonar otro CLIC
pinctrl get 22
```

**Qué debes observar:**

- Un clic mecánico audible en cada cambio
- El LED del canal 1 del módulo encendiéndose y apagándose
- `pinctrl get` reportando `dh` y luego `dl`

Si no hay clic pero el LED de alimentación del módulo está encendido, lo más probable es que el jumper de disparo esté al revés. Prueba invertirlo.

Si no hay ni clic ni LED, revisa VCC y GND: son los dos cables que más se olvidan.

### Probar los seis canales

```bash
for p in 22 23 24 25 5 17; do
  echo "Probando GPIO $p"
  pinctrl set $p op dh
  sleep 1
  pinctrl set $p op dl
  sleep 1
done
```

Deberías escuchar doce clics en total, en orden. Anota si alguno no responde — ese canal puede estar dañado y conviene saberlo antes de cablear la válvula.

### Probar con el script

```bash
cd riego-huerto
git pull
nano config.yaml
```

Cambia una línea:

```yaml
hardware:
  gpio_real: true
```

Y corre un ciclo rápido:

```bash
python3 riego.py --test
```

Ahora los mensajes `ABRE` y `CIERRA` del log deben coincidir exactamente con los clics que escuchas. Ese es el momento en que el software y el hardware se encuentran.

**No sigas a la etapa 2 hasta que esto funcione sin fallas.**

---

## Etapa 2 — Conectar la válvula

Apaga la Pi antes de cablear.

### Cómo funciona un relé

El relé es un interruptor mecánico. Tiene tres terminales por canal:

- **COM** — común, la entrada
- **NO** — normalmente abierto: conectado a COM **solo** cuando el relé está activo
- **NC** — normalmente cerrado: al revés

Usas **COM** y **NO**. Así, sin corriente, la válvula está cerrada.

El relé **no alimenta nada** — solo abre y cierra el paso. Los 12V vienen de tu fuente.

### El circuito

```
  Fuente 12V (+) ─────────── COM  (canal 1)
                              │
                             NO  ──────────── Válvula (cable 1)
                                                   │
                                              [1N4007]   banda blanca
                                                   │     hacia el (+)
  Fuente 12V (−) ─────────────────────────── Válvula (cable 2)
```

Paso a paso:

1. Positivo de la fuente de 12V → terminal **COM** del canal 1
2. Terminal **NO** del canal 1 → un cable de la válvula
3. El otro cable de la válvula → negativo de la fuente
4. El **diodo 1N4007 en paralelo con la válvula**, con la banda blanca del lado que va al positivo

Tu válvula tiene cables azul y amarillo. Al ser corriente continua **sí importa la polaridad de la bobina**, aunque la mayoría de estas válvulas funcionan en ambos sentidos. Si al energizar no abre, invierte los dos cables.

### El diodo, otra vez

Va **en paralelo con la válvula**, no en serie. Las dos patas del diodo tocan los dos cables de la válvula.

La **banda blanca** apunta al cable que va al positivo. Al revés, cortocircuitas la fuente en cuanto energices. Revísalo dos veces antes de conectar la corriente.

Sin diodo, cada vez que cortas la corriente la bobina genera un pico de voltaje que pica los contactos del relé. Funcionará igual al principio, pero los relés se degradan en meses en vez de durar años.

### Antes de energizar

Con la fuente **desconectada**, comprueba con el multímetro:

- **Continuidad entre COM y NO** con el relé en reposo → **no debe haber**. Si hay, el relé está soldado o cableaste en NC
- **Resistencia de la bobina de la válvula** → unos pocos ohms. Si marca 0, hay corto; si marca infinito, la bobina está abierta

### La prueba

Enciende la Pi, conecta la fuente de 12V, y:

```bash
cd riego-huerto
python3 riego.py --zona 1 --minutos 0.2
```

Son 12 segundos. Lo que debes ver y oír:

1. Clic del relé de zona 1
2. **Clac** más fuerte y grave: la válvula abriendo
3. Doce segundos
4. Clac de la válvula cerrando
5. Clic del relé

La válvula hace un sonido distinto al relé — más pesado, y se siente la vibración si la tocas.

### Medir el consumo

Si tienes multímetro, aprovecha: ponlo en serie con la válvula, en modo amperios (escala de 10A), y mide mientras está abierta.

Esperado: entre 1.5 y 2 amperios. Ese número te sirve para dimensionar la fuente del sistema final y confirmar que los 5A que compraste son suficientes.

---

## Etapa 3 — Con agua

Solo cuando la etapa 2 funcione sin fallas.

Conecta la válvula a una manguera con agua de la llave. No necesitas todavía el tinaco ni las tuberías del huerto — una cubeta y una manguera bastan para ver si abre y cierra de verdad.

```bash
python3 riego.py --zona 1 --minutos 0.5
```

**Qué observar:**

- El agua debe salir al abrir y **cortarse por completo** al cerrar
- Un goteo persistente después del cierre significa basura en el asiento de la válvula
- Un golpe seco en la manguera al cerrar es **golpe de ariete** — normal en una prueba corta, pero por eso el código cierra la maestra antes que la zona en el sistema completo

También mide el caudal: llena una cubeta de volumen conocido y cronometra. Con litros por minuto podemos calcular cuántos minutos necesita cada sección para entregar sus 800 litros.

---

## Si algo no funciona

| Síntoma | Causa probable |
|---|---|
| No hay clic ni LED en el módulo | VCC o GND desconectados |
| LED de alimentación sí, pero no hay clic | Jumper de disparo invertido |
| Todos los relés se activan al encender la Pi | Jumper en nivel bajo — cámbialo a alto |
| Clic del relé pero la válvula no abre | Fuente de 12V desconectada, o cableaste en NC |
| La válvula vibra sin abrir | Voltaje insuficiente: revisa la fuente y la sección del cable |
| La Pi se reinicia al activar un relé | Las bobinas consumen demasiado de los 5V: quita el jumper JD-VCC y usa fuente aparte |
| Un canal específico no responde | Prueba ese GPIO con `pinctrl` directo, para aislar si es la Pi o el módulo |

---

## Lo que NO debes hacer

- **Alimentar la válvula desde los 5V o 3.3V de la Pi.** Consume 1.7A; la Pi entrega miliamperios. Quemarías la placa
- **Usar cables dupont para el circuito de 12V.** Son 26 AWG, soportan menos de 1A. Usa cable de 18 o 20 AWG
- **Conectar o desconectar con la Pi encendida**
- **Saltarte el diodo** porque "de todos modos funciona"
- **Pasar a la siguiente etapa** con algo de la anterior a medias

---

## Después de esto

Con la etapa 3 completa tienes validado el sistema entero en pequeño: software, relés, válvula y agua. Lo que sigue es multiplicarlo por seis y llevarlo al campo, que es trabajo de instalación, no de diseño.

Y recuerda el cambio de voltaje: para el campo son válvulas de **24 VAC**, no las de 12V DC. El código no cambia; solo el hardware de potencia y, en AC, el diodo se sustituye por un snubber RC.
