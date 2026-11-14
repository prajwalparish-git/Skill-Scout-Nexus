"use client";

// The floating glass top bar of the public pages.
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion, useMotionValueEvent, useScroll } from "motion/react";
import { ArrowRight, Menu, X } from "lucide-react";
import { useCandidate } from "@/lib/candidate";
import { PAGES, SECTIONS, SPRING } from "@/lib/site";
import { Brand } from "./Brand";
import { useAuth } from "./auth";

export function SiteNav() {
  const path = usePathname();
  const { open } = useAuth();
  const { candidate, loading } = useCandidate();
  const { scrollY } = useScroll();
  const [scrolled, setScrolled] = useState(false);
  const [hovered, setHovered] = useState<string | null>(null);
  const [menu, setMenu] = useState(false);
  const toggle = useRef<HTMLButtonElement>(null);
  useMotionValueEvent(scrollY, "change", (y) => setScrolled(y > 12));

  // Escape closes the mobile menu and hands focus back to the button that opened it.
  useEffect(() => {
    if (!menu) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setMenu(false);
      toggle.current?.focus();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menu]);

  // On the home page the links are in-page anchors (smooth-scrolled); elsewhere they go home.
  const href = (hash: string) => (path === "/" ? hash : `/${hash}`);

  return (
    <header className="fixed inset-x-0 top-0 z-50 px-3 pt-3 sm:px-4">
      <motion.nav
        aria-label="Main"
        initial={{ y: -24, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={SPRING}
        className={`glass mx-auto flex h-14 max-w-6xl items-center gap-2 rounded-2xl pl-4 pr-2 transition-shadow duration-300 ${
          scrolled ? "shadow-[0_8px_30px_-12px_rgb(var(--ink)/0.25)]" : ""
        }`}
      >
        <Link href="/" className="mr-2 rounded-lg text-ink" aria-label="Skill Scout Nexus, home">
          <Brand height={14} />
        </Link>

        <ul className="hidden flex-1 items-center justify-center md:flex" onMouseLeave={() => setHovered(null)}>
          {SECTIONS.map((s) => (
            <li key={s.hash}>
              <a
                href={href(s.hash)}
                onMouseEnter={() => setHovered(s.hash)}
                onFocus={() => setHovered(s.hash)}
                className="relative block rounded-full px-3.5 py-1.5 text-sm text-muted transition-colors hover:text-ink"
              >
                {hovered === s.hash && (
                  <motion.span layoutId="nav-hover" className="absolute inset-0 -z-10 rounded-full bg-ink/[0.06]" transition={SPRING} />
                )}
                {s.label}
              </a>
            </li>
          ))}
          {PAGES.map((pg) => (
            <li key={pg.href}>
              <Link
                href={pg.href}
                aria-current={path === pg.href ? "page" : undefined}
                onMouseEnter={() => setHovered(pg.href)}
                onFocus={() => setHovered(pg.href)}
                className={`relative block rounded-full px-3.5 py-1.5 text-sm transition-colors hover:text-ink ${
                  path === pg.href ? "font-medium text-ink" : "text-muted"
                }`}
              >
                {hovered === pg.href && (
                  <motion.span layoutId="nav-hover" className="absolute inset-0 -z-10 rounded-full bg-ink/[0.06]" transition={SPRING} />
                )}
                {pg.label}
              </Link>
            </li>
          ))}
        </ul>

        <div className="ml-auto hidden items-center gap-1.5 md:flex">
          {loading ? null : candidate ? (
            <Link href="/dashboard" className="btn-ink group">
              Open dashboard
              <ArrowRight size={15} className="transition-transform duration-200 group-hover:translate-x-0.5" aria-hidden />
            </Link>
          ) : (
            <>
              <button type="button" className="btn rounded-full px-3.5 text-ink hover:bg-ink/[0.06]" onClick={() => open("signin")}>
                Sign in
              </button>
              <button type="button" className="btn-ink group" onClick={() => open("signup")}>
                Get started
                <ArrowRight size={15} className="transition-transform duration-200 group-hover:translate-x-0.5" aria-hidden />
              </button>
            </>
          )}
        </div>

        <button
          ref={toggle}
          type="button"
          className="ml-auto rounded-full p-2.5 text-ink hover:bg-ink/[0.06] md:hidden"
          aria-expanded={menu}
          aria-controls="mobile-menu"
          aria-label={menu ? "Close navigation menu" : "Open navigation menu"}
          onClick={() => setMenu((m) => !m)}
        >
          {menu ? <X size={20} aria-hidden /> : <Menu size={20} aria-hidden />}
        </button>
      </motion.nav>

      <AnimatePresence>
        {menu && (
          <motion.div
            id="mobile-menu"
            initial={{ opacity: 0, y: -8, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -8, scale: 0.98 }}
            transition={SPRING}
            className="glass mx-auto mt-2 max-w-6xl rounded-2xl p-2 md:hidden"
          >
            <ul>
              {SECTIONS.map((s) => (
                <li key={s.hash}>
                  <a
                    href={href(s.hash)}
                    onClick={() => setMenu(false)}
                    className="block rounded-xl px-3 py-2.5 text-[15px] text-ink hover:bg-ink/[0.06]"
                  >
                    {s.label}
                  </a>
                </li>
              ))}
              {PAGES.map((pg) => (
                <li key={pg.href}>
                  <Link
                    href={pg.href}
                    onClick={() => setMenu(false)}
                    aria-current={path === pg.href ? "page" : undefined}
                    className="block rounded-xl px-3 py-2.5 text-[15px] text-ink hover:bg-ink/[0.06]"
                  >
                    {pg.label}
                  </Link>
                </li>
              ))}
            </ul>
            <div className="mt-2 grid grid-cols-2 gap-2 border-t border-hair p-2 pt-3">
              {candidate ? (
                <Link href="/dashboard" className="btn-ink col-span-2" onClick={() => setMenu(false)}>
                  Open dashboard
                </Link>
              ) : (
                <>
                  <button
                    type="button"
                    className="btn-hair"
                    onClick={() => {
                      setMenu(false);
                      open("signin");
                    }}
                  >
                    Sign in
                  </button>
                  <button
                    type="button"
                    className="btn-ink"
                    onClick={() => {
                      setMenu(false);
                      open("signup");
                    }}
                  >
                    Get started
                  </button>
                </>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </header>
  );
}
