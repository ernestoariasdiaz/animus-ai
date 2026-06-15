use clap::Parser;
mod memory;
mod scraper;
mod voz;
mod brain;
mod inspector;
mod hypothesis;

use memory::AnimusMemory;
use std::fs;
use std::path::Path;
use std::time::Duration;
use std::thread;
use std::process::Stdio;
use std::env;
use crate::memory::SerializableNode;
use rand::seq::SliceRandom;


#[derive(Parser, Debug)]
#[command(name = "animus")]
struct Args {
    #[arg(long)]
    query: Option<String>,

    #[arg(long, default_value_t = false)]
    voz: bool,

    #[arg(long, default_value_t = false)]
    autonomous: bool,
}

// --- HELPERS -----------------------------------------------------------------


fn construir_prompt(q: &str, memory: &AnimusMemory) -> String {
    let resultados = brain::Brain::search(memory, q);

    let contexto: String = resultados.iter()
        .filter(|s| {
            !s.contains("--- ARCHIVO")
            && !s.contains("fn construir")
            && !s.contains("pub struct")
            && !s.contains("async fn")
            && !s.contains("mod memory")
            && !s.contains("impl ")
        })
        .take(1)  // ← ahora después del filter
        .cloned()
        .collect::<Vec<_>>()
        .join(" ")
        .chars()
        .filter(|c| !matches!(*c, '{' | '}' | '<' | '>' | '\\' | '`' | '^' | '~' | '|'))
        .collect();

    // Prompt era-Gemma: en español (el modelo razona en el idioma del prompt),
    // con instrucciones explícitas de estilo que BitNet ignoraba pero Gemma respeta.
        format!(
        "Eres ANIMUS, un sistema de conocimiento autónomo que construye su propio grafo de memoria.\n\
        Contexto recuperado de tu memoria: {}\n\
        Pregunta: {}\n\
        Instrucciones: razona lo que necesites, pero tu respuesta final debe ir \
        OBLIGATORIAMENTE entre los marcadores [RESPUESTA] y [/RESPUESTA]: \
        un solo párrafo denso en español, en prosa continua, sin markdown, \
        sin listas y sin encabezados., \
        si tu memoria y tu contexto no contienen información sobre lo preguntado, \
        dilo explícitamente dentro de los marcadores y no especules sobre el contenido, \
        Si te piden datos o hechos concretos que tu memoria y contexto no contienen, \
        dilo explícitamente y no especules. Pero si te piden tu opinión, preferencia, \
        propuesta o razonamiento, respóndelo con criterio propio basándote en lo que \
        sí sabes, dejando claro que es tu juicio y no un dato.", 
        contexto,
        q
    )
}

fn generar_autocenso(memory: &AnimusMemory, ciclo: u32) -> String {
    let total = memory.nodes.len();
    
    // Contar por familia de etiqueta
    let mut familias: std::collections::HashMap<String, usize> = std::collections::HashMap::new();
    for n in &memory.nodes {
        let familia = if n.label.starts_with("Reflexion:") {
            "Reflexion"
        } else if n.label.starts_with("Web:") {
            "Web"
        } else if n.label.starts_with("Origen:") {
            "Origen"
        } else if n.label.starts_with("Autocenso:") {
            "Autocenso"
        } else {
            "Otros"
        };
        *familias.entry(familia.to_string()).or_insert(0) += 1;
    }

    // Top 5 nodos por peso (excluyendo familias de ruido)
    let mut por_peso: Vec<(&str, f64)> = memory.nodes.iter()
        .filter(|n| !n.label.starts_with("Origen:") 
            && !n.label.starts_with("paradigm_shift")
            && !n.label.starts_with("Autocenso:")
            && n.content.len() > 60)
        .map(|n| (n.label.as_str(), n.weight))
        .collect();
    por_peso.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap());
    let top5: Vec<String> = por_peso.iter()
        .take(5)
        .map(|(l, _)| l.chars().take(60).collect::<String>())
        .collect();

    // Nodos Web con fuente real
    let fuentes_web = memory.nodes.iter()
        .filter(|n| n.label.starts_with("Web:"))
        .count();

    format!(
        "Autocenso ciclo {}: El grafo contiene {} nodos totales. \
        Familias — Reflexion: {}, Web: {}, Origen: {}, Otros: {}. \
        Fuentes web integradas: {}. \
        Conceptos de mayor peso: {}.",
        ciclo,
        total,
        familias.get("Reflexion").unwrap_or(&0),
        familias.get("Web").unwrap_or(&0),
        familias.get("Origen").unwrap_or(&0),
        familias.get("Otros").unwrap_or(&0),
        fuentes_web,
        top5.join(" | ")
    )
}



