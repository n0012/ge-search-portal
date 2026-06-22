import { MessageSquare } from "lucide-react";

/** Right-edge vertical "Feedback" tab (cf. the Amgen mockup). Visual only in v1. */
export function FeedbackTab() {
  return (
    <button
      className="fixed right-0 top-1/2 z-20 hidden -translate-y-1/2 items-center gap-1.5 rounded-l-lg bg-amgen-blue px-2 py-3 text-xs font-semibold text-white shadow-pill md:flex"
      style={{ writingMode: "vertical-rl" }}
      title="Feedback"
    >
      <MessageSquare size={14} className="rotate-90" />
      Feedback
    </button>
  );
}
