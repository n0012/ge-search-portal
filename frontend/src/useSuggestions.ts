import { useRef, useState } from "react";
import { complete } from "./api";

/**
 * Debounced search-as-you-type suggestions for a query input. Feed it every keystroke via
 * onQueryChange; read `suggestions` (bind to a native <datalist> for a zero-CSS dropdown).
 * A sequence guard drops stale responses so fast typing never shows an out-of-order list.
 */
export function useSuggestions(user?: string, enabled = true) {
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const seq = useRef(0);

  function onQueryChange(q: string) {
    if (!enabled) return;
    if (timer.current) clearTimeout(timer.current);
    if (q.trim().length < 2) {
      setSuggestions([]);
      return;
    }
    const mine = ++seq.current;
    timer.current = setTimeout(async () => {
      const r = await complete(q, user);
      if (mine === seq.current) setSuggestions(r);
    }, 180);
  }

  return { suggestions, onQueryChange };
}
