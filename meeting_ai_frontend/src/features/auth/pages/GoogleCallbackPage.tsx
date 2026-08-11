import { useEffect, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { Lock } from "lucide-react";
import { apiClient } from "../../../services/apiClient";
import Layout from "../../../shared/components/Layout";
import { Card } from "@/components/ui/card";

export default function GoogleCallbackPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [status, setStatus] = useState("Connecting your Google account…");
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const handleCallback = async () => {
      try {
        const searchParams = new URLSearchParams(location.search);
        const code = searchParams.get("code");

        if (!code) {
          throw new Error("No code found in URL");
        }

        await apiClient(
          `/auth/google/exchange-code?code=${encodeURIComponent(code)}`,
        );

        setStatus("Connected. Taking you back…");
        setTimeout(() => navigate("/"), 2000);
      } catch (err) {
        console.error("Google Auth Error:", err);
        setFailed(true);
        setStatus("Couldn't connect your Google account.");
      }
    };

    handleCallback();
  }, [navigate, location]);

  const hue = failed ? "var(--vb-error)" : "var(--vb-info)";

  return (
    <Layout>
      <div className="flex min-h-full items-center justify-center p-11">
        <Card
          variant="default"
          className="w-full max-w-[440px] rounded-2xl px-10 py-12 text-center"
        >
          <div
            className="mx-auto mb-6 flex size-16 items-center justify-center rounded-[18px]"
            style={{ background: `color-mix(in srgb, ${hue} 12%, white)` }}
          >
            {failed ? (
              <Lock className="size-7" style={{ color: hue }} />
            ) : (
              <span
                className="size-[30px] animate-spin rounded-full border-[3px]"
                style={{
                  borderColor: `color-mix(in srgb, ${hue} 25%, white)`,
                  borderTopColor: hue,
                }}
              />
            )}
          </div>
          <h1 className="vb-title-lg">{status}</h1>
          <p className="mt-2.5 text-sm leading-relaxed text-muted-ink">
            {failed
              ? "The authorization code couldn't be exchanged. Try connecting again from Integrations."
              : "Exchanging the authorization code and linking your calendar. This only takes a moment."}
          </p>
          <div className="mt-5 inline-flex items-center gap-2 rounded-full bg-surface-card px-3.5 py-2 font-mono text-xs font-medium text-muted-soft">
            <Lock className="size-3.5" />
            auth/google/exchange-code
          </div>
        </Card>
      </div>
    </Layout>
  );
}
