import { Search, List, Users, Share2 } from "lucide-react";

/** Floating left icon dock (cf. the Amgen hero mockup). Visual only in v1. */
export function SideDock() {
  const items = [
    { icon: Search, label: "Search", active: true },
    { icon: List, label: "Catalog" },
    { icon: Users, label: "People" },
    { icon: Share2, label: "Connections" },
  ];
  return (
    <div className="fixed left-5 top-1/2 z-20 hidden -translate-y-1/2 flex-col items-center gap-5 rounded-full border border-amgen-line bg-white/90 px-2.5 py-4 shadow-pill backdrop-blur md:flex">
      {items.map(({ icon: Icon, label, active }) => (
        <button
          key={label}
          title={label}
          className={`grid h-9 w-9 place-items-center rounded-full transition ${
            active ? "bg-amgen-blue text-white" : "text-amgen-muted hover:bg-amgen-surface"
          }`}
        >
          <Icon size={18} />
        </button>
      ))}
    </div>
  );
}
