// Right pane of the run detail view: content keyed on the selected stage.
//   training         → live metrics chart + training.log tail
//   hill-climb stages → score chart + experiment tree
//   anything else     → tiny key/value stage summary

import { TAG_COLORS } from "../../constants.js";
import { Card, Row } from "../../primitives.jsx";
import { ScoreChart, ExperimentTree } from "../../Experiments.jsx";
import { TrainingPanel } from "../../TrainingPanel.jsx";
import { fmtRelTime, fmtScore } from "../../format.js";

const HILLCLIMB_STAGES = new Set([
  "hillclimb", "proposal", "implement", "hillclimb_test",
]);

function StagePanel({
  runId, run, stage, stageMap, experiments, selStep, onSelectStep,
}) {
  return (
    <div style={{
      flex: 1, overflow: "auto", padding: "14px 20px",
      display: "flex", flexDirection: "column",
    }}>
      {stage === "training" && <TrainingStagePanel runId={runId} run={run} />}
      {HILLCLIMB_STAGES.has(stage) && (
        <HillClimbStagePanel
          experiments={experiments}
          selStep={selStep}
          onSelectStep={onSelectStep}
        />
      )}
      {stage !== "training" && !HILLCLIMB_STAGES.has(stage) && (
        <GenericStageCard stage={stage} stageMap={stageMap} run={run} />
      )}
    </div>
  );
}

function TrainingStagePanel({ runId, run }) {
  return (
    <Card style={{
      padding: 0, flex: 1, overflow: "hidden",
      display: "flex", flexDirection: "column",
    }}>
      <div style={{
        padding: "14px 18px 8px", borderBottom: "1px solid var(--border)",
      }}>
        <div style={{ fontSize: 11, fontWeight: 700 }}>TRAINING</div>
        <div style={{
          fontSize: 9, color: "var(--text-faint)", marginTop: 2,
          fontFamily: "'JetBrains Mono',monospace",
        }}>
          workspace/training.log · live
        </div>
      </div>
      <TrainingPanel runId={runId} isRunning={run.status === "running"} />
    </Card>
  );
}

function HillClimbStagePanel({ experiments, selStep, onSelectStep }) {
  const selExp = selStep !== null
    ? experiments.find(e => e.step === selStep)
    : (experiments.length ? experiments[experiments.length - 1] : null);

  return (
    <>
      <Card style={{ padding: 18, marginBottom: 12 }}>
        <div style={{ fontSize: 11, fontWeight: 700, marginBottom: 8 }}>
          PERFORMANCE TRAJECTORY
        </div>
        <ScoreChart experiments={experiments} />
      </Card>
      <Card style={{ padding: 18 }}>
        <div style={{
          display: "flex", justifyContent: "space-between",
          alignItems: "center", marginBottom: 10,
        }}>
          <div style={{ fontSize: 11, fontWeight: 700 }}>EXPERIMENT TREE</div>
          <div style={{
            display: "flex", gap: 10, fontSize: 9,
            fontFamily: "'JetBrains Mono',monospace",
          }}>
            <span style={{ color: "#22d3ee" }}>kept</span>
            <span style={{ color: "#f87171" }}>reverted</span>
          </div>
        </div>
        <ExperimentTree
          experiments={experiments}
          selected={selStep}
          onSelect={onSelectStep}
        />
        {selExp && <SelectedExperimentCard exp={selExp} />}
      </Card>
    </>
  );
}

function SelectedExperimentCard({ exp }) {
  return (
    <div style={{
      marginTop: 10, padding: 12, borderRadius: 8,
      background: "var(--surface)",
      border: "1px solid var(--border-subtle)",
    }}>
      <div style={{
        display: "flex", justifyContent: "space-between",
        alignItems: "center", marginBottom: 4,
      }}>
        <div>
          <span style={{
            fontSize: 11, fontWeight: 700,
            fontFamily: "'JetBrains Mono',monospace",
          }}>
            {exp.step === 0 ? "Baseline" : `Iter ${exp.step}`}
          </span>
          <span style={{
            color: exp.kept ? "#4ade80" : "#f87171",
            fontSize: 9, marginLeft: 6,
          }}>
            {exp.kept ? "KEPT" : "REVERTED"}
          </span>
          {exp.tag && (
            <span style={{
              color: TAG_COLORS[exp.tag] || "#666",
              fontSize: 8, marginLeft: 6,
              background: "var(--surface)", padding: "1px 5px", borderRadius: 3,
            }}>
              {exp.tag}
            </span>
          )}
        </div>
        <div style={{
          fontSize: 18, fontWeight: 700,
          fontFamily: "'JetBrains Mono',monospace",
          color: exp.kept ? "#22d3ee" : "#f87171",
        }}>
          {fmtScore(exp.score)}
        </div>
      </div>
      <div style={{
        fontSize: 10, color: "var(--text-subtle)", whiteSpace: "pre-wrap",
      }}>
        {exp.proposal || "(no proposal recorded)"}
      </div>
    </div>
  );
}

function GenericStageCard({ stage, stageMap, run }) {
  const s = stageMap[stage];
  return (
    <div>
      <h3 style={{ fontSize: 14, fontWeight: 700, marginBottom: 12 }}>{stage}</h3>
      <Card style={{ padding: 16 }}>
        <Row label="Status" value={s?.status || "—"} />
        <Row label="Started"
             value={s?.started_at ? fmtRelTime(s.started_at, run.started_at) : "—"} />
        <Row label="Completed"
             value={s?.completed_at ? fmtRelTime(s.completed_at, run.started_at) : "—"} />
        {s?.attempt > 0 && (
          <Row label="Attempt" value={`${s.attempt} / ${s.max_attempts}`} />
        )}
      </Card>
    </div>
  );
}

export { StagePanel };
