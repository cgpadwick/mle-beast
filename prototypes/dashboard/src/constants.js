// Shared constants used by multiple components.

const STAGES_ORDER = [
  { key: "setup", name: "Setup" },
  { key: "data_analysis", name: "Data Analysis" },
  { key: "data_analysis_critic", name: "Data Analysis Critic" },
  { key: "baseline", name: "Baseline" },
  { key: "testing", name: "Testing" },
  { key: "training", name: "Training" },
  { key: "train_finder", name: "Train Finder" },
  { key: "train_finder_critic", name: "Train Finder Critic" },
  { key: "analysis", name: "Analysis" },
  { key: "evaluate", name: "Evaluate" },
  { key: "eval_finder", name: "Eval Finder" },
  { key: "eval_finder_critic", name: "Eval Finder Critic" },
  { key: "proposal", name: "Proposal" },
  { key: "proposal_critic", name: "Proposal Critic" },
  { key: "implement", name: "Implement" },
  { key: "hillclimb_test", name: "Hill-climb Test" },
];

const TAG_COLORS = {
  MODEL: "#818cf8",
  FEATURE: "#f59e0b",
  HYPERPARAM: "#22d3ee",
  DATA: "#4ade80",
  ENSEMBLE: "#f472b6",
};

const cardBase = {
  background: "var(--surface)",
  border: "1px solid var(--border)",
  borderRadius: 14,
};


export { STAGES_ORDER, TAG_COLORS, cardBase };
