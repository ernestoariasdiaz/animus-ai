"""
reconectar_pdfs_por_contenido.py
----------------------------------
Complemento de reconectar_pdfs_retroactivo.py (que conecta PDFs por
coincidencia de palabras en el NOMBRE de archivo). Este script conecta
PDFs por similitud de CONTENIDO, usando TF-IDF + similitud coseno.

POR QUÉ EXISTE:
    Tras correr el benchmark con las conexiones por nombre de archivo, se
    vio mejora en preguntas multi-fuente (Q15-Q26) donde los nombres de
    archivo eran descriptivos (ej. Q24, Q25, Q26), pero NO en las que
    requerían combinar documentos con nombres opacos tipo "P090402-05",
    "w161031-01", "JM251127-04" — códigos que no tienen ninguna palabra
    en común con su contraparte temática aunque traten exactamente el
    mismo tema. Comparar por contenido real (no por nombre de archivo)
    cierra esa brecha.

CONFIRMACIÓN DE QUE FUNCIONA:
    El par con score 1.000 más relevante encontrado:
    "PDF: reglamento-riesgo-operacional" <-> "PDF: P090402-05"
    Esto es el caso Q18 del paper (duplicados de reglamento de riesgo
    operacional) — exactamente el tipo de relación que el nombre de
    archivo por sí solo nunca habría revelado.

QUÉ HACE:
    1. Backup automático con timestamp antes de tocar nada.
    2. Limpia el texto de cada nodo PDF (quita caracteres rotos de
       encoding tipo '�', normaliza a minúsculas, filtra stopwords en
       español + términos genéricos del dominio regulatorio que no
       discriminan, ej. "superintendencia", "circular", "resolución").
    3. Vectoriza con TF-IDF (3000 features, min_df=2) y calcula similitud
       coseno entre TODOS los pares de PDFs.
    4. Para pares con similitud >= UMBRAL que no estén ya conectados
       (revisa edges existentes en ambas direcciones), crea una arista
       nueva.
    5. Tope de MAX_CONEXIONES_POR_NODO conexiones nuevas por nodo, igual
       criterio que el script por nombre de archivo, para no saturar el
       grafo de ruido.
    6. Guarda el resultado en animus_memory.json.

UMBRAL ELEGIDO (0.5):
    Se inspeccionó la distribución completa de similitud entre los 564
    PDFs. La mediana es ~0.045 (la mayoría de pares no tienen relación).
    En la banda 0.45-0.55 los pares siguen siendo temáticamente
    coherentes (series del mismo informe, reglamentos relacionados). Por
    debajo de ~0.3-0.4 empieza a aparecer más boilerplate legal
    compartido (encabezados tipo "EL CONGRESO NACIONAL... DICTA LA
    SIGUIENTE LEY") que no refleja relación temática real, solo forma
    jurídica compartida. 0.5 es un punto conservador que evita ese ruido.

USO:
    pip install scikit-learn --break-system-packages
    python reconectar_pdfs_por_contenido.py
    (colocar en la misma carpeta que animus_memory.json, o ajustar MEMORY_PATH)

IMPORTANTE:
    - Corre con ANIMUS detenido (mismo cuidado de race condition de siempre).
    - Es seguro correr DESPUÉS de reconectar_pdfs_retroactivo.py (el script
      por nombre de archivo) — este revisa edges existentes y no duplica.
    - Es idempotente: correrlo dos veces no duplica aristas.
"""

import json
import re
import shutil
import time
from pathlib import Path
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# ---------- CONFIGURACIÓN ----------
MEMORY_PATH = Path("animus_memory.json")
UMBRAL_SIMILITUD = 0.5
MAX_CONEXIONES_POR_NODO = 2
MAX_FEATURES_TFIDF = 3000
MIN_DF = 2  # ignorar términos que aparecen en menos de 2 documentos

# Stopwords español + términos del dominio regulatorio tan frecuentes que
# no discriminan entre documentos (aparecen en casi cualquier circular).
STOPWORDS = set("""
de la el en y a los del las que con para por su es se al un una como ya o
fue son sus al superintendencia bancos republica dominicana junta monetaria
circular resolucion reglamento articulo presente entidad
entidades financiera financieras intermediacion banco bancaria
nacional general fecha mediante dicho dicha cual cuales considerando titulo
seccion numero no sib csb
""".split())


def limpiar_texto(texto: str) -> str:
    """Quita caracteres rotos de encoding, normaliza y filtra stopwords."""
    texto = texto.replace("�", " ")
    texto = texto.lower()
    texto = re.sub(r"[^a-záéíóúñ\s]", " ", texto)
    palabras = [w for w in texto.split() if len(w) >= 4 and w not in STOPWORDS]
    return " ".join(palabras)


