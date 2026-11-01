"""Paso 4: el reel. Mi voz clonada narra el guion sobre los gráficos y el dashboard.

Lee reel/guion.json (revisado contra datos/procesados/hallazgos.json) y deja en reel/:
  reel.mp4         video vertical 1080 × 1920 con narración, música y subtítulos
  subtitulos.srt   subtítulos sincronizados
  portada.png      primer cuadro, para la miniatura
  recursos/musica.wav   la pista de fondo, generada aquí mismo (sin derechos de terceros)

Uso (desde la carpeta del proyecto, con el entorno que tiene Qwen3-TTS y Whisper):
    python reel/hacer_reel.py --voz reel/recursos/mi_voz.mp4 --modelos ../reel-reporte-inflacion-bcrp/modelos
"""

import argparse
import json
import re
import subprocess
from pathlib import Path

import jiwer
import numpy as np
import soundfile
import torch
from faster_whisper import WhisperModel
from imageio_ffmpeg import get_ffmpeg_exe
from num2words import num2words
from PIL import Image, ImageDraw, ImageFont
from qwen_tts import Qwen3TTSModel

CARPETA_REEL = Path("reel")
CARPETA_AUDIO = CARPETA_REEL / "audio"

ANCHO = 1080
ALTO = 1920
CUADROS_POR_SEGUNDO = 30
MARGEN = 90

FONDO = (28, 26, 23)
CREMA = (245, 240, 232)
NARANJA = (240, 140, 60)
GRIS = (150, 145, 138)
CAJA = (48, 45, 41)

# Zona donde va la imagen de cada escena. Abajo dejamos libre la franja que
# tapan los botones de LinkedIn e Instagram.
CAJA_IMAGEN = (MARGEN, 620, ANCHO - MARGEN, 1450)
ALTO_SUBTITULO = 1490

FUENTES = "C:/Windows/Fonts/"
FUENTE_CIFRA = ImageFont.truetype(FUENTES + "seguibl.ttf", 150)
FUENTE_ETIQUETA = ImageFont.truetype(FUENTES + "segoeuib.ttf", 48)
FUENTE_CABECERA = ImageFont.truetype(FUENTES + "segoeuib.ttf", 30)
FUENTE_SUBTITULO = ImageFont.truetype(FUENTES + "segoeuib.ttf", 58)
FUENTE_PIE = ImageFont.truetype(FUENTES + "segoeui.ttf", 30)

# Más del 15 % de palabras mal entendidas por Whisper = la escena se genera de nuevo.
ERROR_MAXIMO = 0.15
INTENTOS = 4
# Nombres que Whisper no conoce: sin esta pista escribe "Ucayaly" o "Inei".
PALABRAS_ESPERADAS = "INEI Callao Ucayali Tumbes Lima Metropolitana pandemia"
CORRECCIONES = {"Inei": "INEI", "inei": "INEI", "Ucayaly": "Ucayali", "Callali": "Callao", "Callali,": "Callao,"}
PAUSA_ENTRE_ESCENAS = 0.45
PALABRAS_POR_SUBTITULO = 4
# La música va unos 20 dB por debajo de la voz para que nunca la tape.
VOLUMEN_MUSICA = 0.09


def numero_en_palabras(coincidencia):
    partes = re.split(r"[.,]", coincidencia.group())
    palabras = []
    for parte in partes:
        palabras.append(num2words(int(parte), lang="es"))
    return " coma ".join(palabras)


def normalizar(texto):
    """Whisper escribe '20,2%' y el guion dice 'veinte coma dos por ciento': los igualamos."""
    texto = texto.lower().replace("%", " por ciento")
    texto = re.sub(r"\d+(?:[.,]\d+)?", numero_en_palabras, texto)
    texto = re.sub(r"[^\w\s]", " ", texto)
    return " ".join(texto.split())


