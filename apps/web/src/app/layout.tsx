import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "RunwayKeeper — Autonomous Cash-Flow Operations",
  description:
    "Cash-flow analyst and invoice follow-up operations agent for small agencies.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-[#ffffff] text-[#0a0f1d] antialiased">
        {children}
      </body>
    </html>
  );
}
