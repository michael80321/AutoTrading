"use client";

import { useCallback, useState } from "react";
import PoolStats from "@/components/PoolStats";
import ChatRoom from "@/components/ChatRoom";
import SignalWall from "@/components/SignalWall";
import BotGrid from "@/components/BotGrid";
import type { PoolSignal } from "@/lib/api";

export default function EquityPage() {
  const [latestSignal, setLatestSignal] = useState<PoolSignal | null>(null);

  const handleSignalUpdate = useCallback((signal: PoolSignal) => {
    setLatestSignal(signal);
  }, []);

  return (
    <div className="max-w-screen-2xl mx-auto px-4 py-6">
      {/* Pool Stats Header */}
      <PoolStats
        pool="stock"
        signalActiveBots={latestSignal?.active_bots}
      />

      {/* Main two-column layout */}
      <div className="flex gap-4 mb-6" style={{ minHeight: "560px" }}>
        {/* Left 60%: ChatRoom */}
        <div className="flex-none" style={{ width: "60%" }}>
          <ChatRoom pool="stock" />
        </div>

        {/* Right 40%: SignalWall */}
        <div className="flex-none" style={{ width: "40%" }}>
          <SignalWall pool="stock" onSignalUpdate={handleSignalUpdate} />
        </div>
      </div>

      {/* BotGrid below */}
      <BotGrid pool="stock" />
    </div>
  );
}
