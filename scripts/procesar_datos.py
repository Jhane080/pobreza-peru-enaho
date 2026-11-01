"""Paso 2: pobreza monetaria por año, departamento y ámbito, 2019-2024.

Lee la sumaria de cada año (una fila por hogar), calcula tres indicadores
ponderados con su intervalo de confianza al 95 % y los valida contra la
cifra nacional oficial del INEI. Deja en datos/procesados/:
  pobreza_departamentos.csv   25 departamentos × 6 años
  pobreza_ambitos.csv         Perú, urbano, rural y regiones naturales × 6 años
  validacion.txt              la prueba de que replicamos al INEI
y en docs/data/ el JSON y el GeoJSON que usa el dashboard.

Uso:  uv run python scripts/procesar_datos.py
"""

import json
import shutil
from pathlib import Path

import pandas as pd

CARPETA_ORIGINALES = Path("datos/originales")
CARPETA_PROCESADOS = Path("datos/procesados")
CARPETA_WEB = Path("docs/data")
RUTA_LIMITES = Path("datos/limites/peru_departamental_simple.geojson")
ANIOS = [2019, 2020, 2021, 2022, 2023, 2024]

# Cifras oficiales del INEI (% de personas), del informe "Evolución de la
# pobreza monetaria" de cada año. Sirven solo para validar.
POBREZA_OFICIAL = {2019: 20.2, 2020: 30.1, 2021: 25.9, 2022: 27.5, 2023: 29.0, 2024: 27.6}
EXTREMA_OFICIAL = {2019: 2.9, 2020: 5.1, 2021: 4.1, 2022: 5.0, 2023: 5.7, 2024: 5.5}

NOMBRE_DEPARTAMENTO = {
    "01": "Amazonas", "02": "Áncash", "03": "Apurímac", "04": "Arequipa",
    "05": "Ayacucho", "06": "Cajamarca", "07": "Callao", "08": "Cusco",
    "09": "Huancavelica", "10": "Huánuco", "11": "Ica", "12": "Junín",
    "13": "La Libertad", "14": "Lambayeque", "15": "Lima", "16": "Loreto",
    "17": "Madre de Dios", "18": "Moquegua", "19": "Pasco", "20": "Piura",
    "21": "Puno", "22": "San Martín", "23": "Tacna", "24": "Tumbes", "25": "Ucayali",
}

# dominio: 1-3 costa, 4-6 sierra, 7 selva, 8 Lima Metropolitana (Lima y Callao).
REGION_NATURAL = {1: "Costa", 2: "Costa", 3: "Costa", 4: "Sierra", 5: "Sierra",
                  6: "Sierra", 7: "Selva", 8: "Lima Metropolitana"}

INDICADORES = {"pobre": "pobreza", "pobre_extremo": "extrema", "brecha": "brecha"}


def estimar_con_intervalo(hogares, columna):
    """Porcentaje ponderado por personas y su intervalo de confianza al 95 %.

    La ENAHO no es una muestra al azar simple: se sortean conglomerados
    (manzanas o grupos de viviendas) dentro de estratos. Los hogares de un
    mismo conglomerado se parecen, así que el error se calcula sumando por
    conglomerado (linealización de Taylor), igual que hace svy en Stata.
    """
    peso = hogares["factor_personas"]
    total_peso = peso.sum()
    tasa = (peso * hogares[columna]).sum() / total_peso

    aporte = peso * (hogares[columna] - tasa) / total_peso
    aportes = pd.DataFrame({"estrato": hogares["estrato_diseno"],
                            "conglome": hogares["conglome"], "aporte": aporte})
    por_conglomerado = aportes.groupby(["estrato", "conglome"])["aporte"].sum().reset_index()

    varianza = 0.0
    for _, conglomerados in por_conglomerado.groupby("estrato"):
        cantidad = len(conglomerados)
        # Un estrato con un solo conglomerado no permite medir su variación.
        if cantidad > 1:
            desvios = conglomerados["aporte"] - conglomerados["aporte"].mean()
            varianza += cantidad / (cantidad - 1) * (desvios**2).sum()

    error = varianza**0.5
    return tasa * 100, (tasa - 1.96 * error) * 100, (tasa + 1.96 * error) * 100


def resumir(hogares):
    """Una fila con los tres indicadores, sus intervalos y el tamaño de muestra."""
    fila = {"hogares_muestra": len(hogares),
            "poblacion": round(hogares["factor_personas"].sum())}
    for columna, nombre in INDICADORES.items():
        tasa, inferior, superior = estimar_con_intervalo(hogares, columna)
        fila[nombre] = round(tasa, 2)
        fila[f"{nombre}_ic_inf"] = round(inferior, 2)
        fila[f"{nombre}_ic_sup"] = round(superior, 2)
    return fila


filas_departamentos = []
filas_ambitos = []
lineas_validacion = []

