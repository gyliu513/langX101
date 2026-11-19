-- KPI views over the five datasets (paper section 4). SQLite dialect.
-- Every view is per phase (baseline / incident / ...) so the demo can compare.

-- Cost of each Task = sum of its allocated telemetry rows (2.3.2).
DROP VIEW IF EXISTS task_cost;
CREATE VIEW task_cost AS
SELECT t.x_Phase AS phase, t.WorkloadId, t.TaskId, t.TaskQualityBarMet,
       COALESCE(SUM(tel.x_AllocatedCost), 0)                       AS cost,
       COALESCE(SUM(tel.x_PrefillSeconds + tel.x_DecodeSeconds), 0) AS gpu_s
FROM task t LEFT JOIN telemetry tel
  ON tel.TaskId = t.TaskId AND tel.WorkloadId = t.WorkloadId AND tel.x_Phase = t.x_Phase
WHERE t.TaskId <> 'UNLINKED'
GROUP BY t.x_Phase, t.WorkloadId, t.TaskId, t.TaskQualityBarMet;

-- 4.1 Infrastructure KPIs, per phase and workload (incl. UNLINKED and IDLE lines).
DROP VIEW IF EXISTS kpi_infra;
CREATE VIEW kpi_infra AS
SELECT x_Phase AS phase, WorkloadId,
       SUM(InvocationCount)                                         AS requests,
       SUM(InputTokenCount)                                         AS input_tokens,
       SUM(OutputTokenCount)                                        AS output_tokens,
       ROUND(1.0 * SUM(CacheReadTokenCount) / NULLIF(SUM(InputTokenCount), 0), 3) AS kv_cache_hit_ratio,
       ROUND(SUM(x_PrefillSeconds), 2)                              AS prefill_gpu_s,
       ROUND(SUM(x_DecodeSeconds), 2)                               AS decode_gpu_s,
       SUM(x_AllocatedCost)                                         AS cost_usd,
       1e6 * SUM(x_AllocatedCost) / NULLIF(SUM(InputTokenCount + OutputTokenCount), 0) AS cost_per_1m_tokens
FROM telemetry
GROUP BY x_Phase, WorkloadId;

-- 4.2 Yield, scrap and friction; 4.3 outcome; 4.4 cost to value. Per phase and workload.
DROP VIEW IF EXISTS kpi_workload;
CREATE VIEW kpi_workload AS
WITH c AS (
  SELECT phase, WorkloadId, SUM(cost) AS cost, SUM(gpu_s) AS gpu_s,
         SUM(CASE WHEN TaskQualityBarMet = 0 THEN cost ELSE 0 END) AS failed_task_cost
  FROM task_cost GROUP BY phase, WorkloadId),
t AS (
  SELECT x_Phase AS phase, WorkloadId, SUM(AttemptedTaskCount) AS tasks, SUM(QualifiedTaskCount) AS q_tasks,
         SUM(x_Requests) AS requests,
         SUM(TaskFrictionQuantity + TaskReworkPenaltyQuantity) / NULLIF(SUM(ObservedTaskQuantity), 0) AS friction_ratio
  FROM task WHERE TaskId <> 'UNLINKED' GROUP BY x_Phase, WorkloadId),
o AS (
  SELECT x_Phase AS phase, WorkloadId, SUM(AttemptedOutcomeCount) AS outcomes, SUM(QualifiedOutcomeCount) AS q_outcomes,
         SUM(NetOutcomeQuantity) AS net_outcome, MAX(OutcomeUnit) AS unit,
         SUM(CASE WHEN OutcomeStatus = 'Settled' THEN 1 ELSE 0 END) AS settled
  FROM outcome GROUP BY x_Phase, WorkloadId),
v AS (
  SELECT x_Phase AS phase, WorkloadId, SUM(RealizedValue) AS realized, SUM(EstimatedValue) AS estimated,
         SUM(PlannedValue) AS planned
  FROM value GROUP BY x_Phase, WorkloadId)
SELECT c.phase, c.WorkloadId,
       t.tasks, t.q_tasks, t.requests,
       ROUND(1.0 * t.q_tasks / NULLIF(t.tasks, 0), 3)          AS task_yield,
       c.cost                                                   AS cost_usd,
       c.gpu_s,
       c.failed_task_cost,
       c.cost / NULLIF(t.q_tasks, 0)                            AS cpqt,
       ROUND(t.friction_ratio, 3)                               AS friction_rework_ratio,
       o.outcomes, o.q_outcomes, o.settled,
       ROUND(1.0 * o.q_outcomes / NULLIF(o.outcomes, 0), 3)    AS sla_survival,
       c.cost / NULLIF(o.q_outcomes, 0)                         AS cpqo,
       c.gpu_s / NULLIF(o.q_outcomes, 0)                        AS gpu_s_per_qo,
       o.net_outcome, o.unit,
       v.realized, v.estimated, v.planned,
       CASE WHEN v.estimated > 0 THEN c.cost / v.estimated END  AS spend_to_value
FROM c JOIN t USING (phase, WorkloadId) JOIN o USING (phase, WorkloadId) LEFT JOIN v USING (phase, WorkloadId);

-- Portfolio view per phase: Scrap Rate with UNLINKED as its own line, and IDLE kept apart.
DROP VIEW IF EXISTS kpi_phase;
CREATE VIEW kpi_phase AS
WITH tot AS (
  SELECT x_Phase AS phase,
         SUM(x_AllocatedCost)                                                   AS total_cost,
         SUM(CASE WHEN WorkloadId = 'IDLE' THEN x_AllocatedCost ELSE 0 END)     AS idle_cost,
         SUM(CASE WHEN WorkloadId = 'UNLINKED' THEN x_AllocatedCost ELSE 0 END) AS unlinked_cost
  FROM telemetry GROUP BY x_Phase),
f AS (SELECT phase, SUM(failed_task_cost) AS failed_cost, SUM(q_outcomes) AS q_outcomes,
             SUM(estimated) AS value FROM kpi_workload GROUP BY phase)
SELECT tot.phase, tot.total_cost, tot.idle_cost, tot.unlinked_cost, f.failed_cost,
       ROUND((tot.unlinked_cost + f.failed_cost) / NULLIF(tot.total_cost - tot.idle_cost, 0), 3) AS scrap_rate,
       ROUND(tot.unlinked_cost / NULLIF(tot.total_cost - tot.idle_cost, 0), 3)                  AS scrap_unlinked_share,
       f.q_outcomes, f.value
FROM tot LEFT JOIN f USING (phase);
