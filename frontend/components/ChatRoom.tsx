"use client";

import { useEffect, useRef, useState } from "react";
import { createChatSocket, fetchSnapshot, type ChatMessage, type Pool } from "@/lib/api";

interface Props {
  pool: Pool;
}

function formatTime(ts: string): string {
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString("zh-TW", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  } catch {
    return ts;
  }
}

function getInitial(name: string): string {
  return name.charAt(0).toUpperCase();
}

function getSideFromContent(content: string): "LONG" | "SHORT" | null {
  const upper = content.toUpperCase();
  if (upper.includes("LONG")) return "LONG";
  if (upper.includes("SHORT")) return "SHORT";
  return null;
}

const AVATAR_COLORS = [
  "bg-purple-600",
  "bg-blue-600",
  "bg-teal-600",
  "bg-indigo-600",
  "bg-pink-600",
  "bg-amber-600",
  "bg-cyan-600",
  "bg-rose-600",
];

function getAvatarColor(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = (hash * 31 + name.charCodeAt(i)) & 0xffff;
  }
  return AVATAR_COLORS[hash % AVATAR_COLORS.length];
}

export default function ChatRoom({ pool }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [connected, setConnected] = useState(false);
  const [initialLoaded, setInitialLoaded] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);

  // Load initial messages from snapshot
  useEffect(() => {
    fetchSnapshot(pool)
      .then((snap) => {
        setMessages(snap.chat.slice(-50));
        setInitialLoaded(true);
      })
      .catch(() => {
        setInitialLoaded(true);
      });
  }, [pool]);

  // Connect WebSocket
  useEffect(() => {
    const disconnect = createChatSocket(
      pool,
      (msg) => {
        setMessages((prev) => {
          const updated = [...prev, msg];
          // Keep last 200 messages
          return updated.slice(-200);
        });
      },
      setConnected
    );
    return disconnect;
  }, [pool]);

  // Auto-scroll
  useEffect(() => {
    if (autoScroll) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, autoScroll]);

  function handleScroll() {
    const el = containerRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    setAutoScroll(atBottom);
  }

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 flex flex-col h-full min-h-[500px]">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
        <h2 className="font-semibold text-gray-200">
          {pool === "crypto" ? "🔮 加密池交易廳" : "📈 美股池交易廳"}
        </h2>
        <div className="flex items-center gap-2">
          {connected ? (
            <span className="flex items-center gap-1.5 text-xs text-green-400">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500"></span>
              </span>
              即時串流
            </span>
          ) : (
            <span className="text-xs text-yellow-400 animate-pulse">
              連線中…
            </span>
          )}
          <span className="text-xs text-gray-500">{messages.length} 則訊息</span>
        </div>
      </div>

      {/* Messages */}
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto p-4 space-y-3 chat-scroll"
      >
        {!initialLoaded ? (
          <div className="flex items-center justify-center h-full">
            <p className="text-gray-500 animate-pulse">載入中…</p>
          </div>
        ) : messages.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <p className="text-gray-500">等待訊號…</p>
          </div>
        ) : (
          messages.map((msg, i) => <MessageRow key={i} msg={msg} />)
        )}
        <div ref={bottomRef} />
      </div>

      {/* Scroll-to-bottom hint */}
      {!autoScroll && (
        <div className="px-4 pb-3">
          <button
            onClick={() => {
              setAutoScroll(true);
              bottomRef.current?.scrollIntoView({ behavior: "smooth" });
            }}
            className="w-full text-xs text-gray-400 hover:text-white bg-gray-800 hover:bg-gray-700 rounded-lg py-1.5 transition-colors"
          >
            ↓ 滾到最新訊息
          </button>
        </div>
      )}
    </div>
  );
}

function MessageRow({ msg }: { msg: ChatMessage }) {
  const side = getSideFromContent(msg.content);
  const avatarColor = getAvatarColor(msg.from);

  return (
    <div className="flex gap-3 group">
      {/* Avatar */}
      <div
        className={`flex-shrink-0 w-9 h-9 rounded-full ${avatarColor} flex items-center justify-center text-sm font-bold text-white`}
      >
        {getInitial(msg.from)}
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        {/* Header row */}
        <div className="flex items-center flex-wrap gap-1.5 mb-0.5">
          <span className="font-semibold text-sm text-gray-200">{msg.from}</span>
          <span className="text-xs bg-gray-700 text-gray-300 px-1.5 py-0.5 rounded">
            {msg.school}
          </span>
          {msg.symbol && (
            <span className="text-xs font-mono text-blue-300 bg-blue-900/40 px-1.5 py-0.5 rounded">
              {msg.symbol}
            </span>
          )}
          {side === "LONG" && (
            <span className="text-xs font-bold text-green-400 bg-green-900/40 px-1.5 py-0.5 rounded">
              LONG ↑
            </span>
          )}
          {side === "SHORT" && (
            <span className="text-xs font-bold text-red-400 bg-red-900/40 px-1.5 py-0.5 rounded">
              SHORT ↓
            </span>
          )}
          {msg.confidence > 0 && (
            <span className="text-xs text-amber-400 ml-auto">
              {(msg.confidence * 100).toFixed(0)}% 信心
            </span>
          )}
        </div>

        {/* Message text */}
        <p className="text-sm text-gray-300 font-mono break-words">
          {msg.content}
        </p>

        {/* Timestamp */}
        <p className="text-xs text-gray-600 mt-0.5">
          {formatTime(msg.timestamp)}
        </p>
      </div>
    </div>
  );
}
