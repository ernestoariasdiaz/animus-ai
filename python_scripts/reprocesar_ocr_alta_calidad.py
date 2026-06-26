"""
reprocesar_ocr_alta_calidad.py
--------------------------------
Reprocesa SOLO los PDFs que en la corrida anterior fueron rescatados vía
OCR (no los que ya tenían texto nativo bueno), esta vez con mayor DPI y
preprocesamiento de imagen, para reducir el ruido tipográfico que
introdujo el OCR a 200 DPI sin preprocesamiento.

POR QUÉ EXISTE:
    Se confirmó con un caso concreto (Circular SIB 009/17, sobre remisión
    de reportes UAF/ROS/RTE) que el contenido rescatado por OCR a 200 DPI
    tiene errores sistemáticos: sustituciones de letras (i<->í, a<->o),
    palabras de encabezado repetidas muchas veces ("Considerando" x7,
    "Visto" x6), y palabras fusionadas o mal separadas. El contenido
    semántico está ahí pero Brain::search (búsqueda por coincidencia
    literal de substring) no puede encontrarlo porque las palabras clave
    de las preguntas no calzan con las variantes corruptas en el texto.

QUÉ CAMBIA RESPECTO AL OCR ANTERIOR:
    1. DPI subido de 200 a 300 (estándar recomendado para Tesseract en
       documentos de texto; ganancias por encima de 300-400 son marginales
       y más que duplican el tiempo de procesamiento).
    2. Preprocesamiento de imagen antes de pasar a Tesseract:
       - Conversión a escala de grises
       - Binarización (umbral adaptativo) para mejorar contraste texto/fondo
       - Esto ayuda especialmente en escaneos con fondo no perfectamente
         blanco o con ligera inclinación/ruido de escáner.
    3. Configuración de Tesseract con --psm 6 (asume un bloque uniforme de
       texto, mejor para páginas de circulares/cartas que el modo
       automático por defecto que a veces confunde columnas/encabezados).

QUÉ HACE:
    1. Backup de animus_memory.json.
    2. Identifica qué nodos PDF corresponden a los archivos en
       pdfs_faltantes.txt (los que se rescataron por OCR la vez anterior).
    3. Para cada uno, vuelve a abrir el PDF original, renderiza a 300 DPI
       con preprocesamiento, corre OCR, y REEMPLAZA el content del nodo
       existente (no crea un nodo duplicado).
    4. Guarda un reporte comparando longitud de texto antes/después, como
       proxy rápido de si la nueva extracción capturó más o menos
       contenido (no mide calidad directamente, pero es una señal útil).

REQUISITOS:
    pip install pytesseract pillow pymupdf numpy --break-system-packages
    Tesseract OCR ya instalado (mismo que en el script anterior).

USO:
    python reprocesar_ocr_alta_calidad.py
    (colocar en C:\\projects\\animus_rust, junto a animus_memory.json,
     pdfs_procesados/ y pdfs_faltantes.txt)

IMPORTANTE:
    - Corre con ANIMUS detenido.
    - Esto reemplaza el 'content' de nodos YA EXISTENTES (los que se
      crearon en la corrida de OCR anterior) — no crea entradas nuevas
      ni duplica nodos.
    - Es más lento que el OCR anterior (mayor DPI + preprocesamiento).
      Con 101 documentos, espera que tome notablemente más tiempo que
      la corrida pasada.
"""

import sys
import json
import shutil
import time
import unicodedata
from pathlib import Path

MEMORY_PATH = Path("animus_memory.json")
PDF_DIR = Path("pdfs_procesados")
LISTA_FALTANTES = Path("pdfs_faltantes.txt")
OCR_DPI = 300
OCR_LANG = "spa"
MAX_PAGINAS = 15
MAX_CHARS_CONTENT = 3000
UMBRAL_TEXTO_UTIL = 100
TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
REPORTE_PATH = Path("reprocesar_ocr_reporte.txt")


def log(msg, archivo=None):
    print(msg)
    if archivo:
        archivo.write(msg + "\n")
        archivo.flush()


def limpiar_texto(texto: str) -> str:
    texto = unicodedata.normalize("NFC", texto)
    texto = "".join(c for c in texto if ord(c) < 0x10000 and (c.isprintable() or c in "\n\t"))
    return " ".join(texto.split())


def preprocesar_imagen(img):
    """Escala de grises + binarización adaptativa simple, sin dependencias
    pesadas (sin opencv) para mantener el script liviano."""
    import numpy as np
    from PIL import Image, ImageOps

    gris = img.convert("L")
    # Binarización simple por umbral global (Otsu manual aproximado):
    # suficiente para documentos de texto escaneado con fondo razonablemente uniforme.
    arr = np.array(gris)
    umbral = arr.mean() * 0.85  # algo por debajo de la media, conservador
    binaria = (arr > umbral) * 255
    return Image.fromarray(binaria.astype("uint8"))


