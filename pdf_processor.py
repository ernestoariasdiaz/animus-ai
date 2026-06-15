import sys
import json
import pathlib

def procesar_pdf(ruta):
    import fitz  # pymupdf
    texto = ""
    try:
        doc = fitz.open(ruta)
        # Máximo 15 páginas, pero rápido
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
    return texto.strip()

if __name__ == "__main__":
    ruta = sys.argv[1]
    nombre = pathlib.Path(ruta).stem
    try:
        texto = procesar_pdf(ruta)
        result = {
            "url": f"pdf://{nombre}",
            "episodic": texto[:3000],
            "full": texto[:6000],
            "ok": len(texto) > 100
        }
    except Exception as e:
        result = {"url": f"pdf://{nombre}", "episodic": "", "full": "", "ok": False}
    print(json.dumps(result, ensure_ascii=False))