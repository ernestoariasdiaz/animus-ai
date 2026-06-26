"""
reintentar_pdfs_faltantes.py
-------------------------------
Reintenta la ingesta de los PDFs que están en pdfs_procesados/ pero NUNCA
llegaron a integrarse como nodos en animus_memory.json.

POR QUÉ EXISTE:
    Se detectó que 262 de 817 PDFs (32%) en pdfs_procesados/ no tienen
    nodo correspondiente en el grafo. Causa raíz confirmada en
    pdf_processor.py: la extracción de texto usa fitz.get_text(), que
    solo lee texto YA EMBEBIDO en el PDF. Si el PDF es un escaneo (común
    en cartas circulares firmadas, ~43% de los faltantes tienen "signed"
    en el nombre), get_text() devuelve poco o nada, el resultado cae por
    debajo del umbral `len(texto) > 100`, "ok" queda en False, y
    main.rs descarta el PDF sin reintentar (solo imprime "PDF sin
    contenido útil"). El archivo de todos modos se mueve a
    pdfs_procesados/, lo cual oculta el fallo — la carpeta dice
    "procesado" pero el grafo nunca lo recibió.

QUÉ HACE:
    1. Backup automático de animus_memory.json antes de tocar nada.
    2. Para cada PDF en la lista de faltantes:
       a. Intenta fitz.get_text() normal (texto nativo), igual que
          pdf_processor.py original.
       b. Si el resultado es <= 100 caracteres, renderiza cada página
          como imagen (pixmap) y le pasa OCR con pytesseract (español).
       c. Si CUALQUIERA de los dos métodos da >100 caracteres útiles,
          se integra el nodo al grafo (misma estructura que
          Brain::integrate_knowledge en Rust: label "PDF: <nombre>",
          content, source = ruta del archivo).
       d. Si ninguno de los dos métodos funciona, se reporta como
          "sigue sin contenido" (puede ser un PDF realmente vacío,
          corrupto, o con calidad de escaneo muy mala) — no se inventa
          contenido falso.
    3. Guarda animus_memory.json actualizado y un reporte de qué se
       logró integrar vía OCR vs qué sigue fallando.

REQUISITOS:
    pip install pytesseract pillow pymupdf --break-system-packages
    Tesseract OCR debe estar instalado en el sistema (no es un paquete
    Python, es un binario):
      Windows: descargar instalador de
      https://github.com/UB-Mannheim/tesseract/wiki
      y asegurarse de que tesseract.exe esté en el PATH, o ajustar
      TESSERACT_CMD abajo con la ruta completa.

USO:
    python reintentar_pdfs_faltantes.py
    (colocar en C:\\projects\\animus_rust, junto a animus_memory.json
     y la carpeta pdfs_procesados/)

IMPORTANTE:
    - Corre con ANIMUS detenido (mismo cuidado de race condition de siempre).
    - OCR es mucho más lento que extracción de texto nativo (varios
      segundos por página, no milisegundos). Con ~262 PDFs candidatos
      esto puede tardar bastante — el script imprime progreso pregunta
      por pregunta para que puedas estimar el tiempo total temprano.
    - Es seguro re-correr: si un PDF ya tiene nodo en el grafo, se
      omite automáticamente (no se duplica).
"""

import sys
import json
import shutil
import time
import unicodedata
from pathlib import Path

# ---------- CONFIGURACIÓN ----------
MEMORY_PATH = Path("animus_memory.json")
PDF_DIR = Path("pdfs_procesados")
LISTA_FALTANTES = Path("pdfs_faltantes.txt")  # una ruta de archivo .pdf por línea
UMBRAL_TEXTO_UTIL = 100       # mismo umbral que pdf_processor.py original
MAX_PAGINAS = 15              # mismo límite que pdf_processor.py original
MAX_CHARS_CONTENT = 3000      # mismo límite que usa "episodic" en pdf_processor.py
OCR_DPI = 200                 # resolución del render para OCR (más alto = más lento, más preciso)
OCR_LANG = "spa"              # paquete de idioma de Tesseract para español
# Si tesseract.exe no está en el PATH de Windows, descomenta y ajusta:
TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
# TESSERACT_CMD = None

REPORTE_PATH = Path("reintentar_pdfs_reporte.txt")


def log(msg: str, archivo=None):
    print(msg)
    if archivo:
        archivo.write(msg + "\n")
        archivo.flush()


def limpiar_texto(texto: str) -> str:
    texto = unicodedata.normalize("NFC", texto)
    texto = "".join(c for c in texto if ord(c) < 0x10000 and (c.isprintable() or c in "\n\t"))
    return " ".join(texto.split())


def extraer_texto_nativo(doc, max_paginas: int) -> str:
    """Mismo método que pdf_processor.py original: fitz.get_text()."""
    texto = ""
    paginas = min(len(doc), max_paginas)
    for i in range(paginas):
        t = doc[i].get_text()
        if t:
            texto += t + "\n"
        if len(texto) > 5000:
            break
    return texto.strip()


def extraer_texto_ocr(doc, max_paginas: int, dpi: int, lang: str) -> str:
    """Fallback para PDFs escaneados: renderiza cada página y le pasa OCR."""
    import pytesseract
    from PIL import Image
    import io

    texto = ""
    paginas = min(len(doc), max_paginas)
    zoom = dpi / 72  # fitz usa 72 dpi de base
    matriz = __import__("fitz").Matrix(zoom, zoom)

    for i in range(paginas):
        pix = doc[i].get_pixmap(matrix=matriz)
        img_bytes = pix.tobytes("png")
        img = Image.open(io.BytesIO(img_bytes))
        t = pytesseract.image_to_string(img, lang=lang)
        if t:
            texto += t + "\n"
        if len(texto) > 5000:
            break
    return texto.strip()


