"use client";

import { useEffect, useState } from "react";
import {
  createSignalsSocket,
  fetchSnapshot,
  type Pool,
  type PoolSignal,
  type EvolutionEvent,
  type ChatMessage,
} from "@/lib/api";

interface Props {
  pool: Pool;
  onSignalUpdate?: (signal: PoolSignal) => void;
}

function formatTime(ts: string): string {
  try {
    const d = new Date(ts);
    return d.toLocaleString("zh-TW", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  } catch {
    return ts;
  }
}

function getActionLabel(action: string): string {
  const map: Record<string, string> = {
    promote_breed: "🧬 晉升繁殖",
    demote: "⬇️ 降級",
    retire: "🪦 退役",
    spawn: "🌱 生成",
    mutate: "🔬 變異",
    compete: "⚔️ 競賽",
  };
  return map[action] ?? action;
}

export default function SignalWall({ pool, onSignalUpdate }: Props) {
  const [latestSignal, setLatestSignal] = useState<PoolSignal | null>(null);
  const [evolutionEvents, setEvolutionEvents] = useState<EvolutionEvent[]>([]);
  const [recentChats, setRecentChats] = useState<ChatMessage[]>([]);
  const [wsConnected, setWsConnected] = useState(false);

  // Load initial data from snapshot
  useEffect(() => {
    fetchSnapshot(pool)
      .then((snap) => {
        setEvolutionEvents(snap.evolution_events.slice(-10));
        setRecentChats(snap.chat.slice(-5));
      })
      .catch(() => {});
  }, [pool]);

  // WebSocket for live signals
  useEffect(() => {
    const disconnect = createSignalsSocket(
      (signal) => {
        if (signal.pool === pool || signal.pool === (pool === "crypto" ? "crypto" : "stock")) {
          setLatestSignal(signal);
          onSignalUpdate?.(signal);
        }
      },
      setWsConnected
    );
    return disconnect;
  }, [pool, onSignalUpdate]);

  return (
    <div className="flex flex-col gap-4 h-full">
      {/* Live Signal Panel */}
      <div className="bg-gray-900 rounded-xl border border-gray-800">
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
          <h2 className="font-semibold text-gray-200">📡 即時訊號</h2>
          <span
            className={`text-xs ${
              wsConnected ? "text-green-400" : "text-yellow-400 animate-pulse"
            }`}
          >
            {wsConnected ? "• 連線中" : "連線中…"}
          </span>
        </div>

        <div className="p-4">
          {latestSignal ? (
            <SignalCard signal={latestSignal} />
          ) : (
            <div className="text-center py-6 text-gray-500 text-sm">
              等待訊號…
            </div>
          )}
        </div>
      </div>

      {/* Recent Signals from snapshot */}
      {recentChats.length > 0 && (
        <div className="bg-gray-900 rounded-xl border border-gray-800">
          <div className="px-4 py-3 border-b border-gray-800">
            <h2 className="font-semibold text-gray-200">⚡ 最新信號</h2>
          </div>
          <div className="p-3 space-y-2">
            {recentChats.map((msg, i) => (
              <MiniSignalRow key={i} msg={msg} />
            ))}
          </div>
        </div>
      )}

      {/* Evolution Events */}
      <div className="bg-gray-900 rounded-xl border border-gray-800 flex-1">
        <div className="px-4 py-3 border-b border-gray-800">
          <h2 className="font-semibold text-gray-200">🧬 進化事件</h2>
        </div>
        <div className="p-3 space-y-2 max-h-64 overflow-y-auto">
          {evolutionEvents.length === 0 ? (
            <div className="text-center py-4 text-gray-500 text-sm">
              暫無進化事件
            </div>
          ) : (
            [...evolutionEvents].reverse().map((ev, i) => (
              <EvolutionRow key={i} event={ev} />
            ))
          )}
        </div>
      </div>
    </div>
  );
}

function SignalCard({ signal }: { signal: PoolSignal }) {
  const pnlPositive = signal.realized_pnl >= 0;
  return (
    <div className="space-y-3">
      <div className="flex justify-between items-center">
        <span className="text-sm text-gray-400">池</span>
        <span className="font-mono text-sm text-white capitalize">
          {signal.pool}
        </span>
      </div>
      <div className="flex justify-between items-center">
        <span className="text-sm text-gray-400">開倉數</span>
        <span className="font-bold text-lg text-white">
          {signal.open_positions}
        </span>
      </div>
      <div className="flex justify-between items-center">
        <span className="text-sm text-gray-400">已實現 PnL</span>
        <span
          className={`font-bold text-lg ${
            pnlPositive ? "text-green-400" : "text-red-400"
          }`}
        >
          {pnlPositive ? "+" : ""}
          {signal.realized_pnl.toFixed(2)}
        </span>
      </div>
      <div className="flex justify-between items-center">
        <span className="text-sm text-gray-400">活躍機器人</span>
        <span className="font-bold text-lg text-blue-400">
          {signal.active_bots}
        </span>
      </div>
    </div>
  );
}

function MiniSignalRow({ msg }: { msg: ChatMessage }) {
  const upper = msg.content.toUpperCase();
  const isLong = upper.includes("LONG");
  const isShort = upper.includes("SHORT");

  return (
    <div className="flex items-center gap-2 text-xs bg-gray-800 rounded-lg px-3 py-2">
      <span className="font-mono text-blue-300 shrink-0">{msg.symbol}</span>
      {isLong && (
        <span className="text-green-400 font-bold shrink-0">↑ LONG</span>
      )}
      {isShort && (
        <span className="text-red-400 font-bold shrink-0">↓ SHORT</span>
      )}
      <span className="text-gray-400 truncate flex-1">{msg.from}</span>
      {msg.confidence > 0 && (
        <span className="text-amber-400 shrink-0">
          {(msg.confidence * 100).toFixed(0)}%
        </span>
      )}
    </div>
  );
}

function EvolutionRow({ event }: { event: EvolutionEvent }) {
  return (
    <div className="bg-gray-800 rounded-lg px-3 py-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-semibold text-gray-200">
          {event.bot_name}
        </span>
        <span className="text-xs text-purple-400 shrink-0">
          {getActionLabel(event.action)}
        </span>
      </div>
      {event.note && (
        <p className="text-xs text-gray-500 mt-0.5 truncate">{event.note}</p>
      )}
      <p className="text-xs text-gray-600 mt-0.5">
        {formatTime(event.timestamp)}
      </p>
    </div>
  );
}
