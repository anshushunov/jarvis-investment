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
