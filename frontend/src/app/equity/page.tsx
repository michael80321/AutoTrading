"use client";
import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import BotTable from "@/components/BotTable";
import ChatFeed from "@/components/ChatFeed";
import PortfolioCard from "@/components/PortfolioCard";
import PositionTable from "@/components/PositionTable";
import type { PoolSnapshot } from "@/lib/api";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function EquityPage() {
  const [data, setData] = useState<PoolSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdate, setLastUpdate] = useState<string>("");

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/stock/snapshot`);
      if (!res.ok) throw new Error("API error");
      const d = await res.json();
      setData(d);
      setLastUpdate(new Date().toLocaleTimeString("zh-TW", { timeZone: "Asia/Taipei" }));
    } catch {
      // silent fail on polling
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 10000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const portfolio = data?.portfolio?.stock_pool;
  const positions = ((portfolio as unknown as Record<string, unknown>)?.positions as Parameters<typeof PositionTable>[0]["positions"]) ?? [];

  return (
    <main className="min-h-screen bg-gray-950 text-white p-6">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <Link href="/" className="text-gray-500 hover:text-gray-300 text-sm mb-1 block">← 首頁</Link>
            <h1 className="text-3xl font-bold text-blue-400">美股池</h1>
            <p className="text-gray-400 text-sm mt-1">18 席分析師 · IBKR · #equities-floor</p>
          </div>
          <div className="text-right">
            {lastUpdate && <p className="text-gray-500 text-xs">更新: {lastUpdate}</p>}
            {!loading && !data && (
              <div className="bg-red-900/40 border border-red-700 rounded-lg px-4 py-2 text-red-400 text-sm">
                API 離線
              </div>
            )}
          </div>
        </div>

        {loading && (
          <div className="text-center py-24 text-gray-600">
            <p className="text-xl animate-pulse">載入中...</p>
          </div>
        )}

        {!loading && data && (
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
            {/* 左欄 */}
            <div className="xl:col-span-1 space-y-4">
              <h2 className="text-lg font-semibold text-gray-300">資金概覽</h2>
              {portfolio && <PortfolioCard info={portfolio} pool="stock" />}

              {/* 開放倉位 */}
              <div>
                <h2 className="text-lg font-semibold text-gray-300 mb-3">
                  開放倉位
                  {positions.length > 0 && (
                    <span className="ml-2 text-sm text-blue-400 font-normal">{positions.length} 筆</span>
                  )}
                </h2>
                <PositionTable positions={positions} pool="stock" />
              </div>

              {/* 進化事件 */}
              <div className="bg-gray-900 rounded-xl p-4">
                <h3 className="text-sm font-semibold text-gray-400 mb-3">近期進化事件</h3>
                <div className="space-y-2 text-xs">
                  {data.evolution_events?.slice(-5).map((ev, i) => (
                    <div key={i} className="flex items-start gap-2">
                      <span className="text-gray-600 shrink-0">{new Date(ev.timestamp).toLocaleDateString()}</span>
                      <span className="text-blue-400 shrink-0">{ev.bot_name}</span>
                      <span className="text-gray-400">{ev.action}</span>
                    </div>
                  ))}
                  {!data.evolution_events?.length && <p className="text-gray-600">暫無事件</p>}
                </div>
              </div>
            </div>

            {/* 右欄 */}
            <div className="xl:col-span-2 space-y-6">
              <div>
                <h2 className="text-lg font-semibold text-gray-300 mb-3">即時聊天室</h2>
                <ChatFeed pool="stock" initialMessages={data.chat ?? []} />
              </div>
              <div>
                <h2 className="text-lg font-semibold text-gray-300 mb-3">18 席分析師</h2>
                <BotTable bots={data.bots ?? []} pool="stock" />
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
