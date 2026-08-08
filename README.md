# Coach de audio para iRacing

Avisos sonoros de frenada y de reapertura de gas, a partir de una vuelta
de referencia exportada de Garage61.

## Los tres modulos

| fichero | que hace | necesita iRacing |
|---|---|---|
| `analyzer.py` | CSV de Garage61 -> JSON de eventos | no |
| `source.py`   | telemetria: CSV reproducido o iRacing en vivo | solo la clase `IRacingSource` |
| `coach.py`    | bucle en vivo, anticipacion y audio | no |

## Desarrollo en Mac

`pyirsdk` es exclusivo de Windows, pero solo lo toca `IRacingSource`.
Todo lo demas se desarrolla y se prueba en el Mac reproduciendo un CSV,
que es una grabacion del mismo flujo de datos a la misma frecuencia:

```bash
pip install -r requirements.txt

python analyzer.py vuelta.csv --track hockenheim_gp \
    --car ferrari_296_gt3 -o ref_hockenheim.json

# tiempo real, con sonido
python coach.py ref_hockenheim.json --replay vuelta.csv

# ocho veces mas rapido y sin sonido, para iterar deprisa
python coach.py ref_hockenheim.json --replay vuelta.csv \
    --replay-speed 8 --console
```

## Puesta en marcha en el PC de juego (Windows)

```powershell
git clone <tu-repo>
cd coach
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install pyirsdk

# iRacing abierto y en pista
python coach.py ref_hockenheim.json
```

Sin `--replay` usa `IRacingSource` automaticamente.

## Parametros que vas a querer tocar

- `--lead` segundos de antelacion del aviso (por defecto 0.35)
- `--margin` metros extra de margen de seguridad
- `--speed-tol` desviacion de velocidad tolerada frente a la referencia
- `--skip-mismatch` callar el aviso si llegas muy lejos de la referencia
