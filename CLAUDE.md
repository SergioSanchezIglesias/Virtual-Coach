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
| `coach.py` | bucle, anticipación, audio y voz | validado en pista (Hockenheim, Winton, Indianápolis) |
| `gui.py` | ventana para elegir referencia y lanzar el coach | estrenada en pista (ago-2026) |
| `review.py` | análisis post-vuelta con el ABS: por qué has ido lento | estrenado en pista: el canal de ABS del PC llega y diagnostica |
| `standings.py` | clasificación por clases, SoF e iRating ESTIMADO (lógica pura) | estrenado en práctica; el gap es distancia en pista en vivo |
| `overlay.py` | tabla de clasificación encima del juego (ventana sin bordes) | **estrenado en práctica** (ago-2026); falta validar en carrera online |
| `gen_voces.py` | genera los clips de voz (neuronal, edge-tts) | funciona |
| `app.py` | punto de entrada único (GUI/coach/analyzer) para el `.exe` | funciona |
| `VirtualCoach.spec` | receta de PyInstaller (construir en Windows) | validada en Mac |
| `tests/` | red de regresión sobre las dos vueltas validadas (+ Tsukuba y VIR como fixtures) | 136 tests, verdes |

Validado: los 12 avisos por vuelta caen donde deben, el paso por meta se
resuelve, la vuelta 2 rearma sola, los pitidos se oyen, y `IRacingSource`
funcionó en pista real. La cuenta atrás afinada al oído es
`--countdown 3 --countdown-interval 0.75` (la carrera se corrió con 0.5, pero
rodando después con el 0.75 de la GUI Sergio lo prefirió y lo fijó en
ago-2026; los tests congelan sus golden con 0.5 y eso es irrelevante para el
oído: solo cambia el ritmo, no dónde caen los avisos).

Pendiente: **reconstruir el `.exe` en Windows** con los cambios de ago-2026
(latencia sin compensar, umbral 0.20, rearme por evento, registro con flush) y
**re-elegir el CSV de Indy en la GUI** para regenerar su referencia con la
frenada del 60 % incluida.

## Arquitectura

Un solo módulo (`source.py`) sabe de dónde vienen los datos. Todo lo demás
consume `Frame` y no sabe si detrás hay iRacing o un CSV reproducido.
**No romper esa separación**: es lo que permite desarrollar en el Mac sin
el simulador, y lo que abarataría un port futuro a Le Mans Ultimate.

`ReplaySource` no es un mock: el CSV de Garage61 es una grabación del mismo
flujo, a la misma frecuencia y en las mismas unidades que produce iRacing.

**Hay un SEGUNDO canal en `source.py`: la sesión** (`SessionSnapshot`, todos
los coches a 2 Hz), para el overlay de clasificación. Mismo patrón: iRacing en
vivo (`IRacingSessionSource`), grabación a JSONL (`SessionRecorder`) y replay
(`ReplaySessionSource`). El CSV de Garage61 no sirve aquí (solo trae tu coche),
por eso **la GUI graba cada sesión sola en `sesiones/`** (ignorado por git):
esa grabación es el fixture con el que se afina el overlay en el Mac.
`tests/data/demo_sesion.jsonl` es una carrera SINTÉTICA para arrancar; en
cuanto haya una real grabada en el PC, sustituirla.

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
espaciados en tiempo (ritmo de metrónomo). El aviso de gas es un "ya puedes",
no necesita preparación, y ponérsela subiría de 30 a 48 sonidos por vuelta.

**Los ticks son una ESCALA ASCENDENTE que remata en el pitido de frenada**
(333 → 400 → 511 Hz, y el pitido a 622). Antes compartían el tono del freno y
solo se distinguían por durar menos y sonar más bajo; **rodando se comprobó que
esa diferencia es demasiado fina**: con ruido de motor un tick y el pitido se
confunden. La escala los separa y además dice en qué tick vas sin contarlos —
el más agudo es el último. La rampa se reparte entre `--count-freq` y el tono
del freno en vez de subir un factor fijo, así ningún tick puede alcanzar al
pitido tenga la cuenta 3 ticks u 8. Cambiar esto **no movió ni un aviso**: los
golden de `tests/` siguen idénticos a los de la versión que corrió la carrera.

**Validación de velocidad**: cada evento guarda la velocidad de la referencia
en ese punto. Si el piloto llega con una desviación mayor que `--speed-tol`,
el punto de frenada ajeno no le aplica. Existe `--skip-mismatch` para callarlo.

