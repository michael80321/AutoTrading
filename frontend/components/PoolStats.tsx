"use client";

import { useEffect, useState } from "react";
import { fetchSnapshot, type Pool, type PoolSnapshot } from "@/lib/api";

interface Props {
  pool: Pool;
  signalActiveBots?: number;
}

export default function PoolStats({ pool, signalActiveBots }: Props) {
  const [snapshot, setSnapshot] = useState<PoolSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    async function load() {
      try {
        const data = await fetchSnapshot(pool);
        setSnapshot(data);
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

  // Aggregate portfolio data
  const portfolioValues = snapshot
    ? Object.values(snapshot.portfolio)
    : [];
  const totalOpenPositions = portfolioValues.reduce(
    (sum, p) => sum + p.open_positions,
    0
  );
  const totalRealizedPnl = portfolioValues.reduce(
    (sum, p) => sum + p.realized_pnl,
    0
  );
  const activeBots = signalActiveBots ?? snapshot?.bots.filter(
    (b) => b.status === "active"
  ).length ?? 0;

  if (loading) {
    return (
      <div className="grid grid-cols-3 gap-4 mb-6">
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            className="bg-gray-800 rounded-xl p-4 animate-pulse h-24"
          />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="grid grid-cols-3 gap-4 mb-6">
        <StatCard label="持倉數" value="—" sublabel="後端離線" error />
        <StatCard label="已實現 PnL" value="—" sublabel="後端離線" error />
        <StatCard label="活躍機器人" value="—" sublabel="後端離線" error />
      </div>
    );
  }

  return (
    <div className="grid grid-cols-3 gap-4 mb-6">
      <StatCard
        label="持倉數"
        value={totalOpenPositions.toString()}
        sublabel="目前開倉"
      />
      <StatCard
        label="已實現 PnL"
        value={`$${totalRealizedPnl >= 0 ? "+" : ""}${totalRealizedPnl.toFixed(2)}`}
        sublabel="本週"
        positive={totalRealizedPnl >= 0}
      />
      <StatCard
        label="活躍機器人"
        value={activeBots.toString()}
        sublabel={`共 ${snapshot?.bots.length ?? 0} 個機器人`}
      />
    </div>
  );
}

function StatCard({
  label,
  value,
  sublabel,
  positive,
  error,
}: {
  label: string;
  value: string;
  sublabel?: string;
  positive?: boolean;
  error?: boolean;
}) {
  return (
    <div className="bg-gray-800 rounded-xl p-4 border border-gray-700">
      <p className="text-xs text-gray-400 uppercase tracking-wide mb-1">
        {label}
      </p>
      <p
        className={`text-2xl font-bold ${
          error
            ? "text-gray-500"
            : positive === undefined
            ? "text-white"
            : positive
            ? "text-green-400"
            : "text-red-400"
        }`}
      >
        {value}
      </p>
      {sublabel && (
        <p className="text-xs text-gray-500 mt-1">{sublabel}</p>
      )}
    </div>
  );
}