def extraer_texto_ocr_mejorado(doc, max_paginas: int, dpi: int, lang: str) -> str:
    import pytesseract
    import fitz

    texto = ""
    paginas = min(len(doc), max_paginas)
    zoom = dpi / 72
    matriz = fitz.Matrix(zoom, zoom)
    config_tesseract = "--psm 6"

    for i in range(paginas):
        pix = doc[i].get_pixmap(matrix=matriz)
        img_bytes = pix.tobytes("png")
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(img_bytes))
        img_proc = preprocesar_imagen(img)
        t = pytesseract.image_to_string(img_proc, lang=lang, config=config_tesseract)
        if t:
            texto += t + "\n"
        if len(texto) > 5000:
            break
    return texto.strip()


def main():
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

    import fitz  # pymupdf, confirmar disponible temprano

    if not MEMORY_PATH.exists():
        print(f"❌ No se encontró {MEMORY_PATH.resolve()}")
        sys.exit(1)
    if not LISTA_FALTANTES.exists():
        print(f"❌ No se encontró {LISTA_FALTANTES.resolve()}")
        sys.exit(1)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    backup_path = MEMORY_PATH.with_name(f"{MEMORY_PATH.stem}_backup_ocrHQ_{timestamp}{MEMORY_PATH.suffix}")
    shutil.copy2(MEMORY_PATH, backup_path)
    print(f"📦 Backup creado: {backup_path}")

    with open(MEMORY_PATH, "r", encoding="utf-8") as f:
        memoria = json.load(f)
    nodos = memoria["nodes"]

    with open(LISTA_FALTANTES, "r", encoding="utf-8") as f:
        nombres_faltantes = [l.strip() for l in f if l.strip()]

    # Mapear nombre de archivo -> índice del nodo correspondiente
    label_a_indice = {}
    for idx, n in enumerate(nodos):
        if n["label"].startswith("PDF:"):
            label_a_indice[n["label"][5:].lower()] = idx

    print(f"📋 PDFs candidatos a reprocesar: {len(nombres_faltantes)}")

    with open(REPORTE_PATH, "w", encoding="utf-8") as log_file:
        mejorados = 0
        sin_cambio_significativo = 0
        no_encontrados_en_grafo = 0
        errores = []

        for idx_archivo, nombre_archivo in enumerate(nombres_faltantes, start=1):
            stem = Path(nombre_archivo).stem.lower()
            log(f"\n[{idx_archivo}/{len(nombres_faltantes)}] {nombre_archivo}", log_file)

            if stem not in label_a_indice:
                log("  ℹ️ No tiene nodo en el grafo (probablemente sigue fallido), se omite.", log_file)
                no_encontrados_en_grafo += 1
                continue

            idx_nodo = label_a_indice[stem]
            content_anterior = nodos[idx_nodo]["content"]
            ruta = PDF_DIR / nombre_archivo

            if not ruta.exists():
                log(f"  ❌ Archivo no encontrado en disco: {ruta}", log_file)
                errores.append(nombre_archivo)
                continue

            try:
                doc = fitz.open(str(ruta))
                texto_nuevo = limpiar_texto(extraer_texto_ocr_mejorado(doc, MAX_PAGINAS, OCR_DPI, OCR_LANG))
                doc.close()
            except Exception as e:
                log(f"  ⚠️ Error en OCR mejorado: {e}", log_file)
                errores.append(nombre_archivo)
                continue

            if len(texto_nuevo) <= UMBRAL_TEXTO_UTIL:
                log(f"  ⚠️ OCR mejorado dio muy poco texto ({len(texto_nuevo)} chars), se conserva el anterior.", log_file)
                sin_cambio_significativo += 1
                continue

            nodos[idx_nodo]["content"] = texto_nuevo[:MAX_CHARS_CONTENT]
            mejorados += 1
            log(f"  ✅ Reemplazado. Antes: {len(content_anterior)} chars -> Ahora: {len(texto_nuevo[:MAX_CHARS_CONTENT])} chars", log_file)

        memoria["nodes"] = nodos
        with open(MEMORY_PATH, "w", encoding="utf-8") as f:
            json.dump(memoria, f, ensure_ascii=False, indent=2)

        resumen = (
            f"\n=== RESUMEN ===\n"
            f"Total candidatos: {len(nombres_faltantes)}\n"
            f"Reemplazados con OCR mejorado: {mejorados}\n"
            f"Sin cambio (OCR mejorado no dio suficiente texto): {sin_cambio_significativo}\n"
            f"No encontrados en grafo: {no_encontrados_en_grafo}\n"
            f"Errores: {len(errores)}\n"
        )
        log(resumen, log_file)

    print(f"\n✅ Listo. Reporte en {REPORTE_PATH}")


if __name__ == "__main__":
    main()
