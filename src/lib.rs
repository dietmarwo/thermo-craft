mod domain;

use serde::{Deserialize, Serialize};
use serde_json::{Value, json, value::RawValue};
use sha2::{Digest, Sha256};
use std::{
    collections::HashSet,
    path::PathBuf,
    sync::{
        OnceLock,
        atomic::{AtomicUsize, Ordering},
    },
    time::{Duration, Instant},
};

pub type Evaluation = Result<(f64, Value), Failure>;

#[derive(Debug, Clone)]
pub struct Failure {
    status: &'static str,
    detail: String,
    metrics: Option<Value>,
}
pub fn invalid(detail: impl Into<String>) -> Failure {
    Failure {
        status: "invalid",
        detail: detail.into(),
        metrics: None,
    }
}
pub fn infeasible(detail: impl Into<String>) -> Failure {
    Failure {
        status: "infeasible",
        detail: detail.into(),
        metrics: None,
    }
}

impl Failure {
    pub fn with_metrics(mut self, metrics: Value) -> Self {
        self.metrics = Some(metrics);
        self
    }
}

#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Candidate {
    pub id: String,
    pub parameters: Vec<f64>,
    #[serde(default)]
    pub trace: bool,
}

#[derive(Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct Budget {
    workers: usize,
    max_steps: u64,
    wall_ms: Option<u64>,
    cancel_file: Option<PathBuf>,
}
impl Default for Budget {
    fn default() -> Self {
        Self {
            workers: 1,
            max_steps: 1_000_000,
            wall_ms: None,
            cancel_file: None,
        }
    }
}

pub struct Work<'a> {
    budget: &'a Budget,
    deadline: Option<Instant>,
    used: u64,
    monitored: bool,
    metrics_enabled: bool,
}
impl Work<'_> {
    pub fn metrics(&self, make: impl FnOnce() -> Value) -> Value {
        if self.metrics_enabled {
            make()
        } else {
            Value::Null
        }
    }

    #[inline]
    pub fn step(&mut self) -> Result<(), Failure> {
        if self.used < self.budget.max_steps && !self.monitored {
            self.used += 1;
            return Ok(());
        }
        self.checked_step()
    }

    #[cold]
    fn checked_step(&mut self) -> Result<(), Failure> {
        if self.budget.cancel_file.as_ref().is_some_and(|p| p.exists()) {
            return Err(Failure {
                status: "cancelled",
                detail: "cancel file exists".into(),
                metrics: None,
            });
        }
        if self.deadline.is_some_and(|d| Instant::now() >= d) {
            return Err(Failure {
                status: "wall_limit",
                detail: "batch deadline reached".into(),
                metrics: None,
            });
        }
        if self.used == self.budget.max_steps {
            return Err(Failure {
                status: "work_limit",
                detail: "candidate step budget reached".into(),
                metrics: None,
            });
        }
        self.used += 1;
        Ok(())
    }
}

/// One untraced candidate's outcome from `Prepared::score_matrix`.
#[derive(Clone, Debug, PartialEq)]
pub struct MatrixScore {
    /// Same status strings as the JSON records.
    pub status: &'static str,
    pub steps: u64,
    /// `Some` only for `"complete"`.
    pub score: Option<f64>,
}

#[derive(Serialize)]
struct Record<'a> {
    id: &'a str,
    status: &'static str,
    steps: u64,
    score: Option<f64>,
    metrics: Option<Value>,
    detail: Option<String>,
}

#[derive(Serialize)]
struct Batch<'a> {
    model_sha256: &'a str,
    records: Vec<Record<'a>>,
    schema: &'static str,
    version: &'static str,
}

pub struct Prepared {
    model: domain::Model,
    model_sha256: String,
}
impl Prepared {
    pub fn new(model: &str) -> Result<Self, String> {
        let model_sha256 = format!("{:x}", Sha256::digest(model.as_bytes()));
        let model = domain::prepare(serde_json::from_str(model).map_err(|e| e.to_string())?)?;
        Ok(Self {
            model,
            model_sha256,
        })
    }

    pub fn evaluate_json(&self, candidates: &str, budget: &str) -> Result<String, String> {
        let candidates: Vec<Candidate> =
            serde_json::from_str(candidates).map_err(|e| e.to_string())?;
        let budget = serde_json::from_str(budget).map_err(|e| e.to_string())?;
        self.evaluate_encoded(candidates, budget, true)
    }