**Audio de latencia mínima**: un único stream abierto toda la sesión y los
tonos pregenerados en RAM. Nada de abrir streams ni cargar ficheros por aviso.
Los tonos llevan envolvente de 6 ms para no hacer click.

**El retraso de la tarjeta NO se descuenta por defecto** (`--audio-latency`
compensa solo un retraso MEDIDO por el usuario). Esta decisión dio la vuelta
entera y conviene saber por qué: la cifra que declara el sistema (182.9 ms en
el PC de juego) primero no se usaba para nada, luego se descontó sola de la
antelación… y un **A/B en pista (Indianápolis, ago-2026)** demostró que
descontarla ADELANTA los avisos respecto al tacto validado en carrera —
Sergio lo notó comparando con otro coach. La causa: ese número **no es una
medida, es la sugerencia del modo de alta latencia de PortAudio** (sounddevice
abre los streams con `latency=('high','high')` si no se le pide otra cosa; en
el Mac declara 122.6 ms por defecto, 67.4 con "low", con un dispositivo de
18 ms). El tacto que quedó 2º en carrera rodó sin compensar: ese es el
defecto. Lo vigila `test_la_latencia_declarada_no_mueve_los_avisos`. La
palanca honesta sigue ahí: un retraso medido de verdad (grabando pantalla y
altavoz a la vez) sí merece pasarse por `--audio-latency`.

**El volumen de la voz es un ajuste PERCEPTUAL, no matemático** (`--voice-volume`,
por defecto 0.60). La voz se oía más alta que los pitidos, pero **no es que los
clips vengan saturados**: medidos, sus picos van de 0.295 a 0.561, comparables al
0.35 del tono, y su RMS (0.06-0.10) es MENOR que el del pitido (0.247). La causa
es otra: el oído integra la sonoridad en unos 200 ms y el pitido dura 90, así que
se percibe más bajo de lo que mide. Por eso **no hay que normalizar por pico**
(empeoraría): se atenúa la voz y se afina al oído.

**Los cuatro pitidos escalan JUNTOS con `--volume`** (por defecto 0.35, el
afinado que corrió la carrera). Antes el volumen del tono estaba fijo en
`make_tone` y no había forma de subirlo sin tocar código, mientras que la voz y
los ticks sí eran ajustables — una asimetría que no respondía a ninguna
decisión, solo a que nadie lo había necesitado. Escalan juntos a propósito: sus
alturas relativas son lo que deja distinguir freno de gas sin pensar, y si uno
subiera más que otro se borraría esa diferencia justo con el motor rugiendo. Lo
vigilan tres tests, y **el defecto sigue siendo 0.35**: quien no toca nada oye
exactamente lo mismo que el día del podio.

**El motor de audio es un MEZCLADOR**: suma los sonidos activos en vez de que
cada uno corte al anterior. Así la voz de preparación y el pitido del punto
suenan a la vez, y el aviso de una curva no pisa el de la siguiente (crítico
donde las curvas van juntas, como Winton). El mix se clipa a [-1, 1].

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
`BRAKE_MIN_PEAK` ha bajado dos veces, siempre con datos: de 0.35 a 0.30 por la
curva 1 de Hockenheim (un toque de 0.34), y de 0.30 a **0.20** por
Indianápolis (ago-2026): una curva real al 60 % de la vuelta — pico 0.245 con
**1.4 s de pedal**, eso no es un roce — se quedaba muda, y Sergio la echó en
falta rodando. La profecía del párrafo que había aquí se cumplió tal cual:
un circuito nuevo metió un pico en la banda dudosa y hubo que mirarlo sobre
los datos. El ruido medido en los tres circuitos no pasa de 0.148 (Winton:
cinco toques de 0.036 a 0.109, todos entre el 35 % y el 41 % de la vuelta,
que es estabilizar el coche, no frenar; Indy: roces de hasta 0.148), así que
0.20 conserva hueco real. Y los descartes dudosos **ya no son silenciosos**:
un freno sostenido que quede bajo el umbral se canta al procesar
(`[!] freno sostenido descartado…`) para que decida el piloto, que es quien
conoce la vuelta. Lo vigilan `test_hueco_alrededor_del_umbral_de_freno`,
`test_una_frenada_suave_como_la_de_indianapolis_avisa` y
`test_un_freno_sostenido_bajo_el_umbral_se_canta`.