def audio_para_whisper(ruta):
    """Whisper espera audio a 16 kHz; lo convertimos con ffmpeg."""
    resultado = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(ruta), "-f", "f32le", "-ac", "1", "-ar", "16000", "-"],
        capture_output=True, check=True,
    )
    return np.frombuffer(resultado.stdout, dtype=np.float32)


def transcribir(whisper, ruta):
    """Devuelve la lista de palabras con su segundo de inicio y de fin."""
    segmentos, _ = whisper.transcribe(audio_para_whisper(ruta), language="es", word_timestamps=True,
                                      hotwords=PALABRAS_ESPERADAS)
    palabras = []
    for segmento in segmentos:
        for palabra in segmento.words:
            texto = palabra.word.strip()
            texto = CORRECCIONES.get(texto, texto)
            # Whisper separa "20" de ",2%": los volvemos a unir para el subtítulo.
            if palabras and texto[0] in ",.%":
                palabras[-1]["texto"] += texto
                palabras[-1]["fin"] = palabra.end
            else:
                palabras.append({"texto": texto, "inicio": palabra.start, "fin": palabra.end})
    return palabras


def partir_en_lineas(dibujo, texto, fuente, ancho_maximo):
    lineas = []
    linea_actual = ""
    for palabra in texto.split():
        prueba = (linea_actual + " " + palabra).strip()
        if dibujo.textlength(prueba, font=fuente) <= ancho_maximo:
            linea_actual = prueba
        else:
            lineas.append(linea_actual)
            linea_actual = palabra
    lineas.append(linea_actual)
    return lineas


def dibujar_fondo_de_escena(escena, numero, total, titulo, pie):
    """Lo que no cambia durante la escena: cabecera, aviso de IA, cifra, etiqueta y pie."""
    imagen = Image.new("RGB", (ANCHO, ALTO), FONDO)
    dibujo = ImageDraw.Draw(imagen)

    # Barra de avance: cuántas escenas van.
    dibujo.rectangle([MARGEN, 150, ANCHO - MARGEN, 156], fill=CAJA)
    avance = MARGEN + (ANCHO - 2 * MARGEN) * numero / total
    dibujo.rectangle([MARGEN, 150, avance, 156], fill=NARANJA)

    dibujo.text((MARGEN, 184), titulo.upper(), font=FUENTE_CABECERA, fill=NARANJA)
    aviso = "Voz generada con IA"
    ancho_aviso = dibujo.textlength(aviso, font=FUENTE_PIE)
    x_aviso = ANCHO - MARGEN - ancho_aviso - 40
    dibujo.rounded_rectangle([x_aviso, 176, ANCHO - MARGEN, 228], radius=12, outline=GRIS, width=2)
    dibujo.text((x_aviso + 20, 182), aviso, font=FUENTE_PIE, fill=CREMA)

    dibujo.text((MARGEN, 260), escena["cifra"], font=FUENTE_CIFRA, fill=CREMA)
    y = 470
    for linea in partir_en_lineas(dibujo, escena["etiqueta"], FUENTE_ETIQUETA, ANCHO - 2 * MARGEN):
        dibujo.text((MARGEN, y), linea, font=FUENTE_ETIQUETA, fill=GRIS)
        y += 60

    y = 1600
    for linea in pie:
        dibujo.text((MARGEN, y), linea, font=FUENTE_PIE, fill=GRIS)
        y += 40
    return imagen


