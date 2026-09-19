# LMU Corner Cues

Referencias sonoras por distancia de vuelta para Le Mans Ultimate en Windows. Lee la telemetría nativa; nunca envía controles al juego. **Son referencias fijas, no consejos de frenada ni un entrenador adaptativo.**

## De la instalación a tu primera vuelta con señales

Necesitas Windows y Python **3.9 o superior**. Abre PowerShell en la carpeta del proyecto, usando el mismo entorno de Python para todos los comandos.

1. **Instala el proyecto** (sin dependencias externas de ejecución):
   ```powershell
   pip install .
   ```
2. Activa la salida nativa de LMU: **Settings → Gameplay → Enable Plugins**, reinicia el juego y entra en una sesión de práctica privada con el coche local. Si el ajuste difiere, consulta la configuración de telemetría de tu versión. No instales el antiguo plugin de memoria compartida de rFactor 2.
3. **Con el coche detenido**, comprueba circuito, vehículo/clase y distancia observados:
   ```powershell
   python -m lmu_corner_cues session
   ```
4. **Inicia la grabación antes de conducir**:
   ```powershell
   python -m lmu_corner_cues record mi-vuelta
   ```
   Conduce una vuelta limpia y conservadora. El programa espera el siguiente paso por meta, graba una vuelta completa y termina automáticamente en el paso posterior. No pide ninguna entrada ni reproduce señales: **no leas ni uses el terminal mientras conduces**. Guarda `recordings/mi-vuelta.json` al terminar. Una grabación interrumpida o discontinua no produce un nuevo borrador.
5. **Detén el coche y espera a que `record` termine**. Después abre el asistente:
   ```powershell
   python -m lmu_corner_cues profile create recordings/mi-vuelta.json
   ```
   Verás el circuito, vehículo/clase y todos los candidatos en metros desde el inicio de vuelta. Escribe `STOPPED` para confirmar que estás detenido. Para cada curva, pulsa Enter para aceptar el nombre y cada distancia, o escribe sus valores corregidos. Elige un nombre como `mi-perfil` y revisa el resumen. Solo `SAVE` guarda `profiles/mi-perfil.json`; `cancel`, Ctrl+C o fin de entrada cancelan sin guardar. El asistente no puede ejecutarse a la vez que otro comando `record` de esta aplicación.
6. **Inicia las señales antes del primer marcador**, todavía detenido:
   ```powershell
   python -m lmu_corner_cues drive profiles/mi-perfil.json
   ```
   Comprueba una vuelta controlada: tono grave al frenar, par descendente al soltar freno y tono agudo al volver al gas. Detén el coche antes de usar Ctrl+C para cerrar el programa.

**No necesitas editar JSON.** Los archivos JSON son artefactos de exportación: conserva el borrador para volver a revisarlo con el asistente y el perfil confirmado para conducir.

> **Borrador no verificado ni calibrado:** «vuelta limpia» significa únicamente continuidad de la telemetría observada. La aplicación no conoce la validez deportiva de la vuelta. Los candidatos automáticos no son puntos seguros de frenada; el asistente exige tu revisión, pero confirmar no demuestra su seguridad. `drive` rechaza los borradores. Si no se detecta ninguna secuencia completa, graba otra vuelta.

## Opciones avanzadas y límites

- `record mi-vuelta --overwrite` permite reemplazar un borrador. `profile create recordings/mi-vuelta.json --overwrite` permite reemplazar el perfil elegido **solo después de `SAVE`**. Sin esa opción se evita sobrescribir, incluso si aparece un archivo durante la revisión.
- Los nombres de archivo admiten 1–64 letras ASCII, dígitos, guiones y guiones bajos; comienzan por letra o dígito y excluyen nombres reservados de Windows.
- `record` y `drive` aceptan `--interval 0.02` (segundos; finito y positivo). `python -m lmu_corner_cues profile create --help` muestra la ayuda del asistente. La invocación antigua `python -m lmu_corner_cues profiles/mi-perfil.json` sigue funcionando.
- La detección usa cruces de pedal: freno al 20 %, liberación al 5 % y gas al 20 % en una muestra posterior. Puede omitir curvas, frenadas ligeras y secuencias que cruzan la meta; no es una reconstrucción completa de tu conducción.
- El perfil conserva el circuito y vehículo exactos observados. El formato avanzado permite vehículo/clase o cualquier vehículo si se omite; el asistente usa siempre el vehículo concreto. Los identificadores distinguen mayúsculas. Repite la revisión y validación si cambian coche, setup, combustible, neumáticos, clima o agarre.
- El formato exportado contiene `circuit`, `vehicle` y `markers`: nombres únicos y distancias numéricas finitas no negativas `BRAKE < RELEASE_BRAKE < THROTTLE`. Cada curva comienza después del gas de la anterior. No se verifica la longitud del circuito ni la seguridad de los metros. [`profiles/example.json`](profiles/example.json) es ficticio, no está calibrado y no debe usarse como referencia real.
- Las señales dependen solo de vuelta y distancia: no filtran boxes, pausas, repeticiones ni peligros. Al arrancar a mitad de vuelta pueden sonar todos los marcadores ya alcanzados. Empieza antes del primero; ignora cualquier ráfaga atrasada. Una reducción de distancia en la misma vuelta silencia las señales hasta cambiar el contador de vuelta.
- Los pitidos bloquean el muestreo mientras suenan y pueden llegar tarde. Se emiten una vez por vuelta; reinicia el programa al cambiar de sesión o perfil. No hay reconexión automática ni garantía de tiempo real. Nunca consultes el terminal ni ajustes referencias mientras conduces.