**Si la referencia no acelera tras soltar el freno (inercia), esa zona no
lleva aviso de GAS.** El analyzer calculaba esa validación (`coasting`) desde
el primer día… y no la usaba: el aviso se emitía igual. Ordenar "GAS" donde el
piloto rápido va en banda es información falsa, la línea roja del proyecto.
Ahora `to_reference` lo omite y el analyzer avisa de la omisión al procesar.
En Hockenheim, Winton e Indy no hay ninguna zona así (verificado): el caso es
de circuito futuro. Lo vigila `test_una_zona_de_inercia_no_emite_aviso_de_gas`.

**El freno ARRASTRADO no es inercia: la suelta es cuando el pedal llega a
cero, no cuando baja de `BRAKE_OFF`.** Lección de Tsukuba (ago-2026, Ferrari
296, referencia de Travis Newsome): en las tres curvas lentas (30 %, 58 %,
88 %) el piloto baja el freno a 0.01-0.05 y lo deja apoyado 0.5-1.3 s mientras
gira, y solo pisa gas al soltarlo del todo. Como el analyzer daba la frenada
por terminada al cruzar 0.03, en 0.6 s no había gas → `coasting` → **3 de 5
curvas sin aviso de GAS**, y era un aviso BUENO: medido desde la suelta real
(freno ≤ `BRAKE_ZERO` = 0.005) el gas llega +0.03/+0.48/+0.07 s después, o sea
que la regla "gas = suelta del freno" seguía siendo cierta, fallaba el umbral.
Es una firma del PIE del piloto, no de su ritmo: no se arregla cambiando de
referencia. El arreglo es quirúrgico a propósito: solo cuando `coasting` sale
verdadero se avanza el punto de gas hasta el cero real y se reevalúa. Bajar
`BRAKE_OFF` en general habría movido el gas de Winton 0.03-0.28 s (allí la
suelta real va un pelín después del cruce) y tocado un golden validado en
pista; así Hockenheim y Winton no se mueven ni un metro. Lo vigilan
`test_el_freno_arrastrado_no_es_inercia` y
`test_tsukuba_avisa_gas_en_las_cinco_frenadas` (con `tests/data/tsukuba.csv`
como tercer fixture congelado; no entra en los golden porque no está validado
en pista).

**El freno se normaliza al PICO de la propia vuelta; los umbrales son
fracciones de lo que ese piloto pisa como mucho, no valores absolutos.**
Lección de VIR (ago-2026, Yeonwoo Lee, AMG GT4, 2:22): su pedal llega a
**0.376** en toda la vuelta, y las otras referencias a 1.00 (Hockenheim), 0.78
(Winton) y 0.59 (Tsukuba). Es calibración/fuerza de SU pedal, no ritmo. Con
`BRAKE_ON = 0.15` absoluto (el 40 % de su frenada máxima) se perdían **4
frenadas reales de 13** (12.4, 15.0, 52.4 y 83.0 %) y la del 43.6 % sonaba
13 m TARDE — la dirección que no queremos. Sergio lo notó como "ningún pitido
funciona bien". Ahora `load_lap` divide `Brake` por su máximo (misma filosofía
que la longitud: se mide de la vuelta, no se teclea) y guarda la escala en
`df.attrs["brake_scale"]`; la única constante que sigue en unidades crudas es
`BRAKE_ZERO` (ruido de lectura del pedal, no fuerza). Medido: Hockenheim no
cambia nada; en Winton ninguna frenada se mueve, los gas van UNA muestra más
tarde (0.3-1.4 m) y el `manage` +3.3 m, y el `peak` que dice la voz pasa a ser
relativo al pedal del piloto ("frena, cien" en su frenada más fuerte, que es lo
honesto). Se re-fotografiaron los dos golden de Winton por eso. Lo vigilan
`test_la_escala_del_pedal_no_mueve_las_frenadas` (el mismo CSV con el freno
×0.4 y ×0.7 da las mismas zonas al micrómetro) y
`test_vir_detecta_las_trece_frenadas` (con `tests/data/vir.csv` como cuarto
fixture). Lo que VIR también enseñó y queda **pendiente**: sus 4 "lifts" son
falsos (la velocidad no baja en ninguno: 78→101, 140→140, 149→147, 95→101
km/h; es gas parcial en salidas y eses), pero el lift validado de Winton
tampoco pierde velocidad, así que una regla de "un lift frena el coche" tocaría
un golden y hay que pensarla con más datos. Y este piloto rueda en inercia de
verdad en 6 de 13 curvas (1-3.8 s sin gas tras soltar): ahí el coach calla el
GAS, y eso es correcto.