for anio in ANIOS:
    # 1. Leer ------------------------------------------------------------------
    ruta_sumaria = list(CARPETA_ORIGINALES.glob(f"*-Modulo34/sumaria-{anio}.dta"))[0]
    columnas = ["conglome", "vivienda", "hogar", "ubigeo", "dominio", "estrato",
                "mieperho", "factor07", "pobreza", "linea", "gashog2d"]
    # convert_categoricals=False deja pobreza como 1, 2, 3 y no como etiquetas.
    hogares = pd.read_stata(ruta_sumaria, columns=columnas, convert_categoricals=False)

    # 2. Limpiar ---------------------------------------------------------------
    # El ubigeo es texto de 6 dígitos: leído como número, Amazonas (01) se
    # convierte en "1" y no cruza con el mapa.
    hogares["ubigeo"] = hogares["ubigeo"].astype(str).str.zfill(6)
    hogares["conglome"] = hogares["conglome"].astype(str).str.zfill(6)
    hogares = hogares.dropna(subset=["pobreza", "factor07"])
    duplicados = hogares.duplicated(["conglome", "vivienda", "hogar"]).sum()
    assert duplicados == 0, f"{anio}: hay {duplicados} hogares repetidos"

    # 3. Construir indicadores -------------------------------------------------
    hogares["codigo_departamento"] = hogares["ubigeo"].str[:2]
    hogares["estrato_diseno"] = hogares["codigo_departamento"] + "-" + hogares["estrato"].astype(str)
    hogares["area"] = "Rural"
    hogares.loc[hogares["estrato"] <= 5, "area"] = "Urbano"
    hogares["region"] = hogares["dominio"].map(REGION_NATURAL)

    # pobreza es un código (1 extremo, 2 no extremo, 3 no pobre), no un número.
    hogares["pobre"] = hogares["pobreza"] <= 2
    hogares["pobre_extremo"] = hogares["pobreza"] == 1

    # Un hogar representa factor07 hogares, o sea factor07 × mieperho personas.
    hogares["factor_personas"] = hogares["factor07"] * hogares["mieperho"]

    # Brecha de pobreza: cuánto le falta en promedio al gasto de cada persona
    # para llegar a la línea, como % de la línea (0 si no es pobre).
    gasto_mensual_por_persona = hogares["gashog2d"] / (12 * hogares["mieperho"])
    faltante = (hogares["linea"] - gasto_mensual_por_persona) / hogares["linea"]
    hogares["brecha"] = faltante.clip(lower=0)

    # 4. Estimar ---------------------------------------------------------------
    nacional = resumir(hogares)
    filas_ambitos.append({"anio": anio, "ambito": "Perú", "tipo": "Nacional", **nacional})
    for area, hogares_area in hogares.groupby("area"):
        filas_ambitos.append({"anio": anio, "ambito": area, "tipo": "Área", **resumir(hogares_area)})
    for region, hogares_region in hogares.groupby("region"):
        filas_ambitos.append({"anio": anio, "ambito": region, "tipo": "Región natural",
                              **resumir(hogares_region)})

    for codigo, hogares_departamento in hogares.groupby("codigo_departamento"):
        filas_departamentos.append({"anio": anio, "codigo": codigo,
                                    "departamento": NOMBRE_DEPARTAMENTO[codigo],
                                    **resumir(hogares_departamento)})

    # 5. Validar ---------------------------------------------------------------
    # La condición de pobreza del INEI debe coincidir con comparar gasto y línea.
    coincide = ((gasto_mensual_por_persona < hogares["linea"]) == hogares["pobre"]).mean() * 100
    diferencia = abs(nacional["pobreza"] - POBREZA_OFICIAL[anio])
    estado = "OK" if diferencia < 0.1 else "REVISAR"
    lineas_validacion.append(
        f"{anio}  hogares {len(hogares):>6,}  pobreza {nacional['pobreza']:5.2f} % "
        f"(INEI {POBREZA_OFICIAL[anio]})  extrema {nacional['extrema']:4.2f} % "
        f"(INEI {EXTREMA_OFICIAL[anio]})  gasto<línea = pobre en {coincide:.1f} %  {estado}"
    )
    print(lineas_validacion[-1])

# 6. Guardar -------------------------------------------------------------------
CARPETA_PROCESADOS.mkdir(parents=True, exist_ok=True)
CARPETA_WEB.mkdir(parents=True, exist_ok=True)

departamentos = pd.DataFrame(filas_departamentos)
ambitos = pd.DataFrame(filas_ambitos)
departamentos.to_csv(CARPETA_PROCESADOS / "pobreza_departamentos.csv", index=False, encoding="utf-8")
ambitos.to_csv(CARPETA_PROCESADOS / "pobreza_ambitos.csv", index=False, encoding="utf-8")

texto_validacion = "Validación contra la pobreza oficial del INEI (% de personas)\n\n"
texto_validacion += "\n".join(lineas_validacion) + "\n"
(CARPETA_PROCESADOS / "validacion.txt").write_text(texto_validacion, encoding="utf-8")

datos_web = {
    "anios": ANIOS,
    "fuente": "INEI, Encuesta Nacional de Hogares (ENAHO), módulo 34 Sumaria, 2019-2024",
    "departamentos": departamentos.to_dict(orient="records"),
    "ambitos": ambitos.to_dict(orient="records"),
}
with open(CARPETA_WEB / "pobreza.json", "w", encoding="utf-8") as archivo:
    json.dump(datos_web, archivo, ensure_ascii=False)
shutil.copy(RUTA_LIMITES, CARPETA_WEB / "departamentos.geojson")

if "REVISAR" in texto_validacion:
    raise SystemExit("Alguna cifra no replica al INEI: revisen validacion.txt antes de seguir.")
print("Listo: datos/procesados/ y docs/data/")
