import sys
import json
import pathlib
import unicodedata
sys.stdout.reconfigure(encoding='utf-8')

def procesar_pdf(ruta):
    import fitz  # pymupdf
    texto = ""
    try:
        doc = fitz.open(ruta)
        paginas = min(len(doc), 15)
        for i in range(paginas):
            t = doc[i].get_text()
            if t:
                texto += t + "\n"
            if len(texto) > 5000:
                break
        doc.close()
    except Exception as e:
        return ""
    texto = unicodedata.normalize('NFC', texto)
    return texto.strip()

if __name__ == "__main__":
    ruta = sys.argv[1]
    nombre = pathlib.Path(ruta).stem
    try:
        texto = procesar_pdf(ruta)
        texto = ''.join(c for c in texto if ord(c) < 0x10000 and (c.isprintable() or c in '\n\t'))
        texto = " ".join(texto.split())
        result = {
            "url": f"pdf://{nombre}",
            "episodic": texto[:3000],
            "full": texto[:6000],
            "ok": len(texto) > 100
        }
    except Exception as e:
        result = {"url": f"pdf://{nombre}", "episodic": "", "full": "", "ok": False}
    print(json.dumps(result, ensure_ascii=False))