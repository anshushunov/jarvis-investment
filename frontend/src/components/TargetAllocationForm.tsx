import { useState } from "react";

import type { AllocationTarget, AllocationTargetInput, PositionRow } from "../api/client";
import { ASSET_CLASS_TITLES } from "../api/format";
import { Button } from "../ui/Button";
import { Field, FieldLabel } from "../ui/Field";
import { Table, Td, Th } from "../ui/Table";

// Тот же класс, что у выпадающих списков панели решений (DecisionPanel.tsx):
// select — не Field, но выглядеть обязан так же.
const CONTROL =
  "block w-full rounded-sm border border-line bg-bg1/60 px-2.5 py-1.5 text-sm text-tx outline-none focus:border-blue";

// Классы, на которые можно задать цель. «Деньги и металлы» — ключ разреза
// доходности, а не класс аллокации, и в цели не годится.
const TARGETABLE_CLASSES = Object.keys(ASSET_CLASS_TITLES).filter((key) => key !== "cash_and_metals");

type Kind = "asset_class" | "instrument";

export interface TargetRow {
  id: string;
  kind: Kind;
  key: string;      // класс или ISIN
  title: string;
  percent: string;  // как набрано владельцем: "60", "12,5"
}

// Проценты — единственная величина модуля, которой разрешён Number: та же
// оговорка, что у formatPercent в api/format.ts. Это доля, а не деньги.
export function percentToShare(percent: string): string {
  return (Number.parseFloat(percent.replace(",", ".")) / 100).toFixed(4);
}

export function shareToPercent(share: string): string {
  // Через целые сотые процента: 0.07 * 100 в двоичной арифметике — это
  // 7.000000000000001, а в поле ввода владелец ждёт «7».
  return String(Math.round(Number.parseFloat(share) * 10000) / 100);
}

export function sumPercent(rows: TargetRow[]): number {
  return rows.reduce(
    (total, row) => total + (Number.parseFloat(row.percent.replace(",", ".")) || 0), 0);
}

// Пустая, нечисловая или неположительная доля — не цель, а недоразумение:
// ноль и меньше неотличимы от отсутствия цели, а пустая строка на save()
// превратилась бы в NaN.toFixed(4) и ушла бы на бэкенд буквальной строкой
// "NaN". Сохранять нельзя, пока такая строка есть хоть одна.
export function invalidRows(rows: TargetRow[]): TargetRow[] {
  return rows.filter((row) => {
    const value = Number.parseFloat(row.percent.replace(",", "."));
    return row.percent.trim() === "" || Number.isNaN(value) || value <= 0;
  });
}

export function rowsFromTargets(targets: AllocationTarget[]): TargetRow[] {
  return targets.map((target, index) =>
    target.asset_class !== null
      ? { id: `class-${index}`, kind: "asset_class", key: target.asset_class,
          title: ASSET_CLASS_TITLES[target.asset_class] ?? target.asset_class,
          percent: shareToPercent(target.share) }
      : { id: `isin-${index}`, kind: "instrument", key: target.isin ?? "",
          title: target.name ?? target.isin ?? "—", percent: shareToPercent(target.share) },
  );
}

function plainPercent(value: number): string {
  return `${String(Math.round(value * 100) / 100).replace(".", ",")} %`;
}

