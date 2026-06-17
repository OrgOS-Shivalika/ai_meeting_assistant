// Phase 14 K3 — column-footer "add card" affordance.
//
// Collapsed by default (just "+ Add card"). Click to open an inline
// input. Enter to save, Escape to cancel.
import { useState } from "react";
import { Plus } from "lucide-react";

interface Props {
  onAdd: (title: string) => Promise<void> | void;
}

export default function QuickAddCard({ onAdd }: Props) {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    const v = value.trim();
    if (!v) return;
    setSaving(true);
    try {
      await onAdd(v);
      setValue("");
      // Keep open after a save — lets the user batch-add several cards.
    } catch (e) {
      console.error("Failed to add card", e);
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    setOpen(false);
    setValue("");
  };

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="w-full text-left text-[11px] font-bold uppercase tracking-wider text-slate-400 hover:text-indigo-600 hover:bg-white rounded px-2 py-1.5 flex items-center gap-1.5 transition-colors"
      >
        <Plus className="w-3 h-3" />
        Add card
      </button>
    );
  }

  return (
    <div className="bg-white border border-indigo-200 rounded-lg p-2 shadow-sm space-y-1.5">
      <textarea
        autoFocus
        rows={2}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            void handleSave();
          }
          if (e.key === "Escape") handleCancel();
        }}
        placeholder="Card title — enter to save, shift+enter for newline"
        className="w-full text-xs px-2 py-1.5 border border-slate-200 rounded focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-500 outline-none resize-none"
      />
      <div className="flex items-center gap-1.5">
        <button
          onClick={handleSave}
          disabled={saving || !value.trim()}
          className="text-[10px] font-bold uppercase tracking-wider px-2 py-1 bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50"
        >
          {saving ? "Adding…" : "Add"}
        </button>
        <button
          onClick={handleCancel}
          className="text-[10px] font-bold uppercase tracking-wider px-2 py-1 text-slate-500 hover:bg-slate-100 rounded"
        >
          Close
        </button>
      </div>
    </div>
  );
}
