"""Paso 3: los tres hallazgos, con sus cifras, y las figuras que los muestran.

Lee las tablas de datos/procesados/ y deja:
  datos/procesados/hallazgos.json   las cifras que usan el README y el guion del reel
  figuras/*.png                     gráficos y mapas en formato cuadrado para el reel

Uso:  uv run python scripts/analizar_datos.py
"""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # sin ventanas: solo guardamos los PNG
import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm

CARPETA_PROCESADOS = Path("datos/procesados")
CARPETA_FIGURAS = Path("figuras")
RUTA_LIMITES = Path("datos/limites/peru_departamental_simple.geojson")

# Los mismos colores del dashboard y del reel.
FONDO = "#1c1a17"
CREMA = "#f5f0e8"
GRIS = "#968f8a"
NARANJA = "#f08c3c"
AZUL = "#5aa0c8"

plt.rcParams.update({
    "figure.facecolor": FONDO, "axes.facecolor": FONDO, "savefig.facecolor": FONDO,
    "text.color": CREMA, "axes.labelcolor": CREMA, "xtick.color": GRIS, "ytick.color": GRIS,
    "axes.edgecolor": GRIS, "font.family": "Segoe UI", "font.size": 22,
})

departamentos = pd.read_csv(CARPETA_PROCESADOS / "pobreza_departamentos.csv", dtype={"codigo": str})
ambitos = pd.read_csv(CARPETA_PROCESADOS / "pobreza_ambitos.csv")
limites = gpd.read_file(RUTA_LIMITES)
CARPETA_FIGURAS.mkdir(exist_ok=True)


def fila(tabla, anio, columna, valor):
    """La única fila de la tabla para ese año y ese ámbito o departamento."""
    return tabla[(tabla["anio"] == anio) & (tabla[columna] == valor)].iloc[0]


def millones_de_pobres(registro):
    return registro["pobreza"] / 100 * registro["poblacion"] / 1_000_000


# Hallazgo 1: la pobreza no volvió a su nivel de antes de la pandemia ----------
peru_2019 = fila(ambitos, 2019, "ambito", "Perú")
peru_2020 = fila(ambitos, 2020, "ambito", "Perú")
peru_2024 = fila(ambitos, 2024, "ambito", "Perú")
hallazgo_1 = {
    "pobreza_2019": peru_2019["pobreza"],
    "pobreza_2020": peru_2020["pobreza"],
    "pobreza_2024": peru_2024["pobreza"],
    "extrema_2019": peru_2019["extrema"],
    "extrema_2024": peru_2024["extrema"],
    "millones_pobres_2019": round(millones_de_pobres(peru_2019), 2),
    "millones_pobres_2024": round(millones_de_pobres(peru_2024), 2),
}

# Hallazgo 2: la pobreza se volvió urbana ---------------------------------------
hallazgo_2 = {}
for anio in [2019, 2024]:
    urbano = fila(ambitos, anio, "ambito", "Urbano")
    rural = fila(ambitos, anio, "ambito", "Rural")
    lima = fila(ambitos, anio, "ambito", "Lima Metropolitana")
    pobres_urbanos = millones_de_pobres(urbano)
    pobres_rurales = millones_de_pobres(rural)
    hallazgo_2[f"urbano_{anio}"] = urbano["pobreza"]
    hallazgo_2[f"rural_{anio}"] = rural["pobreza"]
    hallazgo_2[f"lima_metropolitana_{anio}"] = lima["pobreza"]
    hallazgo_2[f"millones_pobres_urbanos_{anio}"] = round(pobres_urbanos, 2)
    hallazgo_2[f"millones_pobres_rurales_{anio}"] = round(pobres_rurales, 2)
    hallazgo_2[f"porcentaje_pobres_en_ciudades_{anio}"] = round(
        pobres_urbanos / (pobres_urbanos + pobres_rurales) * 100, 1)

