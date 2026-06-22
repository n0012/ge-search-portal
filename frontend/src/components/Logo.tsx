/** "Intelligent Search" wordmark + the Amgen logo lockup. Click → search home. */
export function Wordmark({ onLight = false, onHome }: { onLight?: boolean; onHome?: () => void }) {
  const main = onLight ? "text-amgen-blue" : "text-white";
  const sub = onLight ? "text-amgen-teal" : "text-white/70";
  const inner = (
    <>
      {/* logo svg is Amgen blue; invert to white on the dark (blue) header so it's visible */}
      <img src="/amgen-logo.svg" alt="Amgen"
           className={`h-5 w-auto ${onLight ? "" : "brightness-0 invert"}`} />
      <span className={`h-6 w-px ${onLight ? "bg-amgen-line" : "bg-white/25"}`} />
      <div className="leading-none text-left">
        <div className={`text-[15px] font-extrabold tracking-tight ${main}`}>Intelligent</div>
        <div className={`text-[13px] font-medium ${sub}`}>Search</div>
      </div>
    </>
  );
  if (onHome) {
    return (
      <button type="button" onClick={onHome} title="Search home"
              aria-label="Go to search home"
              className="flex items-center gap-3 rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-white/60">
        {inner}
      </button>
    );
  }
  return <div className="flex items-center gap-3">{inner}</div>;
}
