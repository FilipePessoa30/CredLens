-- Grain: one row per distinct scenario NAME actually present in the
-- loaded runs (not an invented, hardcoded full list - section 7.4 "do not
-- invent attributes"). Descriptions are static labels for the scenario
-- IDs this project defines (docs/counterfactual_scenarios.md); an
-- unrecognized future scenario name still gets a row, just with its own
-- name as the description, rather than being silently dropped.
select distinct
    scenario as scenario_key,
    scenario,
    case scenario
        when 'baseline' then 'Baseline synthetic portfolio - no intervention.'
        when 'policy_expansion' then 'Synthetic policy expansion - lower approval cutoff (same population, same features, same truth layer).'
        when 'policy_tightening' then 'Synthetic policy tightening - higher approval cutoff (same population, same features, same truth layer).'
        when 'macroeconomic_stress' then 'Synthetic macroeconomic stress shock from a documented date onward.'
        when 'collections_change' then 'Synthetic collections strategy intensification (contact/cure/recovery parameters only).'
        when 'contract_coverage' then 'Small, deterministic test fixture with deliberately extreme parameters - NOT a plausible population.'
        else scenario
    end as scenario_description,
    (scenario != 'contract_coverage') as is_comparable_to_baseline
from {{ ref('stg_generation_runs') }}
