{#
  Unions one operational table across every selected source run, tagging
  each row with which run/suite/scenario/seed/scale/generator_version it
  came from. `selected_runs` is ALWAYS passed explicitly via
  `dbt build --vars` by credlens.warehouse (see
  credlens.warehouse.sources.SourceRecord) - dbt_project.yml's own
  `selected_runs: []` default exists only so a bare `dbt build` with no
  vars fails loudly (see the raise_compiler_error below) instead of
  silently building an empty warehouse from an implicit "most recent run".

  Every raw_<table>.sql model is a one-line call to this macro - see
  models/raw/_raw__models.yml for what each one documents.
#}
{% macro raw_union_sources(table_name) %}
    {%- set runs = var('selected_runs', []) -%}
    {%- if runs | length == 0 -%}
        {{ exceptions.raise_compiler_error(
            "No selected_runs provided. credlens warehouse prepare/build always passes "
            "this explicitly via --vars from a validated run/suite selection - never run "
            "dbt directly against this project without it."
        ) }}
    {%- endif -%}
    {%- for run in runs %}
    select
        cast('{{ run.run_id }}' as varchar) as run_id,
        {%- if run.suite_id %}
        cast('{{ run.suite_id }}' as varchar) as suite_id,
        {%- else %}
        cast(null as varchar) as suite_id,
        {%- endif %}
        cast('{{ run.scenario }}' as varchar) as scenario,
        cast({{ run.seed }} as bigint) as seed,
        cast('{{ run.scale }}' as varchar) as scale,
        cast('{{ run.generator_version }}' as varchar) as generator_version,
        *
    from read_parquet('{{ run.source_path }}/{{ table_name }}.parquet')
    {% if not loop.last -%}
    union all
    {% endif -%}
    {%- endfor %}
{% endmacro %}