def recorte_de_imagen(escena, imagen, avance):
    """El pedazo de la imagen que se ve en este cuadro: así nada queda quieto.

    zoom: la imagen se acerca un 8 % a lo largo de la escena.
    paneo: una ventana baja por una captura larga del dashboard, como si alguien hiciera scroll.
    avance va de 0 (inicio de la escena) a 1 (final).
    """
    ancho_caja = CAJA_IMAGEN[2] - CAJA_IMAGEN[0]
    alto_caja = CAJA_IMAGEN[3] - CAJA_IMAGEN[1]
    ancho, alto = imagen.size

    if escena["movimiento"] == "paneo":
        alto_ventana = round(ancho * alto_caja / ancho_caja)
        # Suavizado: arranca y termina despacio.
        suave = (1 - np.cos(np.pi * avance)) / 2
        arriba = escena["desde"] + (escena["hasta"] - escena["desde"]) * suave
        arriba = min(arriba, alto - alto_ventana)
        recorte = imagen.crop((0, round(arriba), ancho, round(arriba) + alto_ventana))
        return recorte.resize((ancho_caja, alto_caja), Image.BILINEAR)

    zoom = 1 + 0.08 * avance
    ancho_visible = ancho / zoom
    alto_visible = alto / zoom
    izquierda = (ancho - ancho_visible) / 2
    arriba = (alto - alto_visible) / 2
    recorte = imagen.crop((round(izquierda), round(arriba),
                           round(izquierda + ancho_visible), round(arriba + alto_visible)))
    # Cabe entero en la caja sin deformarse.
    escala = min(ancho_caja / recorte.width, alto_caja / recorte.height)
    return recorte.resize((round(recorte.width * escala), round(recorte.height * escala)), Image.BILINEAR)


def dibujar_subtitulo(imagen, palabras, segundo):
    """Muestra el grupo de palabras que se está diciendo; la palabra actual va en naranja."""
    grupo_actual = None
    for inicio_grupo in range(0, len(palabras), PALABRAS_POR_SUBTITULO):
        grupo = palabras[inicio_grupo : inicio_grupo + PALABRAS_POR_SUBTITULO]
        if grupo[0]["inicio"] <= segundo:
            grupo_actual = grupo
    if grupo_actual is None:
        return

    dibujo = ImageDraw.Draw(imagen)
    texto_completo = " ".join(palabra["texto"] for palabra in grupo_actual)
    fuente = FUENTE_SUBTITULO
    ancho_texto = dibujo.textlength(texto_completo, font=fuente)
    # Si las palabras son largas, achicamos la letra para que no se salga de la zona segura.
    if ancho_texto > ANCHO - 2 * MARGEN - 60:
        fuente = ImageFont.truetype(FUENTES + "segoeuib.ttf", 44)
        ancho_texto = dibujo.textlength(texto_completo, font=fuente)
    x = (ANCHO - ancho_texto) / 2
    dibujo.rounded_rectangle([x - 30, ALTO_SUBTITULO, x + ancho_texto + 30, ALTO_SUBTITULO + 96],
                             radius=20, fill=CAJA)
    for palabra in grupo_actual:
        color = CREMA
        if palabra["inicio"] <= segundo <= palabra["fin"]:
            color = NARANJA
        dibujo.text((x, ALTO_SUBTITULO + 12), palabra["texto"], font=fuente, fill=color)
        x += dibujo.textlength(palabra["texto"] + " ", font=fuente)


