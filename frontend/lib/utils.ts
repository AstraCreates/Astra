import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export type GoalField = { label: string; value: string };

/**
 * Goals built from the onboarding quiz are `\n`-joined "Label: value" lines
 * (see BusinessQuizModal.buildQuizContext). Rendered through a plain
 * paragraph, those newlines collapse into one run-on sentence — this
 * recovers the structure so callers can render a real field list instead.
 */
export function parseGoalFields(goal: string): GoalField[] {
  return (goal || "")
    .split("\n")
    .map((line) => line.trim())
    // Drop blank lines and separator artifacts ("---") some goal strings
    // carry between sections — they're not a field, just noise.
    .filter((line) => line && /[a-z0-9]/i.test(line))
    .map((line) => {
      const i = line.indexOf(": ");
      return i > 0 ? { label: line.slice(0, i), value: line.slice(i + 2) } : { label: "", value: line };
    });
}

/** Short, word-safe title for a goal string: the project name if present, else its first field. */
export function goalTitle(goal: string, maxLen = 72): string {
  const fields = parseGoalFields(goal);
  const named = fields.find((f) => /project name/i.test(f.label))?.value;
  const fallback = named || fields[0]?.value || goal || "";
  return fallback.length > maxLen ? `${fallback.slice(0, maxLen - 1)}…` : fallback;
}