**Los avisos se rearman POR EVENTO, media vuelta después de pasarlo — no
todos juntos en meta.** Rearmar en meta comprimía contra la línea los avisos
de los primeros eventos de la vuelta: la voz de la curva 1 de Hockenheim
(a 167 m de la línea) necesita arrancar ~60 m ANTES de meta y no podía —
salía en el primer frame tras cruzar, con 2.7 s en vez de 3.75 y con los
ticks sonando encima de la frase. Con el rearme por evento suena en el 99.2 %
de la vuelta anterior, donde toca, y una sola vez. Los golden no se movieron
(sin voz, ninguna ventana cruza meta en los circuitos validados); en un
circuito con la frenada 1 pegada a meta esto además evitaba perder el propio
pitido. Lo vigila `test_la_antelacion_de_la_voz_no_se_comprime_en_meta`.

**La voz (`--voice`) es preparación anticipada; el pitido sigue siendo el
gatillo.** Secuencia por frenada: VOZ ("Frena, 40%, tercera") → cuenta atrás
(ticks) → PITIDO en el punto. La voz dice el QUÉ con antelación, el pitido el
CUÁNDO exacto. Resuelve la latencia de la voz: una frase de ~1.5 s no vale como
gatillo pero sí como aviso previo. Los lifts dicen "Suelta"; el gas no lleva voz
(el pitido basta). Solo en frenadas/lifts, nunca al acelerar.

**La voz se genera un 15 % más lenta que la que sale de fábrica** (`RATE` en
`gen_voces.py`). Probado en pista: a velocidad normal cuesta entenderla con el
ruido del coche encima. No es gratis — la frase más larga pasa de 1.55 s a
1.79 s — pero el coste medido es pequeño (ver abajo).

**Ya hay solapamiento entre frases, y no es un fallo.** Medido ANTES de tocar la
velocidad: en la curva del 92 % de Hockenheim la frase necesita 99 m de
antelación y solo hay 63 m de hueco (**-36 m**); en Winton, **-64 m**. Se
sostiene porque el motor de audio SUMA los sonidos en vez de cortarlos. Con la
voz más lenta pasa a -39 m y -72 m: **3 y 8 metros peor**, nada. Lo vigila
`test_el_solape_entre_frases_sigue_acotado`, que salta si crece de verdad. Si
algún día estorba, las palancas son acortar la cuenta atrás o la propia frase —
no volver a acelerar la voz.

**La voz es clips pregenerados, no TTS en vivo.** `gen_voces.py` los crea con
**voces neuronales de Microsoft** (edge-tts, es-ES-AlvaroNeural — casi humana),
decodificadas a WAV con miniaudio (sin ffmpeg) y con el silencio de relleno
recortado. Se versionan en `voces/` y en Windows solo se reproducen: cero
dependencia de voz e internet en runtime (edge-tts solo hace falta para
REGENERAR). El coach los concatena en RAM ("frena"+"cuarenta"+"tercera").

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

**El ABS no vale como sí/no: TODO EL MUNDO lo activa. Vale el CUÁNTO.**
(`review.py`, rama `feat/analisis-abs`.) La premisa de partida era *"si el
rápido no activa el ABS y tú sí, te pasaste"*. **Medido: es falsa.** El piloto
de referencia lo activa en las **7 frenadas de Hockenheim y en las 9 de
Winton** — frena al límite y deja que el sistema module, que es lo que hace un
piloto rápido. Lo que sí discrimina es la DURACIÓN, que además escala con la
intensidad: de 0.05 s en un roce a 2.33 s en la frenada más al límite. Lo vigila
`test_el_piloto_de_referencia_usa_el_abs_en_todas_las_frenadas`.

**El diagnóstico cruza el ABS con la velocidad de paso**, porque son dos errores
que dan el MISMO síntoma (ir lento) y se corrigen al revés:

| ABS vs referencia | Paso por curva | Veredicto | Se dice |
|---|---|---|---|
| mucho más | más lento | te pasaste de frenada | "suave" |
| bastante menos | más lento | te sobra margen | "aprieta" |
| más | igual | vas al límite, castiga goma | nada |
| parecido | igual o mejor | bien | nada |

