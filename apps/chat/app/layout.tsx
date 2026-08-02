import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "FounderBlaze Chat",
  description: "Chat with the FounderBlaze agent across A2MCP services",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
