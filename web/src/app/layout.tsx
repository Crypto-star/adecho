import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Troopod — Ad-personalized landing pages",
  description:
    "Upload an ad + paste a landing page URL. Get your page enhanced in-place to match the ad.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
