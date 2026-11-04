use serde_json::{Value, json};
use std::{hint::black_box, time::Instant};
use thermo_craft::{MatrixScore, Prepared};

enum Api {
    Full,
    Lean,
    Matrix,
}

enum Output {
    Json(String),
    Rows(Vec<MatrixScore>),
}

fn main() {
    let mut args = std::env::args().skip(1);
    let example = std::fs::read_to_string(args.next().expect("example JSON")).unwrap();
    let example: Value = serde_json::from_str(&example).unwrap();
    let mode = args.next().expect("workload");
    let mut model = example["model"].clone();
    #[allow(unused_mut)]
    let mut parameters = example["parameters"].clone();
    let (count, workers, traced, repeats) = match mode.as_str() {
        "one" => (1, 1, false, 40),
        "serial" => (96, 1, false, 4),
        "parallel" => (96, 4, false, 4),
        "trace" => (12, 1, true, 6),
        "invalid" => (1024, 1, false, 6),
        "domain" => {
            model["inlet_k"] = json!(950.0);
            (48, 1, false, 5)
        }
        "domain2" => {
            model = json!({"kind":"property"});
            parameters = json!([1000000.0, 750.0]);
            (48, 1, false, 5)
        }
        _ => panic!("unknown workload"),
    };
    let candidates: Vec<_> = (0..count)
        .map(|i| {
            let mut values = parameters.clone();
            if mode == "invalid" {
                values = json!(vec![1.0; 63]);
            } else if let Some(first) = values.as_array_mut().unwrap().first_mut() {
                *first = json!(first.as_f64().unwrap() * (1.0 + (i % 13) as f64 * 0.003));
            }
            json!({"id": format!("candidate-{i:04}"), "parameters": values, "trace": traced})
        })
        .collect();
    // Row-major parameter matrix holding exactly the values of the JSON candidates.
    let matrix: Vec<f64> = candidates
        .iter()
        .flat_map(|c| c["parameters"].as_array().unwrap().iter())
        .map(|v| v.as_f64().unwrap())
        .collect();
    let candidates = serde_json::to_string(&candidates).unwrap();
    let budget = json!({"workers":workers}).to_string();
    let evaluator = Prepared::new(&model.to_string()).unwrap();
    let api = if std::env::var_os("CRAFT_MATRIX").is_some() {
        assert!(!traced, "matrix mode evaluates untraced candidates only");
        Api::Matrix
    } else if std::env::var_os("CRAFT_SCORES").is_some() {
        Api::Lean
    } else {
        Api::Full
    };
    let evaluate = || match api {
        Api::Full => evaluator
            .evaluate_json(&candidates, &budget)
            .map(Output::Json),
        Api::Lean => evaluator
            .scores_json(&candidates, &budget)
            .map(Output::Json),
        Api::Matrix => evaluator
            .score_matrix(count, &matrix, &budget)
            .map(Output::Rows),
    };
    let first = evaluate().unwrap();
    if args.next().as_deref() == Some("probe") {
        match first {
            Output::Json(text) => println!("{text}"),
            // Print matrix outcomes in the shape of `scores_json` records for pairing.
            Output::Rows(rows) => {
                let records: Vec<_> = rows
                    .iter()
                    .enumerate()
                    .map(|(i, row)| {
                        json!({"id": format!("candidate-{i:04}"), "status": row.status,
                               "steps": row.steps, "score": row.score,
                               "metrics": null, "detail": null})
                    })
                    .collect();
                println!(
                    "{}",
                    json!({"model_sha256": evaluator.model_sha256(), "records": records,
                           "schema": concat!(env!("CARGO_PKG_NAME"), ".result/0.1"),
                           "version": env!("CARGO_PKG_VERSION")})
                );
            }
        }
        return;
    }
    black_box(first);
    let start = Instant::now();
    for _ in 0..repeats {
        black_box(evaluate().unwrap());
    }
    println!("{}", start.elapsed().as_secs_f64() / f64::from(repeats));
}
