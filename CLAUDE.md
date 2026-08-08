# Virtual-Coach — contexto del proyecto

Coach de audio para iRacing: avisa con un pitido de dónde frenar y dónde
volver a abrir gas, a partir de una vuelta de referencia.

El objetivo real es **aprender circuitos rápido teniendo poco tiempo entre
semana**, no exprimir la décima. Eso condiciona varias decisiones de abajo.

Trabajamos en español.

## Estado

| módulo | qué hace | estado |
|---|---|---|
| `analyzer.py` | CSV de Garage61 → JSON de eventos | funcionando y validado; estima la longitud sola |
| `source.py` | telemetría: replay de CSV o iRacing en vivo | replay validado; `IRacingSource` **validado en pista** |
| `coach.py` | bucle, anticipación, audio y voz | pitidos validados en pista; **voz sin probar** |
| `gui.py` | ventana para elegir referencia y lanzar el coach | funciona; **sin probar en Windows** (en Mac no pinta, ver Entorno) |
| `gen_voces.py` | genera los clips de voz con `say` (macOS), se versionan | funciona |

Validado: los 12 avisos por vuelta caen donde deben, el paso por meta se
resuelve, la vuelta 2 rearma sola, los pitidos se oyen, y `IRacingSource`
funcionó en pista real. La cuenta atrás quedó afinada al oído en
`--countdown 3 --countdown-interval 0.5`.

Pendiente: estrenar `gui.py` en Windows (en el Mac la ventana abre vacía por
el Tk 8.5 viejo; ver Entorno).

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

**La longitud del circuito se estima integrando la velocidad**, no se teclea:
`track_length ≈ Σ Speed / 60`. Validado en Hockenheim (4516 vs 4574 m
oficiales, 1.3 %). Como el aviso va en tiempo con `--margin` de colchón, ese
1-2 % son milisegundos. `analyzer.py` la calcula sola si no le pasas
`--track-length`. Es lo que permite usar cualquier circuito de iRacing sin
trabajo manual por pista.

**La GUI lanza `analyzer.py` y `coach.py` como procesos aparte (subprocess),
no los importa.** El core validado en pista no se toca ni se acopla: la ventana
solo teclea por ti los mismos comandos, así que un fallo en la GUI no puede
tumbar el coach. Ojo al empaquetar el `.exe`: dentro de un ejecutable no hay un
`python` suelto al que llamar, habrá que revisar este punto.

**Los lifts (curvas rápidas de solo LEVANTAR el gas, sin frenar) se detectan
como una caída desde gas pleno (`>0.90` a `<0.70`) sostenida y sin que aparezca
el freno.** Esa definición los separa por construcción de las frenadas (ahí
sube el freno) y de las salidas de curva (ahí el gas sube desde cero). Avisan
en pareja igual que las frenadas: `SUELTA` (tono propio, 820 Hz) + `GAS` cuando
el pie vuelve. El aviso de vuelta es el primer contacto tras el valle, no el gas
pleno, coherente con la regla del gas en las frenadas.

**Toda frenada real avisa, por suave que sea; el umbral solo filtra roces.**
`BRAKE_MIN_PEAK` bajó de 0.35 a 0.30 para no perder la curva 1 de Hockenheim
(un toque de 0.34). Hay hueco limpio: no existen picos reales entre 0.05 y 0.34.
Si en otro circuito aparecen avisos fantasma, subirlo por CLI.

**La voz (`--voice`) es preparación anticipada; el pitido sigue siendo el
gatillo.** Secuencia por frenada: VOZ ("Frena, 40%, tercera") → cuenta atrás
(ticks) → PITIDO en el punto. La voz dice el QUÉ con antelación, el pitido el
CUÁNDO exacto. Resuelve la latencia de la voz: una frase de ~1.5 s no vale como
gatillo pero sí como aviso previo. Los lifts dicen "Suelta"; el gas no lleva voz
(el pitido basta). Solo en frenadas/lifts, nunca al acelerar.

**La voz es clips pregenerados, no TTS en vivo.** `gen_voces.py` los crea con
`say` en el Mac; se versionan en `voces/` y en Windows solo se reproducen (cero
dependencia de voz). El coach los concatena en RAM ("frena"+"cuarenta"+"tercera").

**El % de freno se dice REDONDEADO a tramos de 20 %**, no el número exacto: el
`peak` es del piloto de referencia (1 s más rápido), así que "Frena 40%" es una
guía honesta y "Frena 73%" sería falsa precisión. **La marcha es la de la CURVA
(punto de gas), no la del inicio de frenada**: en una horquilla frenas en 5ª
pero la tomas en 1ª; decir la de frenada engañaría.

**Cuarto tipo de aviso: zonas de gestión (`manage`).** Curvas rápidas
encadenadas que se toman a gas PARCIAL, sin frenar y sin volver a pleno (el gas
oscila, se modula). No hay un instante que avisar, así que se avisa la ENTRADA
con "Medio gas, [marcha]" + un pitido propio (720 Hz). Se detectan contando los
cruces del gas sobre su media (≥3 = modulación real, no una salida de curva) y
se descartan las pegadas a una frenada o lift ya detectados. La marcha es la del
ápex. Validado: aparece en Winton (curva rápida al 36 %), cero en Hockenheim. Es
el patrón MÁS delicado: vigilar falsos positivos al estrenar circuitos, se ajusta
con `--manage-*` (crossings, duración, umbrales).

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
  Tools con **Tk 8.5**: `gui.py` abre vacía en el Mac por un bug viejo de ese
  Tk (los widgets no se pintan). En Windows (Tk 8.6) no ocurre. Migrar a un
  Python de Homebrew lo arreglaría y sigue pendiente
- `.gitignore` excluye los CSV crudos; los JSON de referencia sí se versionan

## Siguiente paso

Estrenar la **voz** en Windows (casilla "Voz" en la GUI, o `--voice`): confirmar
que se oye bien la secuencia voz → ticks → pitido, que las marchas cuadran con lo
que haces, y ajustar al oído si hace falta (la voz se cambia en `gen_voces.py`).
La voz suena algo más alta que los pitidos; si molesta, igualar niveles. Recordar
llevarse un CSV al PC: los `*.csv` están en `.gitignore`, no viajan en el repo.

Después: la Fase C, empaquetar en un `.exe` con PyInstaller (revisar antes el
punto del subprocess; ahora hay que incluir también la carpeta `voces/`). Y en
pista, seguir afinando `--lead` (0.35 s por defecto).
