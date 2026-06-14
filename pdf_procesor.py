# pdf_processor.py
import sys, json, pdfplumber, pathlib

def procesar_pdf(ruta):
    texto = ""
    with pdfplumber.open(ruta) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                texto += t + "\n"
    return texto.strip()

if __name__ == "__main__":
    ruta = sys.argv[1]
    texto = procesar_pdf(ruta)
    nombre = pathlib.Path(ruta).stem
    result = {
        "url": f"pdf://{nombre}",
        "episodic": texto[:3000],
        "full": texto[:8000],
        "ok": len(texto) > 100
    }
    print(json.dumps(result, ensure_ascii=False))