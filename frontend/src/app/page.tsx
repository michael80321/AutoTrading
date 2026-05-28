import Link from "next/link";

export default function Home() {
  return (
    <main className="min-h-screen bg-gray-950 text-white flex flex-col items-center justify-center p-8">
      <h1 className="text-4xl font-bold mb-2">AI Trading Collective</h1>
      <p className="text-gray-400 mb-10 text-lg">雙池 36 席分析師交易系統</p>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 w-full max-w-2xl">
        <Link
          href="/crypto"
          className="bg-gray-900 hover:bg-gray-800 border border-yellow-500/30 hover:border-yellow-500 rounded-2xl p-8 transition-all"
        >
          <div className="text-4xl mb-3">₿</div>
          <h2 className="text-2xl font-semibold text-yellow-400 mb-1">加密池</h2>
          <p className="text-gray-400 text-sm">18 席分析師 · $5,400 USDT · Binance</p>
          <p className="text-gray-500 text-xs mt-2">SMC · 訂單流 · 鏈上 · 套利 · 拍賣理論</p>
        </Link>

        <Link
          href="/equity"
          className="bg-gray-900 hover:bg-gray-800 border border-blue-500/30 hover:border-blue-500 rounded-2xl p-8 transition-all"
        >
          <div className="text-4xl mb-3">📈</div>
          <h2 className="text-2xl font-semibold text-blue-400 mb-1">美股池</h2>
          <p className="text-gray-400 text-sm">18 席分析師 · $5,400 USD · IBKR</p>
          <p className="text-gray-500 text-xs mt-2">拍賣理論 · 量化統計 · 財報事件 · 期權流</p>
        </Link>
      </div>
    </main>
  );
}
