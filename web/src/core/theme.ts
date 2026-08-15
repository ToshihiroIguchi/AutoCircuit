// Which palette the page wears, and where the plots get their colours from.
//
// Three choices, not two: "light", "dark", and "system", which follows the operating system and
// keeps following it while the page is open. The resolved value is stamped on <html> as
// `data-theme`, so the stylesheet needs one override block rather than one per delivery mechanism.
// index.html stamps the same attribute from an inline script before the first paint -- that is the
// one place this rule is written twice, and it is written twice because the alternative is a white
// page flashing at someone who asked for a dark one.
//
// The plots are not styled by CSS: Plotly draws into a canvas from a layout object. So the same
// custom properties are *read back* here and handed to it, rather than a second palette being
// written in TypeScript for the plots to disagree with the page through.

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

export type ThemeChoice = "system" | "light" | "dark";
export type Theme = "light" | "dark";

const STORAGE_KEY = "autocircuit.theme";

/** The stored choice, or "system" when there is none -- and when storage refuses to answer. */
export function storedChoice(): ThemeChoice {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw === "light" || raw === "dark" || raw === "system") return raw;
  } catch {
    // Storage can be unavailable (private windows, blocked cookies). Not being able to remember
    // the choice is not a reason to fail to make one.
  }
  return "system";
}

function storeChoice(choice: ThemeChoice): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, choice);
  } catch {
    // As above: the page still themes itself, it just forgets by the next visit.
  }
}

function systemTheme(): Theme {
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/**
 * Stamps the resolved theme on <html>.
 *
 * Called from the event that decides the theme rather than from an effect afterwards, because the
 * plots read their colours out of the computed style during the render that follows. An effect
 * would run too late for the render it belongs to -- and child effects run before their parent's,
 * so moving it there would only make the staleness harder to see.
 */
function applyTheme(resolved: Theme): void {
  document.documentElement.dataset.theme = resolved;
}

/**
 * The theme in force, the choice behind it, and how to change that choice.
 *
 * Under "system" the media query is subscribed to, so switching the OS to dark while the page is
 * open switches the page too -- which is what "system" means, as opposed to "whatever the system
 * said when this tab was opened".
 */
export function useTheme(): {
  choice: ThemeChoice;
  resolved: Theme;
  setChoice: (choice: ThemeChoice) => void;
} {
  const [choice, setChoiceState] = useState<ThemeChoice>(storedChoice);
  const [system, setSystem] = useState<Theme>(systemTheme);
  const resolved: Theme = choice === "system" ? system : choice;

  useEffect(() => {
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = (): void => {
      const next = query.matches ? "dark" : "light";
      setSystem(next);
      // Only when nothing more specific was asked for; under an explicit choice the OS is not
      // the authority and the attribute must not be moved out from under it.
      if (storedChoice() === "system") applyTheme(next);
    };
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  // The mount case, and the only one an effect is right for: index.html has already stamped this
  // value, so there is nothing here for a render to be stale about.
  // Deliberately empty: this runs once, and every later change is stamped by whoever made it.
  useEffect(() => {
    applyTheme(resolved);
  }, []);

  const setChoice = useCallback((next: ThemeChoice) => {
    applyTheme(next === "system" ? systemTheme() : next);
    setChoiceState(next);
    storeChoice(next);
  }, []);

  return { choice, resolved, setChoice };
}

/**
 * The theme in force, for the parts of the page CSS cannot reach.
 *
 * Only the plots need this, and they need it as a *value* rather than as a stylesheet, so it is
 * carried rather than looked up: a second `useTheme()` would be a second piece of state, and the
 * toggle would move one of them.
 */
export const ThemeContext = createContext<Theme>("light");

/** The plot palette for the theme in force, recomputed when it changes and not otherwise. */
export function usePlotTokens(): PlotTokens {
  const resolved = useContext(ThemeContext);
  return useMemo(() => plotTokens(resolved), [resolved]);
}

/** The colours a Plotly layout needs, in the values the stylesheet is currently using. */
export interface PlotTokens {
  /** The measured data. */
  measured: string;
  /** Whatever is drawn over it -- the Lin-KK reconstruction, or a fitted model. */
  model: string;
  text: string;
  grid: string;
  /** Axis lines, and the zero lines a Nyquist plot needs to be readable. */
  axis: string;
}

function tokenValue(styles: CSSStyleDeclaration, name: string, fallback: string): string {
  const value = styles.getPropertyValue(name).trim();
  return value === "" ? fallback : value;
}

/**
 * Reads the palette back out of the document.
 *
 * `resolved` is not used for the lookup -- the custom properties already carry the right values by
 * then -- but it is what tells the caller to read again, so it stays in the signature and in the
 * dependency list rather than being an argument nobody passes.
 */
export function plotTokens(resolved: Theme): PlotTokens {
  const styles = getComputedStyle(document.documentElement);
  return {
    measured: tokenValue(styles, "--series-1", resolved === "dark" ? "#5aa2f0" : "#2a78d6"),
    model: tokenValue(styles, "--series-2", resolved === "dark" ? "#f58a5a" : "#eb6834"),
    text: tokenValue(styles, "--text-secondary", resolved === "dark" ? "#b2b5ba" : "#52514e"),
    grid: tokenValue(styles, "--plot-grid", resolved === "dark" ? "#34373d" : "#e1e0d9"),
    axis: tokenValue(styles, "--plot-axis", resolved === "dark" ? "#4a4e55" : "#c3c2b7"),
  };
}