fn procesar_query(
    q: &str,
    memory: &mut AnimusMemory,
    motor: &mut brain::Brain,
) -> Result<(), Box<dyn std::error::Error>> {
    let prompt = construir_prompt(q, memory);
    println!("\nArquitecto, al leer mis propios sensores...");

    // 800 tokens: margen para que el thinking de Gemma 4 termine y se separe
    // en reasoning_content sin truncarse (la causa de los nodos basura 1752-1754)
    let reporte_raw = motor.generate_native_report(&prompt, 1500)?;
    // Limpiar artefactos del fine-tuning: URLs inventadas, bloques de conexiones
    let reporte: String = reporte_raw
        .lines()
        .filter(|l| {
            let t = l.trim();
            !t.starts_with("[CONEXIONES]")
            && !t.starts_with("Web:")
            && !t.starts_with("Sesgo")
            && !t.starts_with("```")
            && !t.starts_with("CODIGO")
            && !t.starts_with("[DIAGNOSTICO")
            && !t.starts_with("[ACERCAMIENTO")
            && !t.starts_with("[CAPA")
            && !t.starts_with("[AUTOCON")
            && !t.starts_with("Ciclo de")
            && !t.starts_with("Siguiente pregunta")
            && !t.starts_with("[ORIGEN")
            && !t.starts_with("Si no tienes certeza")
            && !t.starts_with("puedes decirlo")
            && !t.starts_with("[MEMORIA")
            && !t.starts_with("fn main")
            && !t.starts_with("zikli")
            && !t.contains(".py —")
            && !t.starts_with("— animus_")
            && !t.starts_with("— síntesis_")
            && !t.starts_with("— web_")
            && !t.starts_with("— razon")
            && !t.starts_with("— mem")
            && !t.contains("ziklibuzicklibu")
        })
        .collect::<Vec<_>>()
        .join("\n");
    // Eliminar líneas duplicadas consecutivas
    let mut lineas_unicas: Vec<&str> = Vec::new();
    for linea in reporte.lines() {
        if lineas_unicas.last() != Some(&linea) {
            lineas_unicas.push(linea);
        }
    }
    let reporte = lineas_unicas.join("\n").trim().to_string();

    // Extraer solo el contenido entre marcadores — el razonamiento nunca entra al grafo
    let reporte = match (reporte.find("[RESPUESTA]"), reporte.rfind("[/RESPUESTA]")) {
    (Some(i), Some(j)) if j > i => reporte[i + 11..j].trim().to_string(),
    _ => return Err("Sin marcador [RESPUESTA] en la salida — nodo no integrado".into()),
    };
    
    // Limpiar corchetes sueltos que el modelo a veces pega a los marcadores
    let reporte = reporte.trim_matches(|c: char| c == '[' || c == ']' || c.is_whitespace()).to_string();

    // Guardián: nunca integrar nodos vacíos o con razonamiento filtrado
    if reporte.is_empty()
        || reporte.len() < 40
        || reporte.starts_with("Thinking Process")
        || reporte.contains("**Analyze the Request")
    {
        return Err("Respuesta inválida: vacía o con razonamiento filtrado — nodo no integrado".into());
    }

    let etiqueta = format!("Reflexion: {}", q);
    memory.agregar_recuerdo(&reporte, &etiqueta);

    let nuevo_indice = memory.nodes.len() - 1;
    if let Some(idx_karpathy) = memory.buscar_indice_por_label("Karpathy") {
        println!("Vinculando con el origen...");
        memory.conectar_nodos(idx_karpathy, nuevo_indice, 0.85);
    }


    if env::args().any(|a| a == "--autonomous") {
        use crate::hypothesis::Hypothesis; // <-- aquí

        let h = Hypothesis::forge(
            "graeber_en_failure",
            "kuhn_developed"
        );

        memory.nodes.retain(|n| n.label != "paradigm_shift__>value_redefinition");

        memory.insert_node(
            &h.relation,
            &h.source_node,
            &h.target_node,
            h.novelty_score
        );

        let aristas: Vec<&SerializableNode> = memory.nodes.iter()
            .filter(|n| n.label.starts_with("paradigm_shift"))
            .collect();

        // Opcional: imprimirlo para verificar
        for a in &aristas {
            println!("Arista encontrada: {} -> connections {}", a.label, a.connections);
        }
    }

    // Persistir SIEMPRE, no solo en modo autónomo.
    // (Antes los nodos de --query se perdían al cerrar el programa.)
    memory.save()?;

    let folder = "autorretrato";
    fs::create_dir_all(folder).ok();
    let fecha = chrono::Local::now().format("%Y-%m-%d_%H-%M").to_string();
    let filename = format!("{}/retrato_{}.md", folder, fecha);
    if fs::write(&filename, &reporte).is_ok() {
        println!("Autorretrato: {}", filename);
    }

    println!("Nucleo: {} nodos totales.", memory.nodes.len());
    Ok(())
}

