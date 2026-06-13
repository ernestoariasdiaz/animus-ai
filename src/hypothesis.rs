pub struct Hypothesis {
    pub source_node: String,
    pub target_node: String,
    pub relation: String,
    pub novelty_score: f64,
}

impl Hypothesis {
    pub fn forge(a: &str, b: &str) -> Self {
        Hypothesis {
            source_node: a.to_string(),
            target_node: b.to_string(),
            relation: "paradigm_shift__>value_redefinition".to_string(),
            novelty_score: 0.94,
        }
    }
}