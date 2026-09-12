# Riego automatizado del huerto

Sistema de riego por zonas con Raspberry Pi. Controla una válvula maestra y cinco electroválvulas de zona, regando cada sección en secuencia según un horario fijo.

Huerto de 1 hectárea, 5 secciones de ~10 árboles, dos tinacos de 2000 L alimentados de la red municipal.

---

## Arquitectura

```
    Red municipal
          │
    ┌─────┴─────┐
    │  Tinaco 1 │  2000 L      ── flotador de nivel ──┐
    │  Tinaco 2 │  2000 L                             │
    └─────┬─────┘                                     │
          │                                           │
   ┌──────┴───────┐                                   │
   │ VÁLVULA      │  ← solo abre durante el riego     │
   │ MAESTRA      │                                   │
   └──────┬───────┘                                   │
          │                                           │
   ┌──────┴──────┬──────┬──────┬──────┐              │
  Z1     Z2     Z3     Z4     Z5                      │
                                                      │
              Raspberry Pi ──── relés ────────────────┘
```

**No hay bomba.** El agua viene de la red municipal y llega por presión. Eso simplifica el sistema enormemente: no hay contactor, no hay motor de 110 V, y no hace falta un electricista. Todo queda en baja tensión.

### Por qué válvula maestra

Sin ella, la línea principal quedaría presurizada las 24 horas. Si una válvula de zona se atora abierta, gotea, o se rompe un tubo enterrado de madrugada, el agua corre hasta que alguien lo note — y con agua de red, eso se paga.

Con válvula maestra, la línea solo tiene presión durante los minutos del riego. El resto del día está despresurizada. Es la diferencia entre una fuga de 15 minutos y una de dos días.

Es práctica estándar en riego profesional, no un invento de este proyecto.

### Capacidad

4000 L entre 5 zonas son 800 L por sección, unos 80 L por árbol. Eso encaja con regar **una zona a la vez** en secuencia, que es como se diseñan estos sistemas: abrir todas juntas reparte la presión y ninguna riega bien.

---

## Estado

| Fase | Descripción | Estado |
|---|---|---|
| 1 | Raspberry Pi funcionando, GPIO verificado | ✅ |
| 2 | Relés respondiendo en banco de pruebas | pendiente |
| 3 | Una válvula abriendo por software | pendiente |
| 4 | Instalación en campo | pendiente |
| 5 | Automatización con systemd | pendiente |

---

## Probarlo sin hardware

El script corre en **modo simulación** por defecto: imprime lo que haría con cada pin sin tocar nada. Puedes validar toda la lógica en cualquier computadora.

```bash
pip install -r requirements.txt
python3 riego.py --test
```

---

## Uso

```bash
python3 riego.py                  # ciclo completo con los tiempos de config.yaml
python3 riego.py --zona 2         # solo la zona 2
python3 riego.py --minutos 5      # sobrescribe la duración
python3 riego.py --test           # ciclo rápido, 3 s por zona
python3 riego.py --cerrar-todo    # cierra todo y sale
```

---

## Configuración

Todo vive en `config.yaml`:

```yaml
hardware:
  gpio_real: false          # true cuando estés en la Raspberry
  rele_activo_en_alto: true # según el jumper de tu módulo de relés

pines:
  valvula_maestra: 17
  flotador: 27

zonas:
  - nombre: "Sección 1 - Norte"
    pin: 22
    minutos: 15
```

Los pines usan numeración **BCM**, no la física del conector.

---

## La secuencia de seguridad

```
1. Abrir la válvula de zona
2. Esperar 3 segundos
3. Abrir la válvula maestra
4. Regar el tiempo programado
5. Cerrar la válvula maestra
6. Esperar 5 segundos
7. Cerrar la válvula de zona
```

