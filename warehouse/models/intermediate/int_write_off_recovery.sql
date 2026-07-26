-- One row per write-off, left-joined to its (at most one - see
-- credlens.generation.recoveries's own docstring) recovery event.
select
    w.write_off_key,
    w.contract_key,
    w.run_id,
    w.suite_id,
    w.scenario,
    w.seed,
    w.scale,
    w.write_off_id,
    w.write_off_date,
    w.amount as write_off_amount,
    w.principal as write_off_principal,
    w.interest as write_off_interest,
    w.fees as write_off_fees,
    w.reason,
    w.policy_reference,
    r.recovery_key,
    r.recovery_id,
    r.recovery_date,
    r.amount as recovery_amount,
    r.channel as recovery_channel,
    case
        when r.recovery_date is not null
        then cast(datediff('day', w.write_off_date, r.recovery_date) as integer)
    end as days_to_recovery,
    (r.recovery_key is not null) as has_recovery,
    case
        when r.amount is not null and w.amount > 0
        then r.amount / w.amount
    end as recovery_rate
from {{ ref('stg_write_off_events') }} w
left join {{ ref('stg_recovery_events') }} r on w.write_off_key = r.write_off_key