def hacer_backup(path: Path) -> Path:
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    backup_path = path.with_name(f"{path.stem}_backup_contenido_{timestamp}{path.suffix}")
    shutil.copy2(path, backup_path)
    print(f"📦 Backup creado: {backup_path}")
    return backup_path


def main():
    if not MEMORY_PATH.exists():
        print(f"❌ No se encontró {MEMORY_PATH.resolve()}")
        return

    hacer_backup(MEMORY_PATH)

    with open(MEMORY_PATH, "r", encoding="utf-8") as f:
        memoria = json.load(f)

    nodos = memoria.get("nodes", [])
    edges = memoria.get("edges", [])
    print(f"🔍 Cargados {len(nodos)} nodos y {len(edges)} edges existentes.")

    pdf_indices = [i for i, n in enumerate(nodos) if n.get("label", "").startswith("PDF:")]
    print(f"📄 Nodos PDF encontrados: {len(pdf_indices)}")

    if len(pdf_indices) < 2:
        print("⚠️ Menos de 2 PDFs en memoria, no hay nada que comparar.")
        return

    textos = [limpiar_texto(nodos[i]["content"]) for i in pdf_indices]

    print("🧮 Vectorizando contenido (TF-IDF)...")
    vectorizer = TfidfVectorizer(max_features=MAX_FEATURES_TFIDF, min_df=MIN_DF)
    matriz = vectorizer.fit_transform(textos)
    print(f"   Matriz: {matriz.shape}")

    print("🧮 Calculando similitud coseno entre todos los pares...")
    sim = cosine_similarity(matriz)

    # Pares ya conectados (en cualquier dirección), para no duplicar
    pares_existentes = set()
    for e in edges:
        pares_existentes.add((e["from"], e["to"]))
        pares_existentes.add((e["to"], e["from"]))

    n = len(pdf_indices)
    candidatos = []
    for a in range(n):
        for b in range(a + 1, n):
            score = sim[a][b]
            if score >= UMBRAL_SIMILITUD:
                real_i, real_j = pdf_indices[a], pdf_indices[b]
                if (real_i, real_j) not in pares_existentes:
                    candidatos.append((score, real_i, real_j))

    candidatos.sort(reverse=True)
    print(f"🔗 Candidatos por encima de umbral {UMBRAL_SIMILITUD}, no conectados aún: {len(candidatos)}")

    conexiones_nuevas_por_nodo = {}
    nuevas_aristas = []
    for score, i, j in candidatos:
        if conexiones_nuevas_por_nodo.get(i, 0) >= MAX_CONEXIONES_POR_NODO:
            continue
        if conexiones_nuevas_por_nodo.get(j, 0) >= MAX_CONEXIONES_POR_NODO:
            continue
        nuevas_aristas.append({"from": i, "to": j, "weight": round(float(score), 3)})
        pares_existentes.add((i, j))
        pares_existentes.add((j, i))
        conexiones_nuevas_por_nodo[i] = conexiones_nuevas_por_nodo.get(i, 0) + 1
        conexiones_nuevas_por_nodo[j] = conexiones_nuevas_por_nodo.get(j, 0) + 1

    print(f"✅ Aristas nuevas a crear: {len(nuevas_aristas)}")

    if not nuevas_aristas:
        print("ℹ️ No se encontraron pares por encima del umbral. Considera bajar UMBRAL_SIMILITUD.")
        return

    for arista in nuevas_aristas:
        nodos[arista["from"]]["connections"] = nodos[arista["from"]].get("connections", 0) + 1
        nodos[arista["to"]]["connections"] = nodos[arista["to"]].get("connections", 0) + 1

    edges.extend(nuevas_aristas)
    memoria["edges"] = edges

    with open(MEMORY_PATH, "w", encoding="utf-8") as f:
        json.dump(memoria, f, ensure_ascii=False, indent=2)

    print(f"✅ Listo. {len(nuevas_aristas)} aristas nuevas guardadas en {MEMORY_PATH}.")
    print(f"   Total de edges ahora: {len(edges)}")

    print("\n📋 Muestra de las 10 aristas con mayor similitud:")
    for arista in nuevas_aristas[:10]:
        label_from = nodos[arista["from"]]["label"][:55]
        label_to = nodos[arista["to"]]["label"][:55]
        print(f"   {arista['weight']:.3f}  {label_from}  <->  {label_to}")


if __name__ == "__main__":
    main()