Hace falta salto **relativo Y absoluto** (`ABS_MORE_RATIO` + `ABS_MORE_ABS_S`).
Sin el absoluto, la frenada 5 de Hockenheim (0.05 s de ABS) convierte cualquier
roce en "siete veces más" y el coach cantaría un error por vuelta.

**La corrección va DENTRO de la frase que ya existe, y es una ORDEN, no un
reproche.** `--training` (casilla en la GUI, colgada de la de voz) convierte
*"Frena, 40%, tercera"* en *"Frena, 40%, tercera, **suave**"*. Ni un sonido
nuevo, ni un hueco que buscar. Y se dice **"suave"**, no *"aquí te pasaste"*:
un aviso que mira al pasado te mete duda tres segundos antes de frenar, y **la
duda cuesta más tiempo que el error que intenta corregir**. Solo se corrige UNA
curva por vuelta, la peor: corregir siete a la vez es ruido y acabas apagándolo.

**Tres correcciones de la primera sesión real** (feedback de pista, no de mesa):

1. **Habla de NÚMERO de frenada, no de porcentaje.** *"Frenada @ 58.6%"* no
   significa nada al volante; *"Frenada 4"* sí, y es la misma numeración que ya
   imprime el analyzer al procesar la vuelta. Ojo: es la cuarta ZONA DE FRENADA
   contando desde meta, no la "curva 4" del plano oficial.
2. **Las zonas por las que no se pasó rodando se descartan** (`NOT_A_LAP_DROP`,
   30 %). En la sesión salió esto: `Frenada @ 3.6% ABS 0.00s (el 0.80s)
   -162.5 km/h -> te sobra margen`. **162 km/h más lento** no es un error de
   pilotaje: estaba saliendo de boxes a 61 por hora. Out-lap, entrada a boxes,
   bandera o incidente → no hay nada que diagnosticar, y aconsejar ahí es peor
   que callarse.
3. **Como mucho las 2 peores, ordenadas** (`--review-top`). Salieron CUATRO
   consejos y los cuatro decían lo mismo. Cuando todo dice lo mismo no informas,
   haces ruido.

**Si la vuelta fue limpia, el coach no dice nada.** El silencio es información.
Validado: pasar la referencia contra sí misma da 7/7 y 9/9 frenadas "ok" y cero
correcciones. Es la garantía contra el coach cansino.

**Nada del análisis suena EN VIVO.** Un "¡ABS!" mientras frenas es la peor
distracción posible y además llega tarde: cuando lo oyes, ya te has pasado. El
diagnóstico se cierra al cruzar meta, que es cuando el dato sigue fresco.

**El iRating del overlay es una ESTIMACIÓN y la pantalla lo dice (`≈`).**
iRacing no publica el iRating en vivo, solo al acabar la sesión; lo que
enseñan todos los overlays es la fórmula reconstruida por la comunidad (tipo
Elo con `BR1 = 1600/ln 2`, suma cero dentro de cada clase, el tapado gana más
que el favorito). Es fiel pero es una predicción: presentarla como dato sería
información falsa. Lo vigilan los tests de `test_standings.py` (suma cero,
monotonía, favorito vs tapado). El overlay va como proceso aparte igual que el
coach, con Tk puro (sin customtkinter) porque necesita `-transparentcolor`, e
**iRacing tiene que ir en ventana sin bordes** para que se vea encima.

**Los tests congelan lo que ganó la carrera, y por eso van SIEMPRE primero.**
Antes de tocar nada del core se fotografía el comportamiento actual (`golden`) y
solo entonces se cambia. Si se escriben después, se congela el comportamiento
nuevo — el que nadie ha validado — y la red no sirve de nada. Ver `## Tests`.

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
- `ABSActive` viene poblado y **ya se usa** (`review.py`): marca dónde el piloto
  pidió más freno del que la goma daba. Ver la decisión sobre el ABS arriba
- `LapDistPct × longitud` es aproximado (spline del circuito vs trazada real);
  no fiarse de los metros al centímetro

## Tests

    .venv/bin/python -m pytest tests/ -q      # 136 tests, ~4 s

Corren sin iRacing, sin audio y sin internet: el replay a `speed=0` es
determinista, así que "lo que suena en una vuelta" se puede congelar en un
fichero y comparar. Tres capas:

