"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { fetchHealth, type HealthStatus } from "@/lib/api";

export default function NavBar() {
  const pathname = usePathname();
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [online, setOnline] = useState<boolean | null>(null);

  useEffect(() => {
    async function checkHealth() {
      try {
        const h = await fetchHealth();
        setHealth(h);
        setOnline(true);
      } catch {
        setOnline(false);
        setHealth(null);
      }
    }
    checkHealth();
    const interval = setInterval(checkHealth, 30_000);
    return () => clearInterval(interval);
  }, []);

  return (
    <nav className="fixed top-0 left-0 right-0 z-50 h-16 bg-gray-900 border-b border-gray-800 flex items-center px-4 shadow-lg">
      {/* Logo */}
      <div className="flex items-center gap-2 flex-1">
        <div className="w-8 h-8 rounded-full bg-gradient-to-br from-purple-500 to-blue-500 flex items-center justify-center text-xs font-bold">
          AI
        </div>
        <span className="font-bold text-white text-sm md:text-base whitespace-nowrap">
          AI Trading Collective
        </span>
      </div>

      {/* Tab switcher */}
      <div className="flex items-center gap-1 bg-gray-800 rounded-lg p-1">
        <Link
          href="/crypto"
          className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${
            pathname === "/crypto"
              ? "bg-purple-600 text-white shadow"
              : "text-gray-400 hover:text-white hover:bg-gray-700"
          }`}
        >
          加密池 🔮
        </Link>
        <Link
          href="/equity"
          className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${
            pathname === "/equity"
              ? "bg-blue-600 text-white shadow"
              : "text-gray-400 hover:text-white hover:bg-gray-700"
          }`}
        >
          美股池 📈
        </Link>
      </div>

      {/* Status dot */}
      <div className="flex items-center gap-2 flex-1 justify-end">
        {online === null ? (
          <span className="text-xs text-gray-500">連線中…</span>
        ) : online ? (
          <div className="flex items-center gap-1.5">
            <span className="relative flex h-2.5 w-2.5">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-green-500"></span>
            </span>
            <span className="text-xs text-gray-400 hidden md:inline">
              {health
                ? `C:${health.crypto_bots} | S:${health.stock_bots}`
                : "上線"}
            </span>
          </div>
        ) : (
          <div className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full bg-red-500"></span>
            <span className="text-xs text-red-400 hidden md:inline">離線</span>
          </div>
        )}
      </div>
    </nav>
  );
}
