# Virtual-Coach — contexto del proyecto

Coach de audio para iRacing: avisa con un pitido de dónde frenar y dónde
volver a abrir gas, a partir de una vuelta de referencia.

El objetivo real es **aprender circuitos rápido teniendo poco tiempo entre
semana**, no exprimir la décima. Eso condiciona varias decisiones de abajo.

Trabajamos en español.

## Estado

| módulo | qué hace | estado |
|---|---|---|
| `analyzer.py` | CSV de Garage61 → JSON de eventos | funcionando y validado |
| `source.py` | telemetría: replay de CSV o iRacing en vivo | replay validado; `IRacingSource` **sin probar nunca** |
| `coach.py` | bucle, anticipación y audio | funcionando en Mac con replay |

Validado hasta ahora: los 12 avisos por vuelta caen donde deben, el paso por
meta se resuelve, la vuelta 2 rearma sola, y los pitidos se oyen.

Pendiente: probarlo en pista. Nadie ha ejecutado `IRacingSource` todavía.

## Arquitectura

Un solo módulo (`source.py`) sabe de dónde vienen los datos. Todo lo demás
consume `Frame` y no sabe si detrás hay iRacing o un CSV reproducido.
**No romper esa separación**: es lo que permite desarrollar en el Mac sin
el simulador, y lo que abarataría un port futuro a Le Mans Ultimate.

`ReplaySource` no es un mock: el CSV de Garage61 es una grabación del mismo
flujo, a la misma frecuencia y en las mismas unidades que produce iRacing.

## Decisiones tomadas (no deshacer sin hablarlo)

**El punto de gas se detecta por la SUELTA DEL FRENO, no por la subida del
acelerador.** Medido sobre la referencia real, ambos coinciden dentro de
0-6 m en las seis zonas. Y es crítico: estos coches llevan auto-blip, el
acelerador sube solo por encima de 0.5 durante las reducciones en plena
frenada. Detectar por `throttle > X` sitúa el evento entre 76 y 101 metros
ANTES de lo correcto. Ya se comprobó.

**El aviso es el primer contacto con el gas, no el gas pleno.** Gas pleno es
una consecuencia de la entrada, no una orden ejecutable. Además el tramo de
0.10 a 0.90 de gas varía entre 0.20 s y 1.08 s según la curva.

**La anticipación se calcula en tiempo, no en metros.** `lead` en segundos,
convertido a distancia con la velocidad instantánea. Un offset fijo en metros
sería correcto en una curva y absurdo en las demás. El `--margin` sí va en
metros porque es un margen de seguridad deliberado.

**La cuenta atrás (`--countdown`) solo va en las frenadas**, con ticks
espaciados en tiempo (ritmo de metrónomo) y usando el mismo tono del freno
pero corto y bajito. El aviso de gas es un "ya puedes", no necesita
preparación, y ponérsela subiría de 30 a 48 sonidos por vuelta.

**Validación de velocidad**: cada evento guarda la velocidad de la referencia
en ese punto. Si el piloto llega con una desviación mayor que `--speed-tol`,
el punto de frenada ajeno no le aplica. Existe `--skip-mismatch` para callarlo.

**Audio de latencia mínima**: un único stream abierto toda la sesión y los
tonos pregenerados en RAM. Nada de abrir streams ni cargar ficheros por aviso.
Los tonos llevan envolvente de 6 ms para no hacer click.

## Contexto que importa

La referencia es de **otro piloto más rápido** (1 s). Eso es deliberado pero
tiene riesgo: su punto de frenada depende de su velocidad de entrada, su
trazada y su reglaje. El aviso de gas se puede seguir con confianza (abrir
pronto da respuesta barata: subviraje, levantas). El de freno no: por eso
existen `--margin` y `--speed-tol`. **No quitar esas salvaguardas.**

Sergio se define como piloto seguro. Si hay que elegir, error hacia frenar
pronto.

## Formato del CSV de Garage61 (iRacing)

- 60 Hz uniformes, **sin canal de tiempo** (se reconstruye: `t = n / 60`)
- `LapDistPct` nativo 0-1 — el mismo canal que da el SDK en vivo, sin conversión
- `Speed` en m/s, `Brake` y `Throttle` en 0-1 (con ruido de coma flotante
  negativo, hay que hacer clip)
- `ABSActive` viene poblado y todavía no se usa: marca dónde está al límite
- `LapDistPct × longitud` es aproximado (spline del circuito vs trazada real);
  no fiarse de los metros al centímetro

## Entorno

- Desarrollo en **Mac**; iRacing está en una **máquina Windows aparte**
- `pyirsdk` es solo Windows y solo lo toca `IRacingSource`
- Venv en `.venv/`, creado con `--copies`. Python 3.9 de las Command Line
  Tools: conviene migrar a un Python de Homebrew más moderno en algún momento
- `.gitignore` excluye los CSV crudos; los JSON de referencia sí se versionan

## Siguiente paso

Llevarlo al PC de Windows. Primero con `--replay` para validar entorno y
anotar la latencia de audio en WASAPI (distinta a la de CoreAudio), y solo
después con iRacing abierto para estrenar `IRacingSource`.

Después, en pista: afinar `--lead` (0.35 s por defecto) y decidir si la
cuenta atrás ayuda o agobia.
