import { useState } from "react";
import { Megaphone, X } from "lucide-react";

/** Slim service-notice strip (cf. the Amgen mockup's banner), modernized. */
export function NoticeBanner() {
  const [open, setOpen] = useState(true);
  if (!open) return null;
  return (
    <div className="flex items-center gap-2 bg-amgen-green/15 px-4 py-1.5 text-xs text-amgen-ink">
      <Megaphone size={14} className="text-amgen-green" />
      <span className="truncate">
        <strong className="font-semibold">Enterprise Search</strong> — demo over a Gemini
        Enterprise data store with per-user security trimming.
      </span>
      <button
        onClick={() => setOpen(false)}
        className="ml-auto rounded-full p-1 text-amgen-muted hover:bg-black/5"
        aria-label="Dismiss"
      >
        <X size={14} />
      </button>
    </div>
  );
}
