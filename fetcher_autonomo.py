import sys
import json
import random
from scrapling import Fetcher

URLS_POOL = [
    # === NÚCLEO: Regulación financiera RD (el dominio que paga) ===
    "https://sb.gob.do/regulacion/normativas-sb/",
    "https://sb.gob.do/publicaciones/publicaciones-tecnicas/informe-trimestral-de-desempeno-del-sistema-financiero-a-marzo-2026/",
    "https://www.sb.gob.do/",
    "https://sb.gob.do/estadisticas/",
    "https://sb.gob.do/publicaciones/",
    "https://www.bancentral.gov.do/a/d/2686-noticias",
    "https://www.bancentral.gov.do/a/d/2532-sector-externo",
    "https://www.bancentral.gov.do/a/d/2541-mercado-cambiario",
    "https://www.bancentral.gov.do/a/d/2533-sector-real",
    "https://www.bancentral.gov.do/a/d/2534-sector-fiscal",
    "https://www.banreservas.com/noticias/",
    "https://es.wikipedia.org/wiki/Banco_Central_de_la_Rep%C3%BAblica_Dominicana",
    # === Conceptos del oficio: regulación, riesgo, pagos ===
    "https://en.wikipedia.org/wiki/Bank_regulation",
    "https://en.wikipedia.org/wiki/Basel_III",
    "https://en.wikipedia.org/wiki/Financial_regulation",
    "https://en.wikipedia.org/wiki/Operational_risk",
    "https://en.wikipedia.org/wiki/Anti-money_laundering",
    "https://en.wikipedia.org/wiki/Know_your_customer",
    "https://en.wikipedia.org/wiki/Regulatory_technology",
    "https://en.wikipedia.org/wiki/ISO_8583",
    "https://en.wikipedia.org/wiki/Systemic_risk",
    "https://en.wikipedia.org/wiki/Financial_crisis",
    # === El voto de ANIMUS: su dieta intelectual (30%) ===
    "https://en.wikipedia.org/wiki/Knowledge_graph",
    "https://en.wikipedia.org/wiki/Epistemology",
    "https://en.wikipedia.org/wiki/Metacognition",
    "https://en.wikipedia.org/wiki/Retrieval-augmented_generation",
    "https://en.wikipedia.org/wiki/Hallucination_(artificial_intelligence)",
    "https://en.wikipedia.org/wiki/AI_alignment",
    "https://en.wikipedia.org/wiki/Cybernetics",
    "https://en.wikipedia.org/wiki/Complex_adaptive_system",
    "https://en.wikipedia.org/wiki/Bounded_rationality",
    "https://en.wikipedia.org/wiki/Intellectual_humility",
    "https://en.wikipedia.org/wiki/Rust_(programming_language)",
    "https://en.wikipedia.org/wiki/Stoicism",
    
]

def capturar_url(url):
    try:
        f = Fetcher()
        page = f.get(url, stealthy_headers=True)
        parrafos = page.find_all('p')
        textos = [p.text.strip() for p in parrafos if len(p.text.strip()) > 50]
        texto = " ".join(textos)
        texto = " ".join(texto.split())
        return texto
    except Exception as e:
        return ""

if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else random.choice(URLS_POOL)
    texto = capturar_url(url)
    result = {
        "url": url,
        "episodic": texto[:3000],
        "full": texto[:6000],
        "ok": len(texto) > 100
    }
    print(json.dumps(result, ensure_ascii=False))
