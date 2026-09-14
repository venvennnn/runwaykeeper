"use client";

import React, { useEffect, useState } from "react";
import { Header } from "@/components/Header";
import { fetchApi, formatMoney } from "@/lib/api";
import { RotateCcw, Upload, CheckCircle2, AlertTriangle } from "lucide-react";

export default function SettingsPage() {
  const [settings, setSettings] = useState<any>(null);
  const [bufferInput, setBufferInput] = useState("");
  const [resetting, setResetting] = useState(false);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);

  // Inbound simulation test form
  const [inboundFrom, setInboundFrom] = useState("ap@northwind.test");
  const [inboundRef, setInboundRef] = useState("INV-1042");
  const [inboundBody, setInboundBody] = useState(
    "This invoice was already paid. Reference INV-1042."
  );
  const [inboundResult, setInboundResult] = useState<any>(null);

  async function loadSettings() {
    try {
      const res = await fetchApi("/api/settings");
      setSettings(res);
      setBufferInput(((res.buffer_minor || 0) / 100).toFixed(2));
    } catch (e) {
      console.error(e);
    }
  }

  useEffect(() => {
    loadSettings();
  }, []);

  async function handleResetSimulation() {
    if (!confirm("Reset simulation to fictional seed agency?")) return;
    setResetting(true);
    setStatusMsg(null);
    try {
      await fetchApi("/api/simulation/reset", { method: "POST" });
      setStatusMsg("Simulation state reset successfully to Harbour Studio seed.");
      await loadSettings();
    } catch (e: any) {
      setStatusMsg(`Reset error: ${e.message}`);
    } finally {
      setResetting(false);
    }
  }

  async function handleSaveBuffer() {
    setStatusMsg(null);
    try {
      await fetchApi("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ buffer: bufferInput }),
      });
      setStatusMsg("Buffer requirement updated.");
      await loadSettings();
    } catch (e: any) {
      setStatusMsg(`Error: ${e.message}`);
    }
  }

  async function handleSendTestInbound() {
    setInboundResult(null);
    try {
      const res = await fetchApi("/api/simulation/inbound", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          from_email: inboundFrom,
          subject: "Test Inbound",
          body: inboundBody,
          invoice_reference: inboundRef,
        }),
      });
      setInboundResult(res);
    } catch (e: any) {
      setInboundResult({ error: e.message });
    }
  }

  return (
    <div className="min-h-screen bg-[#ffffff]">
      <Header mode={settings?.mode} />

      <main className="max-w-4xl mx-auto px-6 py-8 space-y-8">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-slate-900">
            Data, Imports & Settings
          </h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Configure required cash buffers, reminder cooldowns, provider credentials, and test simulations.
          </p>
        </div>

        {statusMsg && (
          <div className="text-xs px-3 py-2 bg-slate-50 border border-slate-200 rounded-md text-slate-700">
            {statusMsg}
          </div>
        )}

        {/* Cash Buffer & Cooldown settings */}
        <section className="p-6 border border-gray-100 rounded-xl bg-white space-y-4">
          <h2 className="text-sm font-semibold text-slate-900">Workspace Policy</h2>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs text-slate-600 block mb-1">
                Required Cash Buffer ($)
              </label>
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={bufferInput}
                  onChange={(e) => setBufferInput(e.target.value)}
                  className="text-xs border border-gray-200 rounded px-2.5 py-1.5 font-mono w-44"
                />
                <button
                  onClick={handleSaveBuffer}
                  className="text-xs px-3 py-1.5 bg-slate-900 text-white rounded font-medium hover:bg-slate-800"
                >
                  Save
                </button>
              </div>
            </div>

            <div>
              <div className="text-xs text-slate-600">Reminder Cooldown</div>
              <div className="text-xs font-mono text-slate-900 mt-1">
                {settings?.reminder_cooldown_hours ?? 72} hours (max {settings?.max_reminders_per_case ?? 3} reminders)
              </div>
            </div>
          </div>
        </section>

        {/* Resettable Simulation Controls */}
        <section className="p-6 border border-amber-200 rounded-xl bg-amber-50/30 space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-sm font-semibold text-slate-900">
                Resettable Simulation Controls
              </h2>
              <p className="text-xs text-slate-500 mt-0.5">
                Simulation mode captures outgoing messages and never displays them as real delivery.
              </p>
            </div>
            <button
              onClick={handleResetSimulation}
              disabled={resetting}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-white border border-gray-300 text-slate-700 text-xs font-medium rounded-full hover:bg-slate-50 disabled:opacity-50"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              {resetting ? "Resetting..." : "Reset Simulation"}
            </button>
          </div>

          {/* Test Inbound Route */}
          <div className="pt-4 border-t border-amber-200/60 space-y-3">
            <h3 className="text-xs font-semibold text-slate-900">
              Trigger Inbound Test Message (Simulation Only)
            </h3>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <input
                type="text"
                value={inboundFrom}
                onChange={(e) => setInboundFrom(e.target.value)}
                placeholder="From Email"
                className="border rounded p-1.5 font-mono text-[11px]"
              />
              <input
                type="text"
                value={inboundRef}
                onChange={(e) => setInboundRef(e.target.value)}
                placeholder="Invoice Ref"
                className="border rounded p-1.5 font-mono text-[11px]"
              />
            </div>
            <textarea
              rows={2}
              value={inboundBody}
              onChange={(e) => setInboundBody(e.target.value)}
              className="w-full text-xs font-mono p-2 border rounded"
            />
            <button
              onClick={handleSendTestInbound}
              className="text-xs px-3 py-1.5 bg-slate-900 text-white rounded font-medium hover:bg-slate-800"
            >
              Send Inbound Event
            </button>

            {inboundResult && (
              <pre className="p-3 bg-white rounded border text-[11px] font-mono text-slate-700 overflow-x-auto">
                {JSON.stringify(inboundResult, null, 2)}
              </pre>
            )}
          </div>
        </section>

        {/* Integration Credentials Placeholders */}
        <section className="p-6 border border-gray-100 rounded-xl bg-white space-y-3 text-xs">
          <h2 className="text-sm font-semibold text-slate-900">Deployment & Bedrock</h2>
          <div className="grid grid-cols-2 gap-4 font-mono text-slate-600">
            <div>
              <span className="text-[10px] uppercase text-slate-400 block font-sans">
                AWS Builder ID
              </span>
              <span>{settings?.aws_builder_id_placeholder}</span>
            </div>
            <div>
              <span className="text-[10px] uppercase text-slate-400 block font-sans">
                Deployment URL
              </span>
              <span>{settings?.deployment_url_placeholder}</span>
            </div>
            <div>
              <span className="text-[10px] uppercase text-slate-400 block font-sans">
                Bedrock Model ID
              </span>
              <span>{settings?.bedrock?.model_id}</span>
            </div>
            <div>
              <span className="text-[10px] uppercase text-slate-400 block font-sans">
                AWS Region
              </span>
              <span>{settings?.bedrock?.region}</span>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
