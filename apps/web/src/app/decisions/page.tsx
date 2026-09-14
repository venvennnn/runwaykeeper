"use client";

import React, { useEffect, useState } from "react";
import { Header } from "@/components/Header";
import { fetchApi } from "@/lib/api";
import { Check, X, ShieldAlert, Sparkles } from "lucide-react";

export default function DecisionsPage() {
  const [approvals, setApprovals] = useState<any[]>([]);
  const [feedback, setFeedback] = useState<string | null>(null);

  async function loadApprovals() {
    try {
      const res = await fetchApi("/api/approvals");
      setApprovals(res.approvals || []);
    } catch (e) {
      console.error(e);
    }
  }

  useEffect(() => {
    loadApprovals();
  }, []);

  async function handleDecide(id: string, approve: boolean) {
    setFeedback(null);
    try {
      await fetchApi(`/api/approvals/${id}/decide`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approve }),
      });
      setFeedback(`Decision recorded: ${approve ? "Approved" : "Rejected"}`);
      await loadApprovals();
    } catch (e: any) {
      setFeedback(`Error: ${e.message}`);
    }
  }

  return (
    <div className="min-h-screen bg-[#ffffff]">
      <Header />

      <main className="max-w-4xl mx-auto px-6 py-8">
        <div className="mb-6">
          <h1 className="text-xl font-semibold tracking-tight text-slate-900">
            Owner Decisions & Approvals
          </h1>
          <p className="text-xs text-slate-500 mt-0.5">
            RunwayKeeper isolates exceptions requiring human judgment: amount changes, terms, disputes, and ambiguous matches.
          </p>
        </div>

        {feedback && (
          <div className="mb-4 text-xs px-3 py-2 bg-slate-50 border border-slate-200 rounded-md text-slate-700">
            {feedback}
          </div>
        )}

        <div className="space-y-4">
          {approvals.length > 0 ? (
            approvals.map((a) => {
              const isPending = a.status === "pending";
              return (
                <div
                  key={a.id}
                  className="p-5 border border-gray-100 rounded-xl bg-white shadow-sm"
                >
                  <div className="flex items-start justify-between">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="badge-pill bg-slate-100 text-slate-700 text-[10px]">
                          {a.kind}
                        </span>
                        <h2 className="text-sm font-semibold text-slate-900">
                          {a.title}
                        </h2>
                      </div>
                      <p className="text-xs text-slate-600 mt-2">{a.summary}</p>
                    </div>

                    <span
                      className={`badge-pill text-[10px] uppercase font-semibold ${
                        a.status === "approved"
                          ? "bg-teal-50 text-teal-800 border border-teal-200"
                          : a.status === "rejected"
                          ? "bg-red-50 text-red-800 border border-red-200"
                          : "bg-amber-50 text-amber-800 border border-amber-200"
                      }`}
                    >
                      {a.status}
                    </span>
                  </div>

                  {a.proposed_payload && Object.keys(a.proposed_payload).length > 0 && (
                    <div className="mt-3 p-3 bg-slate-50 rounded border border-slate-100 font-mono text-[11px] text-slate-600">
                      {JSON.stringify(a.proposed_payload, null, 2)}
                    </div>
                  )}

                  {isPending && (
                    <div className="mt-4 pt-3 border-t border-gray-100 flex items-center justify-end gap-2">
                      <button
                        onClick={() => handleDecide(a.id, false)}
                        className="inline-flex items-center gap-1 px-3 py-1.5 rounded-full text-xs font-medium text-slate-600 hover:bg-slate-100 transition-colors"
                      >
                        <X className="w-3.5 h-3.5" /> Reject
                      </button>
                      <button
                        onClick={() => handleDecide(a.id, true)}
                        className="inline-flex items-center gap-1 px-3 py-1.5 rounded-full bg-slate-900 text-white text-xs font-medium hover:bg-slate-800 transition-colors"
                      >
                        <Check className="w-3.5 h-3.5" /> Approve
                      </button>
                    </div>
                  )}
                </div>
              );
            })
          ) : (
            <div className="p-12 text-center text-xs text-slate-400 border border-dashed rounded-xl">
              No approval cards pending. All standard follow-up workflows are operating within policy guards.
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
