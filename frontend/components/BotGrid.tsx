"use client";

import { useEffect, useState } from "react";
import { fetchSnapshot, type Bot, type Pool } from "@/lib/api";

interface Props {
  pool: Pool;
}

type BotStatus = Bot["status"];

const STATUS_CONFIG: Record<
  BotStatus,
  { label: string; dot: string; badge: string }
> = {
  active: {
    label: "運行中",
    dot: "bg-green-500",
    badge: "bg-green-900/50 text-green-400 border-green-800",
  },
  breeding: {
    label: "繁殖中",
    dot: "bg-yellow-500",
    badge: "bg-yellow-900/50 text-yellow-400 border-yellow-800",
  },
  sandbox: {
    label: "沙箱",
    dot: "bg-orange-500",
    badge: "bg-orange-900/50 text-orange-400 border-orange-800",
  },
  retired: {
    label: "退役",
    dot: "bg-gray-600",
    badge: "bg-gray-800 text-gray-500 border-gray-700",
  },
};

export default function BotGrid({ pool }: Props) {
  const [bots, setBots] = useState<Bot[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    async function load() {
      try {
        const snap = await fetchSnapshot(pool);
        setBots(snap.bots);
        setError(false);
      } catch {
        setError(true);
      } finally {
        setLoading(false);
      }
    }
    load();
    const interval = setInterval(load, 30_000);
    return () => clearInterval(interval);
  }, [pool]);

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 p-4">
      <div className="flex items-center justify-between mb-4">
        <h2 className="font-semibold text-gray-200">🤖 機器人矩陣</h2>
        {!loading && !error && (
          <div className="flex gap-3 text-xs text-gray-500">
            {(Object.keys(STATUS_CONFIG) as BotStatus[]).map((s) => (
              <span key={s} className="flex items-center gap-1">
                <span
                  className={`w-2 h-2 rounded-full ${STATUS_CONFIG[s].dot}`}
                />
                {STATUS_CONFIG[s].label}
              </span>
            ))}
          </div>
        )}
      </div>

      {loading ? (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-3">
          {Array.from({ length: 18 }).map((_, i) => (
            <div
              key={i}
              className="bg-gray-800 rounded-lg h-32 animate-pulse"
            />
          ))}
        </div>
      ) : error ? (
        <div className="text-center py-10 text-gray-500">
          無法載入機器人資料
        </div>
      ) : bots.length === 0 ? (
        <div className="text-center py-10 text-gray-500">暫無機器人</div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-3">
          {bots.map((bot) => (
            <BotCard key={bot.id} bot={bot} />
          ))}
        </div>
      )}
    </div>
  );
}

function BotCard({ bot }: { bot: Bot }) {
  const status = STATUS_CONFIG[bot.status] ?? STATUS_CONFIG.retired;
  const winRatePct = (bot.metrics.win_rate * 100).toFixed(0);
  const isActive = bot.status === "active";

  return (
    <div
      className={`bg-gray-800 rounded-lg p-3 border transition-colors ${
        isActive
          ? "border-gray-700 hover:border-gray-600"
          : "border-gray-750 opacity-75"
      }`}
    >
      {/* Status dot + ID */}
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs text-gray-500 font-mono">{bot.id}</span>
        <span className={`w-2.5 h-2.5 rounded-full ${status.dot}`} />
      </div>

      {/* Name */}
      <p className="text-sm font-semibold text-gray-100 truncate mb-1">
        {bot.name}
      </p>

      {/* School badge */}
      <p className="text-xs text-gray-400 truncate mb-2">{bot.school}</p>

      {/* Status badge */}
      <span
        className={`inline-block text-xs px-1.5 py-0.5 rounded border mb-2 ${status.badge}`}
      >
        {status.label}
      </span>

      {/* Metrics */}
      <div className="space-y-1">
        <MetricRow
          label="勝率"
          value={`${winRatePct}%`}
          color={
            bot.metrics.win_rate >= 0.6
              ? "text-green-400"
              : bot.metrics.win_rate >= 0.45
              ? "text-yellow-400"
              : "text-red-400"
          }
        />
        <MetricRow
          label="權重"
          value={bot.metrics.win_rate !== undefined ? bot.weight.toFixed(2) : "—"}
          color="text-blue-300"
        />
      </div>
    </div>
  );
}

function MetricRow({
  label,
  value,
  color,
}: {
  label: string;
  value: string | number;
  color: string;
}) {
  return (
    <div className="flex justify-between items-center">
      <span className="text-xs text-gray-500">{label}</span>
      <span className={`text-xs font-mono font-semibold ${color}`}>
        {value}
      </span>
    </div>
  );
}
