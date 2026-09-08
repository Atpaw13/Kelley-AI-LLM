import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Kelley AI Prototype",
  description: "A local proof-of-concept conversational information layer for Kelley source material.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
