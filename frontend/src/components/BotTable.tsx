"use client";
import type { BotInfo } from "@/lib/api";

const STATUS_COLOR: Record<string, string> = {
  active: "text-green-400",
  breeding: "text-yellow-400",
  sandbox: "text-orange-400",
  retired: "text-red-400",
};

export default function BotTable({ bots, pool }: { bots: BotInfo[]; pool: "crypto" | "stock" }) {
  const accent = pool === "crypto" ? "text-yellow-400" : "text-blue-400";
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-gray-500 border-b border-gray-800">
            <th className="text-left pb-2 pr-4">分析師</th>
            <th className="text-left pb-2 pr-4">學派</th>
            <th className="text-right pb-2 pr-4">勝率</th>
            <th className="text-right pb-2 pr-4">夏普</th>
            <th className="text-right pb-2 pr-4">MDD</th>
            <th className="text-right pb-2 pr-4">權重</th>
            <th className="text-right pb-2 pr-4">P&L</th>
            <th className="text-right pb-2">狀態</th>
          </tr>
        </thead>
        <tbody>
          {bots.map((bot) => (
            <tr key={bot.id} className="border-b border-gray-900 hover:bg-gray-900/50">
              <td className={`py-2 pr-4 font-medium ${accent}`}>{bot.name}</td>
              <td className="py-2 pr-4 text-gray-400">{bot.school}</td>
              <td className="py-2 pr-4 text-right">{(bot.metrics.win_rate * 100).toFixed(1)}%</td>
              <td className="py-2 pr-4 text-right">{((bot.metrics.sharpe_ratio ?? (bot.metrics as Record<string,number>).sharpe ?? 0)).toFixed(2)}</td>
              <td className="py-2 pr-4 text-right text-red-400">
                {(bot.metrics.max_drawdown * 100).toFixed(1)}%
              </td>
              <td className="py-2 pr-4 text-right">{bot.weight.toFixed(2)}</td>
              <td className={`py-2 pr-4 text-right ${((bot.metrics.realized_pnl ?? (bot.metrics as Record<string,number>).pnl_pct ?? 0)) >= 0 ? "text-green-400" : "text-red-400"}`}>
                ${((bot.metrics.realized_pnl ?? (bot.metrics as Record<string,number>).pnl_pct ?? 0)).toFixed(2)}
              </td>
              <td className={`py-2 text-right ${STATUS_COLOR[bot.status] ?? "text-gray-400"}`}>
                {bot.status}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
