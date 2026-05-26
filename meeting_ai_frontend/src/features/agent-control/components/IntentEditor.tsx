import { 
  Shield, Zap, Database, MessageSquare, Wrench, Check,
  Sparkles, Layers, Terminal, Globe, Lock
} from "lucide-react";
import type { IntentProfile } from "../types";

interface IntentEditorProps {
  intent: IntentProfile;
  onChange: (intent: IntentProfile) => void;
  loading?: boolean;
}

export default function IntentEditor({ intent, onChange }: IntentEditorProps) {
  const updateSection = (section: keyof IntentProfile, fields: any) => {
    onChange({
      ...intent,
      [section]: { ...intent[section], ...fields },
    });
  };

  const Toggle = ({ checked, onChange: onToggle }: { checked: boolean; onChange: (v: boolean) => void }) => (
    <button
      onClick={() => onToggle(!checked)}
      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-indigo-600 focus:ring-offset-2 ${
        checked ? "bg-indigo-600 shadow-inner" : "bg-gray-200"
      }`}
    >
      <span
        className={`inline-block h-4 w-4 transform rounded-full bg-white shadow-md transition-transform duration-200 ${
          checked ? "translate-x-6" : "translate-x-1"
        }`}
      />
    </button>
  );

  const SectionHeader = ({ icon: Icon, title, desc, colorClass }: { icon: any, title: string, desc?: string, colorClass: string }) => (
    <div className="flex items-center gap-4 mb-6">
      <div className={`p-2.5 rounded-xl ${colorClass} shadow-sm border border-white/20`}>
        <Icon className="w-5 h-5" />
      </div>
      <div>
        <h2 className="text-xl font-bold text-gray-900 tracking-tight">{title}</h2>
        {desc && <p className="text-sm text-gray-500 font-medium">{desc}</p>}
      </div>
    </div>
  );

  return (
    <div className="space-y-12 pb-20">
      {/* 1. AI Behavior */}
      <section className="relative group">
        <SectionHeader 
          icon={Sparkles} 
          title="AI Behavior" 
          desc="Define the personality and communication style of your assistant."
          colorClass="bg-indigo-600 text-white"
        />
        <div className="bg-white border border-gray-200 rounded-2xl shadow-sm p-8 space-y-8 hover:border-indigo-200 transition-colors">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
            <div className="space-y-2.5">
              <label className="block text-sm font-bold text-gray-700 ml-1 uppercase tracking-wider">Role / Focus</label>
              <input
                type="text"
                value={intent.behavior.role_focus}
                onChange={(e) => updateSection("behavior", { role_focus: e.target.value })}
                className="w-full px-5 py-3 bg-gray-50 border border-gray-200 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 focus:bg-white outline-none transition-all font-medium text-gray-900"
                placeholder="e.g. Backend engineering assistant"
              />
            </div>
            <div className="space-y-2.5">
              <label className="block text-sm font-bold text-gray-700 ml-1 uppercase tracking-wider">Communication Style</label>
              <select
                value={intent.behavior.communication_style}
                onChange={(e) => updateSection("behavior", { communication_style: e.target.value })}
                className="w-full px-5 py-3 bg-gray-50 border border-gray-200 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 focus:bg-white outline-none transition-all font-medium text-gray-900 appearance-none cursor-pointer"
              >
                <option value="professional">Professional & Direct</option>
                <option value="casual">Casual & Conversational</option>
                <option value="concise">Concise & Minimal</option>
                <option value="detailed">Detailed & Analytical</option>
                <option value="empathetic">Empathetic & Supportive</option>
              </select>
            </div>
          </div>
          <div className="space-y-2.5">
            <label className="block text-sm font-bold text-gray-700 ml-1 uppercase tracking-wider">Custom Instructions</label>
            <textarea
              value={intent.behavior.custom_instructions || ""}
              onChange={(e) => updateSection("behavior", { custom_instructions: e.target.value })}
              rows={4}
              className="w-full px-5 py-4 bg-gray-50 border border-gray-200 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 focus:bg-white outline-none resize-none transition-all font-medium text-gray-900 leading-relaxed"
              placeholder="e.g. Prioritize technical risks and unresolved blockers. Always format data in tables when possible..."
            />
          </div>
        </div>
      </section>

      {/* 2. Capabilities */}
      <section>
        <SectionHeader 
          icon={Zap} 
          title="Cognitive Capabilities" 
          desc="Enable specialized intelligence modules for your meetings."
          colorClass="bg-amber-500 text-white"
        />
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[
            { key: "summaries", label: "Summaries", desc: "High-level meeting recaps", icon: MessageSquare },
            { key: "action_items", label: "Action Items", desc: "Task and owner extraction", icon: Layers },
            { key: "decisions", label: "Decisions", desc: "Hard outcome logging", icon: Check },
            { key: "risk_detection", label: "Risk Detection", desc: "Blocker & threat analysis", icon: Shield },
            { key: "technical_analysis", label: "Technical Deep-Dive", desc: "Architecture & code review", icon: Terminal },
            { key: "incident_detection", label: "Incidents", desc: "Outage & error surface", icon: Zap },
          ].map((cap) => {
            const Icon = cap.icon;
            const isEnabled = (intent.capabilities as any)[cap.key];
            return (
              <div 
                key={cap.key} 
                className={`p-6 rounded-2xl border transition-all duration-200 ${
                  isEnabled 
                    ? "bg-white border-amber-200 shadow-md shadow-amber-500/5 ring-1 ring-amber-50" 
                    : "bg-gray-50/50 border-gray-100 opacity-70 grayscale-[0.5]"
                }`}
              >
                <div className="flex items-start justify-between mb-4">
                  <div className={`p-2 rounded-lg ${isEnabled ? "bg-amber-100 text-amber-600" : "bg-gray-200 text-gray-400"}`}>
                    <Icon className="w-4 h-4" />
                  </div>
                  <Toggle
                    checked={isEnabled}
                    onChange={(v) => updateSection("capabilities", { [cap.key]: v })}
                  />
                </div>
                <p className="font-bold text-gray-900">{cap.label}</p>
                <p className="text-xs text-gray-500 mt-1 font-medium leading-relaxed">{cap.desc}</p>
              </div>
            );
          })}
        </div>
      </section>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-12">
        {/* 4. Knowledge Access */}
        <section>
          <SectionHeader 
            icon={Database} 
            title="Knowledge Access" 
            desc="Control what data the AI can retrieve."
            colorClass="bg-emerald-600 text-white"
          />
          <div className="bg-white border border-gray-200 rounded-2xl p-6 space-y-4 shadow-sm">
            {[
              { key: "meeting_history", label: "Meeting History" },
              { key: "team_documents", label: "Team Documents" },
              { key: "past_decisions", label: "Decision Registry" },
              { key: "architecture_docs", label: "Architecture Specs" },
            ].map((k) => {
              const isEnabled = (intent.knowledge_access as any)[k.key];
              return (
                <button
                  key={k.key}
                  onClick={() => updateSection("knowledge_access", { [k.key]: !isEnabled })}
                  className={`w-full flex items-center justify-between p-4 rounded-xl border transition-all ${
                    isEnabled
                      ? "bg-emerald-50 border-emerald-100 text-emerald-900 shadow-sm"
                      : "bg-white border-gray-100 text-gray-400 hover:border-gray-200"
                  }`}
                >
                  <span className="font-bold text-sm">{k.label}</span>
                  <div className={`w-2 h-2 rounded-full ${isEnabled ? "bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]" : "bg-gray-200"}`} />
                </button>
              );
            })}
          </div>
        </section>

        {/* 5. Privacy & Safety */}
        <section>
          <SectionHeader 
            icon={Shield} 
            title="Privacy & Safety" 
            desc="Enterprise governance controls."
            colorClass="bg-rose-600 text-white"
          />
          <div className="bg-white border border-gray-200 rounded-2xl p-8 space-y-8 shadow-sm">
            <div className="flex items-start justify-between gap-6">
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <Lock className="w-3.5 h-3.5 text-rose-600" />
                  <p className="font-bold text-gray-900 text-sm">PII Redaction</p>
                </div>
                <p className="text-xs text-gray-500 font-medium leading-relaxed">Automatically mask sensitive personal data before storage.</p>
              </div>
              <Toggle
                checked={intent.privacy_safety.redact_pii}
                onChange={(v) => updateSection("privacy_safety", { redact_pii: v })}
              />
            </div>
            <div className="flex items-start justify-between gap-6">
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <Globe className="w-3.5 h-3.5 text-blue-600" />
                  <p className="font-bold text-gray-900 text-sm">Data Residency</p>
                </div>
                <p className="text-xs text-gray-500 font-medium leading-relaxed">Restricts analysis to regional data centers only.</p>
              </div>
              <select
                value={intent.privacy_safety.data_residency}
                onChange={(e) => updateSection("privacy_safety", { data_residency: e.target.value })}
                className="text-xs font-bold bg-gray-100 border-none rounded-lg px-3 py-1.5 focus:ring-2 focus:ring-rose-500 outline-none"
              >
                <option value="default">Default</option>
                <option value="restricted">Restricted</option>
              </select>
            </div>
          </div>
        </section>
      </div>

      {/* 6. Connected Tools */}
      <section>
        <SectionHeader 
          icon={Wrench} 
          title="Connected Ecosystem" 
          desc="Authorized tools and integration surfaces."
          colorClass="bg-gray-800 text-white"
        />
        <div className="bg-white border border-gray-200 rounded-2xl p-8 shadow-sm">
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-6">
            {[
              { key: "slack_enabled", label: "Slack" },
              { key: "jira_enabled", label: "Jira" },
              { key: "github_enabled", label: "GitHub" },
              { key: "notion_enabled", label: "Notion" },
              { key: "crm_enabled", label: "Salesforce" },
            ].map((t) => {
              const isEnabled = (intent.connected_tools as any)[t.key];
              return (
                <button
                  key={t.key}
                  onClick={() => updateSection("connected_tools", { [t.key]: !isEnabled })}
                  className={`group relative overflow-hidden p-6 rounded-2xl border transition-all duration-300 ${
                    isEnabled
                      ? "bg-gray-900 border-gray-900 text-white shadow-xl shadow-gray-900/10 scale-[1.02]"
                      : "bg-white border-gray-100 text-gray-300 hover:border-gray-200 hover:text-gray-400"
                  }`}
                >
                  <div className={`absolute top-0 left-0 w-full h-1 ${isEnabled ? "bg-indigo-500" : "bg-transparent"}`} />
                  <div className="text-sm font-black uppercase tracking-widest">{t.label}</div>
                  <div className={`mt-2 text-[10px] font-bold ${isEnabled ? "text-indigo-400" : "text-gray-200"}`}>
                    {isEnabled ? "AUTHORIZED" : "DISABLED"}
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      </section>
    </div>
  );
}
