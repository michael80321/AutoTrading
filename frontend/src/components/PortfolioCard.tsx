import type { PortfolioInfo } from "@/lib/api";

export default function PortfolioCard({
  info,
  pool,
}: {
  info: PortfolioInfo;
  pool: "crypto" | "stock";
}) {
  const currency = pool === "crypto" ? "USDT" : "USD";
  const pnlColor = info.realized_pnl >= 0 ? "text-green-400" : "text-red-400";
  const utilization = ((info.total - info.available) / info.total) * 100;

  return (
    <div className="bg-gray-900 rounded-xl p-5 space-y-3">
      <div className="flex justify-between items-center">
        <span className="text-gray-400 text-sm">總資金</span>
        <span className="font-semibold">${info.total.toLocaleString()} {currency}</span>
      </div>
      <div className="flex justify-between items-center">
        <span className="text-gray-400 text-sm">可用</span>
        <span>${info.available.toFixed(2)}</span>
      </div>
      <div className="flex justify-between items-center">
        <span className="text-gray-400 text-sm">開放部位</span>
        <span>{info.open_positions}</span>
      </div>
      <div className="flex justify-between items-center">
        <span className="text-gray-400 text-sm">已實現 P&L</span>
        <span className={pnlColor}>${info.realized_pnl.toFixed(2)}</span>
      </div>
      {/* 資金使用率 bar */}
      <div>
        <div className="flex justify-between text-xs text-gray-500 mb-1">
          <span>資金使用率</span>
          <span>{utilization.toFixed(1)}%</span>
        </div>
        <div className="w-full bg-gray-800 rounded-full h-1.5">
          <div
            className="h-1.5 rounded-full bg-yellow-500"
            style={{ width: `${Math.min(utilization, 100)}%` }}
          />
        </div>
      </div>
    </div>
  );
}