**El orden importa.** Abrir la zona primero evita presurizar contra un extremo cerrado. Cerrar la maestra antes deja que la línea se despresurice a través de la zona todavía abierta, lo que reduce el **golpe de ariete** — ese golpe seco cuando el agua se detiene de golpe, que con el tiempo revienta conexiones.

El cierre de la zona está en un bloque `finally`, así que ocurre pase lo que pase: error, Ctrl+C, o excepción inesperada. Nunca queda agua corriendo.

### Otras protecciones

- **Estado conocido al arrancar.** Lo primero que hace es cerrar todo. Si se fue la luz a media operación, no sabemos cómo quedaron las válvulas físicamente; arrancar cerrando elimina esa incertidumbre.
- **Tope duro por zona.** Si la configuración pide 300 minutos por un error de dedo, el código lo limita a `max_minutos_por_zona`.
- **Flotador de nivel.** Con `requiere_flotador: true`, aborta si los tinacos están vacíos. Evita regar en vacío y meter aire a la línea.
- **Interrupción limpia.** Ctrl+C o SIGTERM cierran todo ordenadamente.

---

## Instalación en la Raspberry Pi

```bash
sudo apt update
sudo apt install -y git python3-yaml python3-rpi.gpio

git clone https://github.com/paulero56/riego-huerto.git
cd riego-huerto
```

Activa el hardware real en `config.yaml`:

```yaml
hardware:
  gpio_real: true
```

Prueba una zona con las válvulas desconectadas primero, escuchando los clics del relé:

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

El timer usa `Persistent=false` a propósito: si la Pi estuvo apagada a las 6 AM, **no** debe regar al encenderla a las 3 PM bajo el sol. Un riego perdido no pasa nada; uno a destiempo desperdicia agua y estresa a los árboles.

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

Se usan 6 de los 8 canales: 5 zonas más la maestra. Sobran 2 para el sensor de lluvia u otra ampliación.

### Campo

Las válvulas de 12V DC **no sirven para el campo**. Con tramos de 80–100 m, la caída de voltaje a 1.7 A deja la válvula sin fuerza para abrir. Además la corriente directa causa corrosión electrolítica en empalmes enterrados.

Para el campo: **6 electroválvulas de riego de 24 VAC** (Rain Bird, Hunter) —cinco de zona más la maestra— con transformador de 110 V a 24 VAC de 40 VA. Consumen ~0.25 A, así que la caída en 100 m es de apenas 1 V.

En 24 VAC los diodos flyback **no aplican** — se usa un snubber RC o un MOV en los contactos del relé.

### Otros componentes

- Flotador de nivel para los tinacos
- Filtro de malla antes de las válvulas
- Gabinete IP65 con prensaestopas
- Cable 18 AWG multipar para las válvulas
- No-break pequeño, para que un corte de luz no deje una válvula abierta

---

## Diodos flyback

Una bobina de solenoide es una carga inductiva: al cortarle la corriente genera un pico de voltaje que va picando los contactos del relé hasta quemarlos.

Un diodo 1N4007 en paralelo a cada válvula, con la **banda blanca hacia el positivo**, absorbe ese pico. Cuestan centavos y son la diferencia entre relés que duran años y relés que fallan en meses.

Al revés, cortocircuitas la fuente en cuanto energices. Revisa la orientación dos veces.

Aplica **solo a las válvulas de 12V DC** del banco de pruebas. En corriente alterna el diodo conduciría en el semiciclo negativo y sería un cortocircuito.

---

## Pendientes

- [ ] Sensor de lluvia — evita regar después de una tormenta. Lo más rentable de agregar
- [ ] Caudalímetro para detectar fugas: si el consumo de una zona sube de golpe, hay un tubo roto
- [ ] Panel web para disparar riegos manuales desde el celular
- [ ] Notificaciones cuando algo falla
- [ ] Reservar la IP de la Pi en el módem, para no perder el acceso remoto
- [ ] Sensores de humedad de suelo por zona (dejar para el final: se ensucian, se corroen y hay que calibrarlos)
