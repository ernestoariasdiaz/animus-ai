"""
reconectar_pdfs_retroactivo.py
-------------------------------
Recorre animus_memory.json y crea aristas (edges) entre nodos "PDF:" que
comparten palabras clave en su etiqueta, replicando en los datos ya
ingeridos la misma lógica que ahora aplica procesar_query() en main.rs
para los PDFs nuevos (ver conectar_pdfs_relacionados.rs).

POR QUÉ EXISTE:
    Antes del fix, cada PDF ingerido solo se conectaba al nodo "Karpathy"
    (el origen). El grafo real era una estrella: documentos sin relación
    directa entre ellos. El fix en main.rs soluciona esto para PDFs que se
    ingieran DE AQUÍ EN ADELANTE, pero no modifica retroactivamente los
    nodos que ya existen en animus_memory.json. Este script cierra esa
    brecha sin tener que volver a correr la ingesta completa de los 805 PDFs.

QUÉ HACE:
    1. Crea un backup con timestamp antes de tocar nada.
    2. Carga todos los nodos cuyo label empieza con "PDF:".
    3. Para cada par de PDFs, cuenta palabras (>=5 letras) compartidas en
       el label.
    4. Si comparten >= UMBRAL_PALABRAS palabras, crea una arista (si no
       existe ya) con peso fijo (PESO_ARISTA).
    5. Limita conexiones nuevas por nodo a MAX_CONEXIONES_POR_NODO, para
       no convertir el grafo en una nube densa de ruido.
    6. Guarda el resultado en animus_memory.json (formato idéntico al que
       escribe memory.rs::save(), pretty-printed).

USO:
    python reconectar_pdfs_retroactivo.py
    (colocar en la misma carpeta que animus_memory.json, o ajustar MEMORY_PATH)

IMPORTANTE:
    - Corre esto con ANIMUS detenido (ni --query ni --autonomous activos),
      mismo cuidado de race condition que ya documentaste para ediciones
      manuales del JSON.
    - Es idempotente: si lo corres dos veces, no duplica aristas ya creadas
      por este mismo script (se verifica antes de insertar).
"""

import json
import re
import shutil
import time
from pathlib import Path
from itertools import combinations

# ---------- CONFIGURACIÓN ----------
MEMORY_PATH = Path("animus_memory.json")
UMBRAL_PALABRAS = 2          # mínimo de palabras compartidas en el label para conectar
MAX_CONEXIONES_POR_NODO = 2  # tope de aristas nuevas por nodo, igual que en main.rs
PESO_ARISTA = 0.6            # mismo peso que usa conectar_pdfs_relacionados.rs
LONGITUD_MIN_PALABRA = 5     # ignorar palabras cortas (poco informativas)


def normalizar_palabras(label: str) -> set:
    """
    Extrae palabras de >=5 letras en minúsculas.

    CORRECCIÓN: los nombres de archivo del corpus usan '-' y '_' como
    separador, no espacios (ej. "2010_carta-circular-cc005_16_fatca.pdf").
    La primera versión de este script solo separaba por espacios, así que
    nombres así se trataban como UNA sola palabra gigante y nunca
    coincidían con nada — de ahí las 0 conexiones encontradas en el primer
    corrido. También se descartan tokens puramente numéricos (fechas,
    códigos como "20250010" o "0031") porque coincidir en eso es ruido,
    no relación temática real.
    """
    tokens = re.split(r"[\s\-_./]+", label.lower())
    palabras = set()
    for t in tokens:
        t_limpio = re.sub(r"[^a-záéíóúñ0-9]", "", t)
        if len(t_limpio) >= LONGITUD_MIN_PALABRA and not t_limpio.isdigit():
            palabras.add(t_limpio)
    return palabras


def hacer_backup(path: Path) -> Path:
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    backup_path = path.with_name(f"{path.stem}_backup_{timestamp}{path.suffix}")
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

    # Índices de todos los nodos PDF
    indices_pdf = [i for i, n in enumerate(nodos) if n.get("label", "").startswith("PDF:")]
    print(f"📄 Nodos PDF encontrados: {len(indices_pdf)}")

    if len(indices_pdf) < 2:
        print("⚠️ Menos de 2 PDFs en memoria, no hay nada que conectar.")
        return

    # Set de pares ya conectados, para no duplicar (en cualquier dirección)
    pares_existentes = set()
    for e in edges:
        pares_existentes.add((e["from"], e["to"]))
        pares_existentes.add((e["to"], e["from"]))

    palabras_por_nodo = {i: normalizar_palabras(nodos[i]["label"]) for i in indices_pdf}
    conexiones_nuevas_por_nodo = {i: 0 for i in indices_pdf}

    nuevas_aristas = []

    # Comparar cada par de PDFs una sola vez (combinations evita pares duplicados/reflexivos)
    for i, j in combinations(indices_pdf, 2):
        if conexiones_nuevas_por_nodo[i] >= MAX_CONEXIONES_POR_NODO:
            continue
        if conexiones_nuevas_por_nodo[j] >= MAX_CONEXIONES_POR_NODO:
            continue
        if (i, j) in pares_existentes:
            continue

        compartidas = palabras_por_nodo[i] & palabras_por_nodo[j]
        if len(compartidas) >= UMBRAL_PALABRAS:
            nuevas_aristas.append({"from": i, "to": j, "weight": PESO_ARISTA})
            pares_existentes.add((i, j))
            pares_existentes.add((j, i))
            conexiones_nuevas_por_nodo[i] += 1
            conexiones_nuevas_por_nodo[j] += 1

    print(f"🔗 Aristas nuevas a crear: {len(nuevas_aristas)}")

    if not nuevas_aristas:
        print("ℹ️ No se encontraron pares de PDFs con suficientes palabras compartidas.")
        print("   (Revisa UMBRAL_PALABRAS si esperabas más conexiones.)")
        return

    # Actualizar contador de conexiones en los nodos afectados, igual que
    # hace conectar_nodos() en memory.rs
    for arista in nuevas_aristas:
        nodos[arista["from"]]["connections"] = nodos[arista["from"]].get("connections", 0) + 1
        nodos[arista["to"]]["connections"] = nodos[arista["to"]].get("connections", 0) + 1

    edges.extend(nuevas_aristas)
    memoria["edges"] = edges

    with open(MEMORY_PATH, "w", encoding="utf-8") as f:
        json.dump(memoria, f, ensure_ascii=False, indent=2)

    print(f"✅ Listo. {len(nuevas_aristas)} aristas nuevas guardadas en {MEMORY_PATH}.")
    print(f"   Total de edges ahora: {len(edges)}")

    # Pequeño resumen de ejemplo para verificación manual
    print("\n📋 Muestra de las primeras 5 aristas nuevas:")
    for arista in nuevas_aristas[:5]:
        label_from = nodos[arista["from"]]["label"][:60]
        label_to = nodos[arista["to"]]["label"][:60]
        print(f"   {label_from}  <->  {label_to}")


if __name__ == "__main__":
    main()