- **Golden** (`tests/data/golden/`): el JSON de eventos del analyzer y la
  secuencia completa de avisos del coach, evento a evento y con su posición.
  Para re-fotografiar a propósito, borra el golden y vuelve a correr — pero
  solo si el cambio está validado.
- **Invariantes**: cada test defiende una decisión de arriba (el auto-blip que
  obliga a detectar el gas por la suelta del freno, el margen que adelanta el
  aviso, el % redondeado a tramos de 20, la rotación de Winton…). No comprueban
  la implementación, comprueban el MOTIVO.
- **Audio** (`test_audio.py`): mide por FFT la frecuencia real de cada tono. Un
  aviso que no se distingue de otro no sirve, y eso no se ve leyendo el código.

Los CSV de `tests/data/` son **copias congeladas** de las dos vueltas
validadas (más Tsukuba y VIR como fixtures no validados en pista), versionadas con una excepción en `.gitignore` (353 KB comprimidos).
Son copias a propósito: los CSV de la raíz los sobrescribes al exportar de
Garage61, y un fixture que cambia bajo los pies no congela nada.

**Defecto conocido y documentado en `test_el_lap_del_replay_no_es_la_vuelta_del_circuito`:**
`ReplaySource` incrementa `lap` al agotar el buffer del CSV, no al cruzar meta.
En Hockenheim da igual (empieza en meta), pero **Winton arranca en el 16 %** y
ahí el cruce cae a mitad del buffer, con `frame.lap` desfasado. Hoy no rompe
nada porque **nadie fuera de `source.py` lee `frame.lap`** — el coach se orienta
solo con `lap_pos`. Pero en este punto el replay **no es fiel a iRacing**, que
sí incrementa `Lap` al cruzar meta, y cualquier función que cuente vueltas (el
análisis post-vuelta) se comería el desfase.

## Entorno

- Desarrollo en **Mac**; iRacing está en una **máquina Windows aparte**
- `pyirsdk` es solo Windows y solo lo toca `IRacingSource`
- Venv en `.venv/`, creado con `--copies` sobre el **Python 3.11 de Homebrew**
  (`/opt/homebrew/bin/python3.11`) con **Tk 8.6.18** (`brew install
  python-tk@3.11`). Antes era el Python 3.9 de las Command Line Tools, cuyo
  **Tk 8.5 dejaba `gui.py` en blanco en el Mac** (los widgets no se pintaban):
  se desarrollaba la ventana a ciegas. Ya no. El salto arrastró **pandas 2.3 →
  3.0 y numpy 2.0 → 2.4** (versiones mayores) y **no movió ni un aviso**: los
  110 tests pasaron a la primera, que es exactamente para lo que está la red
- `.gitignore` excluye los CSV crudos; los JSON de referencia sí se versionan.
  **Excepción**: `tests/data/*.csv` sí van al repo (son los fixtures)
- Dependencias en `requirements.txt` (rodar) y `requirements-dev.txt` (tests,
  `.exe`, regenerar voces). Van separadas a propósito: nada de lo de desarrollo
  viaja en el ejecutable. Montar el entorno:

      pip install -r requirements.txt -r requirements-dev.txt

## Empaquetado (.exe)

El `.exe` se construye **en Windows** (el binario es de Windows; en el Mac solo
se valida la receta). `app.py` es un punto de entrada único: la GUI se lanza a sí
misma como `VirtualCoach.exe coach ...` en vez de `python coach.py`, porque en un
`.exe` no hay python ni `.py` sueltos (ver `_tool_cmd` en gui.py y `_base_dir` en
coach.py con `sys._MEIPASS`). Es `--onedir` (carpeta portable), no `--onefile`,
para que esas re-invocaciones no re-extraigan el bundle. En Windows:

    pip install -r requirements.txt -r requirements-dev.txt
    pyinstaller VirtualCoach.spec
    # -> dist\VirtualCoach\VirtualCoach.exe  (carpeta portable, sin Python)

**PyInstaller empaqueta lo que hay INSTALADO, no lo que importa el código.** Si
falta una dependencia en la máquina que construye, el `.exe` sale igual y
revienta al abrirlo. Pasó con `customtkinter`: la receta lo recogía
correctamente, pero no estaba instalado en Windows, así que no había nada que
recoger. Si tocas un `import`, mira si esa línea también hace falta.

