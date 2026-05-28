export const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export const WS_URL = API_URL.replace(/^http/, "ws");

// ── Types ──────────────────────────────────────────────────────────────────

export type Pool = "crypto" | "stock";

export interface BotMetrics {
  win_rate: number;
  expectancy: number;
  total_trades: number;
  sharpe: number;
  max_drawdown: number;
}

export interface Bot {
  id: string;
  name: string;
  school: string;
  status: "active" | "breeding" | "sandbox" | "retired";
  metrics: BotMetrics;
  weight: number;
}

export interface ChatMessage {
  channel: string;
  timestamp: string;
  from: string;
  school: string;
  symbol: string;
  content: string;
  confidence: number;
}

export interface EvolutionEvent {
  timestamp: string;
  bot_name: string;
  action: string;
  note: string;
}

export interface PortfolioInfo {
  open_positions: number;
  realized_pnl: number;
  unrealized_pnl: number;
}

export interface PoolSnapshot {
  pool_name: string;
  channel: string;
  portfolio: Record<string, PortfolioInfo>;
  bots: Bot[];
  chat: ChatMessage[];
  evolution_events: EvolutionEvent[];
}

export interface HealthStatus {
  status: string;
  crypto_bots: number;
  stock_bots: number;
}

export interface PoolSignal {
  pool: string;
  open_positions: number;
  realized_pnl: number;
  active_bots: number;
}

// ── Fetch helpers ──────────────────────────────────────────────────────────

async function fetchJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    next: { revalidate: 0 },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<T>;
}

export async function fetchHealth(): Promise<HealthStatus> {
  return fetchJSON<HealthStatus>("/health");
}

export async function fetchSnapshot(pool: Pool): Promise<PoolSnapshot> {
  const endpoint = pool === "crypto" ? "crypto" : "stock";
  return fetchJSON<PoolSnapshot>(`/api/snapshot/${endpoint}`);
}

export async function fetchEvolution(
  pool: Pool
): Promise<{ events: EvolutionEvent[] }> {
  const endpoint = pool === "crypto" ? "crypto" : "stock";
  return fetchJSON<{ events: EvolutionEvent[] }>(
    `/api/evolution/${endpoint}`
  );
}

// ── WebSocket helpers ──────────────────────────────────────────────────────

export function createChatSocket(
  pool: Pool,
  onMessage: (msg: ChatMessage) => void,
  onStatusChange?: (connected: boolean) => void
): () => void {
  const endpoint = pool === "crypto" ? "crypto" : "stock";
  let ws: WebSocket | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let stopped = false;

  function connect() {
    if (stopped) return;
    try {
      ws = new WebSocket(`${WS_URL}/ws/chat/${endpoint}`);

      ws.onopen = () => {
        onStatusChange?.(true);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as ChatMessage;
          onMessage(data);
        } catch {
          // ignore parse errors
        }
      };

      ws.onerror = () => {
        onStatusChange?.(false);
      };

      ws.onclose = () => {
        onStatusChange?.(false);
        if (!stopped) {
          reconnectTimer = setTimeout(connect, 3000);
        }
      };
    } catch {
      onStatusChange?.(false);
      if (!stopped) {
        reconnectTimer = setTimeout(connect, 3000);
      }
    }
  }

  connect();

  return () => {
    stopped = true;
    if (reconnectTimer) clearTimeout(reconnectTimer);
    ws?.close();
  };
}

export function createSignalsSocket(
  onMessage: (signal: PoolSignal) => void,
  onStatusChange?: (connected: boolean) => void
): () => void {
  let ws: WebSocket | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let stopped = false;

  function connect() {
    if (stopped) return;
    try {
      ws = new WebSocket(`${WS_URL}/ws/signals`);

      ws.onopen = () => {
        onStatusChange?.(true);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as PoolSignal;
          onMessage(data);
        } catch {
          // ignore parse errors
        }
      };

      ws.onerror = () => {
        onStatusChange?.(false);
      };

      ws.onclose = () => {
        onStatusChange?.(false);
        if (!stopped) {
          reconnectTimer = setTimeout(connect, 3000);
        }
      };
    } catch {
      onStatusChange?.(false);
      if (!stopped) {
        reconnectTimer = setTimeout(connect, 3000);
      }
    }
  }

  connect();

  return () => {
    stopped = true;
    if (reconnectTimer) clearTimeout(reconnectTimer);
    ws?.close();
  };
}
