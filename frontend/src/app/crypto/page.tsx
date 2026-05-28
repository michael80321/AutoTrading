"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import BotTable from "@/components/BotTable";
import ChatFeed from "@/components/ChatFeed";
import PortfolioCard from "@/components/PortfolioCard";
import type { PoolSnapshot } from "@/lib/api";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function CryptoPage() {
  const [data, setData] = useState<PoolSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE}/api/crypto/snapshot`, { cache: "no-store" })
      .then((r) => r.json())
      .then((d) => { setData(d); setLoading(false); })
      .catch(() => { setError(true); setLoading(false); });

    const interval = setInterval(() => {
      fetch(`${API_BASE}/api/crypto/snapshot`, { cache: "no-store" })
        .then((r) => r.json())
        .then((d) => setData(d))
        .catch(() => {});
    }, 10000);
    return () => clearInterval(interval);
  }, []);

  return (
    <main className="min-h-screen bg-gray-950 text-white p-6">
      <div className="max-w-7xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <div>
            <Link href="/" className="text-gray-500 hover:text-gray-300 text-sm mb-1 block">← 首頁</Link>
            <h1 className="text-3xl font-bold text-yellow-400">加密池</h1>
            <p className="text-gray-400 text-sm mt-1">18 席分析師 · Binance · #crypto-floor</p>
          </div>
          {(error || (!loading && !data)) && (
            <div className="bg-red-900/40 border border-red-700 rounded-lg px-4 py-2 text-red-400 text-sm">
              API 離線 — 後端未啟動
            </div>
          )}
        </div>

        {loading && (
          <div className="text-center py-24 text-gray-600">
            <p className="text-xl animate-pulse">載入中...</p>
          </div>
        )}

        {!loading && data && (
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
            <div className="xl:col-span-1 space-y-4">
              <h2 className="text-lg font-semibold text-gray-300">倉位概覽</h2>
              {data.portfolio?.crypto_pool && (
                <PortfolioCard info={data.portfolio.crypto_pool} pool="crypto" />
              )}
              <div className="bg-gray-900 rounded-xl p-4">
                <h3 className="text-sm font-semibold text-gray-400 mb-3">近期進化事件</h3>
                <div className="space-y-2 text-xs">
                  {data.evolution_events?.slice(-5).map((ev, i) => (
                    <div key={i} className="flex items-start gap-2">
                      <span className="text-gray-600 shrink-0">{new Date(ev.timestamp).toLocaleDateString()}</span>
                      <span className="text-yellow-400 shrink-0">{ev.bot_name}</span>
                      <span className="text-gray-400">{ev.action}</span>
                    </div>
                  ))}
                  {!data.evolution_events?.length && <p className="text-gray-600">暫無事件</p>}
                </div>
              </div>
            </div>
            <div className="xl:col-span-2 space-y-6">
              <div>
                <h2 className="text-lg font-semibold text-gray-300 mb-3">即時聊天室</h2>
                <ChatFeed pool="crypto" initialMessages={data.chat ?? []} />
              </div>
              <div>
                <h2 className="text-lg font-semibold text-gray-300 mb-3">18 席分析師</h2>
                <BotTable bots={data.bots ?? []} pool="crypto" />
              </div>
            </div>
          </div>
        )}

        {!loading && !data && (
          <div className="text-center py-24 text-gray-600">
            <p className="text-2xl mb-2">後端未連線</p>
            <p className="text-sm">請確認後端服務正常運作</p>
          </div>
        )}
      </div>
    </main>
  );
}