    /// Evaluate untraced candidates with full feasibility checks and null metrics.
    pub fn scores_json(&self, candidates: &str, budget: &str) -> Result<String, String> {
        let candidates: Vec<Candidate> =
            serde_json::from_str(candidates).map_err(|e| e.to_string())?;
        let budget = serde_json::from_str(budget).map_err(|e| e.to_string())?;
        if candidates.iter().any(|c| c.trace) {
            return Err("scores mode accepts untraced candidates only".into());
        }
        self.evaluate_encoded(candidates, budget, false)
    }

    fn evaluate_encoded(
        &self,
        candidates: Vec<Candidate>,
        budget: Budget,
        metrics_enabled: bool,
    ) -> Result<String, String> {
        serde_json::to_string(&self.evaluate(&candidates, budget, metrics_enabled)?)
            .map_err(|e| e.to_string())
    }

    /// SHA-256 of the exact model bytes passed to [`Prepared::new`].
    pub fn model_sha256(&self) -> &str {
        &self.model_sha256
    }

    /// Evaluate `rows` untraced candidates whose parameters are stored row-major in
    /// `parameters`. Each row has `parameters.len() / rows` values; dimension 0 is
    /// allowed. Budget JSON, limits, worker dispatch, deadlines, cancellation and
    /// failure classification are the same as `scores_json`.
    pub fn score_matrix(
        &self,
        rows: usize,
        parameters: &[f64],
        budget: &str,
    ) -> Result<Vec<MatrixScore>, String> {
        if !(1..=4096).contains(&rows) {
            return Err("matrix rows must be between 1 and 4096".into());
        }
        if !parameters.len().is_multiple_of(rows) {
            return Err("parameter count is not a multiple of the row count".into());
        }
        let dimension = parameters.len() / rows;
        if dimension > 64 {
            return Err("parameter vector exceeds limit".into());
        }
        let budget: Budget = serde_json::from_str(budget).map_err(|e| e.to_string())?;
        check_budget(&budget, rows)?;
        let deadline = deadline(&budget);
        Ok(dispatch(rows, budget.workers, |index| {
            let row = &parameters[index * dimension..(index + 1) * dimension];
            match self.outcome(row, &budget, deadline, false) {
                (steps, Ok((score, _))) => MatrixScore {
                    status: "complete",
                    steps,
                    score: Some(score),
                },
                (steps, Err(e)) => MatrixScore {
                    status: e.status,
                    steps,
                    score: None,
                },
            }
        }))
    }

    fn outcome(
        &self,
        parameters: &[f64],
        budget: &Budget,
        deadline: Option<Instant>,
        metrics_enabled: bool,
    ) -> (u64, Evaluation) {
        let mut work = Work {
            budget,
            deadline,
            used: 0,
            metrics_enabled,
            monitored: deadline.is_some() || budget.cancel_file.is_some(),
        };
        let result = domain::evaluate(&self.model, parameters, &mut work);
        let result = result.and_then(|(score, metrics)| {
            if score.is_finite() {
                Ok((score, metrics))
            } else {
                Err(invalid("nonfinite objective"))
            }
        });
        (work.used, result)
    }

    fn record<'a>(
        &self,
        c: &'a Candidate,
        budget: &Budget,
        deadline: Option<Instant>,
        metrics_enabled: bool,
    ) -> Record<'a> {
        match self.outcome(&c.parameters, budget, deadline, metrics_enabled) {
            (steps, Ok((score, metrics))) => Record {
                id: &c.id,
                status: "complete",
                steps,
                score: Some(score),
                metrics: Some(metrics),
                detail: None,
            },
            (steps, Err(e)) => Record {
                id: &c.id,
                status: e.status,
                steps,
                score: None,
                metrics: if metrics_enabled { e.metrics } else { None },
                detail: Some(e.detail),
            },
        }
    }

    fn evaluate<'a>(
        &'a self,
        candidates: &'a [Candidate],
        budget: Budget,
        metrics_enabled: bool,
    ) -> Result<Batch<'a>, String> {
        check_budget(&budget, candidates.len())?;
        let mut seen = HashSet::with_capacity(candidates.len());
        for c in candidates {
            if c.id.is_empty() || c.id.len() > 128 || !seen.insert(&c.id) || c.parameters.len() > 64
            {
                return Err(
                    "invalid or duplicate candidate id, or parameter vector exceeds limit".into(),
                );
            }
        }
        if candidates.iter().filter(|c| c.trace).count() > 16 {
            return Err("at most 16 traced candidates per batch".into());
        }
        let deadline = deadline(&budget);
        let records = dispatch(candidates.len(), budget.workers, |index| {
            self.record(&candidates[index], &budget, deadline, metrics_enabled)
        });
        Ok(Batch {
            model_sha256: &self.model_sha256,
            records,
            schema: concat!(env!("CARGO_PKG_NAME"), ".result/0.1"),
            version: env!("CARGO_PKG_VERSION"),
        })
    }
}

