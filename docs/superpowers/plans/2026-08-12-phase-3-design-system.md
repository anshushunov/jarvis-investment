# Фаза 3 «Дизайн-система и навигация» — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Новый экран собирается из готовых компонентов, а не рисуется заново: токены, примитивы, состояния данных, навигация по четырём экранам, регулятор анимаций и переключатель периода графика.

**Architecture:** Единственный источник значений — `src/design/tokens.ts`; из него Tailwind получает утилиты, CSS — переменные, а ECharts — цвета напрямую (объектом, потому что классы он не понимает). Компоненты переводятся на примитивы **на месте**, композиция экрана при этом не меняется — и только после этого появляются роутер и четыре экрана. Порядок обратный обесценил бы скриншотную проверку.

**Tech Stack:** React 19, TypeScript, Vite, Tailwind 3.4, `cva`, `react-router`, TanStack Query, Apache ECharts, vitest + @testing-library/react.

## Global Constraints

- **Дизайн-документ:** [`docs/superpowers/specs/2026-08-12-phase-3-design-system-design.md`](../specs/2026-08-12-phase-3-design-system-design.md). Решения владельца оттуда менять нельзя.
- **Перенос один в один.** Вид блока после перевода совпадает с видом до него. Исключения ровно два, оба названы в дизайне: элементы без собственных стилей (кнопки, поля) и схлопывание цветовых расхождений (`#e2b93b` → `--amber`, `#638cff` → `--blue`).
- **Комментарии и текст интерфейса — по-русски**, как во всём проекте. Комментарий объясняет причину, а не пересказывает код.
- **Тесты фронта:** `cd frontend && pnpm exec vitest run`. Команды `pnpm test` в проекте нет.
- **Проверка типов:** `cd frontend && pnpm run build` (`tsc -b && vite build`).
- **Бэкенд не трогаем вовсе.** Если задача требует изменений в API — это ошибка плана, остановиться и сказать владельцу.
- **Числа остаются строками.** Деньги приходят с бэкенда строками и форматируются через `formatMoney`/`formatQuantity` из `src/api/format.ts`. `Number.parseFloat` допустим только там, где значение уходит в геометрию графика.
- **Коммиты — по-русски**, в стиле истории: `feat: …`, `fix: …`, `refactor: …`, `docs: …`.
- Ветка `feature/phase-3-design-system` уже создана и содержит дизайн-документ.

---

## Карта файлов

**Создаются:**

| Файл | Ответственность |
|---|---|
| `frontend/src/design/tokens.ts` | единственное место, где цвет и размер записаны значением |
| `frontend/src/design/tokens.test.ts` | проверка, что токены доезжают до Tailwind и до `:root` |
| `frontend/src/ui/Card.tsx` | `Card`, `CardTitle` |
| `frontend/src/ui/CardState.tsx` | `CardState` — загрузка, пусто, ошибка |
| `frontend/src/ui/Button.tsx` | `Button` |
| `frontend/src/ui/Field.tsx` | `Field`, `FieldLabel` |
| `frontend/src/ui/Badge.tsx` | `Badge` |
| `frontend/src/ui/Table.tsx` | `Table`, `Th`, `Td` |
| `frontend/src/ui/SegmentedControl.tsx` | переключатель периода |
| `frontend/src/ui/*.test.tsx` | тесты примитивов |
| `frontend/src/components/AsOfLabel.tsx` | возраст данных |
| `frontend/src/components/CoverageNotice.tsx` | охват оценки (вынос из `SummaryCard`) |
| `frontend/src/app/AppShell.tsx` | каркас: навигация, шапка, содержимое |
| `frontend/src/app/routes.tsx` | адреса и пункты меню |
| `frontend/src/pages/AssetsPage.tsx` | Активы |
| `frontend/src/pages/TradesPage.tsx` | Сделки и расхождения |
| `frontend/src/pages/SettingsPage.tsx` | Настройки |
| `frontend/src/design/animation.tsx` | режим анимаций и `useAnimatedNumber` |
| `frontend/scripts/check-styles.mjs` | счётчик инлайн-стилей и hex-литералов |

**Меняются:**

| Файл | Что |
|---|---|
| `frontend/tailwind.config.js` | токены и плагин `:root` |
| `frontend/src/theme.css` | остаются структурные правила, цвета уходят |
| `frontend/src/components/SummaryCard.tsx` | на примитивы; `CoverageNotice` уезжает |
| `frontend/src/components/CashCard.tsx`, `AllocationChart.tsx`, `ValueChart.tsx`, `PositionsTable.tsx`, `ReconciliationBanner.tsx`, `DecisionPanel.tsx`, `MoneyValue.tsx` | на примитивы и токены |
| `frontend/src/pages/PortfolioPage.tsx` | теряет шапку и разъезжается по экранам |
| `frontend/src/App.tsx` | роутер |
| `frontend/package.json` | `cva`, `react-router`, команда `check:styles` |
| `README.md`, `docs/roadmap.md` | итоги фазы |

---

### Task 1: Токены и единственный источник истины

Сегодня цвет записан значением в трёх местах сразу: 13 переменных в `theme.css`, 18 hex-литералов в модулях графиков, и среди них два дубля токенов **с расхождением** — `#e2b93b` против `--amber: #e8b04b` и `#638cff` против `--blue: #7b9cff`. Один смысл нарисован двумя цветами.

**Files:**
- Create: `frontend/src/design/tokens.ts`
- Create: `frontend/src/design/tokens.test.ts`
- Modify: `frontend/tailwind.config.js`
- Modify: `frontend/src/theme.css`

**Interfaces:**
- Consumes: ничего.
- Produces: `tokens` — объект с полями `color`, `chart`, `assetClass`, `fontSize`, `radius`; `cssVariables: Record<string, string>` (имя переменной → значение) для плагина Tailwind.

- [ ] **Step 1: Написать падающий тест**

Создать `frontend/src/design/tokens.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { cssVariables, tokens } from "./tokens";

describe("токены", () => {
  it("не содержат двух цветов на один смысл", () => {
    // До этой фазы жёлтый был записан дважды: --amber #e8b04b в theme.css и
    // #e2b93b в ValueChart. Один смысл, два цвета — расхождение, которое
    // невозможно заметить глазом и нечем поймать, кроме такой проверки.
    expect(tokens.chart.incomplete).toBe(tokens.color.amber);
    expect(tokens.chart.line).toBe(tokens.color.blue);
    expect(tokens.chart.label).toBe(tokens.color.muted);
  });

  it("объявляют переменную на каждый цвет палитры", () => {
    // Плагин Tailwind объявляет их в :root — на них опирается theme.css.
    for (const [name, value] of Object.entries(tokens.color)) {
      expect(cssVariables).toHaveProperty(`--${kebab(name)}`, value);
    }
  });

  it("держат палитру классов активов отдельно от семантики", () => {
    // Цвет облигаций — не «предупреждение» и не «ошибка»: он про класс актива.
    // Сведение их к семантическим токенам заставило бы называть золото
    // «вниманием», и первый же новый класс сломал бы это соответствие.
    expect(Object.keys(tokens.assetClass)).toContain("bonds");
    expect(Object.values(tokens.color)).not.toContain(tokens.assetClass.bonds);
  });
});

function kebab(name: string): string {
  return name.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`);
}
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd frontend && pnpm exec vitest run src/design/tokens.test.ts`
Expected: FAIL — `Failed to resolve import "./tokens"`.

- [ ] **Step 3: Написать токены**

Создать `frontend/src/design/tokens.ts`. Значения `color` перенесены из `theme.css` дословно, `chart.axis` и `chart.grid` — из `ValueChart`, `assetClass` — из `AllocationChart`:

```ts
/**
 * Единственное место, где цвет и размер записаны значением.
 *
 * Источник — TypeScript, а не CSS: ECharts настраивается объектом и принимает
 * цвет строкой, классов он не понимает, а достать значение переменной из CSS в
 * JS можно только через getComputedStyle, которого в jsdom нет. Обратное
 * направление (TS → переменные :root) выражается плагином Tailwind и
 * проверяется сборкой.
 */

export const tokens = {
  color: {
    bg0: "#0a0e18",
    bg1: "#0f1424",
    card: "rgba(255, 255, 255, 0.035)",
    line: "rgba(130, 150, 200, 0.16)",
    tx: "#e7ecf9",
    muted: "#9aa5c4",
    blue: "#7b9cff",
    green: "#4fd39a",
    red: "#f2749a",
    amber: "#e8b04b",
  },

  /**
   * Цвета графиков. Оси и сетка своих токенов раньше не имели вовсе, а линия и
   * метка неполноты были записаны литералами, отличавшимися от палитры на
   * пару процентов яркости.
   */
  chart: {
    axis: "#3a4763",
    grid: "#1c2438",
    get line() { return tokens.color.blue; },
    area: "rgba(123,156,255,0.18)",
    get incomplete() { return tokens.color.amber; },
    get label() { return tokens.color.muted; },
    get pieBorder() { return tokens.color.bg1; },
  },

  /**
   * Палитра классов активов. Держится отдельно от семантики намеренно: цвет
   * здесь про класс актива, а не про «хорошо или плохо», и свести её к
   * семантическим токенам значило бы называть золото «вниманием».
   */
  assetClass: {
    equity: "#3987e5",
    bonds: "#d95926",
    money_market: "#199e70",
    gold: "#c98500",
    silver: "#9aa5b8",
    platinum: "#4fb0bf",
    palladium: "#8f9a3f",
    cash: "#d55181",
    derivatives: "#008300",
    mixed: "#9085e9",
    other: "#e66767",
  },

  // Вся шкала интерфейса: замер 12.08.2026 нашёл ровно пять размеров, и 12–13
  // покрывают 50 обращений из 58.
  fontSize: {
    "2xs": "11px",
    xs: "12px",
    sm: "13px",
    title: "22px",
    hero: "34px",
  },

  radius: {
    sm: "8px",
    md: "9px",
    lg: "14px",
  },
} as const;

