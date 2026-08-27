// "Generate Size Set" on a meeting — Option A from the client's spec.
//
// Renders nothing unless the meeting sits in the configured category (the
// "Triburg org, Quality Team section" placement). The category name is server
// configuration, fetched once, so the client never holds that decision.
//
// Deliberately hands off to /size-set once the job exists rather than
// duplicating the polling, review table and download buttons that page already
// has.
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Loader2, Ruler } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogFooter,
  DialogHeader,
} from "@/components/ui/dialog";
import { Select } from "@/components/ui/select";
import { createJobFromMeeting, listStyles, readConfig } from "../api";

interface Props {
  meetingId: number;
  categoryName?: string | null;
}

export default function SizeSetAction({ meetingId, categoryName }: Props) {
  const [enabledFor, setEnabledFor] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [styles, setStyles] = useState<string[]>([]);
  const [styleNo, setStyleNo] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const navigate = useNavigate();

  useEffect(() => {
    readConfig()
      .then((config) => setEnabledFor(config.category_name))
      .catch(() => setEnabledFor(null));
  }, []);

  useEffect(() => {
    if (!open) return;
    listStyles()
      .then(setStyles)
      .catch((err) => setError(err.message));
  }, [open]);

  // An empty configured name means "any category"; otherwise it has to match.
  const allowed =
    enabledFor !== null &&
    (enabledFor === "" || enabledFor === (categoryName ?? "").trim());
  if (!allowed) return null;

  const generate = async () => {
    setBusy(true);
    setError("");
    try {
      await createJobFromMeeting(meetingId, styleNo);
      setOpen(false);
      navigate("/size-set");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Button variant="outline" onClick={() => setOpen(true)}>
        <Ruler className="w-3.5 h-3.5" />
        Generate Size Set
      </Button>

      {open && (
        <Dialog open={open} onClose={() => setOpen(false)}>
          <DialogHeader
            title="Generate Size Set report"
            description="Formats this meeting's transcript into the standard inspection report."
          />
          <DialogBody>
            <label className="text-xs font-semibold text-slate-500 uppercase tracking-wider block mb-2">
              Style
            </label>
            <Select
              value={styleNo}
              onChange={(e) => setStyleNo(e.target.value)}
            >
              <option value="">As announced in the meeting</option>
              {styles.map((style) => (
                <option key={style} value={style}>
                  Style {style}
                </option>
              ))}
            </Select>
            <p className="text-[11px] text-slate-500 mt-2 leading-relaxed">
              Picks the spec sheet to grade against. Leave it as announced to use
              the style number spoken during the review.
            </p>
            {error && (
              <p className="mt-3 text-xs font-semibold text-red-600">{error}</p>
            )}
          </DialogBody>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button onClick={generate} disabled={busy}>
              {busy ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" /> Generating
                </>
              ) : (
                "Generate"
              )}
            </Button>
          </DialogFooter>
        </Dialog>
      )}
    </>
  );
}
