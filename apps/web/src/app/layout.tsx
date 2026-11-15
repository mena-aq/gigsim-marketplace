import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = { title: "GigBid", description: "Your freelance work, with you in control." };
export default function Layout({ children }: { children: React.ReactNode }) {
  return <html lang="en"><body>{children}</body></html>;
}
