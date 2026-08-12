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
    plugin(({ addBase }) => addBase({
      ":root": {
        ...cssVariables,
        // Прежние имена переменных. Живут до задачи 11, где исчезает последнее
        // обращение к ним; задача 15 их снимает и проверяет, что обращений не
        // осталось.
        "--tx-2": tokens.color.muted,
        "--bg-0": tokens.color.bg0,
        "--bg-1": tokens.color.bg1,
      },
    })),
  ],
};
