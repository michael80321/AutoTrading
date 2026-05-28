"use client";
import { usePoolWebSocket } from "@/lib/useWebSocket";
import type { ChatMessage } from "@/lib/api";

function ConfidenceBadge({ v }: { v: number }) {
  const color = v >= 0.8 ? "bg-green-700" : v >= 0.6 ? "bg-yellow-700" : "bg-gray-700";
  return (
    <span className={`ml-2 px-1.5 py-0.5 text-xs rounded ${color}`}>
      {(v * 100).toFixed(0)}%
    </span>
  );
}

export default function ChatFeed({
  pool,
  initialMessages,
}: {
  pool: "crypto" | "stock";
  initialMessages: ChatMessage[];
}) {
  const { messages: liveMessages, connected } = usePoolWebSocket(pool);
  const accent = pool === "crypto" ? "text-yellow-400" : "text-blue-400";

  const all = [
    ...initialMessages,
    ...(liveMessages as ChatMessage[]),
  ].slice(-100);

  return (
    <div className="flex flex-col h-96 bg-gray-900 rounded-xl overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2 border-b border-gray-800">
        <span className="font-mono text-sm text-gray-400">
          {pool === "crypto" ? "#crypto-floor" : "#equities-floor"}
        </span>
        <span className={`text-xs ${connected ? "text-green-400" : "text-gray-600"}`}>
          {connected ? "● live" : "○ connecting"}
        </span>
      </div>
      <div className="flex-1 overflow-y-auto px-4 py-2 space-y-2 text-sm font-mono">
        {all.map((msg, i) => (
          <div key={i} className="flex flex-col">
            <div className="flex items-center gap-2">
              <span className={`font-semibold ${accent}`}>{msg.from}</span>
              <span className="text-gray-600 text-xs">{msg.school}</span>
              <span className="text-gray-600 text-xs">·</span>
              <span className="text-gray-500 text-xs">{msg.symbol}</span>
              <ConfidenceBadge v={msg.confidence} />
            </div>
            <p className="text-gray-300 mt-0.5 leading-snug">{msg.content}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
