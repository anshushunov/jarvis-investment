/**
 * Считает то, что фаза 3 обязана свести к нулю.
 *
 * Инлайновые стили разрешены только в модулях графиков: ECharts настраивается
 * объектом и принимает цвет строкой. Hex-литералы разрешены только в
 * tokens.ts — это и есть единственное место, где цвет записан значением.
 *
 * Запуск:
 *   pnpm check:styles            печатает счётчики, всегда выходит с нулём
 *   pnpm check:styles --strict   требует нулей (задача 15)
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

// fileURLToPath, а не URL.pathname: на Windows pathname даёт "/C:/…", и
// readdirSync такой путь не открывает.
const ROOT = fileURLToPath(new URL("../src", import.meta.url));
// Модули графиков: ECharts конфигурируется объектом, инлайн там неизбежен.
const CHART_FILES = ["ValueChart.tsx", "AllocationChart.tsx"];
const TOKENS_FILE = "tokens.ts";

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? walk(path) : [path];
  });
}

const files = walk(ROOT).filter(
  (path) => /\.tsx?$/.test(path) && !path.endsWith(".test.ts") && !path.endsWith(".test.tsx"),
);

let inlineStyles = 0;
let hexLiterals = 0;
const offenders = { styles: [], hex: [] };

for (const path of files) {
  const source = readFileSync(path, "utf8");
  const name = path.split(/[\\/]/).pop();

  if (!CHART_FILES.includes(name)) {
    const found = source.match(/style=\{\{/g)?.length ?? 0;
    inlineStyles += found;
    if (found) offenders.styles.push(`${name}: ${found}`);
  }
  if (name !== TOKENS_FILE) {
    const found = source.match(/#[0-9a-fA-F]{6}\b/g)?.length ?? 0;
    hexLiterals += found;
    if (found) offenders.hex.push(`${name}: ${found}`);
  }
}

console.log(`Инлайновых style вне графиков: ${inlineStyles}`);
offenders.styles.forEach((line) => console.log(`  ${line}`));
console.log(`Hex-литералов вне tokens.ts: ${hexLiterals}`);
offenders.hex.forEach((line) => console.log(`  ${line}`));

if (process.argv.includes("--strict") && (inlineStyles || hexLiterals)) {
  console.error("\nПризнак готовности фазы 3 не выполнен.");
  process.exit(1);
}