/** Имя CSS-переменной → значение. Объявляются плагином Tailwind в :root. */
export const cssVariables: Record<string, string> = Object.fromEntries(
  Object.entries(tokens.color).map(([name, value]) => [
    `--${name.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`)}`,
    value,
  ]),
);
```

- [ ] **Step 4: Подключить токены к Tailwind**

Заменить `frontend/tailwind.config.js`:

```js
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
```

- [ ] **Step 5: Убрать цвета из `theme.css`**

Заменить `frontend/src/theme.css` (блок `:root` уходит целиком — его объявляет плагин; `.card` остаётся до задачи 3, где его заменит примитив):

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

body {
  margin: 0;
  min-height: 100vh;
  background:
    radial-gradient(1100px 620px at 12% -8%, rgba(90, 130, 255, 0.16), transparent 60%),
    linear-gradient(170deg, var(--bg1) 0%, var(--bg0) 55%);
  background-attachment: fixed;
  color: var(--tx);
  font-family: -apple-system, "Segoe UI", Inter, sans-serif;
  font-variant-numeric: tabular-nums;
}

.card {
  border: 1px solid var(--line);
  border-radius: 14px;
  background: var(--card);
  backdrop-filter: blur(8px);
  padding: 18px 20px;
}
```

Правило `@media (prefers-reduced-motion: reduce) { * { animation: none !important } }` удаляется: оно делает регулятор анимаций из задачи 12 неработающим. Системная настройка будет учтена там как значение по умолчанию.

**Внимание:** имена переменных изменились (`--tx-2` → `--muted`, `--bg-0` → `--bg0`). Прежние имена ещё используются в девяти файлах — они станут недействительными и цвет пропадёт. Это ожидаемо и чинится задачами 5–11; чтобы фаза не оставалась сломанной между задачами, добавить в плагин временный алиас:

```js
    plugin(({ addBase }) => addBase({
      ":root": {
        ...cssVariables,
        // Прежние имена переменных. Живут до задачи 11, где исчезает последнее
        // обращение к ним; задача 14 проверяет, что их не осталось.
        "--tx-2": tokens.color.muted,
        "--bg-0": tokens.color.bg0,
        "--bg-1": tokens.color.bg1,
      },
    })),
```

- [ ] **Step 6: Убедиться, что тесты и сборка проходят**

```bash
cd frontend
pnpm exec vitest run src/design/tokens.test.ts
pnpm run build
```

Expected: тесты PASS, сборка без ошибок типов.

- [ ] **Step 7: Посмотреть глазами**

Запустить `pnpm dev`, открыть `http://localhost:3000`, убедиться, что вид не изменился: цвета на месте, фон градиентный, карточки с рамкой. Расхождение здесь — дефект переноса переменных.

- [ ] **Step 8: Коммит**

```bash
git add frontend/src/design/tokens.ts frontend/src/design/tokens.test.ts frontend/tailwind.config.js frontend/src/theme.css
git commit -m "feat: токены дизайн-системы одним источником истины"
```

---

### Task 2: Счётчик инлайн-стилей

Признак готовности фазы — «инлайн-стилей не осталось» — сейчас не измерен ничем. Счётчик появляется в начале, чтобы прогресс был виден по ходу, а требование нуля включается в задаче 14.

**Files:**
- Create: `frontend/scripts/check-styles.mjs`
- Modify: `frontend/package.json`

**Interfaces:**
- Consumes: ничего.
- Produces: команда `pnpm check:styles`; выход `0`, пока не передан `--strict`; с `--strict` выход `1` при ненулевом счётчике.

- [ ] **Step 1: Написать скрипт**

Создать `frontend/scripts/check-styles.mjs`:

```js
/**
 * Считает то, что фаза 3 обязана свести к нулю.
 *
 * Инлайновые стили разрешены только в модулях графиков: ECharts настраивается
 * объектом и принимает цвет строкой. Hex-литералы разрешены только в
 * tokens.ts — это и есть единственное место, где цвет записан значением.
 *
 * Запуск:
 *   pnpm check:styles            печатает счётчики, всегда выходит с нулём
 *   pnpm check:styles --strict   требует нулей (задача 14)
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const ROOT = new URL("../src", import.meta.url).pathname;
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
```

- [ ] **Step 2: Добавить команду**

В `frontend/package.json` в блок `scripts`:

```json
    "check:styles": "node scripts/check-styles.mjs",
```

- [ ] **Step 3: Снять замер «до»**

Run: `cd frontend && pnpm check:styles`
Expected: `Инлайновых style вне графиков: 121`, `Hex-литералов вне tokens.ts: 0` — 127 минус 6 в `ValueChart`, а hex уехали в токены задачей 1. Записать полученные числа: они пойдут в итоги фазы.

- [ ] **Step 4: Коммит**

```bash
git add frontend/scripts/check-styles.mjs frontend/package.json
git commit -m "feat: счётчик инлайн-стилей и hex-литералов"
```

---

### Task 3: Card и CardTitle

`.card` используется в шести файлах, и рядом с ним в пяти повторяется одна и та же подпись: 12px, `--tx-2`, отступ снизу 8.

**Files:**
- Create: `frontend/src/ui/Card.tsx`
- Create: `frontend/src/ui/Card.test.tsx`

**Interfaces:**
- Consumes: ничего.
- Produces: `Card({ children, className? })`, `CardTitle({ children })`.

- [ ] **Step 1: Написать падающий тест**

Создать `frontend/src/ui/Card.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Card, CardTitle } from "./Card";

describe("Card", () => {
  it("рисует содержимое на подложке", () => {
    render(<Card>содержимое</Card>);
    expect(screen.getByText("содержимое")).toBeInTheDocument();
  });

  it("принимает дополнительные классы, не теряя своих", () => {
    // Карточке иногда нужен свой отступ или колонка сетки, и способ добавить
    // их не должен требовать второй обёртки вокруг.
    render(<Card className="col-span-2">содержимое</Card>);
    const card = screen.getByText("содержимое");
    expect(card.className).toContain("col-span-2");
    expect(card.className).toContain("rounded-lg");
  });

  it("подписывает карточку приглушённым заголовком", () => {
    render(<CardTitle>Денежные остатки</CardTitle>);
    expect(screen.getByText("Денежные остатки").className).toContain("text-muted");
  });
});
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd frontend && pnpm exec vitest run src/ui/Card.test.tsx`
Expected: FAIL — `Failed to resolve import "./Card"`.

- [ ] **Step 3: Написать примитив**

Создать `frontend/src/ui/Card.tsx`:

```tsx
import type { ReactNode } from "react";

/**
 * Подложка карточки — единственная на проект.
 *
 * Заменяет класс .card из theme.css: правило «как выглядит карточка» жило в
 * CSS, а отступы вокруг него дописывались инлайном в каждом файле по-своему.
 */
export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={`rounded-lg border border-line bg-card px-5 py-[18px] backdrop-blur-[8px] ${className}`}
    >
      {children}
    </div>
  );
}

/** Подпись карточки. Повторялась в пяти файлах одинаковым инлайновым стилем. */
export function CardTitle({ children }: { children: ReactNode }) {
  return <div className="mb-2 text-xs text-muted">{children}</div>;
}
```

- [ ] **Step 4: Убедиться, что тест проходит**

Run: `cd frontend && pnpm exec vitest run src/ui/Card.test.tsx`
Expected: PASS, три теста.

- [ ] **Step 5: Коммит**

```bash
git add frontend/src/ui/Card.tsx frontend/src/ui/Card.test.tsx
git commit -m "feat: примитивы Card и CardTitle"
```

---

### Task 4: CardState — загрузка, пусто, ошибка

Правило, добытое фазой 2c, сегодня записано словами в комментариях `ValueChart`, `CashCard` и `PositionsTable`: сбой запроса не выдаётся за отсутствие данных, а «пока не пришло» — за «пусто». В примитиве оно становится непредставимым иначе.

**Files:**
- Create: `frontend/src/ui/CardState.tsx`
- Create: `frontend/src/ui/CardState.test.tsx`

**Interfaces:**
- Consumes: `Card` (задача 3).
- Produces: `CardState({ kind: "loading" | "empty" | "error", children })`.

- [ ] **Step 1: Написать падающий тест**

Создать `frontend/src/ui/CardState.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CardState } from "./CardState";

describe("CardState", () => {
  it("показывает ошибку цветом ошибки", () => {
    render(<CardState kind="error">сеть недоступна</CardState>);
    expect(screen.getByText(/сеть недоступна/).className).toContain("text-red");
  });

  it("не красит ожидание и пустоту как ошибку", () => {
    // Сбой запроса и «данных нет» — разные утверждения о мире. Одинаковый вид
    // заставлял бы владельца гадать, чинить ли сеть или ждать синхронизации.
    render(<CardState kind="loading">Загрузка остатков…</CardState>);
    render(<CardState kind="empty">Остатков нет.</CardState>);

    expect(screen.getByText("Загрузка остатков…").className).not.toContain("text-red");
    expect(screen.getByText("Остатков нет.").className).not.toContain("text-red");
  });

  it("помечает состояние для чтения с экрана", () => {
    // Цвет один не годится: он ничего не сообщает тому, кто его не видит.
    render(<CardState kind="error">сеть недоступна</CardState>);
    expect(screen.getByRole("status")).toHaveTextContent("сеть недоступна");
  });
});
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd frontend && pnpm exec vitest run src/ui/CardState.test.tsx`
Expected: FAIL — `Failed to resolve import "./CardState"`.

- [ ] **Step 3: Написать примитив**

Создать `frontend/src/ui/CardState.tsx`:

```tsx
import type { ReactNode } from "react";

import { Card } from "./Card";

// Три состояния данных различаются и цветом, и текстом. Сбой запроса — не то
// же самое, что «данных нет», а идущий запрос — не то же самое, что пустой
// ответ: до фазы 2c компоненты путали их и показывали заглушку про
// синхронизацию, пока ответ был в пути.
const TONE = {
  loading: "text-muted",
  empty: "text-muted",
  error: "text-red",
} as const;

export function CardState({ kind, children }: {
  kind: keyof typeof TONE;
  children: ReactNode;
}) {
  return (
    <Card>
      {/* role="status" — чтобы состояние читалось с экрана, а не только
          различалось цветом. */}
      <div role="status" className={`text-sm ${TONE[kind]}`}>{children}</div>
    </Card>
  );
}
```

- [ ] **Step 4: Убедиться, что тест проходит**

Run: `cd frontend && pnpm exec vitest run src/ui/CardState.test.tsx`
Expected: PASS, три теста.

- [ ] **Step 5: Коммит**

```bash
git add frontend/src/ui/CardState.tsx frontend/src/ui/CardState.test.tsx
git commit -m "feat: примитив состояний карточки"
```

---

### Task 5: Button и Field

Замер 12.08.2026: стилизована **одна кнопка из одиннадцати** — «Обновить из Т-Банка». Остальные десять в `DecisionPanel` рисуются системными кнопками браузера, а из четырнадцати полей ввода стилей нет ни у одного. Здесь переносить нечего — это первое появление стиля, и скриншотное сравнение к задаче не применяется.

**Files:**
- Create: `frontend/src/ui/Button.tsx`, `frontend/src/ui/Button.test.tsx`
- Create: `frontend/src/ui/Field.tsx`, `frontend/src/ui/Field.test.tsx`
- Modify: `frontend/package.json` (зависимость `class-variance-authority`)

**Interfaces:**
- Consumes: ничего.
- Produces: `Button({ variant?: "primary" | "ghost" | "danger", ...ButtonHTMLAttributes })`; `Field(props: InputHTMLAttributes)`, `FieldLabel({ children })`.

- [ ] **Step 1: Поставить `cva`**

```bash
cd frontend && pnpm add class-variance-authority
```

Библиотека одна и маленькая: она склеивает варианты класса, чтобы у кнопки не появилось три почти одинаковых компонента.

- [ ] **Step 2: Написать падающие тесты**

Создать `frontend/src/ui/Button.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Button } from "./Button";

describe("Button", () => {
  it("зовёт обработчик по нажатию", async () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Подтвердить</Button>);

    await userEvent.click(screen.getByRole("button", { name: "Подтвердить" }));

    expect(onClick).toHaveBeenCalledOnce();
  });

  it("не зовёт обработчик, пока отключена", async () => {
    // Отправка решения идёт секунды; повторное нажатие завело бы второе.
    const onClick = vi.fn();
    render(<Button onClick={onClick} disabled>Отправляем…</Button>);

    await userEvent.click(screen.getByRole("button", { name: "Отправляем…" }));

    expect(onClick).not.toHaveBeenCalled();
  });

  it("различает опасное действие видом", () => {
    // «Отклонить навсегда» необратимо, и выглядеть как «Передумал» не должно.
    render(<Button variant="danger">Отклонить навсегда</Button>);
    expect(screen.getByRole("button").className).toContain("text-red");
  });

  it("по умолчанию не отправляет форму", () => {
    // Кнопки живут внутри панели решений рядом с полями; type="submit" по
    // умолчанию отправлял бы форму при нажатии Enter в любом поле.
    render(<Button>Отмена</Button>);
    expect(screen.getByRole("button")).toHaveAttribute("type", "button");
  });
});
```

Создать `frontend/src/ui/Field.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Field, FieldLabel } from "./Field";

describe("Field", () => {
  it("передаёт введённое наружу", async () => {
    const onChange = vi.fn();
    render(<Field aria-label="Количество" value="" onChange={onChange} />);

    await userEvent.type(screen.getByLabelText("Количество"), "7");

    expect(onChange).toHaveBeenCalled();
  });

  it("связывает подпись с полем", () => {
    // Подпись рядом — не то же самое, что подпись, связанная с полем: по
    // несвязанной нельзя попасть в поле щелчком и её не читает экранный диктор.
    render(
      <>
        <FieldLabel htmlFor="quantity">Количество</FieldLabel>
        <Field id="quantity" value="" onChange={() => {}} />
      </>,
    );

    expect(screen.getByLabelText("Количество")).toBeInTheDocument();
  });

  it("держит числа табличными", () => {
    // Количество и цены набираются в поле и должны стоять в тех же колонках,
    // что и в таблице позиций.
    render(<Field aria-label="Цена" value="" onChange={() => {}} />);
    expect(screen.getByLabelText("Цена").className).toContain("tabular-nums");
  });
});
```

- [ ] **Step 3: Убедиться, что тесты падают**

Run: `cd frontend && pnpm exec vitest run src/ui/Button.test.tsx src/ui/Field.test.tsx`
Expected: FAIL — модули не найдены.

- [ ] **Step 4: Написать примитивы**

Создать `frontend/src/ui/Button.tsx`:

```tsx
import { cva, type VariantProps } from "class-variance-authority";
import type { ButtonHTMLAttributes } from "react";

/**
 * Кнопка интерфейса.
 *
 * До фазы 3 стилизована была ровно одна кнопка из одиннадцати — остальные
 * рисовались системными кнопками браузера. Варианты здесь не украшение:
 * необратимое действие («Отклонить навсегда») обязано отличаться от обычного.
 */
const button = cva(
  "rounded-md border px-3.5 py-[7px] text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-60",
  {
    variants: {
      variant: {
        primary: "border-line bg-blue/[0.14] text-blue hover:bg-blue/25",
        ghost: "border-line bg-transparent text-muted hover:text-tx",
        danger: "border-line bg-red/[0.12] text-red hover:bg-red/20",
      },
    },
    defaultVariants: { variant: "primary" },
  },
);

export function Button({ variant, className = "", type = "button", ...rest }:
  ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof button>) {
  // type="button" по умолчанию: кнопки стоят рядом с полями ввода, и submit по
  // умолчанию отправлял бы форму при нажатии Enter в любом из них.
  return <button type={type} className={`${button({ variant })} ${className}`} {...rest} />;
}
```

Создать `frontend/src/ui/Field.tsx`:

```tsx
import type { InputHTMLAttributes, LabelHTMLAttributes } from "react";

/**
 * Поле ввода. До фазы 3 стилей не имело ни одно из четырнадцати.
 *
 * tabular-nums здесь по той же причине, что и в таблице позиций: в полях
 * набираются количества и цены, и они должны стоять в тех же колонках.
 */
export function Field({ className = "", ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={`rounded-sm border border-line bg-bg1/60 px-2.5 py-1.5 text-sm text-tx tabular-nums outline-none focus:border-blue disabled:opacity-60 ${className}`}
      {...rest}
    />
  );
}

export function FieldLabel({ className = "", ...rest }: LabelHTMLAttributes<HTMLLabelElement>) {
  return <label className={`text-xs text-muted ${className}`} {...rest} />;
}
```

- [ ] **Step 5: Убедиться, что тесты проходят**

Run: `cd frontend && pnpm exec vitest run src/ui/`
Expected: PASS.

- [ ] **Step 6: Коммит**

```bash
git add frontend/src/ui/Button.tsx frontend/src/ui/Button.test.tsx frontend/src/ui/Field.tsx frontend/src/ui/Field.test.tsx frontend/package.json frontend/pnpm-lock.yaml
git commit -m "feat: примитивы Button и Field"
```

---

### Task 6: Badge и Table

**Files:**
- Create: `frontend/src/ui/Badge.tsx`, `frontend/src/ui/Table.tsx`
- Create: `frontend/src/ui/Table.test.tsx`

**Interfaces:**
- Consumes: ничего.
- Produces: `Badge({ tone?: "neutral" | "warning" | "danger", children })`; `Table({ children })`, `Th({ children, numeric? })`, `Td({ children, numeric? })`.

- [ ] **Step 1: Написать падающий тест**

Создать `frontend/src/ui/Table.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Badge } from "./Badge";
import { Table, Td, Th } from "./Table";

describe("Table", () => {
  it("держит числовые ячейки табличными и по правому краю", () => {
    // Иначе суммы дёргаются при обновлении котировок: у пропорционального
    // шрифта единица уже восьмёрки, и колонка «прыгает» на каждом тике.
    render(
      <Table>
        <tbody><tr><Td numeric>1 234 ₽</Td></tr></tbody>
      </Table>,
    );

    const cell = screen.getByText("1 234 ₽");
    expect(cell.className).toContain("tabular-nums");
    expect(cell.className).toContain("text-right");
  });

  it("не делает табличным текстовый столбец", () => {
    render(
      <Table>
        <tbody><tr><Td>Сбербанк</Td></tr></tbody>
      </Table>,
    );

    expect(screen.getByText("Сбербанк").className).not.toContain("text-right");
  });

  it("подписывает шапку приглушённым", () => {
    render(
      <Table>
        <thead><tr><Th>Бумага</Th></tr></thead>
      </Table>,
    );

    expect(screen.getByText("Бумага").className).toContain("text-muted");
  });
});

describe("Badge", () => {
  it("различает тревожную метку от обычной", () => {
    render(<Badge tone="danger">нет у брокера</Badge>);
    expect(screen.getByText("нет у брокера").className).toContain("text-red");
  });
});
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd frontend && pnpm exec vitest run src/ui/Table.test.tsx`
Expected: FAIL — модули не найдены.

- [ ] **Step 3: Написать примитивы**

Создать `frontend/src/ui/Table.tsx`:

```tsx
import type { ReactNode } from "react";

/**
 * Таблица интерфейса.
 *
 * Числовые ячейки помечаются явно (numeric): табличные цифры и правый край —
 * не украшение, а требование спеки. У пропорционального шрифта единица уже
 * восьмёрки, и колонка сумм дёргается при каждом обновлении котировок.
 */
export function Table({ children }: { children: ReactNode }) {
  return <table className="w-full border-collapse text-sm">{children}</table>;
}

export function Th({ children, numeric = false }: { children: ReactNode; numeric?: boolean }) {
  return (
    <th
      className={`border-b border-line px-2 py-2 font-normal text-xs text-muted ${
        numeric ? "text-right" : "text-left"
      }`}
    >
      {children}
    </th>
  );
}

export function Td({ children, numeric = false }: { children: ReactNode; numeric?: boolean }) {
  // Прозрачность через модификатор (border-line/60) здесь не сработает: токен
  // `line` записан как rgba(), а Tailwind умеет подмешивать альфу только к
  // цветам, заданным в формате с <alpha-value>. Рамка та же, что у шапки.
  return (
    <td className={`border-b border-line px-2 py-2 ${numeric ? "text-right tabular-nums" : ""}`}>
      {children}
    </td>
  );
}
```

Создать `frontend/src/ui/Badge.tsx`:

```tsx
import { cva, type VariantProps } from "class-variance-authority";
import type { ReactNode } from "react";

// Метка статуса: расхождение с брокером, блокировка, происхождение точки.
// Цвет здесь несёт смысл, поэтому вариантов ровно столько, сколько различий.
const badge = cva("inline-block rounded-sm px-1.5 py-0.5 text-2xs", {
  variants: {
    tone: {
      neutral: "bg-muted/15 text-muted",
      warning: "bg-amber/15 text-amber",
      danger: "bg-red/15 text-red",
    },
  },
  defaultVariants: { tone: "neutral" },
});

export function Badge({ tone, children }: { children: ReactNode } & VariantProps<typeof badge>) {
  return <span className={badge({ tone })}>{children}</span>;
}
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `cd frontend && pnpm exec vitest run src/ui/`
Expected: PASS.

- [ ] **Step 5: Коммит**

```bash
git add frontend/src/ui/Table.tsx frontend/src/ui/Badge.tsx frontend/src/ui/Table.test.tsx
git commit -m "feat: примитивы Table и Badge"
```

---

### Task 7: Состояния данных — AsOfLabel и CoverageNotice

Несвежесть в проекте двух разных сортов, и сливать их нельзя: возраст данных (`as_of`, `fx_as_of`) и охват оценки (`coverageWarning`). Первое живёт инлайном в шапке `PortfolioPage`, второе — внутри `SummaryCard` и потому недоступно другим экранам.

**Files:**
- Create: `frontend/src/components/AsOfLabel.tsx`, `frontend/src/components/AsOfLabel.test.tsx`
- Create: `frontend/src/components/CoverageNotice.tsx`
- Modify: `frontend/src/components/SummaryCard.tsx` (`CoverageNotice` уезжает)

**Interfaces:**
- Consumes: `formatDate` из `src/api/format.ts`; `coverageWarning` из `src/api/coverage.ts`; `Overview` из `src/api/client.ts`.
- Produces: `AsOfLabel({ asOf: string | null, fxAsOf: string | null })`; `CoverageNotice({ overview: Overview })`.

- [ ] **Step 1: Написать падающий тест**

Создать `frontend/src/components/AsOfLabel.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AsOfLabel } from "./AsOfLabel";