def hacer_musica(duracion, frecuencia):
    """Una pista suave de acordes (la menor, fa, do, sol) hecha con ondas seno.

    La generamos nosotros para no depender de música con derechos de autor.
    """
    acordes = [[220.00, 261.63, 329.63], [174.61, 220.00, 261.63],
               [130.81, 196.00, 261.63], [196.00, 246.94, 293.66]]
    segundos_por_acorde = 4
    tiempo = np.arange(int(duracion * frecuencia)) / frecuencia
    musica = np.zeros_like(tiempo)
    for indice_acorde in range(int(duracion // segundos_por_acorde) + 1):
        inicio = indice_acorde * segundos_por_acorde
        en_el_acorde = (tiempo >= inicio) & (tiempo < inicio + segundos_por_acorde + 1)
        t = tiempo[en_el_acorde] - inicio
        # Cada acorde entra y sale suave, y se solapa un segundo con el siguiente.
        envolvente = np.minimum(1, t / 1.0) * np.minimum(1, np.maximum(0, (segundos_por_acorde + 1 - t) / 1.0))
        for nota in acordes[indice_acorde % len(acordes)]:
            musica[en_el_acorde] += envolvente * (np.sin(2 * np.pi * nota * t)
                                                 + 0.3 * np.sin(2 * np.pi * nota * 2 * t))
        # Una nota grave por acorde para dar cuerpo.
        bajo = acordes[indice_acorde % len(acordes)][0] / 2
        musica[en_el_acorde] += 0.8 * envolvente * np.sin(2 * np.pi * bajo * t)
    # Entrada y salida de dos segundos.
    musica *= np.minimum(1, tiempo / 2) * np.minimum(1, (duracion - tiempo) / 2)
    return musica / np.abs(musica).max()


def formato_srt(segundos):
    milisegundos = int(segundos * 1000)
    horas, milisegundos = divmod(milisegundos, 3_600_000)
    minutos, milisegundos = divmod(milisegundos, 60_000)
    segundos, milisegundos = divmod(milisegundos, 1000)
    return f"{horas:02d}:{minutos:02d}:{segundos:02d},{milisegundos:03d}"


parser = argparse.ArgumentParser()
parser.add_argument("--voz", required=True, help="tu nota de voz (.m4a, .ogg, .mp4, .wav)")
# En Windows los modelos están bajados como archivos normales: la caché de
# Hugging Face usa symlinks y Windows no los permite sin modo desarrollador.
parser.add_argument("--modelos", required=True, help="carpeta con Qwen3-TTS y faster-whisper")
parser.add_argument("--reusar-audio", action="store_true",
                    help="usa los reel/audio/escena_N.wav ya generados y solo rehace el video")
argumentos = parser.parse_args()

ffmpeg = get_ffmpeg_exe()
CARPETA_AUDIO.mkdir(parents=True, exist_ok=True)
(CARPETA_REEL / "recursos").mkdir(exist_ok=True)

with open(CARPETA_REEL / "guion.json", encoding="utf-8") as archivo:
    guion = json.load(archivo)

whisper = WhisperModel(f"{argumentos.modelos}/faster-whisper-small", device="cpu", compute_type="int8")

# --- Mi voz de referencia ---------------------------------------------------
if not argumentos.reusar_audio:
    print("1/5 Preparando la voz de referencia...")
    ruta_voz_completa = CARPETA_AUDIO / "voz_completa.wav"
    subprocess.run([ffmpeg, "-v", "error", "-y", "-i", argumentos.voz, "-ac", "1", "-ar", "24000",
                    str(ruta_voz_completa)], check=True)
    segmentos, _ = whisper.transcribe(audio_para_whisper(ruta_voz_completa), language="es",
                                      word_timestamps=True)

    # La referencia debe durar entre 15 y 25 segundos. Recorremos palabra por palabra
    # porque Whisper puede devolver toda la grabación en un solo segmento largo.
    texto_acumulado = ""
    texto_referencia = ""
    fin_referencia = 0
    for segmento in segmentos:
        for palabra in segmento.words:
            if palabra.end > 25:
                break
            texto_acumulado += palabra.word
            # Cortamos solo donde termina una oración: si la referencia queda a medias,
            # el clon cree que ya dijo esas palabras y se las salta al empezar cada escena.
            if texto_acumulado.strip().endswith("."):
                texto_referencia = texto_acumulado
                fin_referencia = palabra.end
    if fin_referencia < 15:
        raise SystemExit(f"La referencia dura {fin_referencia:.1f} s: graba una nota de voz más larga.")

    audio_completo, frecuencia_voz = soundfile.read(ruta_voz_completa)
    recorte = audio_completo[: int((fin_referencia + 0.2) * frecuencia_voz)]
    soundfile.write(CARPETA_AUDIO / "referencia.wav", recorte, frecuencia_voz)
    print(f"   Referencia de {fin_referencia:.1f} s: «{texto_referencia.strip()}»")

    print("2/5 Narrando con la voz clonada (en CPU tarda varios minutos)...")
    tts = Qwen3TTSModel.from_pretrained(f"{argumentos.modelos}/Qwen3-TTS-12Hz-0.6B-Base",
                                        device_map="cpu", dtype=torch.float32)
    voz_clonada = tts.create_voice_clone_prompt(ref_audio=str(CARPETA_AUDIO / "referencia.wav"),
                                                ref_text=texto_referencia.strip())

# --- Narración, escena por escena -------------------------------------------
pistas = []
escenas_con_tiempos = []
segundo_actual = 0.5
frecuencia = 24000

for numero, escena in enumerate(guion["escenas"], start=1):
    ruta_escena = CARPETA_AUDIO / f"escena_{numero}.wav"

    if argumentos.reusar_audio:
        mejor_audio, frecuencia = soundfile.read(ruta_escena)
        mejores_palabras = transcribir(whisper, ruta_escena)
    else:
        mejor_error = 1.0
        for intento in range(1, INTENTOS + 1):
            audios, frecuencia = tts.generate_voice_clone(text=escena["frase"], language="Spanish",
                                                          voice_clone_prompt=voz_clonada)
            soundfile.write(ruta_escena, audios[0], frecuencia)

            # Control: Whisper vuelve a escuchar lo que dijo el clon.
            palabras = transcribir(whisper, ruta_escena)
            lo_que_se_entiende = " ".join(palabra["texto"] for palabra in palabras)
            error = jiwer.wer(normalizar(escena["frase"]), normalizar(lo_que_se_entiende))
            print(f"   Escena {numero}, intento {intento}: {error:.0%} de palabras mal entendidas")

            if error < mejor_error:
                mejor_error = error
                mejor_audio = audios[0]
                mejores_palabras = palabras
            if error <= ERROR_MAXIMO:
                break
        # Guardamos el mejor intento, no el último.
        soundfile.write(ruta_escena, mejor_audio, frecuencia)

    for palabra in mejores_palabras:
        palabra["inicio"] += segundo_actual
        palabra["fin"] += segundo_actual
    duracion = len(mejor_audio) / frecuencia
    escenas_con_tiempos.append({"inicio": segundo_actual, "fin": segundo_actual + duracion,
                                "palabras": mejores_palabras})
    pistas.append(mejor_audio)
    pistas.append(np.zeros(int(PAUSA_ENTRE_ESCENAS * frecuencia)))
    segundo_actual += duracion + PAUSA_ENTRE_ESCENAS

# Medio segundo de silencio al inicio y un segundo y medio al final.
pistas.insert(0, np.zeros(int(0.5 * frecuencia)))
pistas.append(np.zeros(int(1.5 * frecuencia)))
narracion = np.concatenate(pistas)
duracion_total = len(narracion) / frecuencia
print(f"   Narración de {duracion_total:.0f} segundos")

# --- Música -----------------------------------------------------------------
print("3/5 Generando la música y mezclando...")
musica = hacer_musica(duracion_total, frecuencia)
soundfile.write(CARPETA_REEL / "recursos" / "musica.wav", musica, frecuencia)
voz_normalizada = narracion / np.abs(narracion).max() * 0.9
mezcla = voz_normalizada + VOLUMEN_MUSICA * musica
soundfile.write(CARPETA_AUDIO / "mezcla.wav", mezcla / np.abs(mezcla).max() * 0.95, frecuencia)

# --- Video ------------------------------------------------------------------
print("4/5 Dibujando el video...")
total_escenas = len(guion["escenas"])
pie_normal = ["Fuente: INEI, ENAHO 2019–2024 (módulo 34 Sumaria)",
              "Jhanela Carhuaz · Tablero: jhane080.github.io/pobreza-peru-enaho"]
pie_final = ["Fuente: INEI, ENAHO 2019–2024 · Voz clonada con Qwen3-TTS",
             "Música generada con Python · jhane080.github.io/pobreza-peru-enaho"]
fondos = []
imagenes = []
for numero, escena in enumerate(guion["escenas"], start=1):
    pie = pie_final if numero == total_escenas else pie_normal
    fondos.append(dibujar_fondo_de_escena(escena, numero, total_escenas, guion["titulo"], pie))
    imagenes.append(Image.open(escena["imagen"]).convert("RGB"))

# -14 LUFS es el volumen que usan las redes. Primero medimos y luego ajustamos.
medicion = subprocess.run(
    [ffmpeg, "-hide_banner", "-i", str(CARPETA_AUDIO / "mezcla.wav"),
     "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
    capture_output=True, text=True,
)
salida_ffmpeg = medicion.stderr
volumen = json.loads(salida_ffmpeg[salida_ffmpeg.rfind("{") : salida_ffmpeg.rfind("}") + 1])
filtro_volumen = (
    "loudnorm=I=-14:TP=-1.5:LRA=11:linear=true"
    f":measured_I={volumen['input_i']}:measured_TP={volumen['input_tp']}"
    f":measured_LRA={volumen['input_lra']}:measured_thresh={volumen['input_thresh']}"
    f":offset={volumen['target_offset']}"
)

# H.264 + AAC lo acepta cualquier app.
video = subprocess.Popen(
    [ffmpeg, "-v", "error", "-y",
     "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{ANCHO}x{ALTO}",
     "-r", str(CUADROS_POR_SEGUNDO), "-i", "-",
     "-i", str(CARPETA_AUDIO / "mezcla.wav"),
     "-af", filtro_volumen, "-ar", "48000",
     "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
     "-c:a", "aac", "-b:a", "192k", "-shortest", str(CARPETA_REEL / "reel.mp4")],
    stdin=subprocess.PIPE,
)

total_cuadros = int(duracion_total * CUADROS_POR_SEGUNDO)
for cuadro in range(total_cuadros):
    segundo = cuadro / CUADROS_POR_SEGUNDO
    # La escena que se ve es la última que ya empezó.
    indice = 0
    for posicion, tiempos in enumerate(escenas_con_tiempos):
        if tiempos["inicio"] <= segundo:
            indice = posicion
    tiempos = escenas_con_tiempos[indice]
    # La última escena se queda en pantalla durante el silencio final.
    fin_visible = tiempos["fin"] + PAUSA_ENTRE_ESCENAS
    if indice == total_escenas - 1:
        fin_visible = duracion_total
    avance = min(1, max(0, (segundo - tiempos["inicio"]) / (fin_visible - tiempos["inicio"])))

    imagen = fondos[indice].copy()
    recorte = recorte_de_imagen(guion["escenas"][indice], imagenes[indice], avance)
    x = CAJA_IMAGEN[0] + (CAJA_IMAGEN[2] - CAJA_IMAGEN[0] - recorte.width) // 2
    y = CAJA_IMAGEN[1] + (CAJA_IMAGEN[3] - CAJA_IMAGEN[1] - recorte.height) // 2
    imagen.paste(recorte, (x, y))
    dibujar_subtitulo(imagen, tiempos["palabras"], segundo)
    if cuadro == int(1.5 * CUADROS_POR_SEGUNDO):
        imagen.save(CARPETA_REEL / "portada.png")
    video.stdin.write(imagen.tobytes())

video.stdin.close()
video.wait()

# --- Subtítulos -------------------------------------------------------------
print("5/5 Escribiendo los subtítulos...")
numero_subtitulo = 1
with open(CARPETA_REEL / "subtitulos.srt", "w", encoding="utf-8") as archivo:
    for tiempos in escenas_con_tiempos:
        palabras = tiempos["palabras"]
        for inicio_grupo in range(0, len(palabras), PALABRAS_POR_SUBTITULO):
            grupo = palabras[inicio_grupo : inicio_grupo + PALABRAS_POR_SUBTITULO]
            texto = " ".join(palabra["texto"] for palabra in grupo)
            archivo.write(f"{numero_subtitulo}\n")
            archivo.write(f"{formato_srt(grupo[0]['inicio'])} --> {formato_srt(grupo[-1]['fin'])}\n")
            archivo.write(f"{texto}\n\n")
            numero_subtitulo += 1

print(f"Listo: reel/reel.mp4 ({duracion_total:.0f} s), subtitulos.srt y portada.png")
