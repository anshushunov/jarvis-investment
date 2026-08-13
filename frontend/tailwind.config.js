import plugin from "tailwindcss/plugin";

import { cssVariables, tokens } from "./src/design/tokens.ts";

/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: tokens.color,
      fontSize: tokens.fontSize,
      borderRadius: tokens.radius,
    },
  },
  plugins: [
    // Переменные :root объявляются отсюда, а не руками в theme.css: две копии
    // палитры разъехались бы при первой же правке цвета.
    plugin(({ addBase }) => addBase({ ":root": cssVariables })),
  ],
};
