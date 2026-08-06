/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Calm teal — the product's primary color (#0F766E at the 600 step).
        brand: {
          50: "#F0FDFA",
          100: "#CCFBF1",
          200: "#99F6E4",
          300: "#5EEAD4",
          400: "#2DD4BF",
          500: "#14B8A6",
          600: "#0F766E",
          700: "#115E59",
          800: "#134E4A",
          900: "#0F3D3A",
        },
        // Semantic medical tones
        success: "#16A34A",
        warning: "#F59E0B",
        danger: "#DC2626",
      },
      fontSize: {
        // Product typography scale
        "page-title": ["32px", { lineHeight: "1.2", fontWeight: "700" }],
        "section-title": ["22px", { lineHeight: "1.25", fontWeight: "600" }],
        "card-title": ["18px", { lineHeight: "1.35", fontWeight: "600" }],
      },
      fontFamily: {
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Helvetica",
          "Arial",
          "sans-serif",
        ],
      },
    },
  },
  plugins: [],
};