## Validación manual exacta en Windows/LMU

**La compatibilidad real del ABI nativo y los sonidos todavía requieren esta prueba manual. No se ha realizado una prueba en vivo en este entorno de desarrollo.** Las pruebas sintéticas y `--help` no demuestran compatibilidad con tu versión instalada de LMU.

1. En un entorno limpio de Python en Windows, ejecuta `pip install .` y `python -m lmu_corner_cues --help`. No instales otros paquetes de telemetría.
2. Activa la memoria nativa, reinicia LMU y entra en una práctica privada con coche local. Detenido, ejecuta `python -m lmu_corner_cues session`. Anota versión de LMU, versión de Python, circuito, vehículo/clase y distancia mostrados. Comprueba que no hay errores de `LMU_Data`, tamaño/disposición incompatible ni jugador local.
3. Detenido, ejecuta `python -m lmu_corner_cues record validacion`. Cruza meta, conduce una vuelta completa limpia y cruza meta de nuevo sin tocar el terminal. Detén el coche y comprueba que el proceso terminó y guardó `recordings/validacion.json` como borrador no verificado.
4. Ejecuta `python -m lmu_corner_cues profile create recordings/validacion.json`. Revisa todos los candidatos, acepta o corrige nombres y metros y usa `cancel`: confirma que no apareció un perfil. Repite, elige `validacion` y confirma con `SAVE`; comprueba `profiles/validacion.json`. Repite sin `--overwrite` para comprobar que no lo reemplaza y cancela.
5. Detenido antes del primer marcador, ejecuta `python -m lmu_corner_cues drive profiles/validacion.json`. Confirma los tres sonidos en las distancias revisadas: grave de freno (440 Hz), par descendente de liberación (880/660 Hz) y agudo de gas (1320 Hz). Verifica que no se repiten en muestras consecutivas y vuelven a sonar en la siguiente vuelta. El silencio por sí solo no prueba conexión.
6. Detén el coche, cierra con Ctrl+C y anota perfil, versión del proyecto, resultado de conexión, distancias y sonidos observados. Si hay diferencias, no dependas del perfil: revisa detenido y repite la prueba.

## Resolución de problemas

| Síntoma | Acción |
|---|---|
| `No module named lmu_corner_cues` | Instala y ejecuta con el mismo entorno de Python. |
| Error de `LMU_Data` o plataforma Windows | Usa el PC Windows con LMU, salida nativa habilitada y sesión de conducción activa. |
| Tamaño/disposición incompatible o jugador local inválido | No fuerces la lectura. Comprueba versión del juego y compatibilidad del lector nativo; vuelve a entrar al coche y reinicia el comando. |
| Circuito/vehículo no coincide | Comprueba los identificadores con `session`; graba y revisa un perfil para esa combinación. |
| Borrador inválido o sin candidatos | Usa la salida de `record`, no un perfil confirmado; repite una vuelta completa con secuencias de freno, liberación y gas. |
| Distancias o nombres inválidos | Corrige en el asistente: nombres únicos, metros finitos y secuencias estrictamente crecientes sin solaparse. |
| Grabación/asistente activo o puerto 47863 ocupado | Termina el otro comando antes de reintentar. Se reserva un puerto de bucle local como exclusión entre procesos, sin escuchar ni transmitir datos; si otro programa lo ocupa, se rechaza la operación por seguridad. |
| Archivo ya existente | Elige otro nombre o usa explícitamente `--overwrite`. |
| Intervalo inválido | Usa un valor finito y positivo, por ejemplo `--interval 0.02`. |
| Sin audio o audio tardío | Comprueba salida y volumen de Windows, proceso activo y distancia alcanzada. Revisa los límites de muestreo y vuelta indicados arriba. |

Mantén la vista en la pista. Deja de usar las señales si distraen o resultan incorrectas; no consideran velocidad, tráfico ni adherencia.
