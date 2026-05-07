import MeetingCard from "./MeetingCard";
import type { Meeting } from "../types";

interface MeetingListProps {
  meetings: Meeting[];
  onDelete?: (id: number) => void;
  deletingId?: number | null;
}

export default function MeetingList({ meetings, onDelete, deletingId }: MeetingListProps) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
      {meetings.map((meeting) => (
        <MeetingCard
          key={meeting.id}
          meeting={meeting}
          onDelete={onDelete}
          isDeleting={deletingId === meeting.id}
        />
      ))}
    </div>
  );
}