Si el `.exe` no abre, **mira `VirtualCoach-error.log` junto al ejecutable**. Se
construye con `console=False` (es una GUI, no queremos ventana negra detrás), y
el precio es que un fallo de arranque no enseña nada: la app simplemente no
abre. Por eso `app.py` escribe ahí el traceback y lo enseña en una ventana.

Validado en Mac: construye, empaqueta `voces/`, y el binario corre el coach con
audio y voz encontrando los clips del bundle. **En Windows ya arranca la GUI
nueva** (rama `feat/gui-customtkinter`).

## Siguiente paso

**Validado en carrera real: Sergio quedó 2º.** La app está madura.

Hecho tras el podio (en `main`, con la red de tests puesta antes de tocar nada):
ticks ascendentes, `--voice-volume`, la GUI nueva **estrenada en pista**, y el
paquete de ago-2026 tras el A/B de Indianápolis: la compensación de latencia
revertida con datos, el umbral de freno a 0.20, el rearme por evento, el
`coasting` aplicado y el registro de la GUI arreglado (flush + colores).

Decisión cerrada (ago-2026): el ritmo de la cuenta atrás queda en **0.75**,
el defecto de la GUI, que es con el que Sergio lleva rodando y el que
prefiere. El 0.5 de la carrera pasa a ser historia, no referencia.

### En marcha: rama `feat/overlay-clasificacion` (ago-2026)

Dos features nuevas acordadas, en este orden: (1) **overlay de clasificación**
con iRating estimado encima del juego, (2) **"ingeniero de pista"** que
analiza tus tandas de práctica y recomienda cambios de setup adaptados a tu
conducción. Contexto: Sergio corre GT4, GT3 y Porsche Cup (setup fijo en
muchas series) y quiere meter LMP3/LMP2/Hypercar; iRacing ya va en ventana sin
bordes.

**Overlay: implementado y estrenado en práctica** (`overlay.py`,
`standings.py`, segundo canal en `source.py`, toggle en la GUI, `app.py
overlay`). **El interruptor de la GUI es VIVO e independiente del coach**
(ago-2026): encenderlo arranca el overlay al momento sin necesitar CSV ni
pulsar Empezar, apagarlo lo cierra, y si el overlay muere solo (Esc o fallo)
el interruptor se apaga. Empezar/Parar gobiernan solo el coach: la
clasificación sirve igual en una carrera sin referencia de ese circuito. Boceto en Pencil (frame "Overlay — clasificación (en juego)" en el
`.pen` de la GUI). Lo que enseñó el estreno: el SDK leyó la sesión a la
primera (20 coches), la IA viene con IRating 0/1 (ya no divide por cero),
`CarIdxF2Time` NO sirve de gap (solo cambia en los puntos de control; en
práctica es un delta de mejor vuelta) → el gap es distancia en pista en vivo,
y el panel se ha compactado dos veces porque tapaba pista. Pasos que quedan:

1. **Validar en una carrera online real** (no con IA): iRatings de verdad,
   Δ≈ con sentido, gaps en carrera, doblados (`+1 L`), coches en boxes (`PIT`),
   varias clases. Guardar el `sesiones/*.jsonl` de esa carrera y **sustituir el
   fixture sintético** `tests/data/demo_sesion.jsonl` por uno real recortado.
2. **Contrastar el Δ≈ de iRating con el que iRacing publique al acabar** esa
   carrera. Si se desvía más de unos pocos puntos, revisar la fórmula
   (`standings.irating_changes`) o cómo se cuentan los que puntúan
   (`in_world`, DNS, desconectados).
3. Ajustes de la GUI que faltan para el overlay: exponer `--scale`, `--top`,
   `--around` como ajustes (hoy solo por CLI; la GUI lanza los defectos).
   **La posición ya se recuerda** (ago-2026): se guarda en
   `sesiones/overlay_pos.json` al SOLTAR el arrastre (no al cerrar: la GUI
   mata el proceso con `terminate` y un guardado al cierre nunca llegaría) y
   se lee al arrancar; `--pos` explícito sigue mandando.
4. Fusionar a `main` y **reconstruir el `.exe` en Windows** (pendiente
   también por los cambios de ago-2026 en el coach). El spec no cambia:
   `overlay` entra por `app.py`.

**Ingeniero de pista: sin empezar.** Plan acordado, en dos mitades y con un
paso 0 común (la línea roja sigue: no dar información falsa, así que primero
diagnóstico medido y solo después recomendación):

