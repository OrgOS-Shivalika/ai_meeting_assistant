import type { ReactElement } from "react";
import { Video } from "lucide-react";

type Source = {
  label: string;
  hostnames: string[];
  bg: string;
  hoverBg: string;
  Icon: () => ReactElement;
};

const GoogleMeetMark = () => (
  <svg viewBox="0 0 87.5 72" xmlns="http://www.w3.org/2000/svg" className="w-5 h-5">
    <path fill="#00832d" d="M49.5 36l8.53 9.75 11.47 7.33 2-17.02-2-16.64-11.69 6.44z" />
    <path fill="#0066da" d="M0 51.5V66c0 3.32 2.69 6 6 6h14.5l3-10.96-3-9.54-9.95-3z" />
    <path fill="#e94235" d="M20.5 0L0 20.5l10.55 3 9.95-3 2.95-9.41z" />
    <path fill="#2684fc" d="M0 51.5h20.5v-31H0z" />
    <path fill="#00ac47" d="M82.6 8.68L69.5 19.42v33.66l13.16 10.79c1.97 1.54 4.85.13 4.85-2.37V11c0-2.53-2.95-3.92-4.91-2.32zM49.5 36v15.5h-29V72h43c3.32 0 6-2.68 6-6V53.08z" />
    <path fill="#ffba00" d="M63.5 0h-43v20.5h29V36l20-16.57V6c0-3.32-2.68-6-6-6z" />
  </svg>
);

const ZoomMark = () => (
  <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" className="w-5 h-5">
    <path fill="#2D8CFF" d="M0 7.18v9.64A2.18 2.18 0 0 0 2.18 19h11.32a2.18 2.18 0 0 0 2.18-2.18V7.18A2.18 2.18 0 0 0 13.5 5H2.18A2.18 2.18 0 0 0 0 7.18zm17.13 2.5l5.36-3.91c.46-.37 1.11-.05 1.11.51v11.44c0 .56-.65.88-1.11.51l-5.36-3.91z" />
  </svg>
);

const TeamsMark = () => (
  <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" className="w-5 h-5">
    <path fill="#4B53BC" d="M20.5 9h-5V4.5A2.5 2.5 0 0 0 13 2H5.5A2.5 2.5 0 0 0 3 4.5v11A2.5 2.5 0 0 0 5.5 18H8v2.5A2.5 2.5 0 0 0 10.5 23H18a2.5 2.5 0 0 0 2.5-2.5v-9A2.5 2.5 0 0 0 20.5 9zM12 5h-1.5v6.5H9V5H7.5V3.5h4.5V5z" />
    <path fill="#7B83EB" d="M16.25 12.5a1.75 1.75 0 1 1 0-3.5 1.75 1.75 0 0 1 0 3.5zm-2 9c1.93 0 3.5-1.57 3.5-3.5v-4.25h-7v4.25c0 1.93 1.57 3.5 3.5 3.5z" />
  </svg>
);

const WebexMark = () => (
  <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" className="w-5 h-5">
    <circle cx="12" cy="12" r="10" fill="#00BCEB" />
    <path fill="#fff" d="M7 10c0-.55.45-1 1-1s1 .45 1 1v4c0 .55-.45 1-1 1s-1-.45-1-1zm4-1c.55 0 1 .45 1 1v4c0 .55-.45 1-1 1s-1-.45-1-1v-4c0-.55.45-1 1-1zm4 1c0-.55.45-1 1-1s1 .45 1 1v4c0 .55-.45 1-1 1s-1-.45-1-1z" />
  </svg>
);

const SOURCES: Source[] = [
  {
    label: "Google Meet",
    hostnames: ["meet.google.com"],
    bg: "bg-emerald-50",
    hoverBg: "group-hover/row:bg-emerald-100",
    Icon: GoogleMeetMark,
  },
  {
    label: "Zoom",
    hostnames: ["zoom.us", "zoom.com"],
    bg: "bg-sky-50",
    hoverBg: "group-hover/row:bg-sky-100",
    Icon: ZoomMark,
  },
  {
    label: "Microsoft Teams",
    hostnames: ["teams.microsoft.com", "teams.live.com"],
    bg: "bg-indigo-50",
    hoverBg: "group-hover/row:bg-indigo-100",
    Icon: TeamsMark,
  },
  {
    label: "Webex",
    hostnames: ["webex.com"],
    bg: "bg-cyan-50",
    hoverBg: "group-hover/row:bg-cyan-100",
    Icon: WebexMark,
  },
];

const detectSource = (url?: string | null): Source => {
  if (!url) {
    return {
      label: "Meeting",
      hostnames: [],
      bg: "bg-slate-100",
      hoverBg: "group-hover/row:bg-slate-200",
      Icon: () => <Video className="w-4 h-4 text-slate-400" />,
    };
  }
  try {
    const host = new URL(url).hostname.replace(/^www\./, "").toLowerCase();
    const match = SOURCES.find((s) =>
      s.hostnames.some((h) => host === h || host.endsWith(`.${h}`))
    );
    if (match) return match;
  } catch {
    // fall through
  }
  return {
    label: "Meeting",
    hostnames: [],
    bg: "bg-slate-100",
    hoverBg: "group-hover/row:bg-slate-200",
    Icon: () => <Video className="w-4 h-4 text-slate-400" />,
  };
};

export default function MeetingSourceIcon({
  url,
  showLabel = false,
  size = "md",
}: {
  url?: string | null;
  showLabel?: boolean;
  size?: "sm" | "md";
}) {
  const source = detectSource(url);
  const boxClass =
    size === "sm" ? "w-8 h-8 rounded-lg" : "w-9 h-9 rounded-xl";

  return (
    <div className="flex items-center gap-2">
      <div
        className={`${boxClass} ${source.bg} ${source.hoverBg} flex items-center justify-center transition-colors`}
        title={source.label}
      >
        <source.Icon />
      </div>
      {showLabel && (
        <span className="text-[11px] font-bold text-slate-600 uppercase tracking-wider">
          {source.label}
        </span>
      )}
    </div>
  );
}