export function TargetAllocationForm({ targets, positions, onSave, saving, error }: {
  targets: AllocationTarget[];
  positions: PositionRow[];
  onSave: (body: AllocationTargetInput[]) => void;
  saving: boolean;
  error: string | null;
}) {
  const [rows, setRows] = useState<TargetRow[]>(() => rowsFromTargets(targets));
  const [kind, setKind] = useState<Kind>("asset_class");
  const [key, setKey] = useState("");

  const used = new Set(rows.map((row) => row.key));
  const classOptions = TARGETABLE_CLASSES.filter((klass) => !used.has(klass));
  // Бумаги — из открытых позиций: цель на бумагу, которой в портфеле нет,
  // сравнивать не с чем. Одна бумага на нескольких счетах — один пункт.
  const held = new Map<string, string>();
  for (const row of positions) {
    if (row.isin !== null && !used.has(row.isin) && !held.has(row.isin)) held.set(row.isin, row.name);
  }

  const total = sumPercent(rows);
  const overLimit = total > 100;
  const hasInvalidPercent = invalidRows(rows).length > 0;
  const blocked = overLimit || hasInvalidPercent;

  function addRow() {
    if (key === "") return;
    const title = kind === "asset_class" ? (ASSET_CLASS_TITLES[key] ?? key) : (held.get(key) ?? key);
    setRows([...rows, { id: `${kind}-${key}`, kind, key, title, percent: "" }]);
    setKey("");
  }

  function save() {
    onSave(rows.map((row) => ({
      asset_class: row.kind === "asset_class" ? row.key : null,
      isin: row.kind === "instrument" ? row.key : null,
      share: percentToShare(row.percent),
    })));
  }

  return (
    <div>
      {rows.length === 0 ? (
        <div className="text-sm text-muted">
          Целей пока нет: без них ассистент не скажет, что подрезать, а что нарастить.
        </div>
      ) : (
        <Table>
          <thead>
            <tr>
              <Th>Цель</Th>
              <Th numeric>Доля, %</Th>
              <Th>{""}</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <Td>
                  {row.title}
                  <span className="ml-1.5 text-xs text-muted">
                    {row.kind === "asset_class" ? "класс" : "бумага"}
                  </span>
                </Td>
                <Td numeric>
                  <Field aria-label={`Доля ${row.title}`} className="w-20 text-right" inputMode="decimal"
                         value={row.percent}
                         onChange={(event) => setRows(rows.map((item) =>
                           item.id === row.id ? { ...item, percent: event.target.value } : item))} />
                </Td>
                <Td>
                  <Button variant="ghost" onClick={() => setRows(rows.filter((item) => item.id !== row.id))}>
                    Убрать
                  </Button>
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}

      <div className={`mt-2 text-sm tabular-nums ${blocked ? "text-red" : "text-muted"}`}>
        Итого {plainPercent(total)} · не задано {plainPercent(Math.max(0, 100 - total))}
        {overLimit && " — сумма целей больше 100 %, сохранить нельзя"}
        {hasInvalidPercent && " — у каждой цели нужна доля больше нуля"}
      </div>

      <div className="mt-3 flex flex-wrap items-end gap-2">
        <div>
          <FieldLabel htmlFor="target-kind">Добавить цель</FieldLabel>
          <select id="target-kind" className={CONTROL} value={kind}
                  onChange={(event) => { setKind(event.target.value as Kind); setKey(""); }}>
            <option value="asset_class">на класс активов</option>
            <option value="instrument">на бумагу</option>
          </select>
        </div>
        <div>
          <FieldLabel htmlFor="target-key">{kind === "asset_class" ? "Класс" : "Бумага"}</FieldLabel>
          <select id="target-key" className={CONTROL} value={key}
                  onChange={(event) => setKey(event.target.value)}>
            <option value="">—</option>
            {kind === "asset_class"
              ? classOptions.map((klass) => (
                  <option key={klass} value={klass}>{ASSET_CLASS_TITLES[klass]}</option>
                ))
              : [...held.entries()].map(([isin, name]) => (
                  <option key={isin} value={isin}>{name}</option>
                ))}
          </select>
        </div>
        <Button variant="ghost" onClick={addRow} disabled={key === ""}>Добавить</Button>
        <Button onClick={save} disabled={blocked || saving}>
          {saving ? "Сохраняю…" : "Сохранить"}
        </Button>
      </div>

      {error !== null && <div role="alert" className="mt-2 text-sm text-red">{error}</div>}
    </div>
  );
}