- **Paso 0 — grabador de tu telemetría de chasis por tanda.** Los canales que
  hoy no lee `IRacingSource`: volante (`SteeringWheelAngle`), `YawRate`,
  `LatAccel`/`LongAccel`, temperaturas de neumático por tercios
  (`LFtempCL/CM/CR`…), presiones fría/caliente, `RideHeight` y recorrido de
  amortiguador por rueda, reparto de frenada, y el `CarSetup` del YAML una vez
  por tanda. A un fichero por tanda (out-lap a in-lap), reproducible en el Mac
  como el resto. Sirve además para el "dónde pierdes tiempo" del backlog.
- **2a — diagnóstico por zona de frenada** (la numeración que ya usa
  `review.py`): sub/sobreviraje en entrada, medio y salida (volante frente a
  `YawRate` y velocidad), presiones y temperaturas fuera de ventana, qué eje
  bloquea (ABS + reparto). Solo describe, con datos medidos. Debe leer del
  `CarSetup` qué está bloqueado (setup fijo) para no proponer tocar lo que no
  se puede tocar. Sergio pasará capturas de todos los campos del garaje.
- **2b — recomendación: UN cambio por tanda**, de la lista de campos del
  coche, y en la tanda siguiente medir si el síntoma mejoró o empeoró. Así el
  sistema se adapta al piloto en vez de recitar una tabla síntoma→tornillo,
  que cambia por coche, circuito y estilo. Con LMP2/Hypercar esto además evita
  tocar cosas muy sensibles (ride heights, aero) sin evidencia. Lo que el SDK
  NO permite: escribir el setup; el ingeniero recomienda, tú tocas.

En rama aparte, pendientes de implementar y probar:

- **Usar `ABSActive`** (idea D). Distingue dos errores que dan el mismo síntoma:
  llegar lento por frenar pronto y suave, o por frenar tarde y pasarse (ahí salta
  el ABS, la rueda no genera fuerza lateral y te vas largo). La corrección es la
  contraria en cada caso. **Diagnóstico post-vuelta, jamás en vivo.**
- **Casos raros de sesión** (idea E). Out-lap con gomas y frenos fríos avisando
  puntos de vuelta caliente (información falsa donde más duele), entrada a boxes,
  rearme tras reset, banderas. Un gestor de estado que decida cuándo el coach
  está ACTIVO.

## Ideas de mejora (backlog)

La app está madura y validada en competición; el mayor riesgo al iterar es el
*feature creep*. **Línea roja de cualquier mejora**: respetar lo que la hizo
buena — audio mínimo, no distraer al conducir, no dar información falsa.
Direcciones propuestas (sin prioridad cerrada), planteadas tras el podio:

- **De avisar a ENSEÑAR (feedback de dónde pierdes tiempo).** Hoy el coach dice
  *dónde* frenar/acelerar. El salto cualitativo: tras cada vuelta, decir en qué
  curvas pierdes tiempo respecto a la referencia ("perdiste 3 décimas en la
  curva 3"). Requiere grabar tu telemetría en vivo (`IRacingSource` ya da los
  frames) y compararla con el perfil COMPLETO de la referencia (el CSV, no solo
  los eventos del JSON), alineados por `LapDistPct`. Es lo de mayor valor para
  mejorar, y lo más grande. Cuidado: feedback EN VIVO distrae; hacerlo
  POST-vuelta (al cruzar meta o en boxes) es lo coherente con la filosofía.

- **Comodidad diaria.** (a) Que el coach detecte el circuito activo en iRacing
  (el SDK da el nombre del track) y cargue solo la referencia correcta de una
  biblioteca. (b) Exponer `--lead`, `--countdown-interval`, volumen y elección de
  voz en la GUI (sliders/campos) para afinar al oído sin tocar comandos. Bajo
  riesgo, alta comodidad diaria.

- **Referencias propias (sin Garage61).** Un modo grabación que vuelca los frames
  de `IRacingSource` a un CSV (mismas columnas que Garage61) para procesarlo con
  `analyzer.py`. Da autonomía. Ojo: tu propia vuelta como referencia solo te guía
  hasta tu ritmo actual; el valor de Garage61 es que da vueltas de pilotos más
  rápidos. Útil para consistencia o circuitos sin referencia externa.

- **Pulir y robustecer.** Igualar el volumen de la voz con el de los pitidos.
  Afinar la detección en más circuitos (el patrón `manage` es el más delicado:
  vigilar falsos positivos). Cubrir casos raros de telemetría.
