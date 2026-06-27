import { NavLink } from "react-router-dom";
import { Icon } from "../ui/Icon";

const ITEMS: { to: string; icon: string; label: string }[] = [
  { to: "/dashboard", icon: "dashboard", label: "Dashboard" },
  { to: "/factories", icon: "factory", label: "Sites" },
];

/** Mobile-only bottom navigation (glass, docked). Hidden at md+. */
export default function BottomNav() {
  return (
    <nav
      className="
        min-[600px]:hidden fixed bottom-0 inset-x-0 z-40 h-16
        flex items-center justify-around px-4
        glass rounded-t-xl
        shadow-[0_-8px_28px_-6px_rgba(0,0,0,0.55),0_-2px_18px_color-mix(in_srgb,var(--accent)_10%,transparent)]
      "
    >
      {ITEMS.map((it) => (
        <NavLink
          key={it.to}
          to={it.to}
          end
          className={({ isActive }) =>
            `flex flex-col items-center justify-center gap-0.5 px-4 py-1 rounded-xl transition-all duration-200 active:scale-90 ${
              isActive
                ? "bg-accent-15 text-accent glow-primary"
                : "text-text-mute hover:text-text"
            }`
          }
        >
          {({ isActive }) => (
            <>
              <Icon name={it.icon} size={22} filled={isActive} />
              <span className="font-mono text-[9px] uppercase tracking-wider">{it.label}</span>
            </>
          )}
        </NavLink>
      ))}
    </nav>
  );
}
