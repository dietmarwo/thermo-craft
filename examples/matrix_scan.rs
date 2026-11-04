//! Scan extraction pressures with the typed score-matrix API (no JSON per candidate).
//!
//! `cargo run --release --locked --example matrix_scan -- models/example.json`
use serde_json::Value;
use std::collections::BTreeMap;
use thermo_craft::Prepared;

fn main() -> Result<(), String> {
    let path = std::env::args()
        .nth(1)
        .ok_or("example JSON path required")?;
    let text = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
    let example: Value = serde_json::from_str(&text).map_err(|e| e.to_string())?;
    let prepared = Prepared::new(&example["model"].to_string())?;
    let n = 40;
    let log_space = |a: f64, b: f64, k: usize| a * (b / a).powf(k as f64 / (n - 1) as f64);
    // Row-major matrix: one [low_pa, high_pa] row per candidate.
    let mut parameters = Vec::with_capacity(2 * n * n);
    for i in 0..n {
        for j in 0..n {
            parameters.extend([log_space(50e3, 1.5e6, i), log_space(0.5e6, 6e6, j)]);
        }
    }
    let rows = prepared.score_matrix(n * n, &parameters, r#"{"workers":2}"#)?;
    let mut statuses = BTreeMap::new();
    for row in &rows {
        *statuses.entry(row.status).or_insert(0) += 1;
    }
    let (best, row) = rows
        .iter()
        .enumerate()
        .filter_map(|(k, row)| row.score.map(|score| (k, score)))
        .min_by(|a, b| a.1.total_cmp(&b.1))
        .ok_or("no feasible candidate")?;
    println!("model sha256 {}", prepared.model_sha256());
    println!("{} candidates, statuses {statuses:?}", rows.len());
    println!(
        "best low {:.1} kPa, high {:.4} MPa, efficiency {:.6}, steps {}",
        parameters[2 * best] / 1e3,
        parameters[2 * best + 1] / 1e6,
        -row,
        rows[best].steps
    );
    Ok(())
}
