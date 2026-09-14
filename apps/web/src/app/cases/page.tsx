"use client";

import React, { useEffect, useState } from "react";
import { Header } from "@/components/Header";
import { fetchApi, formatMoney } from "@/lib/api";
import { Clock, Mail, ShieldCheck, AlertCircle } from "lucide-react";

export default function CasesPage() {
  const [cases, setCases] = useState<any[]>([]);
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);
  const [detail, setDetail] = useState<any>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  async function loadCases() {
    try {
      const res = await fetchApi("/api/cases");
      setCases(res.cases || []);
      if (res.cases?.length > 0 && !selectedCaseId) {
        setSelectedCaseId(res.cases[0].id);
      }
    } catch (e) {
      console.error(e);
    }
  }

  useEffect(() => {
    loadCases();
  }, []);

  useEffect(() => {
    if (!selectedCaseId) return;
    setLoadingDetail(true);
    fetchApi(`/api/cases/${selectedCaseId}`)
      .then(setDetail)
      .catch(console.error)
      .finally(() => setLoadingDetail(false));
  }, [selectedCaseId]);

  return (
    <div className="min-h-screen bg-[#ffffff]">
      <Header />

      <main className="max-w-6xl mx-auto px-6 py-8">
        <div className="mb-6">
          <h1 className="text-xl font-semibold tracking-tight text-slate-900">
            Invoice Cases & Provenance
          </h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Track collection states, customer permissions, chronological actions, and immutable ledger balance.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-12 gap-6">
          {/* Left: Case List */}
          <div className="md:col-span-5 border border-gray-100 rounded-xl overflow-hidden divide-y divide-gray-100">
            {cases.map((c) => {
              const active = c.id === selectedCaseId;
              return (
                <button
                  key={c.id}
                  onClick={() => setSelectedCaseId(c.id)}
                  className={`w-full text-left p-4 transition-colors ${
                    active ? "bg-slate-50" : "hover:bg-slate-50/50"
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-xs font-semibold text-slate-900">
                      {c.external_reference}
                    </span>
                    <span className="font-mono text-xs font-medium text-slate-900">
                      {formatMoney(c.outstanding_minor)}
                    </span>
                  </div>
                  <div className="text-xs text-slate-600 mt-1">
                    {c.customer_name}
                  </div>
                  <div className="flex items-center gap-2 mt-2">
                    <span className="badge-pill bg-slate-100 text-slate-700 text-[10px]">
                      {c.collection_state}
                    </span>
                    <span className="text-[10px] text-slate-400">
                      Due {c.due_date}
                    </span>
                  </div>
                </button>
              );
            })}
          </div>

          {/* Right: Case Detail & Auditable Timeline */}
          <div className="md:col-span-7 border border-gray-100 rounded-xl p-6">
            {detail ? (
              <div className="space-y-6">
                <div className="flex items-start justify-between pb-4 border-b border-gray-100">
                  <div>
                    <h2 className="text-lg font-semibold font-mono text-slate-900">
                      {detail.external_reference}
                    </h2>
                    <div className="text-xs text-slate-600 mt-0.5">
                      Customer: <span className="font-medium text-slate-900">{detail.customer_name}</span> ({detail.customer_email})
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-xs text-slate-400 uppercase">Outstanding</div>
                    <div className="text-xl font-semibold font-mono text-slate-900">
                      {formatMoney(detail.outstanding_minor)}
                    </div>
                  </div>
                </div>

                {/* Evidence & Permissions Badges */}
                <div className="grid grid-cols-2 gap-3 text-xs">
                  <div className="p-3 bg-slate-50 rounded-lg border border-slate-100">
                    <div className="text-[10px] text-slate-400 uppercase font-semibold">
                      Recipient Permissions
                    </div>
                    <div className="mt-1 flex items-center gap-1.5 text-slate-700">
                      {detail.email_verified && detail.contact_permission ? (
                        <>
                          <ShieldCheck className="w-3.5 h-3.5 text-teal-600" />
                          <span>Verified & opt-in granted</span>
                        </>
                      ) : (
                        <>
                          <AlertCircle className="w-3.5 h-3.5 text-amber-600" />
                          <span>Unverified or contact denied</span>
                        </>
                      )}
                    </div>
                  </div>

                  <div className="p-3 bg-slate-50 rounded-lg border border-slate-100">
                    <div className="text-[10px] text-slate-400 uppercase font-semibold">
                      Sensitivity Impact
                    </div>
                    <div className="mt-1 text-slate-700 font-mono">
                      +{formatMoney(detail.cash_gap_sensitivity_minor)} cash-gap
                    </div>
                  </div>
                </div>

                {/* Chronological Messages */}
                <div>
                  <h3 className="text-xs font-semibold text-slate-900 uppercase tracking-tight mb-3">
                    Captured & Sent Messages
                  </h3>
                  {detail.messages?.length > 0 ? (
                    <div className="space-y-2">
                      {detail.messages.map((m: any) => (
                        <div
                          key={m.id}
                          className="p-3 bg-slate-50 border border-slate-100 rounded-lg text-xs space-y-1"
                        >
                          <div className="flex items-center justify-between">
                            <span className="font-semibold text-slate-900">
                              {m.direction === "outbound" ? "Outbound reminder" : "Inbound reply"}
                            </span>
                            <span className="badge-pill bg-slate-200 text-slate-700 text-[9px]">
                              {m.delivery_label}
                            </span>
                          </div>
                          <div className="text-slate-600">{m.subject}</div>
                          <div className="text-slate-500 font-mono text-[11px] bg-white p-2 rounded border border-slate-100 whitespace-pre-wrap">
                            {m.body_excerpt}
                          </div>
                          <div className="text-[10px] text-slate-400">
                            {new Date(m.at).toLocaleString()}
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="text-xs text-slate-400 italic">No messages on this case yet.</div>
                  )}
                </div>

                {/* Auditable Timeline */}
                <div>
                  <h3 className="text-xs font-semibold text-slate-900 uppercase tracking-tight mb-3">
                    Audit Event Timeline
                  </h3>
                  <div className="space-y-2">
                    {detail.timeline?.map((e: any) => (
                      <div key={e.id} className="text-xs flex items-start gap-2.5">
                        <Clock className="w-3.5 h-3.5 text-slate-400 mt-0.5 shrink-0" />
                        <div>
                          <span className="font-medium text-slate-800">{e.event_type}</span>
                          {e.case_version && (
                            <span className="text-slate-400 ml-1.5 font-mono text-[10px]">
                              (v{e.case_version})
                            </span>
                          )}
                          <div className="text-slate-500 text-[11px]">
                            {JSON.stringify(e.payload)}
                          </div>
                          <div className="text-[10px] text-slate-400">
                            {new Date(e.at).toLocaleString()}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            ) : (
              <div className="p-8 text-center text-xs text-slate-400">
                Select an invoice case to view details and timeline.
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
