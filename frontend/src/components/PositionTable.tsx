"use client";

interface Position {
  order_id: string;
  symbol: string;
  side: "LONG" | "SHORT";
  qty: number;
  entry_price: number;
  stop_loss: number;
  tp1: number | null;
  tp2: number | null;
  tp1_filled: boolean;
  status: string;
  entry_time: string | null;
  notional_usdt: number;
  consensus_score: number;
  contributors: string[];
}

function PriceCell({ label, value, color }: { label: string; value: number | null; color: string }) {
  if (value == null) return <span className="text-gray-600">—</span>;
  return (
    <div className="text-right">
      <div className={`font-mono text-sm ${color}`}>{value.toFixed(4)}</div>
      <div className="text-gray-600 text-xs">{label}</div>
    </div>
  );
}

export default function PositionTable({ positions, pool }: { positions: Position[]; pool: "crypto" | "stock" }) {
  const accent = pool === "crypto" ? "text-yellow-400" : "text-blue-400";

  if (!positions.length) {
    return (
      <div className="bg-gray-900 rounded-xl p-6 text-center text-gray-600 text-sm">
        目前無開放倉位
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {positions.map((pos) => {
        const sideColor = pos.side === "LONG" ? "text-green-400" : "text-red-400";
        const entryTime = pos.entry_time
          ? new Date(pos.entry_time).toLocaleString("zh-TW", { timeZone: "Asia/Taipei" })
          : "—";

        return (
          <div key={pos.order_id} className="bg-gray-900 rounded-xl p-4 border border-gray-800">
            {/* Header */}
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-3">
                <span className={`font-bold text-lg ${accent}`}>{pos.symbol}</span>
                <span className={`px-2 py-0.5 rounded text-xs font-semibold ${pos.side === "LONG" ? "bg-green-900/50 text-green-400" : "bg-red-900/50 text-red-400"}`}>
                  {pos.side}
                </span>
                {pos.tp1_filled && (
                  <span className="px-2 py-0.5 rounded text-xs bg-yellow-900/50 text-yellow-400">
                    TP1 已止盈
                  </span>
                )}
              </div>
              <div className="text-right">
                <div className="text-white font-mono">${pos.notional_usdt.toLocaleString()}</div>
                <div className="text-gray-500 text-xs">{entryTime}</div>
              </div>
            </div>

            {/* Price grid */}
            <div className="grid grid-cols-5 gap-2 mb-3">
              <div className="text-right">
                <div className={`font-mono text-sm ${sideColor}`}>{pos.entry_price.toFixed(4)}</div>
                <div className="text-gray-600 text-xs">進場</div>
              </div>
              <PriceCell label="SL" value={pos.stop_loss} color="text-red-400" />
              <PriceCell label="TP1 ✓" value={pos.tp1} color={pos.tp1_filled ? "text-gray-500 line-through" : "text-green-400"} />
              <PriceCell label="TP2" value={pos.tp2} color="text-green-300" />
              <div className="text-right">
                <div className="font-mono text-sm text-gray-300">{pos.qty.toFixed(4)}</div>
                <div className="text-gray-600 text-xs">數量</div>
              </div>
            </div>

            {/* Contributors */}
            {pos.contributors.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {pos.contributors.map((c, i) => (
                  <span key={i} className="text-xs bg-gray-800 text-gray-400 px-2 py-0.5 rounded">
                    {c}
                  </span>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
