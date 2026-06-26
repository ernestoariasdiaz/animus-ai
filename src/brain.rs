use chrono::Utc;
use crate::memory::{AnimusMemory, SerializableNode, SerializableEdge};
use sysinfo::System;
use std::process::{Command, Child, Stdio};
use std::time::Duration;
use std::thread;

// ── Configuración del motor (Gemma 4 E2B sobre llama.cpp CUDA) ──
// AJUSTA estas dos rutas a las reales en tu Dell:
const LLAMA_SERVER_PATH: &str = r"C:\projects\llama-b9603-bin-win-cuda-13.3-x64\llama-server.exe";
const MODEL_PATH: &str = r"C:\projects\GEMMA\gemma-4-E2B-it-UD-Q4_K_XL.gguf";
const SERVER_URL: &str = "http://127.0.0.1:8081";

pub struct Brain {
    server_process: Option<Child>,
    client: reqwest::blocking::Client,
}

impl Brain {
    /// Lanza llama-server con Gemma 4. Usado por new() y reiniciar_servidor().
    fn lanzar_proceso() -> Result<Child, Box<dyn std::error::Error>> {
        let child = Command::new(LLAMA_SERVER_PATH)
            .args([
                "-m", MODEL_PATH,
                "-c", "8192",              // contexto; con E2B Q4 cabe en los 4GB de la 3050
                "-ngl", "99",              // todas las capas a GPU
                "-t", "8",                 // hilos CPU para lo que no va a GPU
                "--jinja",                 // aplica el chat template nativo de Gemma 4
                "--temp", "1.0",           // sampling recomendado por Google para Gemma 4
                "--top-p", "0.95",
                "--top-k", "64",
                "--host", "127.0.0.1",
                "--port", "8081",
                "--log-disable",
                "--parallel", "1",
            ])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|e| format!("Error lanzando Gemma (llama-server): {}", e))?;
        Ok(child)
    }

    /// Espera a que /health responda ok. Devuelve true si el servidor está listo.
    fn esperar_servidor() -> bool {
        let client = reqwest::blocking::Client::builder()
            .timeout(Duration::from_secs(5))
            .build()
            .unwrap_or_default();
        for _ in 0..15 {  // máximo 30 segundos (15 × 2s)
            thread::sleep(Duration::from_secs(2));
            print!(".");
            match client.get(format!("{}/health", SERVER_URL))
                .timeout(Duration::from_secs(3))
                .send()
            {
                Ok(resp) => {
                    if let Ok(json) = resp.json::<serde_json::Value>() {
                        if json["status"].as_str() == Some("ok") {
                            return true;
                        }
                    }
                }
                Err(_) => continue,
            }
        }
        false  // timeout — el loop externo maneja el Err
    }

    pub fn new() -> Result<Self, Box<dyn std::error::Error>> {
        println!("🧠 Motor ANIMUS: Gemma 4 E2B (Q4, GPU RTX 3050)");
        println!("📦 Cargando modelo en memoria...");

        let child = Self::lanzar_proceso()?;

        print!("⏳ Inicializando servidor");
        // Gemma Q4 en GPU carga en segundos; ya no hace falta el sleep de 15s de BitNet
        thread::sleep(Duration::from_secs(3));

        if Self::esperar_servidor() {
            println!(" ✅");
        } else {
            println!(" ⚠️ Timeout — servidor puede no estar listo");
        }

        let client = reqwest::blocking::Client::builder()
            .connect_timeout(Duration::from_secs(10))
            .timeout(Duration::from_secs(180))
            .build()?;

        Ok(Brain {
            server_process: Some(child),
            client,
        })
    }

    fn sanitizar_prompt(prompt: &str) -> String {
        prompt
            .chars()
            .filter(|c| {
                // Conservar todo lo imprimible y útil; eliminar solo lo que rompe:
                // caracteres de control (salvo salto de línea y tab) y el replacement char
                (!c.is_control() || *c == '\n' || *c == '\t') && *c != '\u{FFFD}'
            })
            .collect::<String>()
            .replace('\0', "")
    }

    pub fn generate_native_report(
    &mut self,
    prompt: &str,
    max_tokens: usize,
    ) -> Result<String, Box<dyn std::error::Error>> {

        println!("\n🎭 LA VOZ DE ANIMUS:");
        println!("-------------------------------------------");

        let prompt_limpio = Self::sanitizar_prompt(prompt)
            .chars()
            .filter(|c| !c.is_control() || *c == '\n' || *c == '\t')
            .collect::<String>();

        eprintln!("[CKPT 1] prompt sanitizado, {} chars", prompt_limpio.len());

        // Template de Gemma 4 construido a mano, SIN el token <|think|>:
        // el thinking jamás se activa y el modelo responde directo.
        let prompt_gemma = format!(
            "<|turn>user\n{}<turn|>\n<|turn>model\n",
            prompt_limpio
        );
  
        let body = serde_json::json!({
            "prompt": prompt_gemma,
            "n_predict": max_tokens,
            "stop": ["<turn|>", "<|turn>"]
        });

        eprintln!("[CKPT 2] enviando al servidor...");

        let resp = loop {
            match self.client
                .post("http://127.0.0.1:8081/completion")
                .json(&body)
                .send()
            {
                Ok(r) => break r.json::<serde_json::Value>()?,
                Err(e) => {
                    eprintln!("⚠️ Servidor no responde: {}", e);
                    eprintln!("🔄 Reiniciando...");
                    let _ = self.reiniciar_servidor();
                    thread::sleep(Duration::from_secs(8));
                    // Un intento más tras el reinicio
                    match self.client
                        .post("http://127.0.0.1:8081/completion")
                        .json(&body)
                        .send()
                    {
                        Ok(r) => break r.json::<serde_json::Value>()?,
                        Err(e) => return Err(e.into()),
                    }
                }
            }
        };

        eprintln!("[CKPT 3] respuesta recibida");

        let texto = resp["content"]
            .as_str()
            .unwrap_or("Sin respuesta.")
            .lines()
            .filter(|l| {
                !l.trim().starts_with("Exploración interna:")
                && !l.trim().starts_with("===")
                && !l.trim().starts_with("PROMPT")
                && !l.trim().starts_with("FIN DEBUG")
            })
            .collect::<Vec<_>>()
            .join("\n")
            .trim()
            .to_string();

        println!("{}", texto);
        println!("-------------------------------------------");

        Ok(texto)
    }

    pub fn reiniciar_servidor(&mut self) -> Result<(), Box<dyn std::error::Error>> {
        if let Some(mut child) = self.server_process.take() {
            let pid = child.id();
            let _ = child.kill();
            let _ = child.wait();
            // Matar por PID explícito como respaldo
            let _ = std::process::Command::new("taskkill")
                .args(["/F", "/PID", &pid.to_string()])
                .output();
        }
        // Esperar que el puerto quede libre
        thread::sleep(Duration::from_secs(3));
        let child = Self::lanzar_proceso()?;
        self.server_process = Some(child);
        thread::sleep(Duration::from_secs(3));
        if Self::esperar_servidor() {
            println!("🔄 Servidor ANIMUS reiniciado.");
            Ok(())
        } else {
            Err("Timeout reiniciando servidor".into())
        }
    }

    pub fn leer_signos_vitales() -> (f32, u64, u64) {
        let mut sys = System::new_all();
        sys.refresh_cpu_usage();
        std::thread::sleep(sysinfo::MINIMUM_CPU_UPDATE_INTERVAL);
        sys.refresh_cpu_usage();
        let cpu = sys.global_cpu_usage();
        let ram_total = sys.total_memory() / 1024 / 1024 / 1024;
        let ram_libre = sys.available_memory() / 1024 / 1024 / 1024;
        (cpu, ram_libre, ram_total)
    }

    pub fn search(memory: &AnimusMemory, query: &str) -> Vec<String> {
        let palabras_query: Vec<String> = query
                .split_whitespace()
                .filter(|&w| w.len() >= 4)
                .map(|w| w.to_lowercase())
                .collect();

        // Prioridad 1: PDF con TODAS las palabras clave en la etiqueta
        let pdf_exacto_idx: Option<usize> = memory.nodes.iter()
                .position(|n| {
                    n.label.starts_with("PDF:") && {
                        let label = n.label.to_lowercase();
                        palabras_query.iter()
                            .filter(|pq| pq.len() >= 5)
                            .all(|pq| label.contains(pq.as_str()))
                    }
                });

         // Prioridad 2: búsqueda semántica normal en contenido (por índice,
        // para poder expandir luego por edges)
        let frases_vacias = [
            "no se encuentra información",
            "no se encontró información",
            "no es posible determinar",
            "no se especifica",
            "no se encuentra ninguna circular",
            "no se identifica ningún documento",
            "no se proporciona información",
        ];

        let indices_por_contenido: Vec<usize> = memory.nodes.iter()
            .enumerate()
            .rev()
            .filter(|(_, n)| {
                if n.label.starts_with("Origen:")
                    || n.label.starts_with("nacimiento")
                    || n.content.to_lowercase().contains("motor candle")
                {
                    return false;
                }
                // NUEVO: descartar reflexiones que son esencialmente "no sé" —
                // no aportan contexto y desplazan a PDFs reales por antigüedad.
                if n.label.starts_with("Reflexion:") {
                    let c_lower = n.content.to_lowercase();
                    if frases_vacias.iter().any(|f| c_lower.contains(f)) {
                        return false;
                    }
                }
                let c = n.content.to_lowercase();
                palabras_query.iter().any(|pq| c.contains(pq))
            })
            .take(2)
            .map(|(idx, _)| idx)
            .collect();

            // CAMBIO 2: expansión por edges (un salto) desde los nodos semilla
            // encontrados arriba. Antes search() solo hacía coincidencia de texto
            // plano y nunca consultaba memory.edges, así que dos documentos
            // relacionados pero sin palabras literales en común jamás se
            // combinaban en el contexto. Esto es lo que más penalizaba las
            // preguntas multi-fuente del benchmark frente a GraphRAG.
            let mut semillas: Vec<usize> = pdf_exacto_idx.into_iter().collect();
            semillas.extend(indices_por_contenido.iter().copied());

            let mut vecinos: Vec<usize> = Vec::new();
            for &semilla in &semillas {
                for edge in &memory.edges {
                    // Ambas direcciones: no sabemos de antemano si conectar_nodos()
                    // registró la relación como (semilla -> otro) o (otro -> semilla).
                    if edge.from == semilla && !semillas.contains(&edge.to) {
                        vecinos.push(edge.to);
                    } else if edge.to == semilla && !semillas.contains(&edge.from) {
                        vecinos.push(edge.from);
                    }
                }
            }
            // Como mucho 2 vecinos extra, para no inundar el contexto de ruido
            vecinos.truncate(2);

            // Construir el resultado final: semillas primero (mantienen prioridad),
            // luego los vecinos encontrados por grafo.
            let mut indices_finales: Vec<usize> = Vec::new();
            if let Some(idx) = pdf_exacto_idx {
                indices_finales.push(idx);
            }
            for idx in indices_por_contenido {
                if !indices_finales.contains(&idx) {
                    indices_finales.push(idx);
                }
            }
            for idx in vecinos {
                if !indices_finales.contains(&idx) {
                    indices_finales.push(idx);
                }
            }

            let resultados: Vec<String> = indices_finales.iter()
                .filter_map(|&idx| memory.nodes.get(idx))
                .map(|n| n.content.clone())
                .collect();

            // Antes: truncate(3) plano. Ahora se permite algo más de margen
            // (hasta 5) porque ahora SÍ puede haber contexto realmente
            // relacionado por grafo, no solo ruido por coincidencia de palabras.
            let mut resultados = resultados;
            resultados.truncate(5);
            resultados
    }   

    pub fn integrate_knowledge(
        memory: &mut AnimusMemory,
        label: &str,
        content: &str,
        source: Option<&str>,
    ) -> usize {
        let era = Utc::now().to_string();
        if let Some(pos) = memory.nodes.iter().position(|n| n.label == label) {
            memory.nodes[pos].weight += 2.0;
            memory.nodes[pos].connections += 1;
            pos
        } else {
            let new_idx = memory.nodes.len();
            memory.nodes.push(SerializableNode {
                label: label.to_string(),
                content: content.to_string(),
                era,
                weight: 10.0,
                connections: 1,
                source: source.map(|s| s.to_string()),
            });
            new_idx
        }
    }

    pub fn integrate_realtime_knowledge(
        memory: &mut AnimusMemory,
        label: &str,
        content: &str,
    ) {
        let node_idx = Self::integrate_knowledge(memory, label, content, None);
        if node_idx != 0 {
            memory.edges.push(SerializableEdge {
                from: 0,
                to: node_idx,
                weight: 1.0,
            });
        }
    }
}

impl Drop for Brain {
    fn drop(&mut self) {
        if let Some(mut child) = self.server_process.take() {
            let _ = child.kill();
            println!("🔴 Servidor ANIMUS detenido.");
        }
    }
}