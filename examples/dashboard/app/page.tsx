"use client"

import { Suspense } from "react"
import { useSearchParams, useRouter } from "next/navigation"
import { DashboardHeader } from "@/components/dashboard-header"
import { CryptoBenchmarkPage } from "@/components/crypto-benchmark-page"
import { ProjectFooter } from "@/components/project-footer"

type TabType = "dashboard" | "ai-decisions" | "trading" | "watchlist" | "insights" | "jeoningu-lab" | "crypto-benchmark"

function LoadingSpinner() {
  return (
    <div className="flex items-center justify-center min-h-screen">
      <div className="text-center">
        <div className="w-16 h-16 border-4 border-primary border-t-transparent rounded-full animate-spin mx-auto mb-4" />
        <p className="text-muted-foreground">Loading...</p>
      </div>
    </div>
  )
}

function DashboardContent() {
  const searchParams = useSearchParams()
  const router = useRouter()

  const handleTabChange = (tab: TabType) => {
    if (tab !== "crypto-benchmark") return
    const params = new URLSearchParams(searchParams.toString())
    params.set("tab", "crypto-benchmark")
    const queryString = params.toString()
    router.push(queryString ? `?${queryString}` : "/", { scroll: false })
  }

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

export default function Page() {
  return (
    <Suspense fallback={<LoadingSpinner />}>
      <DashboardContent />
    </Suspense>
  )
}
