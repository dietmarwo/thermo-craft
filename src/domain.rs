#[path = "if97.rs"]
mod if97;
use crate::{Evaluation, Work, infeasible, invalid};
use if97::{State, invert, pq, pt, saturation};
use serde::Deserialize;
use serde_json::json;

pub const CAPABILITIES: &[&str] = &[
    "bounded_if97_regions_1_2_4",
    "closed_rankine",
    "two_open_heater_rankine",
];

#[derive(Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Input {
    Property {},
    Rankine {
        boiler_pa: f64,
        condenser_pa: f64,
        inlet_k: f64,
        turbine_efficiency: f64,
        pump_efficiency: f64,
        min_exhaust_quality: f64,
        #[serde(default)]
        extraction: bool,
    },
}
pub enum Model {
    Property,
    Rankine(Plant),
}
pub struct Plant {
    inlet: State,
    condenser: [State; 2],
    turbine_efficiency: f64,
    pump_efficiency: f64,
    min_exhaust_quality: f64,
    extraction: bool,
}
pub fn prepare(input: Input) -> Result<Model, String> {
    match input {
        Input::Property {} => Ok(Model::Property),
        Input::Rankine {
            boiler_pa,
            condenser_pa,
            inlet_k,
            turbine_efficiency,
            pump_efficiency,
            min_exhaust_quality,
            extraction,
        } => {
            if boiler_pa <= condenser_pa
                || !(0.1..=1.0).contains(&turbine_efficiency)
                || !(0.1..=1.0).contains(&pump_efficiency)
                || !(0.0..=1.0).contains(&min_exhaust_quality)
            {
                return Err("invalid pressure ordering, efficiency or exhaust limit".into());
            }
            let inlet = pt(boiler_pa, inlet_k).map_err(|_| "invalid boiler inlet state")?;
            let condenser = saturation(condenser_pa).map_err(|_| "invalid condenser pressure")?;
            if inlet_k
                <= if97::saturation_temperature(boiler_pa).map_err(|_| "invalid boiler pressure")?
            {
                return Err("boiler outlet must be superheated".into());
            }
            Ok(Model::Rankine(Plant {
                inlet,
                condenser,
                turbine_efficiency,
                pump_efficiency,
                min_exhaust_quality,
                extraction,
            }))
        }
    }
}
pub fn evaluate(model: &Model, parameters: &[f64], work: &mut Work<'_>) -> Evaluation {
    work.step()?;
    match model {
        Model::Property => {
            let state = match parameters {
                [p, t] => pt(*p, *t)?,
                [p, x, 0.0] => pq(*p, *x)?,
                _ => {
                    return Err(invalid(
                        "expected [pressure_pa, temperature_k] or [pressure_pa, quality, 0]",
                    ));
                }
            };
            Ok((state.h_j_kg, work.metrics(|| json!({"state":state}))))
        }
        Model::Rankine(plant) => solve(plant, parameters, work),
    }
}
fn solve(p: &Plant, parameters: &[f64], work: &mut Work<'_>) -> Evaluation {
    let cond = p.condenser[0];
    let inlet = p.inlet;
    let turbine = |before: State, pair: [State; 2], work: &mut Work<'_>| {
        let pressure = pair[0].p_pa;
        let ideal = invert::<false>(pressure, pair, before.s_j_kg_k, work)?;
        let h = before.h_j_kg - p.turbine_efficiency * (before.h_j_kg - ideal.h_j_kg);
        invert::<true>(pressure, pair, h, work)
    };
    let pump = |liquid: State, dest: f64| liquid.v_m3_kg * (dest - liquid.p_pa) / p.pump_efficiency;
    let (
        end,
        turbine_work,
        pump_work,
        inlet_heat,
        condenser_mass,
        extractions,
        heater_residuals,
        states,
    ) = if p.extraction {
        let &[lo, hi] = parameters else {
            return Err(invalid("expected low and high extraction pressure in Pa"));
        };
        if !(cond.p_pa < lo && lo < hi && hi < inlet.p_pa) {
            return Err(infeasible(
                "expected condenser < low extraction < high extraction < boiler",
            ));
        }
        let low = saturation(lo)?;
        let high = saturation(hi)?;
        let out_hi = turbine(inlet, high, work)?;
        let out_lo = turbine(out_hi, low, work)?;
        let out_end = turbine(out_lo, p.condenser, work)?;
        let pump0 = pump(cond, lo);
        let pump1 = pump(low[0], hi);
        let pump2 = pump(high[0], inlet.p_pa);
        let h0 = cond.h_j_kg + pump0;
        let h1 = low[0].h_j_kg + pump1;
        let high_frac = (high[0].h_j_kg - h1) / (out_hi.h_j_kg - h1);
        let low_local = (low[0].h_j_kg - h0) / (out_lo.h_j_kg - h0);
        if !(0.0..1.0).contains(&high_frac) || !(0.0..1.0).contains(&low_local) {
            return Err(infeasible(
                "open-heater mix has no feasible extraction fraction",
            ));
        }
        let flow1 = 1.0 - high_frac;
        let low_frac = flow1 * low_local;
        let flow0 = flow1 - low_frac;
        let work_t = inlet.h_j_kg - out_hi.h_j_kg
            + flow1 * (out_hi.h_j_kg - out_lo.h_j_kg)
            + flow0 * (out_lo.h_j_kg - out_end.h_j_kg);
        let work_p = flow0 * pump0 + flow1 * pump1 + pump2;
        let q = inlet.h_j_kg - high[0].h_j_kg - pump2;
        let residuals = [
            flow0 * h0 + low_frac * out_lo.h_j_kg - flow1 * low[0].h_j_kg,
            flow1 * h1 + high_frac * out_hi.h_j_kg - high[0].h_j_kg,
        ];
        (
            out_end,
            work_t,
            work_p,
            q,
            flow0,
            [low_frac, high_frac],
            residuals,
            work.metrics_enabled
                .then(|| vec![inlet, out_hi, out_lo, out_end, cond, low[0], high[0]]),
        )
    } else {
        if !parameters.is_empty() {
            return Err(invalid("simple Rankine model has no candidate parameters"));
        }
        let end = turbine(inlet, p.condenser, work)?;
        let pump_work = pump(cond, inlet.p_pa);
        (
            end,
            inlet.h_j_kg - end.h_j_kg,
            pump_work,
            inlet.h_j_kg - cond.h_j_kg - pump_work,
            1.0,
            [0.0, 0.0],
            [0.0, 0.0],
            work.metrics_enabled.then(|| vec![inlet, end, cond]),
        )
    };
    let quality = end
        .quality
        .unwrap_or(if end.t_k >= cond.t_k { 1.0 } else { 0.0 });
    if quality < p.min_exhaust_quality {
        return Err(infeasible("turbine exhaust violates minimum quality"));
    }
    let heat_rejected = condenser_mass * (end.h_j_kg - cond.h_j_kg);
    let net = turbine_work - pump_work;
    let residual = inlet_heat - heat_rejected - net;
    if !(inlet_heat > 0.0
        && net > 0.0
        && heat_rejected > 0.0
        && residual.abs() <= 1e-6 * inlet_heat)
        || heater_residuals.iter().any(|v| v.abs() > 1e-6 * inlet_heat)
    {
        return Err(infeasible("cycle fails power, heat or balance checks"));
    }
    let efficiency = net / inlet_heat;
    Ok((
        -efficiency,
        work.metrics(|| json!({"efficiency":efficiency,"gross_work_j_kg":turbine_work,
        "pump_work_j_kg":pump_work,"net_work_j_kg":net,"heat_in_j_kg":inlet_heat,
        "heat_rejected_j_kg":heat_rejected,"exhaust_quality":quality,"energy_residual_j_kg":residual,
        "condenser_mass_fraction":condenser_mass,"extractions_low_high":extractions,
        "heater_residuals_j_kg":heater_residuals,"states":states})),
    ))
}
