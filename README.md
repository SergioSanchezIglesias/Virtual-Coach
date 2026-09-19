# LMU Corner Cues

Referencias sonoras por distancia de vuelta para Le Mans Ultimate en Windows. Lee la telemetría nativa; nunca envía controles al juego. **Son referencias fijas, no consejos de frenada ni un entrenador adaptativo.**

## Inicio rápido en Windows: interfaz gráfica

Necesitas Windows y Python **3.9 o superior con Tcl/Tk (Tkinter)**. Abre PowerShell en la carpeta del proyecto y usa siempre el mismo entorno de Python:

```powershell
python -m pip install .
python -m lmu_corner_cues gui
```

La ventana puede abrirse sin LMU en ejecución. Después del lanzamiento, el flujo normal no necesita comandos ni edición de JSON. Los botones están en inglés.

1. **Conecta, con el coche detenido.** Activa en LMU **Settings → Gameplay → Enable Plugins**, reinicia el juego y entra en práctica privada con el coche local. Pulsa **Check connection** y comprueba circuito, vehículo, clase, vuelta y distancia. Si el ajuste difiere, consulta tu versión de LMU; no instales el antiguo plugin de rFactor 2. La consulta es puntual, no un monitor continuo.
2. **Graba antes de conducir.** En **Profile name**, escribe un nombre nuevo, como `mi-vuelta`, y pulsa **Start recording**. Espera el siguiente paso por meta; conduce una vuelta completa, limpia y conservadora hasta el paso posterior. La grabación termina sola en **Draft ready** y guarda `recordings/mi-vuelta.json`. No reproduce señales ni pide intervención. **No mires ni uses la ventana mientras conduces.** Una cancelación observada antes de iniciar la persistencia, o una grabación discontinua, no produce un nuevo borrador; una cancelación durante la escritura final puede dejar el borrador completo.
3. **Revisa detenido.** La tabla se carga al terminar. Revisa o corrige cada nombre y los metros desde el inicio de vuelta en **Brake**, **Release brake** y **Throttle**. Deben ser valores finitos no negativos, estrictamente crecientes, con nombres únicos y sin solapamiento entre curvas. Si no hay candidatos completos, graba otra vuelta.
4. **Confirma y guarda.** Elige **Output profile name**, pulsa **Confirm and save profile** y acepta solo tras revisar la advertencia. Se guarda `profiles/<nombre>.json`. Cancelar el diálogo no guarda. Si el perfil existe, se solicita otra confirmación para reemplazarlo: **es irreversible**. La GUI no reemplaza borradores existentes; usa otro nombre de grabación.
5. **Activa las señales detenido, antes del primer marcador.** Selecciona el perfil confirmado en **Drive cues** (usa **Refresh profiles** si hace falta) y pulsa **Start cues**. Comprueba el estado **Active** y valida una vuelta controlada: tono grave de freno, par descendente al soltarlo y tono agudo de gas. Los borradores no se pueden reproducir.
6. **Detén el coche antes de operar la ventana.** Usa **Stop cues** para parar las señales o **Cancel** para cancelar una operación. Espera a que termine la limpieza. Al cerrar la ventana se solicita la cancelación y se espera al trabajador para liberar el lector; el cierre puede no ser inmediato. Las acciones incompatibles quedan deshabilitadas durante grabación y reproducción.

> **Confirmado no significa calibrado:** «vuelta limpia» solo acredita continuidad de la telemetría observada, no validez deportiva. Los candidatos no son puntos seguros de frenada. Confirma únicamente detenido y después valida tus referencias en condiciones controladas; guardarlas no demuestra su seguridad.

Conserva borrador y perfil: son artefactos JSON, no archivos que debas editar a mano. La GUI revisa la grabación recién terminada; para reabrir un borrador anterior, utiliza el asistente CLI.

## Referencia CLI: diagnóstico y automatización

Antepon `python -m lmu_corner_cues` a cada comando:

| Comando | Uso |
|---|---|
| `--help` | Ayuda general. |
| `gui` | Abrir la interfaz gráfica (Windows/Tkinter). |
| `session` | Consultar una vez la sesión y sus identificadores. |
| `record mi-vuelta` | Grabar automáticamente de meta a meta. |
| `profile create recordings/mi-vuelta.json` | Revisar un borrador: `STOPPED` confirma que estás detenido; Enter acepta cada valor; solo `SAVE` guarda. `cancel`, Ctrl+C o fin de entrada cancelan. |
| `drive profiles/mi-perfil.json` | Reproducir referencias confirmadas; detener el coche antes de cerrar con Ctrl+C. |

## Opciones avanzadas y límites