fn check_budget(budget: &Budget, count: usize) -> Result<(), String> {
    if !(1..=64).contains(&budget.workers)
        || !(1..=100_000_000).contains(&budget.max_steps)
        || budget.wall_ms.is_some_and(|n| n == 0 || n > 86_400_000)
        || count == 0
        || count > 4096
    {
        return Err("invalid budget or batch size".into());
    }
    Ok(())
}

fn deadline(budget: &Budget) -> Option<Instant> {
    budget
        .wall_ms
        .map(|n| Instant::now() + Duration::from_millis(n))
}

/// Evaluate `count` indexed items inline or on scoped workers, returning them in index order.
fn dispatch<T: Send + Sync>(
    count: usize,
    workers: usize,
    evaluate: impl Fn(usize) -> T + Sync,
) -> Vec<T> {
    if workers == 1 || count == 1 {
        return (0..count).map(evaluate).collect();
    }
    let next = AtomicUsize::new(0);
    let slots: Vec<_> = (0..count).map(|_| OnceLock::new()).collect();
    std::thread::scope(|scope| {
        for _ in 0..workers.min(count) {
            scope.spawn(|| {
                loop {
                    let index = next.fetch_add(1, Ordering::Relaxed);
                    if index >= count {
                        break;
                    }
                    assert!(
                        slots[index].set(evaluate(index)).is_ok(),
                        "duplicate work index"
                    );
                }
            });
        }
    });
    slots
        .into_iter()
        .map(|slot| slot.into_inner().expect("missing evaluation"))
        .collect()
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    schema: String,
    model: Box<RawValue>,
    candidates: Vec<Candidate>,
    #[serde(default)]
    budget: Budget,
}

pub fn run(text: &str) -> Result<Value, String> {
    let req: Request = serde_json::from_str(text).map_err(|e| e.to_string())?;
    if req.schema != concat!(env!("CARGO_PKG_NAME"), ".request/0.1") {
        return Err("unsupported request schema".into());
    }
    let prepared = Prepared::new(req.model.get())?;
    serde_json::to_value(prepared.evaluate(&req.candidates, req.budget, true)?)
        .map_err(|e| e.to_string())
}

pub fn capabilities() -> Value {
    json!({"schema": concat!(env!("CARGO_PKG_NAME"), ".capabilities/0.1"),
           "version": env!("CARGO_PKG_VERSION"), "models": domain::CAPABILITIES,
           "batch": true, "worker_limit": 64})
}

#[cfg(feature = "python")]
mod python {
    use super::*;
    use pyo3::{exceptions::PyValueError, prelude::*};

    #[pyclass(name = "Prepared")]
    struct PyPrepared(Prepared);

    #[pymethods]
    impl PyPrepared {
        #[new]
        fn new(model: &str) -> PyResult<Self> {
            Prepared::new(model)
                .map(Self)
                .map_err(PyValueError::new_err)
        }
        fn scores(&self, py: Python<'_>, candidates: String, budget: String) -> PyResult<String> {
            py.detach(|| self.0.scores_json(&candidates, &budget))
                .map_err(PyValueError::new_err)
        }
        fn batch(&self, py: Python<'_>, candidates: String, budget: String) -> PyResult<String> {
            py.detach(|| self.0.evaluate_json(&candidates, &budget))
                .map_err(PyValueError::new_err)
        }
        /// Score rectangular untraced rows; NaN marks every non-complete row.
        #[allow(clippy::type_complexity)]
        fn score_matrix(
            &self,
            py: Python<'_>,
            rows: Vec<Vec<f64>>,
            budget: String,
        ) -> PyResult<(Vec<f64>, Vec<&'static str>, Vec<u64>)> {
            let dimension = rows.first().map_or(0, Vec::len);
            if rows.iter().any(|row| row.len() != dimension) {
                return Err(PyValueError::new_err("ragged parameter rows"));
            }
            let count = rows.len();
            let flat = rows.concat();
            let results = py
                .detach(|| self.0.score_matrix(count, &flat, &budget))
                .map_err(PyValueError::new_err)?;
            let scores = results
                .iter()
                .map(|r| r.score.unwrap_or(f64::NAN))
                .collect();
            let statuses = results.iter().map(|r| r.status).collect();
            let steps = results.iter().map(|r| r.steps).collect();
            Ok((scores, statuses, steps))
        }
    }

