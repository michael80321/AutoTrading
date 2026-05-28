import type { Metadata } from "next";
import "./globals.css";
import NavBar from "@/components/NavBar";

export const metadata: Metadata = {
  title: "AI Trading Collective",
  description: "Real-time AI trading bot dashboard",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-TW">
      <body className="min-h-screen bg-gray-950 text-gray-100">
        <NavBar />
        <main className="pt-16">{children}</main>
      </body>
    </html>
  );
}
