"use client"

import { DashboardHeader } from "@/components/dashboard-header"
import { CryptoBenchmarkPage } from "@/components/crypto-benchmark-page"
import { ProjectFooter } from "@/components/project-footer"

type TabType = "dashboard" | "ai-decisions" | "trading" | "watchlist" | "insights" | "jeoningu-lab" | "crypto-benchmark"

export default function Page() {
  const handleTabChange = (_tab: TabType) => {}

  return (
    <div className="min-h-screen bg-background">
      <DashboardHeader
        activeTab="crypto-benchmark"
        onTabChange={handleTabChange}
      />
      <main className="container mx-auto px-4 py-6 max-w-[1600px]">
        <CryptoBenchmarkPage />
      </main>
      <ProjectFooter />
    </div>
  )
}
