"use client";

import React, { useEffect, useState } from "react";
import { Header } from "@/components/Header";
import { ForecastChart } from "@/components/ForecastChart";
import { fetchApi, formatMoney } from "@/lib/api";
import Link from "next/link";
import { ArrowUpRight, ShieldAlert, Sparkles, CheckCircle2 } from "lucide-react";

export default function OverviewPage() {
  const [data, setData] = useState<any>(null);
  const [selectedDay, setSelectedDay] = useState<string | null>(null);
  const [runningAgent, setRunningAgent] = useState(false);
  const [agentMsg, setAgentMsg] = useState<string | null>(null);

  async function loadOverview() {
    try {
      const res = await fetchApi("/api/overview");
      setData(res);
      if (res?.forecast?.days?.length > 0 && !selectedDay) {
        setSelectedDay(res.forecast.days[0].day);
      }
    } catch (e: any) {
      console.error(e);
    }
  }

  useEffect(() => {
    loadOverview();
  }, []);

  async function handleRunAgent() {
    setRunningAgent(true);
    setAgentMsg(null);
    try {
      const res = await fetchApi("/api/simulation/run-agent", { method: "POST" });
      setAgentMsg(`Strands executed: ${res.action} (${res.tool_calls?.length || 0} tool calls)`);
      await loadOverview();
    } catch (e: any) {
      setAgentMsg(`Agent error: ${e.message}`);
    } finally {
      setRunningAgent(false);
    }
  }

  const forecast = data?.forecast;
  const currentCash = data?.current_cash_minor ?? 0;
  const buffer = data?.buffer_minor ?? 0;
  const breachProb = forecast?.breach_probability ?? 0;
  const pathMin = forecast?.median_path_minimum_minor ?? 0;
  const outstanding = data?.outstanding_minor ?? 0;

  const dayDetail = forecast?.days?.find((d: any) => d.day === selectedDay);

  return (
    <div className="min-h-screen bg-[#ffffff]">
      <Header mode={data?.mode} />

      <main className="max-w-6xl mx-auto px-6 py-8">
        {/* Top Minimal Metrics Bar - CALL-E inspired spacious minimalism */}
        <section className="grid grid-cols-2 md:grid-cols-4 gap-4 pb-8 border-b border-gray-100">
          <div>
            <div className="text-[11px] font-medium tracking-tight text-slate-500 uppercase">
              Current Cash Balance
            </div>
            <div className="text-2xl font-semibold tracking-tight text-slate-900 mt-1">
              {formatMoney(currentCash)}
            </div>
            <div className="text-[11px] text-slate-400 mt-0.5">
              As of {data?.cash_effective_at ? new Date(data.cash_effective_at).toLocaleDateString() : "—"}
            </div>
          </div>

          <div>
            <div className="text-[11px] font-medium tracking-tight text-slate-500 uppercase">
              Projected Path Minimum
            </div>
            <div
              className={`text-2xl font-semibold tracking-tight mt-1 ${
                pathMin < buffer ? "text-red-600" : "text-slate-900"
              }`}
            >
              {formatMoney(pathMin)}
            </div>
            <div className="text-[11px] text-slate-400 mt-0.5">
              Buffer requirement: {formatMoney(buffer)}
            </div>
          </div>

          <div>
            <div className="text-[11px] font-medium tracking-tight text-slate-500 uppercase">
              Shortfall Risk (30d)
            </div>
            <div
              className={`text-2xl font-semibold tracking-tight mt-1 ${
                breachProb > 0.2 ? "text-red-600" : "text-teal-700"
              }`}
            >
              {(breachProb * 100).toFixed(1)}%
            </div>
            <div className="text-[11px] text-slate-400 mt-0.5">
              Conditional on assumptions
            </div>
          </div>

          <div>
            <div className="text-[11px] font-medium tracking-tight text-slate-500 uppercase">
              Outstanding Invoices
            </div>
            <div className="text-2xl font-semibold tracking-tight text-slate-900 mt-1">
              {formatMoney(outstanding)}
            </div>
            <div className="text-[11px] text-slate-400 mt-0.5">
              Across open cases
            </div>
          </div>
        </section>

        {/* Forecast Section */}
        <section className="py-8">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-base font-semibold tracking-tight text-slate-900">
                30-Day Daily Cash Forecast
              </h2>
              <p className="text-xs text-slate-500 mt-0.5">
                Deterministic numerical simulation (2,000 seeded scenarios). Click any day to inspect contributors.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={handleRunAgent}
                disabled={runningAgent}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-slate-900 text-white text-xs font-medium hover:bg-slate-800 transition-colors disabled:opacity-50"
              >
                <Sparkles className="w-3.5 h-3.5 text-teal-400" />
                {runningAgent ? "Running Strands..." : "Run autonomous check"}
              </button>
            </div>
          </div>

          {agentMsg && (
            <div className="mb-4 text-xs px-3 py-2 bg-slate-50 border border-slate-200 rounded-md text-slate-700 flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-teal-600 shrink-0" />
              <span>{agentMsg}</span>
            </div>
          )}

          {forecast ? (
            <div className="bg-white border border-gray-100 rounded-xl p-4">
              <ForecastChart
                days={forecast.days}
                bufferMinor={buffer}
                sharedDelayPath={forecast.shared_delay_path}
                onSelectDay={(day) => setSelectedDay(day)}
              />

              {/* Day contributors inspector */}
              {dayDetail && (
                <div className="mt-4 pt-4 border-t border-gray-100">
                  <div className="flex items-center justify-between text-xs mb-2">
                    <span className="font-semibold text-slate-900">
                      Contributors for {dayDetail.day}
                    </span>
                    <span className="text-slate-500 font-mono">
                      Median balance: {formatMoney(dayDetail.p50_minor)}
                    </span>
                  </div>

                  {dayDetail.contributors?.length > 0 ? (
                    <div className="space-y-1.5">
                      {dayDetail.contributors.map((c: any, i: number) => (
                        <div
                          key={i}
                          className="flex items-center justify-between text-xs py-1.5 px-2.5 rounded bg-slate-50 border border-slate-100"
                        >
                          <div className="flex items-center gap-2">
                            <span
                              className={`w-1.5 h-1.5 rounded-full ${
                                c.kind === "inflow" ? "bg-teal-600" : "bg-red-500"
                              }`}
                            />
                            <span className="font-medium text-slate-800">{c.label}</span>
                            <span className="text-[11px] text-slate-400">
                              ({c.timing_note})
                            </span>
                          </div>
                          <span
                            className={`font-mono font-medium ${
                              c.amount_minor > 0 ? "text-teal-700" : "text-red-600"
                            }`}
                          >
                            {formatMoney(c.amount_minor)}
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="text-xs text-slate-400 italic py-2">
                      No explicit inflows or expenses scheduled on this day.
                    </div>
                  )}
                </div>
              )}

              {/* Disclaimers & Data Quality Notes */}
              <div className="mt-4 pt-4 border-t border-gray-100 text-[11px] text-slate-500 space-y-1">
                <p>{forecast.scenario_disclaimer}</p>
                {forecast.data_quality_notes?.map((n: string, i: number) => (
                  <p key={i} className="text-slate-400">
                    • {n}
                  </p>
                ))}
              </div>
            </div>
          ) : (
            <div className="text-xs text-slate-400 p-8 border border-dashed rounded-xl text-center">
              Loading deterministic forecast...
            </div>
          )}
        </section>

        {/* Prioritised Follow-ups */}
        <section className="py-6">
          <div className="flex items-center justify-between mb-3">
            <div>
              <h2 className="text-base font-semibold tracking-tight text-slate-900">
                Actionable Follow-up Queue
              </h2>
              <p className="text-xs text-slate-500">
                Ranked by cash-gap sensitivity (impact on projected maximum deficit), then days overdue.
              </p>
            </div>
            <Link
              href="/cases"
              className="text-xs text-teal-700 hover:text-teal-800 font-medium flex items-center gap-1"
            >
              View all cases <ArrowUpRight className="w-3.5 h-3.5" />
            </Link>
          </div>

          <div className="border border-gray-100 rounded-xl overflow-hidden divide-y divide-gray-100">
            {data?.ranked?.length > 0 ? (
              data.ranked.map((c: any) => (
                <div
                  key={c.case_id}
                  className="p-4 hover:bg-slate-50/60 transition-colors flex items-center justify-between"
                >
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs font-semibold text-slate-900">
                        {c.external_reference}
                      </span>
                      <span className="text-xs text-slate-600">— {c.customer_name}</span>
                      <span className="badge-pill bg-slate-100 text-slate-700 text-[10px]">
                        {c.collection_state}
                      </span>
                    </div>
                    <div className="text-xs text-slate-500 mt-1">
                      {c.priority_reason}
                    </div>
                  </div>

                  <div className="text-right">
                    <div className="font-mono text-sm font-semibold text-slate-900">
                      {formatMoney(c.outstanding_minor)}
                    </div>
                    <div className="text-[11px] text-teal-700 font-medium">
                      +{formatMoney(c.cash_gap_sensitivity_minor)} sensitivity
                    </div>
                  </div>
                </div>
              ))
            ) : (
              <div className="p-8 text-center text-xs text-slate-400">
                No open overdue cases currently eligible after cooldown and verification filters.
              </div>
            )}
          </div>
        </section>
      </main>
    </div>
  );
}
