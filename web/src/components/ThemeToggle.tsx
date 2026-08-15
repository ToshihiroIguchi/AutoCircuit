// Three buttons, not a switch: "System" is a real answer and a two-state toggle cannot express it.
// Someone who has never touched this control is following their operating system, and should keep
// following it when they change it -- which is only true if that is a state the control can be in.

import type { ThemeChoice } from "../core/theme";

const CHOICES: ReadonlyArray<readonly [ThemeChoice, string]> = [
  ["system", "System"],
  ["light", "Light"],
  ["dark", "Dark"],
];

export function ThemeToggle({
  choice,
  onChoice,
}: {
  choice: ThemeChoice;
  onChoice: (choice: ThemeChoice) => void;
}) {
  return (
    <div className="theme-toggle" role="group" aria-label="Colour theme">
      {CHOICES.map(([value, label]) => (
        <button
          key={value}
          type="button"
          className={`theme-toggle__button${choice === value ? " theme-toggle__button--active" : ""}`}
          onClick={() => onChoice(value)}
          aria-pressed={choice === value}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
