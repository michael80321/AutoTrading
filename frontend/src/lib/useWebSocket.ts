"use client";
import { useEffect, useRef, useState } from "react";

const WS_BASE = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000")
  .replace(/^http/, "ws");

export function usePoolWebSocket(pool: "crypto" | "stock") {
  const [messages, setMessages] = useState<unknown[]>([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let ws: WebSocket;
    let pingTimer: ReturnType<typeof setInterval>;

    function connect() {
      ws = new WebSocket(`${WS_BASE}/ws/${pool}`);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        pingTimer = setInterval(() => ws.send("ping"), 20_000);
      };

      ws.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data as string);
          if (data === "pong") return;
          setMessages((prev) => [...prev.slice(-199), data]);
        } catch {}
      };

      ws.onclose = () => {
        setConnected(false);
        clearInterval(pingTimer);
        setTimeout(connect, 3_000);
      };
    }

    connect();
    return () => {
      clearInterval(pingTimer);
      wsRef.current?.close();
    };
  }, [pool]);

  return { messages, connected };
}