# Hallazgo 3: el golpe fue desigual entre departamentos -------------------------
inicio = departamentos[departamentos["anio"] == 2019].set_index("departamento")
final = departamentos[departamentos["anio"] == 2024].set_index("departamento")
cambios = pd.DataFrame({
    "codigo": final["codigo"],
    "pobreza_2019": inicio["pobreza"],
    "pobreza_2024": final["pobreza"],
    "cambio": final["pobreza"] - inicio["pobreza"],
})
# Decimos que un cambio es claro solo si los intervalos de confianza de 2019 y
# 2024 no se tocan. Es una regla exigente: deja fuera cambios dudosos.
cambios["subio_claramente"] = final["pobreza_ic_inf"] > inicio["pobreza_ic_sup"]
cambios["bajo_claramente"] = final["pobreza_ic_sup"] < inicio["pobreza_ic_inf"]
cambios = cambios.sort_values("cambio", ascending=False)

hallazgo_3 = {
    "mas_subio": cambios.head(5)[["pobreza_2019", "pobreza_2024", "cambio"]].round(1).to_dict(orient="index"),
    "mas_bajo": cambios.tail(4)[["pobreza_2019", "pobreza_2024", "cambio"]].round(1).to_dict(orient="index"),
    "departamentos_que_subieron_claramente": int(cambios["subio_claramente"].sum()),
    "departamentos_que_bajaron_claramente": int(cambios["bajo_claramente"].sum()),
    "mayor_pobreza_2024": final["pobreza"].sort_values(ascending=False).head(3).round(1).to_dict(),
    "menor_pobreza_2024": final["pobreza"].sort_values().head(3).round(1).to_dict(),
}

hallazgos = {"hallazgo_1": hallazgo_1, "hallazgo_2": hallazgo_2, "hallazgo_3": hallazgo_3}
with open(CARPETA_PROCESADOS / "hallazgos.json", "w", encoding="utf-8") as archivo:
    json.dump(hallazgos, archivo, ensure_ascii=False, indent=2)
print(json.dumps(hallazgos, ensure_ascii=False, indent=2))

# Figura 1: la serie nacional, urbana y rural ----------------------------------
figura, eje = plt.subplots(figsize=(10, 10))
# Perú y Urbano terminan muy cerca: subimos un poco la etiqueta de Perú para que no se pisen.
for ambito, color, ajuste in [("Rural", GRIS, 0), ("Perú", NARANJA, 2.5), ("Urbano", AZUL, -1.5)]:
    serie = ambitos[ambitos["ambito"] == ambito]
    eje.plot(serie["anio"], serie["pobreza"], color=color, linewidth=6, marker="o", markersize=12)
    eje.text(2024.15, serie["pobreza"].iloc[-1] + ajuste, f"{ambito}\n{serie['pobreza'].iloc[-1]:.1f} %",
             color=color, va="center", fontsize=22, fontweight="bold")
eje.axvspan(2019.6, 2020.4, color=GRIS, alpha=0.15)
eje.text(2020, 3, "Pandemia", ha="center", color=GRIS, fontsize=20)
eje.set_ylim(0, 50)
eje.set_xlim(2018.7, 2025.3)
eje.set_xticks([2019, 2020, 2021, 2022, 2023, 2024])
eje.set_ylabel("% de personas en pobreza")
for borde in ["top", "right"]:
    eje.spines[borde].set_visible(False)
eje.set_title("Pobreza monetaria, 2019-2024", loc="left", fontsize=30, fontweight="bold", pad=20)
figura.tight_layout()
figura.savefig(CARPETA_FIGURAS / "serie_nacional.png", dpi=108)
plt.close(figura)

