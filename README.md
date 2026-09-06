# Riego automatizado del huerto

Sistema de riego por zonas con Raspberry Pi. Controla 5 electroválvulas y una bomba, regando cada sección en secuencia según un horario fijo.

Huerto de 1 hectárea, 5 secciones de ~10 árboles, tinaco de 2000 L con bomba eléctrica.

---

## Estado

| Fase | Descripción | Estado |
|---|---|---|
| 1 | Raspberry Pi funcionando, GPIO básico | en curso |
| 2 | Relés respondiendo en banco de pruebas | pendiente |
| 3 | Una válvula abriendo por software | pendiente |
| 4 | Instalación en campo | pendiente |
| 5 | Automatización con systemd | pendiente |

---

## Probarlo sin hardware

El script corre en **modo simulación** por defecto: imprime lo que haría con cada pin sin tocar nada. Puedes validar toda la lógica en cualquier computadora, sin Raspberry ni válvulas.

```bash
pip install -r requirements.txt
python3 riego.py --test
```

Verás la secuencia completa de las 5 zonas con 3 segundos cada una.

---

## Uso

```bash
python3 riego.py                  # ciclo completo con los tiempos de config.yaml
python3 riego.py --zona 2         # solo la zona 2
python3 riego.py --minutos 5      # sobrescribe la duración
python3 riego.py --test           # ciclo rápido, 3 s por zona
python3 riego.py --cerrar-todo    # apaga bomba y válvulas, y sale
```

---

## Configuración

Todo vive en `config.yaml`. Lo que más vas a tocar:

```yaml
hardware:
  gpio_real: false          # true cuando estés en la Raspberry
  rele_activo_en_alto: true # según el jumper de tu módulo de relés

zonas:
  - nombre: "Sección 1 - Norte"
    pin: 22
    minutos: 15
```

Los pines usan numeración **BCM**, no la física del conector.

---

## La secuencia de seguridad

Este es el corazón del sistema y la razón por la que el código está estructurado así:

```
1. Abrir la válvula de la zona
2. Esperar 3 segundos
3. Arrancar la bomba
4. Regar el tiempo programado
5. Apagar la bomba
6. Esperar 5 segundos
7. Cerrar la válvula
```

**Nunca al revés.** Una bomba centrífuga presurizando contra válvulas cerradas recircula agua que se calienta y daña el sello mecánico en minutos.

El cierre de la válvula está en un bloque `finally`, así que ocurre pase lo que pase: error, Ctrl+C, o excepción inesperada. Nunca queda agua corriendo.

### Otras protecciones

- **Estado conocido al arrancar.** Lo primero que hace es cerrar todo. Si se fue la luz a media operación, no sabemos cómo quedaron las válvulas físicamente; arrancar cerrando elimina esa incertidumbre.
- **Tope duro por zona.** Si la configuración pide 300 minutos por un error de dedo, el código lo limita a `max_minutos_por_zona`. Los límites en código evitan que un typo vacíe el tinaco.
- **Flotador de nivel.** Con `requiere_flotador: true`, aborta el riego si el tinaco está vacío. Una bomba trabajando en seco se destruye en minutos.
- **Interrupción limpia.** Ctrl+C o SIGTERM cierran todo ordenadamente en lugar de dejar el sistema a medias.

---

## Instalación en la Raspberry Pi

```bash
sudo apt update
sudo apt install -y python3-pip python3-yaml python3-rpi.gpio git

git clone https://github.com/TU_USUARIO/riego-huerto.git
cd riego-huerto
```

Activa el hardware real en `config.yaml`:

```yaml
hardware:
  gpio_real: true
```

Prueba una zona con la válvula desconectada primero, escuchando los clics del relé:

```bash
python3 riego.py --zona 1 --minutos 0.1
```

---

## Automatizar con systemd

```bash
sudo cp systemd/riego.service systemd/riego.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now riego.timer

systemctl list-timers riego.timer    # ver cuándo corre
journalctl -u riego.service -f       # ver los logs en vivo
```

El timer está configurado con `Persistent=false` a propósito: si la Pi estuvo apagada a las 6 AM, **no** debe regar al encenderla a las 3 PM bajo el sol. Un riego perdido no pasa nada; uno a destiempo desperdicia agua y estresa a los árboles.

---

## Hardware

### Banco de pruebas

| Componente | Detalle |
|---|---|
| Raspberry Pi 4 Model B | 4 GB |
| Módulo de relés | 8 canales, 5V, **con optoacoplador**, disparo alto/bajo |
| Electroválvula | 2W-250-25, 12V DC, 1", acción directa |
| Fuente | 12V 5A para la válvula |
| Diodos | 1N4007 en paralelo a cada válvula (banda blanca al positivo) |

### Campo

Las válvulas de 12V DC **no sirven para el campo**. Con tramos de 80-100 m, la caída de voltaje a 1.7 A deja la válvula sin fuerza para abrir. Además la corriente directa causa corrosión electrolítica en empalmes enterrados.

Para el campo: **electroválvulas de riego de 24 VAC** (Rain Bird, Hunter) con transformador de 110V a 24 VAC, 40 VA. Consumen ~0.25 A, así que la caída en 100 m es de apenas 1 V.

En 24 VAC los diodos flyback **no aplican** — se usa un snubber RC o un MOV.

### La bomba

La bomba **nunca** se conecta directo a un relé del módulo. Va por un **contactor** dimensionado según sus HP, y ese cableado de 110 V lo hace un electricista.

---

## Diodos flyback

Una bobina de solenoide es una carga inductiva: al cortarle la corriente genera un pico de voltaje que va picando los contactos del relé hasta quemarlos.

Un diodo 1N4007 en paralelo a cada válvula, con la **banda blanca hacia el positivo**, absorbe ese pico. Cuestan centavos y son la diferencia entre relés que duran años y relés que fallan en meses.

Al revés, cortocircuitas la fuente en cuanto energices. Revisa la orientación dos veces.

---

## Pendientes

- [ ] Sensor de lluvia — evita regar después de una tormenta. Es lo más rentable de agregar
- [ ] Caudalímetro para detectar fugas: si el consumo de una zona sube de golpe, hay un tubo roto
- [ ] Panel web para disparar riegos manuales desde el celular
- [ ] Notificaciones cuando algo falla
- [ ] Sensores de humedad de suelo por zona (dejar para el final: se ensucian, se corroen y hay que calibrarlos)
