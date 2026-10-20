import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

export const metadata: Metadata = {
  title: "JL Engine — Autonomous Agent Infrastructure",
  description:
    "Production-ready autonomous agent runtime. Behavioral middleware that scores signals, models state, and acts through real tools — not a chatbot wrapper.",
  openGraph: {
    title: "JL Engine — Autonomous Agent Infrastructure",
    description:
      "Production-ready autonomous agent runtime built in Julia. Runtime tool forge, A2A protocol, MCP bridge, and a full behavioral state machine.",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={inter.variable}>
      <body className="antialiased">{children}</body>
    </html>
  );
}
