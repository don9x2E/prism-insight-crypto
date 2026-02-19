import type { Metadata } from 'next'

export const metadata: Metadata = {
  metadataBase: new URL('https://prism-insight.vercel.app'),
  title: 'PRISM-INSIGHT CRYPTO | AI-Powered Crypto Analysis & Paper Trading',
  description: 'AI agents analyze crypto markets in real-time, generate trading signals, and run paper trading automation. Open source and free to use.',
  keywords: [
    'crypto analysis',
    'AI trading',
    'paper trading',
    'crypto bot',
    'BTC benchmark',
    'trading bot',
    'investment AI',
    'open source trading'
  ],
  authors: [{ name: 'don9x2E' }],
  creator: 'PRISM-INSIGHT CRYPTO',
  publisher: 'PRISM-INSIGHT CRYPTO',
  robots: 'index, follow',
  openGraph: {
    type: 'website',
    locale: 'en_US',
    url: 'https://prism-insight.vercel.app/landing',
    siteName: 'PRISM-INSIGHT CRYPTO',
    title: 'PRISM-INSIGHT CRYPTO | AI-Powered Crypto Analysis & Paper Trading',
    description: 'AI agents analyze crypto markets in real-time. Open source and free to use.',
    images: [
      {
        url: '/og-image.png',
        width: 1200,
        height: 630,
        alt: 'PRISM-INSIGHT CRYPTO - AI Crypto Analysis',
      },
    ],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'PRISM-INSIGHT CRYPTO | AI Crypto Analysis',
    description: 'AI agents for crypto analysis and paper trading automation',
    images: ['/og-image.png'],
  },
  alternates: {
    canonical: 'https://prism-insight.vercel.app/landing',
  },
}

export default function LandingLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return children
}
