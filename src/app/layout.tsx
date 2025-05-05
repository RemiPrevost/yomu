import type { Metadata } from "next";
import { Sniglet } from "next/font/google";
import "./globals.css";

const geistRegular = Sniglet({
  variable: "--font-sniglet-regular",
  subsets: ["latin"],
  weight: "400",
});

const geistBold = Sniglet({
  variable: "--font-sniglet-bold",
  subsets: ["latin"],
  weight: "800",
});

export const metadata: Metadata = {
  title: "Yomu",
  description: "Learn your Japanese words with Yomu",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className={`${geistRegular.variable} ${geistBold.variable}`}>
        {children}
      </body>
    </html>
  );
}
