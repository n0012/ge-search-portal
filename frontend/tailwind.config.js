/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Official Amgen brand (from the Amgen sample portal)
        amgen: {
          blue: "#0063C3",
          blueDark: "#0056B3",
          teal: "#15909C",
          green: "#92BE43",
          ink: "#222222",
          muted: "#747474",
          line: "#E5EAF1",
          surface: "#F7F9FC",
        },
      },
      fontFamily: {
        sans: ['"Open Sans"', "Helvetica", "Arial", "sans-serif"],
      },
      boxShadow: {
        card: "0 1px 3px rgba(16,24,40,.08), 0 1px 2px rgba(16,24,40,.04)",
        hero: "0 12px 40px rgba(0,99,195,.12)",
        pill: "0 6px 24px rgba(16,24,40,.10)",
      },
      keyframes: {
        shimmer: { "100%": { transform: "translateX(100%)" } },
        floaty: { "0%,100%": { transform: "translateY(0)" }, "50%": { transform: "translateY(6px)" } },
      },
      animation: {
        shimmer: "shimmer 1.4s infinite",
        floaty: "floaty 1.8s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