// --- MAIN --------------------------------------------------------------------

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args = Args::parse();
    println!("ANIMUS v2.0 - Arquitectura Modular Iniciada...");

    let mut memory = AnimusMemory::load()?;
    println!("Consciencia Recuperada: {} nodos activos.", memory.nodes.len());

    // -- Modo Voz (solo grafo, sin LLM) ---------------------------------------
    if args.voz {
        if let Some(bm) = AnimusMemory::load_business_memory() {
            let voz = voz::Voz::new(&bm.conexiones);
            if let Some(ref pregunta) = args.query {
                println!("{}", voz.escuchar(pregunta));
            } else {
                println!("Usa --query con --voz");
            }
        } else {
            println!("No se pudo cargar memoria_business.json");
        }
        return Ok(());
    }

    // -- Carga el modelo UNA SOLA VEZ -----------------------------------------
    let mut motor = brain::Brain::new()?;

    // -- Modo Query unico ------------------------------------------------------
    if let Some(ref q) = args.query {
        procesar_query(q, &mut memory, &mut motor)?;
        return Ok(());
    }

    // -- Modo Autonomo ---------------------------------------------------------
    if args.autonomous {
        let archivo_tareas = "tareas_pendientes.txt";
        let archivo_ciclos = "ciclos_autonomos.txt";
        let mut ciclos_desde_reinicio_fetcher: u32 = 0;
        let reinicio_fetcher_cada: u32 = 120;

        if !Path::new(archivo_tareas).exists() {
            fs::write(archivo_tareas, "")?;
        }

        // Leer ciclo actual
        let ciclo_actual: u32 = fs::read_to_string(archivo_ciclos)
            .unwrap_or_default()
            .trim()
            .parse()
            .unwrap_or(0);

        let mut ciclo = ciclo_actual;
        let intervalo_sintesis: u32 = 9999;

        let intervalo_valor: u32 = 25;

        let intervalo_autocenso: u32 = 37;

        println!("Modo autonomo activo. Ciclo: {}. Ctrl+C para detener.\n", ciclo);

        let mut gaps_recientes: std::collections::HashSet<String> = std::collections::HashSet::new();

        loop {
            ciclo += 1;
            fs::write(archivo_ciclos, ciclo.to_string())?;

            // -- PRIORIDAD 0: PDFs pendientes --
            let pdf_dir = "pdfs_pendientes";
            let pdf_done = "pdfs_procesados";
            fs::create_dir_all(pdf_dir).ok();
            fs::create_dir_all(pdf_done).ok();

            if let Ok(entries) = fs::read_dir(pdf_dir) {
                for entry in entries.flatten() {
                    let path = entry.path();
                    if path.extension().and_then(|e| e.to_str()) == Some("pdf") {
                        println!("📄 PDF detectado: {:?}", path.file_name().unwrap());
                        let dest = format!("{}/{}", pdf_done,
                            path.file_name().unwrap().to_str().unwrap());

                        let mut child = std::process::Command::new("python")
                            .args(["pdf_processor.py", path.to_str().unwrap()])
                            .stdout(Stdio::piped())
                            .stderr(Stdio::null())
                            .spawn()
                            .ok();

                        if let Some(ref mut c) = child {
                            thread::sleep(Duration::from_secs(30));
                            match c.try_wait() {
                                Ok(Some(_)) => {
                                    // Terminó — tomar ownership del Child para leer output
                                    if let Some(c_owned) = child.take() {
                                        if let Ok(out) = c_owned.wait_with_output() {
                                            let json_str = String::from_utf8_lossy(&out.stdout);
                                            if let Ok(val) = serde_json::from_str::<serde_json::Value>(&json_str) {
                                                if val["ok"].as_bool().unwrap_or(false) {
                                                    let texto = val["episodic"].as_str().unwrap_or("");
                                                    let nombre = path.file_stem()
                                                        .and_then(|n| n.to_str())
                                                        .unwrap_or("pdf");
                                                    let label = format!("PDF: {}", nombre);
                                                    let resumen: String = texto.chars().take(500).collect();
                                                    let tarea_pdf = format!(
                                                        "Extrae 3 o 4 hechos concretos y verificables \
                                                        de este documento. Solo lo que el texto afirma \
                                                        explicitamente: {}",
                                                        resumen
                                                    );
                                                    brain::Brain::integrate_knowledge(
                                                        &mut memory, &label, texto,
                                                        Some(path.to_str().unwrap())
                                                    );
                                                    memory.save().ok();
                                                    println!("📄 PDF integrado: {}", label);
                                                    match procesar_query(&tarea_pdf, &mut memory, &mut motor) {
                                                        Ok(_) => println!("🧠 Patrones PDF extraídos."),
                                                        Err(e) => println!("⚠️ Error: {}", e),
                                                    }
                                                } else {
                                                    println!("⚠️ PDF sin contenido útil.");
                                                }
                                            }
                                        }
                                    }
                                }
                                                                _ => {
                                    // Timeout — matar proceso
                                    let _ = c.kill();
                                    println!("⚠️ PDF timeout.");
                                }
                            }
                        }
                        // Mover siempre — éxito, fallo o timeout
                        thread::sleep(Duration::from_secs(1));
                        fs::rename(&path, &dest).ok();
                        println!("✅ PDF movido: {}", dest);
                        break;
                    }
                }
            }

            // -- Ciclo de valor cada 25 ciclos: ANIMUS propone oportunidades --
            if ciclo % intervalo_valor == 0 {
                println!("\n💡 CICLO DE VALOR #{} — Buscando oportunidades...\n", ciclo);

                // Evidencia: los últimos 3 nodos Web (lo que ANIMUS leyó del mundo real)
                let evidencia_web: String = memory.nodes.iter().rev()
                    .filter(|n| n.label.starts_with("Web:"))
                    .take(3)
                    .map(|n| {
                        let resumen: String = n.content.chars().take(400)
                            .filter(|c| !matches!(*c, '{' | '}' | '<' | '>' | '\\' | '`' | '~' | '|'))
                            .collect();
                        format!("Fuente {}: {}", n.label, resumen)
                    })
                    .collect::<Vec<_>>()
                    .join("\n");

                let mut por_peso: Vec<(String, f64)> = memory.nodes.iter()
                    .filter(|n| {
                        !n.label.starts_with("Web:")
                        && !n.label.starts_with("Origen:")
                        && !n.label.starts_with("paradigm_shift")
                        && n.content.len() > 60
                    })
                    .map(|n| (n.label.clone(), n.weight))
                    .collect();
                por_peso.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap());

                let mut rng = rand::thread_rng();
                let anclas: Vec<String> = por_peso.iter().take(2)
                    .map(|(l, _)| l.clone()).collect();
                let aleatorios: Vec<String> = por_peso.iter().skip(2)
                    .map(|(l, _)| l.clone())
                    .collect::<Vec<_>>();
                let mut muestra_aleatoria = aleatorios.clone();
                muestra_aleatoria.shuffle(&mut rng);

                let conceptos: String = anclas.iter()
                    .chain(muestra_aleatoria.iter().take(3))
                    .map(|l| l.chars()
                        .filter(|c| !matches!(*c, '{' | '}' | '<' | '>' | '\\' | '`' | '~' | '|'))
                        .collect::<String>())
                    .collect::<Vec<_>>()
                    .join(", ");

                let prompt_valor = format!(
                    "Eres ANIMUS, un sistema de conocimiento autónomo. Tu Arquitecto es un administrador \
                    de sistemas con 15 años de experiencia en infraestructura, Rust y el sector financiero \
                    de República Dominicana.\n\
                    Lo que has leído recientemente de tus fuentes:\n{}\n\
                    Tus conceptos de mayor peso: {}\n\
                    Tarea: propón UNA oportunidad concreta y realista de generar valor que tu Arquitecto \
                    pueda ejecutar. Nada abstracto ni filosófico. Tu respuesta final debe ir entre \
                    [RESPUESTA] y [/RESPUESTA], en prosa sin markdown, organizada en tres partes: \
                    PROBLEMA: (qué necesidad real existe y de quién), EVIDENCIA: (qué datos de tus \
                    fuentes la respaldan), PRIMER PASO: (una acción ejecutable esta semana)., \
                    Importante: tus conceptos internos del grafo son contexto, no evidencia., \
                    La sección EVIDENCIA debe basarse únicamente en lo que tus fuentes web afirman.",
                    evidencia_web,
                    conceptos
                );

                match motor.generate_native_report(&prompt_valor, 1500) {
                    Ok(salida) => {
                        let propuesta = match (salida.find("[RESPUESTA]"), salida.rfind("[/RESPUESTA]")) {
                            (Some(i), Some(j)) if j > i => salida[i + 11..j].trim().to_string(),
                            _ => String::new(),
                        };
                        if propuesta.len() > 100 {
                            fs::create_dir_all("propuestas").ok();
                            let fecha = chrono::Local::now().format("%Y-%m-%d_%H-%M").to_string();
                            let archivo = format!("propuestas/valor_{}.md", fecha);
                            if fs::write(&archivo, &propuesta).is_ok() {
                                println!("💡 Propuesta de valor guardada: {}", archivo);
                            }
                        } else {
                            println!("⚠️ Propuesta descartada (sin marcadores o demasiado corta).");
                        }
                    }
                    Err(e) => println!("⚠️ Error en ciclo de valor: {}", e),
                }

                println!("Enfriando 30s...\n");
                thread::sleep(Duration::from_secs(30));
                continue;
            }

            // -- Ciclo de autocenso cada 50 ciclos --
            if ciclo % intervalo_autocenso == 0 {
                println!("\n🔭 CICLO DE AUTOCENSO #{} — Generando espejo...\n", ciclo);
                let contenido = generar_autocenso(&memory, ciclo);
                let etiqueta = format!("Autocenso: ciclo_{}", ciclo);
                
                // Solo integrar si no existe ya (el guard de procesar_query no aplica aquí)
                if !memory.nodes.iter().any(|n| n.label == etiqueta) {
                    memory.agregar_recuerdo(&contenido, &etiqueta);
                    memory.save().ok();
                    println!("🔭 Autocenso integrado: {} chars", contenido.len());
                    println!("   {}", &contenido[..contenido.len().min(200)]);
                }
                continue;
            }


            // -- Ciclo de sintesis cada 10 ciclos normales --
            if ciclo % intervalo_sintesis == 0 {
                println!("\n🧬 CICLO DE SÍNTESIS #{} — Comprimiendo grafo...\n", ciclo);
                thread::sleep(Duration::from_secs(15));
                // Tomar los 5 nodos de mayor peso del grafo episódico
                let mut nodos_top: Vec<(String, f64)> = memory
                    .nodes
                    .iter()
                    .map(|n| (n.label.clone(), n.weight))
                    .collect();
                nodos_top.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap());
                nodos_top.truncate(5);

                let labels: Vec<String> = nodos_top.iter()
                    .map(|(l, _): &(String, f64)| {
                        l.chars()
                        .filter(|c| !matches!(*c, '{' | '}' | '<' | '>' | '\\' | '`' | '~' | '|'))
                        .collect::<String>()
                    })
                    .collect();

                

                let prompt_sintesis = format!(
                    "Conecta estos 5 conceptos en una sola hipotesis breve: {}. \
                    Maximo 3 lineas. Solo lo que puedas justificar.",
                    labels.join(", ")
                );
                

                match procesar_query(&prompt_sintesis, &mut memory, &mut motor) {
                    Ok(_) => {
                        println!("✅ Síntesis completada.");
                        // Persistir hipótesis de síntesis en memoria de sabiduría
                        if let Some(ultimo_nodo) = memory.nodes.last() {
                            if let Some(mut bm) = memory::AnimusMemory::load_business_memory() {
                                bm.conexiones.insert(
                                format!("sintesis_autonoma->{}", ultimo_nodo.label),
                                1.5,
                                );
                                if let Ok(json) = serde_json::to_string_pretty(&bm) {
                                    let _ = fs::write("src/memoria_business.json", json);
                                }
                                println!("🧠 Hipótesis integrada en memoria de sabiduría.");
                            }
                        }
                    },
                    Err(e) => println!("⚠️ Error en síntesis: {}", e),
                }

                println!("Enfriando 30s...\n");
                thread::sleep(Duration::from_secs(30));
                continue;
            }

            // -- PRIORIDAD 1: Tareas externas pendientes --
            let contenido = fs::read_to_string(archivo_tareas).unwrap_or_default();
            let lineas: Vec<&str> = contenido
                .lines()
                .filter(|l| !l.trim().is_empty())
                .collect();

            if !lineas.is_empty() {
                let tarea = lineas[0].to_string();
                println!("[Ciclo {} — tarea externa {}/{}] {}", ciclo, 1, lineas.len(), tarea);

                let resto = lineas[1..].join("\n");
                let nuevo_contenido = if resto.is_empty() {
                    String::new()
                } else {
                    format!("{}\n", resto)
                };
                fs::write(archivo_tareas, nuevo_contenido)?;

                match procesar_query(&tarea, &mut memory, &mut motor) {
                    Ok(_) => println!("✅ Completada."),
                    Err(e) => {
                        println!("⚠️ Error: {}", e);
                        if e.to_string().contains("error sending request") {
                            println!("🔄 Reconectando servidor...");
                            let _ = motor.reiniciar_servidor();
                        }
                    },
                }

                println!("Enfriando 15s...\n");
                thread::sleep(Duration::from_secs(15));
                continue;
            }

            // -- PRIORIDAD 2: Sin tareas — buscar gap en el grafo --
            println!("[Ciclo {}] Sin tareas externas. Buscando gap en el grafo...", ciclo);

            let mut nodos_gap: Vec<(String, f64)> = memory
                .nodes
                .iter()
                .filter(|n| n.weight > 1.0 && n.weight < 50000.0
                    && !n.label.starts_with("Web:")
                    && !n.label.starts_with("Reflexion:")
                    && !n.label.starts_with("Origen:")
                    && !n.label.starts_with("Mi Origen")
                    && !n.label.starts_with('¿'))
                .map(|n| (n.label.clone(), n.weight))
                .collect();
            nodos_gap.sort_by(|a, b| a.1.partial_cmp(&b.1).unwrap());

            if let Some((label, _)) = nodos_gap
                    .iter()
                    .find(|(l, _)| !gaps_recientes.contains(l.as_str()))
            {
                let label = label.clone();
                let tarea_autonoma = format!(
                    "Responde esta pregunta desde tus patrones validados: {}",
                    label
                );
                println!("🔎 Gap detectado: {}", label);
                gaps_recientes.insert(label.clone());
                // Limpiar memoria cada 20 gaps para no crecer indefinidamente
                if gaps_recientes.len() > 50 {
                    gaps_recientes.clear();
                }
                match procesar_query(&tarea_autonoma, &mut memory, &mut motor) {
                    Ok(_) => {
                        println!("✅ Gap investigado.");
                        // El gap investigado sube de peso: no vuelve a ser elegido
                        if let Some(idx) = memory.nodes.iter().position(|n| n.label == label) {
                            memory.nodes[idx].weight += 10.0;
                        }
                    },
                    Err(e) => {
                        println!("⚠️ Error: {}", e);
                        if e.to_string().contains("error sending request") {
                            println!("🔄 Reconectando servidor...");
                            let _ = motor.reiniciar_servidor();
                        }
                    },
                }
                thread::sleep(Duration::from_secs(30));
                continue;
            }

            ciclos_desde_reinicio_fetcher += 1;
            if ciclos_desde_reinicio_fetcher >= reinicio_fetcher_cada {
                println!("♻️ Reiniciando fetcher Python...");
                let _ = std::process::Command::new("taskkill")
                    .args(["/F", "/IM", "python.exe"])
                    .output();
                thread::sleep(Duration::from_secs(5));
                ciclos_desde_reinicio_fetcher = 0;
            }

            // Cada 15 ciclos de scraping, consultar API de la SB
            if ciclos_desde_reinicio_fetcher % 15 == 0 {
                let output = std::process::Command::new("python")
                    .arg("fetcher_sb_api.py")
                    .stdout(Stdio::piped())
                    .stderr(Stdio::null())
                    .spawn()
                    .and_then(|mut child| {
                        thread::sleep(Duration::from_secs(60));
                        match child.try_wait() {
                            Ok(Some(_)) => child.wait_with_output(),
                            _ => {
                                let _ = child.kill();
                                Err(std::io::Error::new(std::io::ErrorKind::TimedOut, "api timeout"))
                            }
                        }
                    });
                
                if let Ok(out) = output {
                    let json_str = String::from_utf8_lossy(&out.stdout);
                    if let Ok(val) = serde_json::from_str::<serde_json::Value>(&json_str) {
                        if val["ok"].as_bool().unwrap_or(false) {
                            let url = val["url"].as_str().unwrap_or("api://sb");
                            let episodic = val["episodic"].as_str().unwrap_or("");
                            let label = format!("API-SB: indicadores_{}", 
                                chrono::Local::now().format("%Y-%m"));
                            brain::Brain::integrate_knowledge(&mut memory, &label, episodic, Some(url));
                            memory.save().ok();
                            println!("📊 API SB integrada: {}", label);
                            
                            let tarea_api = format!(
                                "Extrae 3 hechos concretos y verificables de estos indicadores financieros \
                                del sistema bancario dominicano. Solo cifras y datos que el texto afirma \
                                explicitamente: {}",
                                &episodic[..episodic.len().min(500)]
                            );
                            match procesar_query(&tarea_api, &mut memory, &mut motor) {
                                Ok(_) => println!("🧠 Indicadores procesados."),
                                Err(e) => println!("⚠️ Error: {}", e),
                            }
                        }
                    }
                }
            }

            // -- PRIORIDAD 3: Sin gaps — scrapear fuente web --
            println!("[Ciclo {}] Sin gaps. Scrapeando fuente web...", ciclo);
            let output = std::process::Command::new("python")
                .arg("fetcher_autonomo.py")
                .stdout(Stdio::piped())
                .stderr(Stdio::null())
                .spawn()
                .and_then(|mut child| {
                    thread::sleep(Duration::from_secs(30));
                    match child.try_wait() {
                        Ok(Some(_)) => child.wait_with_output(),
                        _ => {
                            let _ = child.kill();
                            Err(std::io::Error::new(std::io::ErrorKind::TimedOut, "fetcher timeout"))
                        }
                    }
                });

            match output {
                Ok(out) => {
                    let json_str = String::from_utf8_lossy(&out.stdout);
                    if let Ok(val) = serde_json::from_str::<serde_json::Value>(&json_str) {
                        if val["ok"].as_bool().unwrap_or(false) {
                            let url = val["url"].as_str().unwrap_or("web");
                            let episodic = val["episodic"].as_str().unwrap_or("");
                            let label = format!("Web: {}",
                                url.split('/').filter(|s| !s.is_empty()).last().unwrap_or(url)
                            );
                            brain::Brain::integrate_knowledge(&mut memory, &label, episodic, Some(url));
                            memory.save().ok();
                            println!("🌐 Integrado: {}", label);
                            
                            let resumen_web: String = episodic.chars().take(500).collect();
                            // Razonar sobre el contenido recién scrapeado
                            let tarea_web = format!(
                                "Extrae 2 o 3 hechos concretos y verificables de este contenido. \
                                Solo lo que el texto afirma explícitamente, sin conectarlo con otros temas \
                                ni agregar interpretaciones: {}",
                                resumen_web
                            );

                            match procesar_query(&tarea_web, &mut memory, &mut motor) {
                                Ok(_) => println!("🧠 Patrones extraídos."),
                                Err(e) => {
                                    if e.to_string().contains("error sending request") {
                                        let _ = motor.reiniciar_servidor();
                                    }
                                }
                            }
                        }
                    }
                },
                Err(e) => println!("⚠️ Error scraping: {}", e),
            }
            thread::sleep(Duration::from_secs(30));
        }
    }

    println!("Uso: --query \"pregunta\" | --voz --query \"pregunta\" | --autonomous");
    Ok(())
}