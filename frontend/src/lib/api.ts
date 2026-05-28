const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function fetchJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`API ${path} failed: ${res.status}`);
  return res.json() as Promise<T>;
}

export interface BotInfo {
  id: string;
  name: string;
  school: string;
  status: string;
  weight: number;
  metrics: {
    win_rate: number;
    sharpe_ratio: number;
    max_drawdown: number;
    composite_score: number;
    total_trades: number;
    realized_pnl: number;
  };
}

export interface PortfolioInfo {
  total: number;
  available: number;
  open_positions: number;
  realized_pnl: number;
}

export interface ChatMessage {
  timestamp: string;
  from: string;
  school: string;
  symbol: string;
  content: string;
  confidence: number;
}

export interface PoolSnapshot {
  pool_name: string;
  channel: string;
  bots: BotInfo[];
  portfolio: { crypto_pool?: PortfolioInfo; stock_pool?: PortfolioInfo };
  chat: ChatMessage[];
  evolution_events: { timestamp: string; bot_name: string; action: string; note: string }[];
}