- `record mi-vuelta --overwrite` permite reemplazar un borrador. `profile create recordings/mi-vuelta.json --overwrite` permite reemplazar el perfil elegido **solo después de `SAVE`**. Sin esa opción se evita sobrescribir, incluso si aparece un archivo durante la revisión.
- Los nombres de archivo admiten 1–64 letras ASCII, dígitos, guiones y guiones bajos; comienzan por letra o dígito y excluyen nombres reservados de Windows.
- `record` y `drive` aceptan `--interval 0.02` (segundos; finito y positivo). `python -m lmu_corner_cues profile create --help` muestra la ayuda del asistente. La invocación antigua `python -m lmu_corner_cues profiles/mi-perfil.json` sigue funcionando.
- La detección usa cruces de pedal: freno al 20 %, liberación al 5 % y gas al 20 % en una muestra posterior. Puede omitir curvas, frenadas ligeras y secuencias que cruzan la meta; no es una reconstrucción completa de tu conducción.
- El perfil conserva el circuito y vehículo exactos observados. El formato avanzado permite vehículo/clase o cualquier vehículo si se omite; el asistente usa siempre el vehículo concreto. Los identificadores distinguen mayúsculas. Repite la revisión y validación si cambian coche, setup, combustible, neumáticos, clima o agarre.
- El formato exportado contiene `circuit`, `vehicle` y `markers`: nombres únicos y distancias numéricas finitas no negativas `BRAKE < RELEASE_BRAKE < THROTTLE`. Cada curva comienza después del gas de la anterior. No se verifica la longitud del circuito ni la seguridad de los metros. [`profiles/example.json`](profiles/example.json) es ficticio, no está calibrado y no debe usarse como referencia real.
- Las señales dependen solo de vuelta y distancia: no filtran boxes, pausas, repeticiones ni peligros. Al arrancar a mitad de vuelta pueden sonar todos los marcadores ya alcanzados. Empieza antes del primero; ignora cualquier ráfaga atrasada. Una reducción de distancia en la misma vuelta silencia las señales hasta cambiar el contador de vuelta.
- Los pitidos bloquean el muestreo mientras suenan y pueden llegar tarde, aunque la GUI use un trabajador independiente. Se emiten una vez por vuelta; detén y reinicia las señales al cambiar de sesión o perfil. No hay reconexión automática ni garantía de tiempo real. Nunca consultes la ventana o el terminal ni ajustes referencias mientras conduces.

## Validación manual pendiente en Windows/LMU

**La compatibilidad real del ABI nativo y los sonidos todavía requieren esta prueba manual. No se ha realizado una prueba en vivo en este entorno de desarrollo.** Las pruebas sintéticas y `--help` no demuestran compatibilidad con tu versión instalada de LMU.

1. Instala en Windows y abre `python -m lmu_corner_cues gui` primero sin LMU: comprueba que la ventana abre y muestra un error accionable al consultar la conexión. Después inicia una práctica con telemetría habilitada y repite **Check connection**. Anota versiones de LMU/Python/proyecto e identificadores observados.
2. Sigue el inicio rápido con el nombre `validacion`. Comprueba la espera de meta, grabación autónoma, **Draft ready** y archivo `recordings/validacion.json`; revisa siempre detenido.
3. Cancela la confirmación de guardado y comprueba que no aparece un perfil. Repite y confirma `profiles/validacion.json`. Intenta guardarlo otra vez y rechaza el reemplazo: debe conservarse. Intenta grabar con el mismo nombre de borrador: debe rechazarse sin reemplazarlo.
4. Selecciona el perfil y activa las señales antes del primer marcador. Comprueba freno (440 Hz), liberación (880/660 Hz) y gas (1320 Hz), sin repeticiones en muestras consecutivas y con repetición en la siguiente vuelta. El silencio por sí solo no prueba conexión.
5. Detenido, comprueba **Stop cues**, cancelación de una nueva grabación y cierre de la ventana con un trabajador activo; verifica que termina el proceso y no aparece un borrador parcial. Comprueba también que la ventana responde y bloquea acciones incompatibles durante las operaciones.
6. Anota resultados de conexión, archivos, distancias, sonidos y cierre. Si hay diferencias, no dependas del perfil: revisa detenido y repite la prueba.

## Resolución de problemas

| Síntoma | Acción |
|---|---|
| `No module named lmu_corner_cues` | Instala y ejecuta con el mismo entorno de Python. |
| La GUI requiere Windows o no encuentra Tkinter | Usa Python para Windows con soporte Tcl/Tk instalado; la GUI no es multiplataforma. |
| Error de `LMU_Data` o plataforma Windows | Usa el PC Windows con LMU, salida nativa habilitada y sesión de conducción activa. |
| Tamaño/disposición incompatible o jugador local inválido | No fuerces la lectura. Comprueba versión del juego y compatibilidad del lector nativo; vuelve a entrar al coche y reinicia el comando. |
| Circuito/vehículo no coincide | Comprueba los identificadores con `session`; graba y revisa un perfil para esa combinación. |
| Borrador inválido o sin candidatos | Usa la salida de `record`, no un perfil confirmado; repite una vuelta completa con secuencias de freno, liberación y gas. |
| Distancias o nombres inválidos | Corrige en el asistente: nombres únicos, metros finitos y secuencias estrictamente crecientes sin solaparse. |
| Grabación/asistente activo o puerto 47863 ocupado | Termina el otro comando antes de reintentar. Se reserva un puerto de bucle local como exclusión entre procesos, sin escuchar ni transmitir datos; si otro programa lo ocupa, se rechaza la operación por seguridad. |
| Archivo ya existente | GUI: otro nombre para el borrador; reemplazo de perfil solo con confirmación explícita. CLI: `--overwrite`. |
| Intervalo inválido | Usa un valor finito y positivo, por ejemplo `--interval 0.02`. |
| Sin audio o audio tardío | Comprueba salida y volumen de Windows, proceso activo y distancia alcanzada. Revisa los límites de muestreo y vuelta indicados arriba. |

Mantén la vista en la pista. Deja de usar las señales si distraen o resultan incorrectas; no consideran velocidad, tráfico ni adherencia.
