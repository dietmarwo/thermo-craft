//! Where a prepared call's time goes, measured through the public API only.
//!
//! `decode` parses the candidate JSON, `matrix` is `score_matrix` on the same
//! values (domain evaluation without JSON), `lean` is `scores_json` and `full`
//! is `evaluate_json`. Each figure is the minimum and the median of 25 timed
//! loops, in microseconds per call. Run with `--release`:
//! `cargo run --release --locked --example breakdown -- models/example.json`.
use serde_json::{Value, json};
use std::{hint::black_box, time::Instant};
use thermo_craft::{Candidate, Prepared};

/// A named call returning a size, kept alive so `black_box` sees its result.
type Case<'a> = (&'static str, Box<dyn FnMut() -> usize + 'a>);

/// Time several calls in interleaved rounds so slow host phases hit all of them.
fn time(calls: u32, mut cases: Vec<Case<'_>>) -> Value {
    let mut samples = vec![Vec::new(); cases.len()];
    for (_, f) in &mut cases {
        black_box(f());
    }
    for _ in 0..25 {
        for (k, (_, f)) in cases.iter_mut().enumerate() {
            let start = Instant::now();
            for _ in 0..calls {
                black_box(f());
            }
            samples[k].push(start.elapsed().as_secs_f64() * 1e6 / f64::from(calls));
        }
    }
    let mut out = serde_json::Map::new();
    for ((name, _), mut values) in cases.into_iter().zip(samples) {
        values.sort_by(f64::total_cmp);
        out.insert(
            name.into(),
            json!({"min_us": values[0], "median_us": values[12]}),
        );
    }
    Value::Object(out)
}

struct Workload {
    prepared: Prepared,
    count: usize,
    candidates: String,
    matrix: Vec<f64>,
}

fn workload(example: &Value, name: &str) -> Workload {
    let mut model = example["model"].clone();
    let mut parameters = example["parameters"].clone();
    let count = match name {
        "one" => 1,
        "serial" => 96,
        "invalid" => 1024,
        "large" => 1024,
        "domain" => {
            model["inlet_k"] = json!(950.0);
            48
        }
        "domain2" => {
            model = json!({"kind": "property"});
            parameters = json!([1000000.0, 750.0]);
            48
        }
        _ => panic!("unknown workload"),
    };
    let rows: Vec<Vec<f64>> = (0..count)
        .map(|i| {
            let mut values: Vec<f64> = serde_json::from_value(parameters.clone()).unwrap();
            if name == "invalid" {
                values = vec![1.0; 63];
            } else if let Some(first) = values.first_mut() {
                *first *= 1.0 + (i % 13) as f64 * 0.003;
            }
            values
        })
        .collect();
    let candidates: Vec<_> = rows
        .iter()
        .enumerate()
        .map(|(i, row)| json!({"id": format!("candidate-{i:04}"), "parameters": row}))
        .collect();
    Workload {
        prepared: Prepared::new(&model.to_string()).unwrap(),
        count,
        candidates: Value::from(candidates).to_string(),
        matrix: rows.concat(),
    }
}

fn main() {
    let path = std::env::args().nth(1).expect("example JSON");
    let example: Value = serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
    let mut phases = serde_json::Map::new();
    for name in ["one", "serial", "domain", "domain2", "invalid"] {
        let w = workload(&example, name);
        let calls = if w.count == 1 { 400 } else { 8 };
        let budget = "{}";
        let mut timed = time(
            calls,
            vec![
                (
                    "decode",
                    Box::new(|| {
                        serde_json::from_str::<Vec<Candidate>>(&w.candidates)
                            .unwrap()
                            .len()
                    }),
                ),
                (
                    "matrix",
                    Box::new(|| {
                        w.prepared
                            .score_matrix(w.count, &w.matrix, budget)
                            .unwrap()
                            .len()
                    }),
                ),
                (
                    "lean",
                    Box::new(|| w.prepared.scores_json(&w.candidates, budget).unwrap().len()),
                ),
                (
                    "full",
                    Box::new(|| {
                        w.prepared
                            .evaluate_json(&w.candidates, budget)
                            .unwrap()
                            .len()
                    }),
                ),
            ],
        );
        timed["candidates"] = json!(w.count);
        phases.insert(name.into(), timed);
    }
    let mut scaling = serde_json::Map::new();
    for name in ["serial", "large"] {
        let w = workload(&example, name);
        let budgets: Vec<String> = [1, 2, 4]
            .iter()
            .map(|workers| json!({"workers": workers}).to_string())
            .collect();
        let mut cases: Vec<Case<'_>> = Vec::new();
        for (budget, (matrix, full)) in budgets.iter().zip([
            ("matrix_workers_1", "full_workers_1"),
            ("matrix_workers_2", "full_workers_2"),
            ("matrix_workers_4", "full_workers_4"),
        ]) {
            let w = &w;
            cases.push((
                matrix,
                Box::new(move || {
                    w.prepared
                        .score_matrix(w.count, &w.matrix, budget)
                        .unwrap()
                        .len()
                }),
            ));
            cases.push((
                full,
                Box::new(move || {
                    w.prepared
                        .evaluate_json(&w.candidates, budget)
                        .unwrap()
                        .len()
                }),
            ));
        }
        let rows = time(4, cases);
        scaling.insert(format!("{name}_{}", w.count), rows);
    }
    let model = example["model"].to_string();
    let prepare = time(
        400,
        vec![(
            "prepare",
            Box::new(|| usize::from(Prepared::new(&model).is_ok())),
        )],
    );
    println!(
        "{}",
        serde_json::to_string_pretty(&json!({
            "unit": "microseconds per call; min and median of 25 timed loops",
            "available_parallelism": std::thread::available_parallelism().map_or(1, usize::from),
            "prepare": prepare["prepare"],
            "phases": phases,
            "worker_scaling": scaling,
        }))
        .unwrap()
    );
}