    #[pymodule]
    fn _native(m: &Bound<'_, PyModule>) -> PyResult<()> {
        m.add_class::<PyPrepared>()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn fixture() -> Value {
        serde_json::from_str(include_str!("../models/example.json")).unwrap()
    }
    #[test]
    fn prepared_workers_return_same_completed_records() {
        let example = fixture();
        let prepared = Prepared::new(&example["model"].to_string()).unwrap();
        let candidates = json!([
            {"id":"first","parameters":example["parameters"]},
            {"id":"second","parameters":example["parameters"]},
        ]);
        let serial = prepared
            .evaluate_json(&candidates.to_string(), r#"{"workers":1}"#)
            .unwrap();
        let parallel = prepared
            .evaluate_json(&candidates.to_string(), r#"{"workers":4}"#)
            .unwrap();
        assert_eq!(serial, parallel);
        assert!(serial.contains(r#""status":"complete""#));
    }
    #[test]
    fn scores_keep_order_status_steps_and_objective() {
        let example = fixture();
        let prepared = Prepared::new(&example["model"].to_string()).unwrap();
        let mut candidates = json!([
            {"id":"valid","parameters":example["parameters"]},
            {"id":"invalid","parameters": vec![1.0; 63]},
        ]);
        for budget in ["{}", r#"{"workers":4}"#, r#"{"max_steps":1}"#] {
            let mut full: Value = serde_json::from_str(
                &prepared
                    .evaluate_json(&candidates.to_string(), budget)
                    .unwrap(),
            )
            .unwrap();
            for row in full["records"].as_array_mut().unwrap() {
                row["metrics"] = Value::Null;
            }
            let scores: Value = serde_json::from_str(
                &prepared
                    .scores_json(&candidates.to_string(), budget)
                    .unwrap(),
            )
            .unwrap();
            assert_eq!(full, scores);
        }
        candidates[0]["trace"] = json!(true);
        assert!(prepared.scores_json(&candidates.to_string(), "{}").is_err());
    }

    fn matrix_matches_scores(model: &Value, rows: &[Vec<f64>], budget: &str) -> Vec<MatrixScore> {
        let prepared = Prepared::new(&model.to_string()).unwrap();
        let candidates: Vec<_> = rows
            .iter()
            .enumerate()
            .map(|(i, row)| json!({"id": format!("row-{i}"), "parameters": row}))
            .collect();
        let scores: Value = serde_json::from_str(
            &prepared
                .scores_json(&Value::from(candidates).to_string(), budget)
                .unwrap(),
        )
        .unwrap();
        let flat: Vec<f64> = rows.concat();
        let matrix = prepared.score_matrix(rows.len(), &flat, budget).unwrap();
        let records = scores["records"].as_array().unwrap();
        assert_eq!(records.len(), matrix.len());
        for (record, row) in records.iter().zip(&matrix) {
            assert_eq!(record["status"], row.status, "{budget}");
            assert_eq!(record["steps"].as_u64().unwrap(), row.steps, "{budget}");
            assert_eq!(
                record["score"].as_f64().map(f64::to_bits),
                row.score.map(f64::to_bits),
                "{budget}"
            );
            assert_eq!(row.score.is_some(), row.status == "complete");
        }
        matrix
    }

    #[test]
    fn score_matrix_matches_scores_json() {
        let example = fixture();
        let parameters: Vec<f64> = serde_json::from_value(example["parameters"].clone()).unwrap();
        let rankine = vec![
            parameters.clone(),
            vec![2e6, 1e6],
            vec![parameters[0] * 1.2, parameters[1] * 0.9],
            vec![1e4, 2e6],
        ];
        let cancel =
            std::env::temp_dir().join(format!("thermo-matrix-cancel-{}", std::process::id()));
        std::fs::write(&cancel, b"").unwrap();
        let cancel_budget = json!({"cancel_file": cancel}).to_string();
        for budget in [
            "{}",
            r#"{"workers":4}"#,
            r#"{"max_steps":1}"#,
            r#"{"max_steps":50,"workers":3}"#,
            r#"{"wall_ms":60000,"workers":2}"#,
            cancel_budget.as_str(),
        ] {
            let rows = matrix_matches_scores(&example["model"], &rankine, budget);
            if budget == cancel_budget {
                assert!(rows.iter().all(|r| r.status == "cancelled" && r.steps == 0));
            }
            if budget.contains("max_steps\":50") {
                assert_eq!(rows[0].status, "work_limit");
            }
        }
        std::fs::remove_file(&cancel).unwrap();
        let full = matrix_matches_scores(&example["model"], &rankine, r#"{"workers":2}"#);
        assert_eq!(
            full.iter().map(|r| r.status).collect::<Vec<_>>(),
            ["complete", "infeasible", "complete", "infeasible"]
        );
        // Invalid rows: property queries outside the bounded envelope and wrong dimensions.
        let property = json!({"kind": "property"});
        let mixed = vec![
            vec![3e6, 300.0],
            vec![1.0, 400.0],
            vec![3e6, 2000.0],
            vec![1e5, 700.0],
        ];
        let rows = matrix_matches_scores(&property, &mixed, r#"{"workers":4}"#);
        assert_eq!(
            rows.iter().map(|r| r.status).collect::<Vec<_>>(),
            ["complete", "invalid", "invalid", "complete"]
        );
        let wide = vec![vec![1e5, 0.5, 0.0], vec![1e5, 0.5, 1.0]];
        let rows = matrix_matches_scores(&property, &wide, "{}");
        assert_eq!(rows[1].status, "invalid");
        let rows = matrix_matches_scores(&example["model"], &vec![vec![1.0; 3]; 2], "{}");
        assert!(rows.iter().all(|r| r.status == "invalid" && r.steps == 1));
        // Dimension 0 is allowed.
        let mut simple = example["model"].clone();
        simple["extraction"] = json!(false);
        let rows = matrix_matches_scores(&simple, &[vec![], vec![], vec![]], r#"{"workers":2}"#);
        assert!(rows.iter().all(|r| r.status == "complete"));
    }

    #[test]
    fn score_matrix_rejects_bad_shapes_and_budgets() {
        let example = fixture();
        let prepared = Prepared::new(&example["model"].to_string()).unwrap();
        assert!(prepared.score_matrix(0, &[], "{}").is_err());
        assert!(prepared.score_matrix(4097, &[], "{}").is_err());
        assert!(prepared.score_matrix(4096, &[], "{}").is_ok());
        assert!(prepared.score_matrix(2, &[1.0; 3], "{}").is_err());
        assert!(prepared.score_matrix(1, &[1.0; 65], "{}").is_err());
        assert!(prepared.score_matrix(1, &[1.0; 64], "{}").is_ok());
        for budget in [
            "",
            "null",
            r#"{"workers":0}"#,
            r#"{"workers":65}"#,
            r#"{"max_steps":0}"#,
            r#"{"wall_ms":0}"#,
            r#"{"unknown":1}"#,
        ] {
            assert!(
                prepared.score_matrix(1, &[3e5, 2e6], budget).is_err(),
                "{budget}"
            );
        }
        let hash = format!(
            "{:x}",
            Sha256::digest(example["model"].to_string().as_bytes())
        );
        assert_eq!(prepared.model_sha256(), hash);
    }

    #[test]
    fn model_and_candidate_validation_are_independent() {
        let mut example = fixture();
        example["model"]["unexpected"] = json!(true);
        assert!(Prepared::new(&example["model"].to_string()).is_err());
        let example = fixture();
        let prepared = Prepared::new(&example["model"].to_string()).unwrap();
        let duplicate = json!([
            {"id":"a","parameters":example["parameters"]},
            {"id":"a","parameters":example["parameters"]},
        ]);
        assert!(
            prepared
                .evaluate_json(&duplicate.to_string(), "{}")
                .is_err()
        );
    }
}
