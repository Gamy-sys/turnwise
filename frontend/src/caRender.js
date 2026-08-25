// Client-side rendering of a token into its display form + cue metadata,
// mirroring the backend renderer closely enough for the interactive view.

const VOWELS = "aeiouyAEIOUY";

export const CUE_LABELS = {
  pause: "pause",
  micropause: "micropause",
  latch: "latch",
  overlap: "overlap",
  elongation: "stretch",
  intonation: "intonation",
  stress: "stress",
  loud: "loud",
  quiet: "quiet",
  fast: "fast",
  slow: "slow",
  cutoff: "cut-off",
  in_breath: "in-breath",
  out_breath: "out-breath",
  laughter: "laughter",
};

export const ALL_CUE_TYPES = Object.keys(CUE_LABELS);

export function renderTokenText(tok) {
  let text = tok.text;
  const types = new Set((tok.cues || []).map((c) => c.type));
  const el = (tok.cues || []).find((c) => c.type === "elongation");
  if (el) {
    let pos = -1;
    for (let i = 0; i < text.length; i++) if (VOWELS.includes(text[i])) pos = i;
    if (pos < 0) pos = text.length - 1;
    text = text.slice(0, pos + 1) + el.symbol + text.slice(pos + 1);
  }
  if (types.has("cutoff") && !text.endsWith("-")) text += "-";
  if (types.has("loud")) text = text.toUpperCase();
  if (types.has("quiet")) text = `\u00b0${text}\u00b0`;
  const ic = (tok.cues || []).find((c) => c.type === "intonation");
  return { text, terminal: ic ? ic.symbol : "", stress: types.has("stress") };
}

export function cueColor(type) {
  switch (type) {
    case "pause":
    case "micropause":
      return "#ffb454";
    case "elongation":
      return "#7ee787";
    case "intonation":
      return "#79c0ff";
    case "loud":
    case "quiet":
    case "stress":
      return "#ff7b72";
    case "fast":
    case "slow":
      return "#d2a8ff";
    case "overlap":
    case "latch":
      return "#f0c674";
    case "cutoff":
      return "#ffa657";
    default:
      return "#8b949e";
  }
}
