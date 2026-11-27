"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export interface NavItem {
  href: string;
  label: string;
}

/** The site's menu, with the current page marked for screen readers and the eye. */
export function NavLinks({ items }: { items: NavItem[] }) {
  const pathname = usePathname();
  return (
    <ul className="nav">
      {items.map((item) => {
        const current = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
        return (
          <li key={item.href}>
            <Link href={item.href} aria-current={current ? "page" : undefined}>
              {item.label}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
