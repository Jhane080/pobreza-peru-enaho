"""Paso 1: baja la sumaria (módulo 34) de la ENAHO 2019-2024 del portal del INEI.

Deja cada año descomprimido en datos/originales/<código>-Modulo34/.
La sumaria trae una fila por hogar con la condición de pobreza oficial.

Uso:  uv run python scripts/obtener_datos.py
"""

import re
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

PORTAL = "https://proyectos.inei.gob.pe/microdatos"
DESCARGAS = "https://proyectos.inei.gob.pe/iinei/srienaho/descarga/STATA"
CARPETA_ORIGINALES = Path("datos/originales")
ANIOS = [2019, 2020, 2021, 2022, 2023, 2024]

CARPETA_ORIGINALES.mkdir(parents=True, exist_ok=True)

for anio in ANIOS:
    # El INEI no numera las descargas por año sino por un código de encuesta
    # (2024 es 966). Le hacemos al portal el mismo pedido que hace la página
    # cuando uno elige "Condiciones de Vida y Pobreza - ENAHO", el año y "Anual".
    formulario = urllib.parse.urlencode({
        "bandera": 1,
        "_cmbEncuesta": "Condiciones de Vida y Pobreza - ENAHO",
        "_cmbAnno": anio,
        "_cmbTrimestre": 55,  # 55 es el periodo "Anual - (Ene-Dic)"
    }).encode()
    with urllib.request.urlopen(f"{PORTAL}/cambiaPeriodo.asp", data=formulario) as respuesta:
        pagina = respuesta.read().decode("latin-1")

    codigos = re.findall(r"STATA/(\d+)-Modulo34\.zip", pagina)
    if not codigos:
        raise SystemExit(f"El INEI no tiene la ENAHO anual {anio} en el portal.")
    codigo = codigos[0]

    nombre_zip = f"{codigo}-Modulo34.zip"
    ruta_zip = CARPETA_ORIGINALES / nombre_zip
    # Una descarga cortada a medias no es un zip válido y se vuelve a bajar.
    if not zipfile.is_zipfile(ruta_zip):
        print(f"ENAHO {anio}: bajando {nombre_zip}...")
        urllib.request.urlretrieve(f"{DESCARGAS}/{nombre_zip}", ruta_zip)

    with zipfile.ZipFile(ruta_zip) as archivo_zip:
        archivo_zip.extractall(CARPETA_ORIGINALES)

    ruta_sumaria = CARPETA_ORIGINALES / f"{codigo}-Modulo34" / f"sumaria-{anio}.dta"
    if not ruta_sumaria.exists():
        raise SystemExit(f"{nombre_zip} no trae sumaria-{anio}.dta. Revisen el zip a mano.")
    print(f"Listo: {ruta_sumaria}")
