{#-
    Put each model in the schema named by its folder config (STAGING, CORE, MART), as-is.

    dbt's default glues the profile schema in front: "+schema: staging" would become
    STAGING_STAGING. Our layers already exist as fixed schemas (infra/snowflake/00_setup.sql),
    so we use the configured name directly.
-#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim | upper }}
    {%- endif -%}
{%- endmacro %}
