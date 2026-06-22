/** Emerald hexagon emblem with a magnifier + lightbulb (cf. the Amgen hero mockup). */
export function HexEmblem({ size = 76 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 100 100" aria-hidden="true">
      <defs>
        <linearGradient id="hex" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#92BE43" />
          <stop offset="1" stopColor="#15909C" />
        </linearGradient>
      </defs>
      <path
        d="M50 4 L88 26 V74 L50 96 L12 74 V26 Z"
        fill="url(#hex)"
      />
      <circle cx="45" cy="45" r="15" fill="none" stroke="#fff" strokeWidth="5" />
      <line x1="56" y1="56" x2="70" y2="70" stroke="#fff" strokeWidth="6" strokeLinecap="round" />
      <path d="M45 39 a6 6 0 0 1 0 12 M45 51 v3" fill="none" stroke="#fff" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}