def procesar_un_pdf(ruta: Path, log_file) -> dict:
    import fitz  # pymupdf

    nombre = ruta.stem
    resultado_base = {"label": f"PDF: {nombre}", "source": str(ruta), "metodo": None, "content": ""}

    try:
        doc = fitz.open(str(ruta))
    except Exception as e:
        log(f"  ❌ No se pudo abrir: {e}", log_file)
        return resultado_base

    # 1) Intento normal (texto nativo)
    try:
        texto_nativo = limpiar_texto(extraer_texto_nativo(doc, MAX_PAGINAS))
    except Exception as e:
        log(f"  ⚠️ Error en extracción nativa: {e}", log_file)
        texto_nativo = ""

    if len(texto_nativo) > UMBRAL_TEXTO_UTIL:
        doc.close()
        resultado_base["content"] = texto_nativo[:MAX_CHARS_CONTENT]
        resultado_base["metodo"] = "nativo"
        return resultado_base

    # 2) Fallback a OCR (probablemente es un PDF escaneado)
    log("  🔎 Texto nativo insuficiente, probando OCR...", log_file)
    try:
        texto_ocr = limpiar_texto(extraer_texto_ocr(doc, MAX_PAGINAS, OCR_DPI, OCR_LANG))
    except Exception as e:
        log(f"  ⚠️ Error en OCR: {e}", log_file)
        texto_ocr = ""
    finally:
        doc.close()

    if len(texto_ocr) > UMBRAL_TEXTO_UTIL:
        resultado_base["content"] = texto_ocr[:MAX_CHARS_CONTENT]
        resultado_base["metodo"] = "ocr"
        return resultado_base

    # 3) Ninguno de los dos métodos dio contenido útil
    resultado_base["metodo"] = "fallido"
    return resultado_base


def hacer_backup(path: Path) -> Path:
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    backup_path = path.with_name(f"{path.stem}_backup_reintentopdf_{timestamp}{path.suffix}")
    shutil.copy2(path, backup_path)
    print(f"📦 Backup creado: {backup_path}")
    return backup_path


def main():
    if TESSERACT_CMD:
        import pytesseract
        pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

    if not MEMORY_PATH.exists():
        print(f"❌ No se encontró {MEMORY_PATH.resolve()}")
        sys.exit(1)
    if not LISTA_FALTANTES.exists():
        print(f"❌ No se encontró {LISTA_FALTANTES.resolve()}")
        print("   (debe tener una ruta de archivo .pdf por línea, relativa a pdfs_procesados/)")
        sys.exit(1)

    hacer_backup(MEMORY_PATH)

    with open(MEMORY_PATH, "r", encoding="utf-8") as f:
        memoria = json.load(f)

    nodos = memoria.get("nodes", [])
    labels_existentes = {n["label"].lower() for n in nodos}

    with open(LISTA_FALTANTES, "r", encoding="utf-8") as f:
        nombres_faltantes = [l.strip() for l in f if l.strip()]

    print(f"📋 PDFs a reintentar: {len(nombres_faltantes)}")

    with open(REPORTE_PATH, "w", encoding="utf-8") as log_file:
        integrados_nativo = 0
        integrados_ocr = 0
        fallidos = []
        omitidos_ya_existian = 0

        for idx, nombre_archivo in enumerate(nombres_faltantes, start=1):
            ruta = PDF_DIR / nombre_archivo
            label_esperado = f"pdf: {Path(nombre_archivo).stem}".lower()

            log(f"\n[{idx}/{len(nombres_faltantes)}] {nombre_archivo}", log_file)

            if label_esperado in labels_existentes:
                log("  ℹ️ Ya existe en el grafo, se omite.", log_file)
                omitidos_ya_existian += 1
                continue

            if not ruta.exists():
                log(f"  ❌ No se encontró el archivo en {ruta}", log_file)
                fallidos.append(nombre_archivo)
                continue

            resultado = procesar_un_pdf(ruta, log_file)

            if resultado["metodo"] in ("nativo", "ocr"):
                nodos.append({
                    "label": resultado["label"],
                    "content": resultado["content"],
                    "era": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "weight": 10.0,
                    "connections": 1,
                    "source": resultado["source"],
                })
                labels_existentes.add(resultado["label"].lower())
                if resultado["metodo"] == "nativo":
                    integrados_nativo += 1
                    log(f"  ✅ Integrado vía texto nativo ({len(resultado['content'])} chars).", log_file)
                else:
                    integrados_ocr += 1
                    log(f"  ✅ Integrado vía OCR ({len(resultado['content'])} chars).", log_file)
            else:
                fallidos.append(nombre_archivo)
                log("  ❌ Sigue sin contenido útil (ni texto nativo ni OCR).", log_file)

        memoria["nodes"] = nodos

        with open(MEMORY_PATH, "w", encoding="utf-8") as f:
            json.dump(memoria, f, ensure_ascii=False, indent=2)

        resumen = (
            f"\n=== RESUMEN ===\n"
            f"Total procesados: {len(nombres_faltantes)}\n"
            f"Ya existían (omitidos): {omitidos_ya_existian}\n"
            f"Integrados vía texto nativo: {integrados_nativo}\n"
            f"Integrados vía OCR: {integrados_ocr}\n"
            f"Siguen sin contenido útil: {len(fallidos)}\n"
        )
        log(resumen, log_file)

        if fallidos:
            log("PDFs que siguen sin contenido útil tras OCR:", log_file)
            for f_ in fallidos:
                log(f"  - {f_}", log_file)

    print(f"\n✅ Listo. Reporte completo en {REPORTE_PATH}")
    print(f"   Nodos totales en el grafo ahora: {len(nodos)}")


if __name__ == "__main__":
    main()
