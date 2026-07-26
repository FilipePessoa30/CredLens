{#
  A deterministic, stable, non-null surrogate key: md5 of the given columns
  concatenated with a separator unlikely to appear inside any of them, each
  cast to varchar and coalesced to an empty string so a null natural-key
  component never makes the whole key null. Used everywhere a natural key
  needs to be combined with run_id (Phase 5 section 6: customer_id/
  application_id/contract_id are NOT globally unique across runs that share
  common random numbers, so every surrogate key in this warehouse includes
  run_id).
#}
{% macro surrogate_key(columns) %}
    md5(concat_ws('||', {% for c in columns %}coalesce(cast({{ c }} as varchar), '\x00NULL\x00'){% if not loop.last %}, {% endif %}{% endfor %}))
{% endmacro %}