describe("AsOfLabel", () => {
  it("называет обе даты отдельно", () => {
    // Котировки и курсы обновляются с разной частотой, и одна дата на двоих
    // прикрывала бы недельные курсы сегодняшней ценой.
    render(<AsOfLabel asOf="2026-08-12" fxAsOf="2026-08-08" />);

    expect(screen.getByText(/данные на 12\.08\.2026/)).toBeInTheDocument();
    expect(screen.getByText(/курсы на 08\.08\.2026/)).toBeInTheDocument();
  });

  it("говорит о причине, когда даты нет", () => {
    render(<AsOfLabel asOf={null} fxAsOf={null} />);
    expect(screen.getByText(/нет котировок/)).toBeInTheDocument();
  });

  it("молчит о курсах, когда их не было в расчёте", () => {
    // У чисто рублёвого портфеля курсов в расчёте нет вовсе, и «курсы на —»
    // выглядело бы поломкой.
    render(<AsOfLabel asOf="2026-08-12" fxAsOf={null} />);
    expect(screen.queryByText(/курсы на/)).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd frontend && pnpm exec vitest run src/components/AsOfLabel.test.tsx`
Expected: FAIL — модуль не найден.

- [ ] **Step 3: Написать компоненты**

Создать `frontend/src/components/AsOfLabel.tsx`:

```tsx
import { formatDate } from "../api/format";

/**
 * Возраст данных: когда последний раз обновлялись котировки и курсы.
 *
 * Две даты, а не одна: котировки обновляются каждые пятнадцать минут, курсы —
 * раз в сутки, и общая дата прикрывала бы недельный курс сегодняшней ценой.
 */
export function AsOfLabel({ asOf, fxAsOf }: { asOf: string | null; fxAsOf: string | null }) {
  const priced = formatDate(asOf);
  const rated = formatDate(fxAsOf);

  return (
    <span className="text-xs text-muted">
      {priced ? `данные на ${priced}` : "данные ещё не рассчитаны — нет котировок"}
      {rated ? ` · курсы на ${rated}` : ""}
    </span>
  );
}
```

Создать `frontend/src/components/CoverageNotice.tsx` — перенести функцию `CoverageNotice` из `SummaryCard.tsx` (строки 47–79 текущего файла) без изменения текстов, заменив инлайновые стили на классы:

```tsx
import { coverageWarning } from "../api/coverage";
import type { Overview } from "../api/client";

/**
 * Охват оценки: какой частью портфеля посчитана главная цифра.
 *
 * Стоит вплотную к сумме и называет настоящую причину: нет котировок и нет
 * курсов — разные поломки, и чинятся они по-разному. Вынесено из SummaryCard:
 * то же предупреждение нужно на экране активов, а из чужого файла его не взять.
 */
export function CoverageNotice({ overview }: { overview: Overview }) {
  const warning = coverageWarning(overview);
  if (warning === null) return null;

  if (warning.kind === "rates") {
    return (
      <div className="mt-2.5 rounded-sm bg-red/[0.14] px-2.5 py-[7px] text-sm text-red">
        Нет курса к рублю: {warning.currencies.join(", ")}. Всё, что в этих валютах, в
        сумму не входит — ни бумаги, ни остатки, ни металлы. Курсы подтянутся сами
        (ЦБ, ежедневно в 12:10 МСК; металлы — с MOEX) или вручную — см. README,
        «Курсы, цены и оценка капитала». В рублях посчитаны {warning.valued} позиций
        из {warning.total}.
      </div>
    );
  }

  return (
    <div className="mt-2.5 rounded-sm bg-amber/[0.14] px-2.5 py-[7px] text-sm text-amber">
      Часть портфеля не оценена: цены есть только для {warning.valued} позиций из{" "}
      {warning.total}. Остальные в эту сумму не входят.
    </div>
  );
}
```

В `SummaryCard.tsx` удалить локальную функцию `CoverageNotice` и добавить импорт:

```tsx
import { CoverageNotice } from "./CoverageNotice";
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `cd frontend && pnpm exec vitest run`
Expected: PASS — ни один существующий тест не должен упасть: вынос не меняет ни текстов, ни условий.

- [ ] **Step 5: Коммит**

```bash
git add frontend/src/components/AsOfLabel.tsx frontend/src/components/AsOfLabel.test.tsx frontend/src/components/CoverageNotice.tsx frontend/src/components/SummaryCard.tsx
git commit -m "feat: компоненты возраста данных и охвата оценки"
```

---

### Task 8: Перевод карточек — SummaryCard и CashCard

Первая задача перевода. Дальше — тот же порядок для остальных файлов: снять скриншот «до», перевести, сравнить.

**Files:**
- Modify: `frontend/src/components/SummaryCard.tsx` (16 инлайновых стилей)
- Modify: `frontend/src/components/CashCard.tsx` (10 инлайновых стилей)
- Modify: `frontend/src/components/MoneyValue.tsx` (2 инлайновых стиля)

**Interfaces:**
- Consumes: `Card`, `CardTitle` (задача 3), `CardState` (задача 4), `Button` (задача 5), `CoverageNotice` (задача 7).
- Produces: ничего нового; сигнатуры компонентов не меняются.

- [ ] **Step 1: Снять скриншот «до»**

```bash
cd frontend && pnpm dev
```

Открыть `http://localhost:3000`, снять снимок области сводки капитала и денежных остатков. Composition не меняется — сравнение будет прямым.

- [ ] **Step 2: Перевести `MoneyValue`**

Инлайновые стили здесь только в `ChangeValue`. Знак передаётся стрелкой и цветом одновременно — это требование спеки, и оно сохраняется дословно:

```tsx
export function ChangeValue({ percent }: { percent: string | null }) {
  // Оценки нет — показываем прочерк, а не «• 0,0%»: нулевой результат и
  // отсутствие результата это разные вещи.
  if (percent === null) return <span className="text-muted">—</span>;

  const value = Number.parseFloat(percent);
  // Цвет и стрелка вместе: цвет в одиночку ничего не сообщает тому, кто его
  // не различает.
  const tone = value > 0 ? "text-green" : value < 0 ? "text-red" : "text-muted";
  const arrow = value > 0 ? "▲" : value < 0 ? "▼" : "•";
  return (
    <span className={tone}>
      {arrow} {formatPercent(percent)}
    </span>
  );
}
```

- [ ] **Step 3: Перевести `SummaryCard`**

Заменить обёртку `<div className="card">` на `<Card>`, подпись — на `<CardTitle>`, кнопку синхронизации — на `<Button>`:

```tsx
      <Button onClick={onSync} disabled={syncing} className="mt-3.5">
        {syncing ? "Синхронизируем…" : "Обновить из Т-Банка"}
      </Button>
```

Крупная цифра капитала: `style={{ fontSize: 34, fontWeight: 650, letterSpacing: "-0.025em", margin: "6px 0 0" }}` → `className="mt-1.5 text-hero font-[650] tracking-[-0.025em]"`.

Вспомогательные подписи (`CapitalParts`, `RestrictedNotice`): `style={{ margin: "10px 0 0", fontSize: 12.5, color: "var(--tx-2)" }}` → `className="mt-2.5 text-xs text-muted"`.

- [ ] **Step 4: Перевести `CashCard`**

Три ветки состояния заменяются на `CardState`:

```tsx
  if (error) return <CardState kind="error">{error}</CardState>;
  if (loading) return <CardState kind="loading">Загрузка остатков…</CardState>;
  if (rows.length === 0) {
    return (
      <Card>
        <CardTitle>Денежные остатки</CardTitle>
        <div className="text-sm text-muted">Остатков нет. Они появятся после синхронизации.</div>
      </Card>
    );
  }
```

Строку остатка: `style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}` → `className="flex justify-between text-sm"`; замок `style={{ color: "var(--amber)", marginLeft: 4 }}` → `className="ml-1 text-amber"`.

- [ ] **Step 5: Убедиться, что тесты и типы проходят**

```bash
cd frontend
pnpm exec vitest run
pnpm run build
pnpm check:styles
```

Expected: тесты PASS, сборка чистая, счётчик инлайновых стилей уменьшился на 28 (16 + 10 + 2).

- [ ] **Step 6: Сравнить скриншот**

Снять снимок тех же блоков и сравнить с шагом 1. **Расхождение — дефект перевода, а не улучшение.** Если вид разошёлся, остановиться и починить, а не идти дальше.

- [ ] **Step 7: Коммит**

```bash
git add frontend/src/components/SummaryCard.tsx frontend/src/components/CashCard.tsx frontend/src/components/MoneyValue.tsx
git commit -m "refactor: сводка капитала и остатки на примитивах"
```

---

### Task 9: Перевод графиков — ValueChart и AllocationChart

Единственные два файла, где инлайновые стили остаются законно: ECharts настраивается объектом. Но цвета в них обязаны приехать из токенов — сейчас там 18 hex-литералов, включая два расходящихся с палитрой.

**Files:**
- Modify: `frontend/src/components/ValueChart.tsx` (6 инлайновых стилей, 5 hex)
- Modify: `frontend/src/components/AllocationChart.tsx` (3 инлайновых стиля, 13 hex)

**Interfaces:**
- Consumes: `tokens` (задача 1), `Card`, `CardTitle`, `CardState`.
- Produces: ничего нового.

- [ ] **Step 1: Снять скриншот «до»**

Снять снимок графика стоимости и структуры портфеля. **Ожидается расхождение**: жёлтые треугольники неполноты и синяя линия слегка изменят оттенок (`#e2b93b` → `#e8b04b`, `#638cff` → `#7b9cff`). Это исправление, названное в дизайне; показать владельцу отдельно.

- [ ] **Step 2: Перевести `ValueChart`**

Заменить обёртки состояний на `CardState`, подложку — на `Card` и `CardTitle`, а цвета — на токены:

```tsx
import { tokens } from "../design/tokens";

  if (error) {
    return <CardState kind="error">Не удалось загрузить историю стоимости: {error}</CardState>;
  }
  if (loading) return <CardState kind="loading">Загрузка истории…</CardState>;
  if (points.length === 0) {
    return (
      <CardState kind="empty">
        Истории пока нет: достройте её прогоном app.snapshots.backfill.
      </CardState>
    );
  }
```

В конфигурации графика: `"#3a4763"` → `tokens.chart.axis`, `"#1c2438"` → `tokens.chart.grid`, `"#9aa5c4"` → `tokens.chart.label`, `"#638cff"` → `tokens.chart.line`, `"rgba(99,140,255,0.18)"` → `tokens.chart.area`, `"#e2b93b"` → `tokens.chart.incomplete`.

Подпись под графиком: `style={{ color: "var(--tx-2)", fontSize: 12, marginTop: 8 }}` → `className="mt-2 text-xs text-muted"`.

- [ ] **Step 3: Перевести `AllocationChart`**

Локальную константу `COLORS` удалить целиком и заменить обращением к токенам:

```tsx
import { tokens } from "../design/tokens";

    itemStyle: { color: tokens.assetClass[key as keyof typeof tokens.assetClass] },
```

`legend: { bottom: 0, textStyle: { color: "#9aa5c4" } }` → `tokens.chart.label`; `borderColor: "#0f1424"` → `tokens.chart.pieBorder`.

Пустое состояние — на `CardState kind="empty"`, подложку — на `Card` с `CardTitle`.

- [ ] **Step 4: Убедиться, что тесты, типы и счётчик в порядке**

```bash
cd frontend
pnpm exec vitest run
pnpm run build
pnpm check:styles
```

Expected: тесты PASS (`ValueChart.test.tsx` — шесть тестов из фазы 2c), **`Hex-литералов вне tokens.ts: 0`**.

- [ ] **Step 5: Показать владельцу изменившийся оттенок**

Снять снимок графиков и показать рядом со снимком шага 1: это единственное место фазы, где вид меняется намеренно.

- [ ] **Step 6: Коммит**

```bash
git add frontend/src/components/ValueChart.tsx frontend/src/components/AllocationChart.tsx
git commit -m "refactor: графики берут цвета из токенов"
```

---

### Task 10: Перевод таблицы и баннера

**Files:**
- Modify: `frontend/src/components/PositionsTable.tsx` (18 инлайновых стилей)
- Modify: `frontend/src/components/ReconciliationBanner.tsx` (21 инлайновый стиль)

**Interfaces:**
- Consumes: `Card`, `CardTitle`, `CardState`, `Table`, `Th`, `Td`, `Badge`, `Button`.
- Produces: ничего нового.

- [ ] **Step 1: Снять скриншот «до»**

Снять снимок таблицы позиций и баннера расхождений. В баннере раскрыть подробности — состояние «развёрнут» тоже надо сравнить.

- [ ] **Step 2: Перевести `PositionsTable`**

Ветки состояний — на `CardState`; разметку таблицы — на `Table`/`Th`/`Td`. Числовые колонки (количество, средняя, текущая, стоимость, результат) помечаются `numeric`:

```tsx
        <Th>Бумага</Th>
        <Th>Счёт</Th>
        <Th>Валюта</Th>
        <Th numeric>Количество</Th>
        <Th numeric>Средняя</Th>
        <Th numeric>Текущая</Th>
        <Th numeric>Стоимость</Th>
        <Th numeric>Результат</Th>
```

Инлайновый `fontVariantNumeric: "tabular-nums"` при этом уходит: он теперь в `Td numeric`.

- [ ] **Step 3: Перевести `ReconciliationBanner`**

Метки статусов расхождения — на `Badge` (`quantity_mismatch` → `tone="warning"`, `missing_at_broker` и `missing_in_ledger` → `tone="danger"`), кнопку раскрытия — на `Button variant="ghost"`, подложку — на `Card`.

- [ ] **Step 4: Убедиться, что тесты и типы проходят**

```bash
cd frontend
pnpm exec vitest run
pnpm run build
pnpm check:styles
```

Expected: PASS, включая `ReconciliationBanner.test.tsx` (130 строк тестов из фазы 2b); счётчик уменьшился на 39.

- [ ] **Step 5: Сравнить скриншот**

Свёрнутый и развёрнутый вид баннера, таблица целиком. Расхождение — дефект.

- [ ] **Step 6: Коммит**

```bash
git add frontend/src/components/PositionsTable.tsx frontend/src/components/ReconciliationBanner.tsx
git commit -m "refactor: таблица позиций и баннер расхождений на примитивах"
```

---

### Task 11: Перевод панели решений

Самый большой файл фронта: 369 строк и 42 инлайновых стиля из 127. Здесь же десять кнопок и четырнадцать полей, у которых стиля нет вовсе, — панель заметно изменится, и это ожидаемый исход.

**Files:**
- Modify: `frontend/src/components/DecisionPanel.tsx`

**Interfaces:**
- Consumes: `Card`, `CardTitle`, `CardState`, `Button`, `Field`, `FieldLabel`.
- Produces: ничего нового.

- [ ] **Step 1: Снять скриншот «до»**

Панель решений появляется на экране, когда есть неразобранные расхождения; у владельца их девять. Снять снимок в двух состояниях: список предложений и форма ручного ввода.

- [ ] **Step 2: Перевести разметку**

Пройти файл сверху вниз, заменяя:

- `<div className="card">` → `<Card>`;
- подписи `style={{ color: "var(--tx-2)", fontSize: 12 }}` → `<CardTitle>` либо `className="text-xs text-muted"`;
- `<button …>` → `<Button>`, где «Отклонить навсегда» получает `variant="danger"`, «Передумал» и «Отмена» — `variant="ghost"`, остальные остаются `primary`;
- `<input …>` → `<Field>` с `<FieldLabel htmlFor>`; радиокнопки выбора предложения остаются обычными `<input type="radio">` — это не поле ввода, а выбор, и `Field` к ним не применяется, только инлайновый `marginRight: 6` заменяется на `className="mr-1.5"`.

- [ ] **Step 3: Убедиться, что тесты проходят**

Run: `cd frontend && pnpm exec vitest run src/components/DecisionPanel.test.tsx`
Expected: PASS, все тесты файла (312 строк из фазы 2b). Тест ищет кнопки по доступному имени (`getByRole("button", { name: … })`), поэтому замена тега на `Button` его не ломает. Если тест падает на поиске поля — добавить полю `aria-label` с тем же текстом, что был у подписи рядом, а не менять тест.

- [ ] **Step 4: Проверить типы и счётчик**

```bash
cd frontend
pnpm run build
pnpm check:styles
```

Expected: **`Инлайновых style вне графиков: 9`** — останутся только стили `PortfolioPage`, их снимет задача 13.

- [ ] **Step 5: Показать владельцу новый вид панели**

Скриншотного сравнения здесь нет: до фазы кнопки и поля были системными. Показать, как выглядит панель теперь.

- [ ] **Step 6: Коммит**

```bash
git add frontend/src/components/DecisionPanel.tsx
git commit -m "refactor: панель решений на примитивах"
```

---

### Task 12: Регулятор анимаций

**Files:**
- Create: `frontend/src/design/animation.tsx`, `frontend/src/design/animation.test.tsx`

**Interfaces:**
- Consumes: ничего.
- Produces: `AnimationProvider({ children })`; `useAnimationMode(): { mode, setMode, systemPrefersReduced }`; `useAnimatedNumber(target: number): number`; тип `AnimationMode = "off" | "calm" | "expressive"`; константа `ANIMATION_STORAGE_KEY = "jarvis.animation"`.

- [ ] **Step 1: Написать падающий тест**

Создать `frontend/src/design/animation.test.tsx`:

```tsx
import { act, render, renderHook, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ANIMATION_STORAGE_KEY,
  AnimationProvider,
  useAnimatedNumber,
  useAnimationMode,
} from "./animation";

function mockReducedMotion(matches: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches, media: query, onchange: null,
    addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
    addListener: vi.fn(), removeListener: vi.fn(),
  }));
}

afterEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
});

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <AnimationProvider>{children}</AnimationProvider>
);

describe("режим анимаций", () => {
  it("по умолчанию сдержанный", () => {
    mockReducedMotion(false);
    const { result } = renderHook(() => useAnimationMode(), { wrapper });
    expect(result.current.mode).toBe("calm");
  });

  it("выключен по умолчанию, когда система просит меньше движения", () => {
    mockReducedMotion(true);
    const { result } = renderHook(() => useAnimationMode(), { wrapper });
    expect(result.current.mode).toBe("off");
    expect(result.current.systemPrefersReduced).toBe(true);
  });

  it("выбор владельца перебивает системную настройку", () => {
    // Пользователь один, и он видит переключатель. Переключатель, который не
    // работает, хуже отсутствующего.
    mockReducedMotion(true);
    localStorage.setItem(ANIMATION_STORAGE_KEY, "expressive");

    const { result } = renderHook(() => useAnimationMode(), { wrapper });

    expect(result.current.mode).toBe("expressive");
  });

  it("запоминает выбор между запусками", () => {
    mockReducedMotion(false);
    const { result } = renderHook(() => useAnimationMode(), { wrapper });

    act(() => result.current.setMode("off"));

    expect(localStorage.getItem(ANIMATION_STORAGE_KEY)).toBe("off");
  });
});

function Counter({ value }: { value: number }) {
  return <span>{useAnimatedNumber(value)}</span>;
}

describe("перетекание числа", () => {
  it("при выключенных анимациях ставит значение сразу", () => {
    // Иначе тесты начнут ждать анимацию, а владелец с prefers-reduced-motion
    // увидит ползущую цифру там, где просил её не двигать.
    mockReducedMotion(true);

    render(<AnimationProvider><Counter value={11051805} /></AnimationProvider>);

    expect(screen.getByText("11051805")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd frontend && pnpm exec vitest run src/design/animation.test.tsx`
Expected: FAIL — модуль не найден.

- [ ] **Step 3: Написать модуль**

Создать `frontend/src/design/animation.tsx`:

```tsx
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";

export type AnimationMode = "off" | "calm" | "expressive";

export const ANIMATION_STORAGE_KEY = "jarvis.animation";

// Длительность перетекания числа, мс. Ноль — значение ставится сразу.
const DURATION: Record<AnimationMode, number> = { off: 0, calm: 400, expressive: 900 };

function systemReduced(): boolean {
  return typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function initialMode(): AnimationMode {
  const stored = localStorage.getItem(ANIMATION_STORAGE_KEY) as AnimationMode | null;
  // Явный выбор владельца перебивает системную настройку: пользователь один, и
  // переключатель, который не работает, хуже отсутствующего. Системная
  // настройка задаёт умолчание — и об этом сказано на экране настроек.
  if (stored === "off" || stored === "calm" || stored === "expressive") return stored;
  return systemReduced() ? "off" : "calm";
}

const AnimationContext = createContext<{
  mode: AnimationMode;
  setMode: (mode: AnimationMode) => void;
  systemPrefersReduced: boolean;
} | null>(null);

export function AnimationProvider({ children }: { children: ReactNode }) {
  const [mode, setStoredMode] = useState<AnimationMode>(initialMode);

  const setMode = (next: AnimationMode) => {
    localStorage.setItem(ANIMATION_STORAGE_KEY, next);
    setStoredMode(next);
  };

  return (
    <AnimationContext.Provider value={{ mode, setMode, systemPrefersReduced: systemReduced() }}>
      {children}
    </AnimationContext.Provider>
  );
}

export function useAnimationMode() {
  const value = useContext(AnimationContext);
  if (value === null) throw new Error("useAnimationMode вне AnimationProvider");
  return value;
}

/**
 * Число, перетекающее к новому значению.
 *
 * Библиотека анимаций для этого не нужна: перетекание одно на весь интерфейс,
 * и оно выражается счётчиком на requestAnimationFrame. Появится морфинг линии
 * графика и выезд панели чата — появится и основание для зависимости.
 */
export function useAnimatedNumber(target: number): number {
  const { mode } = useAnimationMode();
  const [value, setValue] = useState(target);
  const from = useRef(target);

  useEffect(() => {
    const duration = DURATION[mode];
    if (duration === 0) {
      from.current = target;
      setValue(target);
      return;
    }

    const start = performance.now();
    const origin = from.current;
    let frame = 0;

    const step = (now: number) => {
      const passed = Math.min((now - start) / duration, 1);
      // Замедление к концу: значение приезжает мягко, а не втыкается.
      const eased = 1 - (1 - passed) ** 3;
      setValue(origin + (target - origin) * eased);
      if (passed < 1) frame = requestAnimationFrame(step);
      else from.current = target;
    };

    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [target, mode]);

  return value;
}
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `cd frontend && pnpm exec vitest run src/design/animation.test.tsx`
Expected: PASS, пять тестов.

- [ ] **Step 5: Подключить перетекание к цифре капитала**

Хук, который никто не зовёт, проверен ровно настолько, насколько его тест похож на боевой вызов, — урок фазы 2c, где так пролежал `close_history`. Единственная анимация фазы подключается здесь же.

В `frontend/src/components/SummaryCard.tsx` заменить показ главной цифры:

```tsx
import { useAnimatedNumber } from "../design/animation";

// Капитал приходит строкой и строкой же форматируется — число здесь живёт
// только внутри анимации. Четыре знака после точки сохраняются, чтобы
// formatMoney получил ровно то же значение, что и без анимации.
function AnimatedTotal({ amount }: { amount: string }) {
  const value = useAnimatedNumber(Number.parseFloat(amount));
  return <MoneyValue amount={value.toFixed(4)} currency={BASE_CURRENCY} />;
}
```

и в разметке карточки `<MoneyValue amount={overview.total_value} …>` → `<AnimatedTotal amount={overview.total_value} />`.

Дописать в `frontend/src/design/animation.test.tsx`:

```tsx
it("доводит число до конечного значения, а не останавливается на полпути", async () => {
  // Анимация обязана заканчиваться ровно на цели: цифра капитала, замершая
  // на 11 049 000 вместо 11 051 805, выглядит как настоящая.
  mockReducedMotion(false);

  const { rerender } = render(
    <AnimationProvider><Counter value={0} /></AnimationProvider>,
  );
  rerender(<AnimationProvider><Counter value={100} /></AnimationProvider>);

  await waitFor(() => expect(screen.getByText("100")).toBeInTheDocument());
});
```

Добавить `waitFor` в импорт из `@testing-library/react`.

- [ ] **Step 6: Убедиться, что тесты проходят**

```bash
cd frontend
pnpm exec vitest run
pnpm run build
```

Expected: PASS. Тесты `SummaryCard` (если есть) продолжают находить сумму: при выключенных анимациях значение ставится сразу, а в тестовой среде `matchMedia` не определён — `systemReduced()` вернёт `false`, поэтому режим будет «сдержанный». Если тест сводки начнёт мигать из-за анимации, добавить в `src/setupTests.ts` заглушку `matchMedia`, возвращающую `matches: true`: тесты не должны ждать анимацию.

- [ ] **Step 7: Коммит**

```bash
git add frontend/src/design/animation.tsx frontend/src/design/animation.test.tsx frontend/src/components/SummaryCard.tsx frontend/src/setupTests.ts
git commit -m "feat: режим анимаций и перетекание цифры капитала"
```

---

### Task 13: Навигация, каркас и четыре экрана

Здесь композиция меняется намеренно: блоки разъезжаются по экранам. Скриншотное сравнение с этого шага не применяется — сравнивать нечего.

**Files:**
- Create: `frontend/src/app/routes.tsx`, `frontend/src/app/AppShell.tsx`, `frontend/src/app/AppShell.test.tsx`
- Create: `frontend/src/pages/AssetsPage.tsx`, `frontend/src/pages/TradesPage.tsx`, `frontend/src/pages/SettingsPage.tsx`
- Modify: `frontend/src/App.tsx`, `frontend/src/pages/PortfolioPage.tsx`
- Modify: `frontend/package.json` (`react-router`)

**Interfaces:**
- Consumes: `AsOfLabel`, `CoverageNotice`, все примитивы, `AnimationProvider` и `useAnimationMode` (задача 12).
- Produces: `NAV_ITEMS: { path: string; title: string; group: string }[]`; `AppShell({ children })`.

- [ ] **Step 1: Поставить роутер**

```bash
cd frontend && pnpm add react-router
```

- [ ] **Step 2: Написать падающий тест**

Создать `frontend/src/app/AppShell.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { describe, expect, it } from "vitest";

import { AppShell } from "./AppShell";
import { NAV_ITEMS } from "./routes";

function renderShell(initial = "/") {
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <AppShell>
        <Routes>
          <Route path="/" element={<div>содержимое портфеля</div>} />
          <Route path="/assets" element={<div>содержимое активов</div>} />
        </Routes>
      </AppShell>
    </MemoryRouter>,
  );
}

describe("AppShell", () => {
  it("показывает содержимое текущего экрана", () => {
    renderShell();
    expect(screen.getByText("содержимое портфеля")).toBeInTheDocument();
  });

  it("переводит на другой экран по ссылке", async () => {
    renderShell();

    await userEvent.click(screen.getByRole("link", { name: "Активы" }));

    expect(screen.getByText("содержимое активов")).toBeInTheDocument();
  });

  it("отмечает текущий пункт меню", async () => {
    // Иначе на четырёх экранах непонятно, где находишься.
    renderShell("/assets");
    expect(screen.getByRole("link", { name: "Активы" })).toHaveAttribute("aria-current", "page");
  });

  it("не показывает пункты экранов, которых ещё нет", () => {
    // Пункт, ведущий в пустоту, — обещание, которого система не выполняет.
    // Порядок и группировка восьми экранов решены в дизайне, но в меню
    // попадают только те, что есть чем наполнить.
    renderShell();

    expect(NAV_ITEMS.map((item) => item.title)).toEqual([
      "Портфель", "Активы", "Сделки и расхождения", "Настройки",
    ]);
    expect(screen.queryByRole("link", { name: "Налоги" })).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Убедиться, что тест падает**

Run: `cd frontend && pnpm exec vitest run src/app/AppShell.test.tsx`
Expected: FAIL — модули не найдены.

- [ ] **Step 4: Написать маршруты и каркас**

Создать `frontend/src/app/routes.tsx`:

```tsx
/**
 * Экраны и их порядок.
 *
 * Группа — это ответ на вопрос владельца, а не тип сущности: «сколько у меня»,
 * «что происходило», «что из этого следует», «на что смотреть». Порядок всех
 * восьми экранов решён в дизайне фазы 3, но в меню попадают только те, что уже
 * есть чем наполнить: пункт, ведущий в пустоту, — обещание, которого система
 * не выполняет. Календарь выплат, Аналитика и Налоги приедут в фазе 4,
 * События — в фазе 7.
 */
export const NAV_ITEMS = [
  { path: "/", title: "Портфель", group: "Капитал" },
  { path: "/assets", title: "Активы", group: "Капитал" },
  { path: "/trades", title: "Сделки и расхождения", group: "Движение" },
  { path: "/settings", title: "Настройки", group: "" },
];
```

Создать `frontend/src/app/AppShell.tsx`:

```tsx
import type { ReactNode } from "react";
import { NavLink, useLocation } from "react-router";

import { NAV_ITEMS } from "./routes";

/**
 * Каркас приложения: слева навигация, сверху заголовок экрана, в центре
 * содержимое.
 *
 * Боковая колонка, а не верхние вкладки: спека обещает восемь экранов и
 * выдвижную панель чата справа, и восемь вкладок переполнили бы строку ровно
 * тогда, когда появится содержание.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  const current = NAV_ITEMS.find((item) => item.path === pathname);

  return (
    <div className="mx-auto flex max-w-[1240px] gap-6 px-6 py-8">
      <nav className="w-[190px] shrink-0">
        <div className="mb-6 text-title font-[640]">Джарвис</div>
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.path === "/"}
            className={({ isActive }) =>
              `mb-1 block rounded-sm px-2.5 py-1.5 text-sm ${
                isActive ? "bg-blue/[0.14] text-blue" : "text-muted hover:text-tx"
              }`
            }
          >
            {item.title}
          </NavLink>
        ))}
      </nav>

      <main className="min-w-0 flex-1">
        <h1 className="mb-4 text-title font-[640]">{current?.title ?? ""}</h1>
        {children}
      </main>
    </div>
  );
}
```

- [ ] **Step 5: Разнести блоки по экранам**

`PortfolioPage` оставляет себе сводку капитала, график, структуру и остатки; шапку с датами заменяет `AsOfLabel`, а баннер расхождений становится свёрнутой строкой со ссылкой:

```tsx
      <Card>
        <div className="flex items-center justify-between text-sm">
          <span>Расхождения с данными брокера: {reconciliations.data?.length ?? 0}</span>
          <Link to="/trades" className="text-blue">разобрать</Link>
        </div>
      </Card>
```

Создать `frontend/src/pages/AssetsPage.tsx` — таблица позиций целиком:

```tsx
import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import { PositionsTable } from "../components/PositionsTable";

export function AssetsPage() {
  const positions = useQuery({ queryKey: ["positions"], queryFn: api.positions });

  return (
    <PositionsTable
      rows={positions.data ?? []}
      error={positions.isError ? (positions.error as Error).message : null}
      loading={positions.isPending}
    />
  );
}
```

Создать `frontend/src/pages/TradesPage.tsx`:

```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import { ReconciliationBanner } from "../components/ReconciliationBanner";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";

export function TradesPage() {
  const queryClient = useQueryClient();
  const reconciliations = useQuery({
    queryKey: ["reconciliations"],
    queryFn: api.reconciliations,
  });

  // Синхронизация переехала сюда со сводки капитала: она про движение данных,
  // а не про их итог, и её место рядом с расхождениями, которые она порождает.
  const sync = useMutation({
    mutationFn: api.syncTbank,
    onSuccess: () => queryClient.invalidateQueries(),
  });

  return (
    <div className="grid gap-3.5">
      <Card>
        <Button onClick={() => sync.mutate()} disabled={sync.isPending}>
          {sync.isPending ? "Синхронизируем…" : "Обновить из Т-Банка"}
        </Button>
        {sync.isError && (
          <div className="mt-2 text-sm text-red">{(sync.error as Error).message}</div>
        )}
      </Card>

      <ReconciliationBanner
        rows={reconciliations.data ?? []}
        error={reconciliations.isError ? (reconciliations.error as Error).message : null}
      />
    </div>
  );
}
```

Панель решений отдельно на экране не монтируется: `ReconciliationBanner` открывает её сам для выбранной строки расхождения (`<DecisionPanel row={row} onDone={…} />`, строка 93). Устройство этой связи в задаче не меняется — это отдельная работа.

Создать `frontend/src/pages/SettingsPage.tsx` — регулятор анимаций:

```tsx
import { useAnimationMode, type AnimationMode } from "../design/animation";
import { Card, CardTitle } from "../ui/Card";
import { SegmentedControl } from "../ui/SegmentedControl";

const MODES: { value: AnimationMode; label: string }[] = [
  { value: "off", label: "Выключены" },
  { value: "calm", label: "Сдержанные" },
  { value: "expressive", label: "Выразительные" },
];

export function SettingsPage() {
  const { mode, setMode, systemPrefersReduced } = useAnimationMode();

  return (
    <Card>
      <CardTitle>Анимации</CardTitle>
      <SegmentedControl options={MODES} value={mode} onChange={setMode} />
      {systemPrefersReduced && (
        <div className="mt-2 text-xs text-muted">
          Система просит уменьшить движение — по умолчанию анимации выключены.
          Выбор здесь эту настройку перебивает.
        </div>
      )}
    </Card>
  );
}
```

**Порядок задач:** `SegmentedControl` создаётся задачей 14. Чтобы экран настроек не остался сломанным, задача 14 идёт сразу за этой; если исполнитель работает по одной задаче с проверкой между ними, `SettingsPage` временно использует три `Button` с тем же поведением, а задача 14 заменяет их на `SegmentedControl`.

- [ ] **Step 6: Подключить роутер**

Заменить `frontend/src/App.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router";

import { AppShell } from "./app/AppShell";
import { AnimationProvider } from "./design/animation";
import { AssetsPage } from "./pages/AssetsPage";
import { PortfolioPage } from "./pages/PortfolioPage";
import { SettingsPage } from "./pages/SettingsPage";
import { TradesPage } from "./pages/TradesPage";

const queryClient = new QueryClient();

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AnimationProvider>
        <BrowserRouter>
          <AppShell>
            <Routes>
              <Route path="/" element={<PortfolioPage />} />
              <Route path="/assets" element={<AssetsPage />} />
              <Route path="/trades" element={<TradesPage />} />
              <Route path="/settings" element={<SettingsPage />} />
            </Routes>
          </AppShell>
        </BrowserRouter>
      </AnimationProvider>
    </QueryClientProvider>
  );
}
```

- [ ] **Step 7: Убедиться, что тесты и типы проходят**

```bash
cd frontend
pnpm exec vitest run
pnpm run build
pnpm check:styles
```

Expected: PASS; **`Инлайновых style вне графиков: 0`**.

- [ ] **Step 8: Посмотреть глазами**

Открыть все четыре адреса, проверить: переход по меню работает, F5 оставляет на том же экране, текущий пункт подсвечен, баннер на портфеле свёрнут и ведёт на `/trades`.

- [ ] **Step 9: Коммит**

```bash
git add frontend/src/app frontend/src/pages frontend/src/App.tsx frontend/package.json frontend/pnpm-lock.yaml
git commit -m "feat: навигация по четырём экранам"
```

---

### Task 14: Переключатель периода графика

После достройки истории график рисует 2219 точек одной линией — отдельный год в ней не разглядеть. Бэкенд уже умеет отдавать окно: `GET /api/portfolio/history?days=N`.

**Files:**
- Create: `frontend/src/ui/SegmentedControl.tsx`, `frontend/src/ui/SegmentedControl.test.tsx`
- Modify: `frontend/src/pages/PortfolioPage.tsx`, `frontend/src/pages/SettingsPage.tsx`

**Interfaces:**
- Consumes: `api.history(days?: number)` из `src/api/client.ts`.
- Produces: `SegmentedControl<T>({ options: { value: T; label: string }[], value: T, onChange: (value: T) => void })`.

- [ ] **Step 1: Написать падающий тест**

Создать `frontend/src/ui/SegmentedControl.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SegmentedControl } from "./SegmentedControl";

const OPTIONS = [
  { value: 30, label: "Месяц" },
  { value: 365, label: "Год" },
  { value: 0, label: "Всё время" },
];

describe("SegmentedControl", () => {
  it("сообщает выбранное значение", async () => {
    const onChange = vi.fn();
    render(<SegmentedControl options={OPTIONS} value={365} onChange={onChange} />);

    await userEvent.click(screen.getByRole("radio", { name: "Месяц" }));

    expect(onChange).toHaveBeenCalledWith(30);
  });

  it("помечает текущий выбор для чтения с экрана", () => {
    render(<SegmentedControl options={OPTIONS} value={365} onChange={() => {}} />);
    expect(screen.getByRole("radio", { name: "Год" })).toBeChecked();
  });
});
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd frontend && pnpm exec vitest run src/ui/SegmentedControl.test.tsx`
Expected: FAIL — модуль не найден.

- [ ] **Step 3: Написать примитив**

Создать `frontend/src/ui/SegmentedControl.tsx`:

```tsx
/**
 * Группа взаимоисключающих переключателей.
 *
 * Под капотом радиокнопки, а не кнопки: выбор одного из нескольких — это и
 * есть радиогруппа, и клавиатура со экранным диктором работают с ней сами.
 */
export function SegmentedControl<T extends string | number>({ options, value, onChange, name = "segmented" }: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
  name?: string;
}) {
  return (
    <div role="radiogroup" className="inline-flex gap-1 rounded-md border border-line p-0.5">
      {options.map((option) => (
        <label
          key={String(option.value)}
          className={`cursor-pointer rounded-sm px-2.5 py-1 text-xs ${
            option.value === value ? "bg-blue/[0.14] text-blue" : "text-muted hover:text-tx"
          }`}
        >
          <input
            type="radio"
            name={name}
            className="sr-only"
            checked={option.value === value}
            onChange={() => onChange(option.value)}
          />
          {option.label}
        </label>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Подключить к графику**

В `PortfolioPage` период становится состоянием экрана (в адрес не уносится — это не место, а взгляд на него):

```tsx
const PERIODS = [
  { value: 30, label: "Месяц" },
  { value: 365, label: "Год" },
  { value: 0, label: "Всё время" },
];

  const [days, setDays] = useState(0);
  // 0 — «всё время»: бэкенд без параметра days отдаёт весь период (фаза 2c).
  const history = useQuery({
    queryKey: ["history", days],
    queryFn: () => api.history(days || undefined),
  });
```

Переключатель ставится в шапку карточки графика, рядом с подписью «Стоимость портфеля». Для этого `ValueChart` принимает необязательный `action?: ReactNode` и рисует его справа от `CardTitle`.

- [ ] **Step 5: Заменить временные кнопки в настройках**

Если задача 13 оставила на экране настроек три `Button`, заменить их на `SegmentedControl`, как показано в её шаге 5.

- [ ] **Step 6: Убедиться, что тесты и типы проходят**

```bash
cd frontend
pnpm exec vitest run
pnpm run build
```

Expected: PASS.

- [ ] **Step 7: Посмотреть глазами**

Открыть портфель, переключить период: «Месяц» показывает последние 30 дней, «Всё время» — историю с 2020 года.

- [ ] **Step 8: Коммит**

```bash
git add frontend/src/ui/SegmentedControl.tsx frontend/src/ui/SegmentedControl.test.tsx frontend/src/pages/PortfolioPage.tsx frontend/src/pages/SettingsPage.tsx frontend/src/components/ValueChart.tsx
git commit -m "feat: переключатель периода на графике стоимости"
```

---

### Task 15: Признак готовности и документация

Здесь фаза либо закрывается, либо нет.

**Files:**
- Modify: `frontend/package.json` (строгий режим счётчика в проверках)
- Modify: `frontend/tailwind.config.js` (убрать временные алиасы переменных)
- Modify: `README.md`, `docs/roadmap.md`

- [ ] **Step 1: Убрать временные алиасы**

Из плагина в `tailwind.config.js` удалить `--tx-2`, `--bg-0`, `--bg-1`, добавленные задачей 1. Если после этого что-то в интерфейсе теряет цвет — значит, файл с обращением к старому имени пропущен при переводе; найти его и починить:

```bash
cd frontend && rg -n 'var\(--tx-2|var\(--bg-0|var\(--bg-1' src
```

Expected: пусто.

- [ ] **Step 2: Включить строгую проверку**

Run: `cd frontend && pnpm check:styles --strict`
Expected: `Инлайновых style вне графиков: 0`, `Hex-литералов вне tokens.ts: 0`, выход `0`.

Если счётчик ненулевой — **остановиться и закрыть остаток**, а не смягчать проверку.

- [ ] **Step 3: Прогнать всё**

```bash
cd frontend
pnpm exec vitest run
pnpm run build
cd ../backend && uv run pytest -q
```

Expected: фронт и бэкенд зелёные. Бэкенд не менялся — прогон подтверждает это, а не проверяет.

- [ ] **Step 4: Собрать новый экран на время, чтобы проверить признак**

Признак готовности роадмепа — «новый экран собирается из готовых компонентов, без изобретения отступов и цветов». Проверяется буквально: собрать черновой экран из `Card`, `CardTitle`, `Table`, `Badge`, `Button` **без единого инлайнового стиля**, убедиться, что он выглядит своим, и удалить его. В коммит он не идёт; в отчёте — сказать, получилось ли и чего не хватило.

- [ ] **Step 5: Обновить README**

В `README.md` добавить раздел о дизайн-системе: где живут токены, почему источник в TypeScript, что проверяет `pnpm check:styles`, какие примитивы есть и куда класть новые.

- [ ] **Step 6: Обновить роадмеп**

В `docs/roadmap.md`: в разделе фазы 3 дописать «завершена <дата>» и «как закрылось» с числами (было 127 инлайновых стилей и 18 hex-литералов, стало 0 и 0); в таблице «Статус» сменить состояние фазы 3 и назвать следующей фазу 4; в разделе «Где мы сейчас» заменить описание интерфейса.

- [ ] **Step 7: Коммит**

```bash
git add frontend/tailwind.config.js frontend/package.json README.md docs/roadmap.md
git commit -m "docs: итоги фазы 3"
```

---

## Самопроверка плана

**Покрытие дизайна.** Раздел 3 (токены) — задача 1. Раздел 4 (примитивы) — задачи 3, 5, 6 и 14 (`SegmentedControl`). Раздел 5 (состояния данных) — задачи 4 и 7. Раздел 6 (навигация и каркас) — задача 13. Раздел 7 (регулятор анимаций) — задача 12. Раздел 8 (переключатель периода) — задача 14. Раздел 9 (порядок работ) — задачи 8–11 идут до задачи 13, как требует подход «сначала одеть, потом расселить». Раздел 10 (проверки) — задача 2 вводит счётчик, задача 15 включает строгий режим; скриншоты — шаги в задачах 8, 9, 10. Раздел 11 (что не входит) — задач нет намеренно.

**Согласованность имён.** `tokens` — задачи 1, 9. `cssVariables` — задача 1. `Card`/`CardTitle` — задачи 3, 8, 9, 10, 11, 13. `CardState` — задачи 4, 8, 9, 10, 11. `Button` — задачи 5, 8, 10, 11, 13. `Field`/`FieldLabel` — задачи 5, 11. `Table`/`Th`/`Td` — задачи 6, 10. `Badge` — задачи 6, 10. `AsOfLabel` — задачи 7, 13. `CoverageNotice` — задачи 7, 8. `AnimationProvider`/`useAnimationMode`/`useAnimatedNumber`/`ANIMATION_STORAGE_KEY` — задачи 12, 13. `NAV_ITEMS`/`AppShell` — задача 13. `SegmentedControl` — задачи 13 (временная замена), 14.

**Замеченное при проверке и учтённое в задачах.** Первая редакция задачи 12
создавала `useAnimatedNumber` и не подключала его ни к одной цифре — ровно тот
дефект, на котором фаза 2c поймала `close_history`: метод, который никто не
зовёт, проверен настолько, насколько его тест похож на боевой вызов. Добавлен
шаг подключения к цифре капитала вместе с тестом на то, что число доезжает до
цели. `Td` в задаче 6 сперва использовал `border-line/60`: подмешать альфу к
токену нельзя, он записан как `rgba()`, — исправлено на сплошную рамку.
`TradesPage` в задаче 13 монтировал `DecisionPanel` отдельно, тогда как её
открывает сам баннер для выбранной строки (`ReconciliationBanner.tsx:93`).
Переименование CSS-переменных (`--tx-2` → `--muted`) в задаче 1 ломает девять файлов, которые переводятся только в задачах 8–11: чтобы фаза не оставалась сломанной между задачами, в задаче 1 добавлены временные алиасы, а задача 15 их снимает и проверяет, что обращений не осталось. `SettingsPage` в задаче 13 использует `SegmentedControl` из задачи 14 — оговорена временная замена на три `Button`. Счётчик из задачи 2 показывает 121, а не 127: шесть инлайновых стилей `ValueChart` разрешены как графические, и задача 9 их не трогает.