# Figura 2: pobres en la ciudad y en el campo, en millones -----------------------
figura, eje = plt.subplots(figsize=(10, 10))
anios = ["2019", "2024"]
urbanos = [hallazgo_2["millones_pobres_urbanos_2019"], hallazgo_2["millones_pobres_urbanos_2024"]]
rurales = [hallazgo_2["millones_pobres_rurales_2019"], hallazgo_2["millones_pobres_rurales_2024"]]
eje.bar(anios, rurales, color=GRIS, width=0.6, label="Rural")
eje.bar(anios, urbanos, bottom=rurales, color=AZUL, width=0.6, label="Urbano")
for posicion in range(2):
    eje.text(posicion, rurales[posicion] / 2, f"{rurales[posicion]:.1f} M", ha="center",
             color=FONDO, fontsize=26, fontweight="bold")
    eje.text(posicion, rurales[posicion] + urbanos[posicion] / 2, f"{urbanos[posicion]:.1f} M",
             ha="center", color=FONDO, fontsize=26, fontweight="bold")
eje.legend(frameon=False, loc="upper left", fontsize=22)
eje.set_ylim(0, 11)
eje.set_ylabel("Millones de personas pobres")
for borde in ["top", "right"]:
    eje.spines[borde].set_visible(False)
eje.set_title("¿Dónde viven los pobres?", loc="left", fontsize=30, fontweight="bold", pad=20)
figura.tight_layout()
figura.savefig(CARPETA_FIGURAS / "pobres_urbano_rural.png", dpi=108)
plt.close(figura)

# Figuras 3 y 4: mapas de 2024 y del cambio 2019-2024 ----------------------------
mapa = limites.merge(cambios, left_on="FIRST_IDDP", right_on="codigo", how="left")
assert mapa["cambio"].notna().all(), "Algún departamento no cruzó con el mapa"

escala_naranja = LinearSegmentedColormap.from_list("naranja", ["#3a332c", NARANJA, "#fff1d6"])
figura, eje = plt.subplots(figsize=(10, 12))
mapa.plot(column="pobreza_2024", cmap=escala_naranja, edgecolor=FONDO, linewidth=1, ax=eje,
          legend=True, legend_kwds={"shrink": 0.5, "label": "% de personas en pobreza"})
eje.set_axis_off()
eje.set_title("Pobreza por departamento, 2024", loc="left", fontsize=30, fontweight="bold")
figura.tight_layout()
figura.savefig(CARPETA_FIGURAS / "mapa_pobreza_2024.png", dpi=108)
plt.close(figura)

escala_cambio = LinearSegmentedColormap.from_list("cambio", [AZUL, "#3a332c", NARANJA])
figura, eje = plt.subplots(figsize=(10, 12))
mapa.plot(column="cambio", cmap=escala_cambio, norm=TwoSlopeNorm(vcenter=0, vmin=-10, vmax=20),
          edgecolor=FONDO, linewidth=1, ax=eje, legend=True,
          legend_kwds={"shrink": 0.5, "label": "Cambio en puntos porcentuales"})
eje.set_axis_off()
eje.set_title("Cambio en la pobreza, 2019 → 2024", loc="left", fontsize=30, fontweight="bold")
figura.tight_layout()
figura.savefig(CARPETA_FIGURAS / "mapa_cambio.png", dpi=108)
plt.close(figura)

# Figura 5: los departamentos ordenados por cambio --------------------------------
orden = cambios.sort_values("cambio")
colores = [NARANJA if cambio > 0 else AZUL for cambio in orden["cambio"]]
figura, eje = plt.subplots(figsize=(10, 12))
eje.barh(orden.index, orden["cambio"], color=colores)
eje.axvline(0, color=GRIS, linewidth=1)
eje.tick_params(axis="y", labelsize=17, colors=CREMA)
eje.set_xlabel("Puntos porcentuales, 2019 → 2024")
for borde in ["top", "right", "left"]:
    eje.spines[borde].set_visible(False)
eje.set_title("¿Dónde subió más la pobreza?", loc="left", fontsize=30, fontweight="bold", pad=20)
figura.tight_layout()
figura.savefig(CARPETA_FIGURAS / "ranking_cambio.png", dpi=108)
plt.close(figura)

print("Listo: datos/procesados/hallazgos.json y figuras/")
