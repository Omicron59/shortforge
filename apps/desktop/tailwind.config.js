/** @type {import('tailwindcss').Config} */
// Jetons du nouveau design (prefixe `sf-`). Les anciens ecrans gardent leurs classes en attendant leur refonte.
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        sf: {
          bg: "#0B0F19",
          surface: "#121826",
          raised: "#161D2B",
          border: "#1F2937",
          text: "#F8FAFC",
          muted: "#94A3B8",
          primary: "#7C3AED",
          "primary-hover": "#8B5CF6",
          success: "#22C55E",
          warning: "#F59E0B",
          danger: "#EF4444",
        },
      },
      borderRadius: { sf: "14px" },
      transitionDuration: { sf: "200ms" },
      boxShadow: { sf: "0 1px 2px rgb(0 0 0 / 0.25)" },
    },
  },
  plugins: [],
};
